"""Constants verified against the AquaSense 2 app panel and one LAN device."""

from datetime import timedelta

DOMAIN = "beatbot_aquasense2_local"
PRODUCT_ID = "c64wbaic8jnkqgix"
CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_HOST = "host"
CONF_VERSION = "version"
CONF_CHARGER_SWITCH = "charger_switch"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_TELEGRAM_BOT = "telegram_bot_entry_id"
CONF_TELEGRAM_CHAT = "telegram_chat_id"
CONF_TELEGRAM_PHOTO = "telegram_photo"
TELEGRAM_NOTIFY = "telegram_bot"
OFFLINE_IDLE_STATES = {"standby", "sleep", "charge_done", "clean_done", "auto_dock", "dock"}
OFFLINE_OFF_DELAY = timedelta(minutes=5)
DIVING_DISPLAY_DURATION = timedelta(seconds=90)

MODE_VALUES = {
    "Boden": 0,
    "Standard": 3,
    "Bereich": 2,
    "MultiZone": 6,
    "ECO": 5,
}
VALUE_MODES = {value: name for name, value in MODE_VALUES.items()}
FLOOR_ONLY_MODES = {"Boden", "ECO"}

STATUS_VALUES = {
    0: "standby",
    1: "goto_charge",
    2: "charging",
    3: "charge_done",
    4: "paused",
    5: "cleaning",
    6: "sleep",
    7: "return_trip",
    8: "clean_done",
    9: "remote_control",
    10: "clean_wait",
    11: "wifi_connect",
    12: "diving",
    13: "emerge",
    14: "auto_dock",
    15: "dock",
}
PARK_ACTIVE_STATES = {"paused", "cleaning", "return_trip", "clean_wait", "diving", "emerge"}
STATUS_LABELS = {
    "standby": "Bereit",
    "goto_charge": "Laderückkehr – unbestätigt",
    "charging": "Lädt",
    "charge_done": "Vollständig geladen",
    "paused": "Pausiert",
    "cleaning": "Reinigt",
    "sleep": "Ruhemodus",
    "return_trip": "Rückkehr läuft",
    "clean_done": "Reinigung abgeschlossen",
    "remote_control": "Manuelle Steuerung",
    "clean_wait": "Wartet auf Reinigung",
    "wifi_connect": "WLAN-Verbindung wird hergestellt",
    "diving": "Taucht ab",
    "emerge": "Aufgetaucht – fährt zum Rand",
    "auto_dock": "Geparkt am Beckenrand",
    "dock": "Dockstatus – unbestätigt",
}
# Device observations, not merely decoded enums or unit-test coverage.
VERIFIED_STATUS_VALUES = {"standby", "charging", "cleaning", "sleep", "diving", "emerge", "auto_dock"}
LEGACY_STATUS_LABELS = {
    "Reinigt – taucht ab": STATUS_LABELS["diving"],
    "Schwebend": STATUS_LABELS["emerge"],
    "Geparkt": STATUS_LABELS["auto_dock"],
    "Parkt": STATUS_LABELS["auto_dock"],
    "Fertig": STATUS_LABELS["clean_done"],
}
PARK_ACCEPTED_STATES = {"auto_dock"}
PARK_DONE_STATES = {"clean_done", "dock"}
IDLE_STATES = {"standby", "sleep", "charge_done", "charging"}

PARK_RETRY_INTERVAL = timedelta(seconds=15)
PARK_AVAILABLE_DELAY = timedelta(minutes=10)
PARK_MAX_DURATION = timedelta(hours=8)
