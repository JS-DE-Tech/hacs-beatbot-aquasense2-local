"""Completion delivery through existing HA integrations; no bot credentials."""

from pathlib import Path
import hashlib
import os
import re
import tempfile

from .const import (
    CONF_NOTIFY_SERVICE, CONF_TELEGRAM_BOT, CONF_TELEGRAM_CHAT,
    CONF_TELEGRAM_PHOTO, TELEGRAM_NOTIFY, DOMAIN,
)

COMPLETION_TITLE = "✅ Beatbot fertig."
COMPLETION_MESSAGE = "AquaSense 2 - Gewähltes Programm beendet."


def parse_chat_id(value) -> int:
    """Accept one exact numeric recipient, including negative group IDs."""
    if type(value) is int:
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"-?[0-9]{1,16}", value.strip()):
        parsed = int(value.strip())
    else:
        raise ValueError("Invalid Telegram chat ID")
    if not 0 < abs(parsed) < 2**52:
        raise ValueError("Invalid Telegram chat ID")
    return parsed


MAX_PHOTO_BYTES = 10 * 1024 * 1024


def _photo_directory(hass) -> Path:
    return Path(hass.config.path(DOMAIN, "notification_images"))


def _read_photo(path: Path) -> tuple[bytes, str]:
    with path.open("rb") as stream:
        data = stream.read(MAX_PHOTO_BYTES + 1)
    if not 0 < len(data) <= MAX_PHOTO_BYTES:
        raise ValueError("Photo is empty or exceeds 10 MiB")
    if data.startswith(b"\xff\xd8\xff"):
        suffix = ".jpg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = ".png"
    else:
        raise ValueError("Invalid image signature")
    return data, suffix


def store_photo(hass, source: Path) -> str:
    """Executor-only, bounded upload; retain previous images for safe rollback."""
    data, suffix = _read_photo(Path(source))
    directory = _photo_directory(hass)
    directory.mkdir(parents=True, exist_ok=True)
    # Never grant Telegram access through an unexpected symlink to another dir.
    if directory.resolve() != directory.absolute():
        raise ValueError("Notification directory must not be a symlink")
    destination = directory / (hashlib.sha256(data).hexdigest() + suffix)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return str(destination)


def validate_photo(hass, value: str) -> str:
    """Executor-only: only files created by our uploader may be sent."""
    directory = _photo_directory(hass).absolute()
    path = Path(value).resolve(strict=True)
    if directory.resolve() != directory or path.parent != directory:
        raise ValueError("Photo is outside the private notification directory")
    if not re.fullmatch(r"[0-9a-f]{64}\.(jpg|png)", path.name):
        raise ValueError("Not an uploaded notification image")
    data, suffix = _read_photo(path)
    if path.name != hashlib.sha256(data).hexdigest() + suffix:
        raise ValueError("Uploaded photo has changed")
    return str(path)


def completion_call(options: dict) -> tuple[str, str, dict]:
    """Explicit recipient only: never use Telegram's default/first chat."""
    service = options.get(CONF_NOTIFY_SERVICE)
    if service == TELEGRAM_NOTIFY:
        bot = options.get(CONF_TELEGRAM_BOT)
        if not isinstance(bot, str) or not bot.strip():
            raise ValueError("Select a Telegram bot")
        data = {
            "config_entry_id": bot,
            "chat_id": [parse_chat_id(options.get(CONF_TELEGRAM_CHAT))],
            "parse_mode": "plain_text",
        }
        text = f"{COMPLETION_TITLE}\n{COMPLETION_MESSAGE}"
        photo = options.get(CONF_TELEGRAM_PHOTO)
        if photo:
            data.update(file=photo, caption=text)
            return TELEGRAM_NOTIFY, "send_photo", data
        data["message"] = text
        return TELEGRAM_NOTIFY, "send_message", data
    if not isinstance(service, str) or not service.startswith("mobile_app_"):
        raise ValueError("Select a notification target")
    return "notify", service, {"title": COMPLETION_TITLE, "message": COMPLETION_MESSAGE}
