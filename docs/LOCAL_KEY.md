# Lokalen Beatbot-Schlüssel beschaffen und in HA importieren

[← Zurück zum README](../README.md)

## Was brauche ich genau?

| Wert | Bedeutung / Quelle |
|---|---|
| Roboter-ID | In der Beatbot-App: Roboter öffnen → Einstellungen → Mehr → **ID des Roboters**. Nicht UUID oder SN verwenden. |
| Lokaler Schlüssel | Ein gerätespezifisches Geheimnis mit **16 Zeichen**, intern `localKey` genannt. Nicht das Beatbot-Passwort und normalerweise nicht in der App-Oberfläche sichtbar. |
| LAN-IP | Im Router bei den verbundenen Geräten oder über die Suche der Integration. Eine DHCP-Reservierung ist sinnvoll. |

**Wichtig:** Die Integration kann einen unbekannten Schlüssel nicht aus einem LAN-Scan gewinnen. Die Beatbot-OAuth-Anmeldung ist kein Ersatz dafür. Diese Anleitung greift nur auf deinen eigenen angemeldeten Android-/HA-Kontext zu; sie errät keinen Schlüssel und umgeht keine fremde Anmeldung.

## Welcher Weg passt?

- **Integration schon eingerichtet:** [Weg B: Export aus deiner HA-Konfiguration](#weg-b-export-aus-einer-bereits-eingerichteten-ha-integration). Dafür brauchst du keine Android-App.
- **Schlüssel noch unbekannt:** [Weg A: Android-App und ADB](#weg-a-android-app-und-adb). Nachgewiesen mit Beatbot **2.4.1** in BlueStacks **Pie 64-bit**. Die App muss im eigenen Konto angemeldet sein und den eigenen Roboter anzeigen.
- **Nur ein iPhone vorhanden:** Für iOS ist hier kein Schlüssel-Exportweg nachgewiesen. Verwende für Weg A eine eigene Android-Installation bzw. BlueStacks am Windows-PC und dasselbe Beatbot-Konto. Kein erneutes Koppeln nur für diesen Export nötig.
- **Aktuelle Android-App liefert kein `localKey`:** Dann ist Weg A mit dieser Version nicht belegt/nutzbar. Ein leerer Export ist kein Beweis für ein falsches Konto. Nicht den Roboter zurücksetzen und nicht wahllos APKs oder Schlüssel-Webseiten ausprobieren. Ohne bereits vorhandenen Schlüssel kann die lokale Integration dann nicht eingerichtet werden.

## Weg A: Android-App und ADB

### 1. Werkzeuge auf dem PC vorbereiten

1. [Python 3](https://www.python.org/downloads/) installieren. In PowerShell `py -3 --version` prüfen. Falls du Python als `python` aufrufst, die Beispiele entsprechend anpassen. Getestete Entwicklungsumgebung: Python 3.12; das Exportwerkzeug benötigt keine zusätzlichen Python-Pakete.
2. Die offiziellen [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools) herunterladen und z. B. nach `C:\Android\platform-tools` entpacken. `adb.exe` muss direkt in diesem Ordner liegen. Android Studio ist dafür nicht erforderlich.
3. Dieses Repository über **Code → Download ZIP** herunterladen und entpacken. Du brauchst das Skript [`tools/export_beatbot_key.py`](../tools/export_beatbot_key.py), das nicht im reinen HA-Integrationspaket liegt. Alternativ das Werkzeug über die GitHub-Dateiansicht herunterladen. HACS installiert den `tools`-Ordner nicht als ausführbares HA-Add-on.
4. Einen privaten Ausgabeordner **außerhalb aller Git-Repositories** verwenden, z. B. `C:\Beatbot-private`. Er darf nicht öffentlich geteilt sein. Die JSON-/XML-Ausgaben enthalten unverschlüsselte Geheimnisse.

Die Pfade unten sind Beispiele. Ersetze die Platzhalter; kopiere keine Geräte-ID aus fremden Screenshots.

### 2a. BlueStacks am Windows-PC verbinden

1. [BlueStacks](https://www.bluestacks.com/) aus offizieller Quelle installieren und eine Android-Instanz starten. Für den bisherigen Nachweis wurde **Pie 64-bit** verwendet; andere Instanzen/App-Versionen sind nicht automatisch gleichwertig getestet.
2. Beatbot aus einer vertrauenswürdigen offiziellen Quelle installieren und mit deinem bestehenden Beatbot-Konto anmelden. Prüfen, dass dein Roboter in der App angezeigt wird. Keine App-Passwörter in PowerShell eingeben.
3. In BlueStacks **Einstellungen → Erweitert → Android Debug Bridge (ADB)** aktivieren. Die dort angezeigte Adresse/Portnummer verwenden; `5555` ist nur ein Beispiel. [Offizielle BlueStacks-Anleitung](https://support.bluestacks.com/hc/de/articles/23925869130381-So-aktivieren-Sie-Android-Debug-Bridge-auf-BlueStacks-5).
4. In PowerShell prüfen:

```powershell
& 'C:\Android\platform-tools\adb.exe' version
& 'C:\Android\platform-tools\adb.exe' connect 127.0.0.1:5555
& 'C:\Android\platform-tools\adb.exe' devices
```

Erwartet wird eine Zeile wie `127.0.0.1:5555    device`. Bei einem anderen BlueStacks-Port diesen in **allen** folgenden Befehlen ersetzen. Die Loopback-Adresse bezeichnet den Android-Emulator auf deinem PC, **nicht** die WLAN-IP des Roboters. ADB nicht ins Internet freigeben.

### 2b. Alternative: eigenes Android-Telefon per USB

Auf dem eigenen Telefon Entwickleroptionen und **USB-Debugging** aktivieren, per Datenkabel verbinden und den RSA-Freigabedialog für diesen PC bestätigen. Danach `adb devices` ausführen und die dort angezeigte Serienkennung bei `--serial` verwenden. Für USB ist kein `adb connect 127.0.0.1:5555` nötig. Details: [Androids ADB-Dokumentation](https://developer.android.com/tools/adb).

Dies ist der allgemeine ADB-Zugangsweg; der **Beatbot-Schlüsselexport selbst wurde hier in BlueStacks**, nicht auf jeder Telefon-/Android-Version geprüft. Root ist für den nachgewiesenen Logcat-Weg nicht nötig. Nicht `adb root`, Bootloader-Entsperrung oder einen Werksreset ausführen.

### 3. Frische App-Meldungen erzeugen

1. Die eigene **Roboter-ID** unter Beatbot → Roboter → Einstellungen → Mehr notieren.
2. Die Beatbot-App vollständig schließen und erneut öffnen; nicht aus dem Konto abmelden und den Roboter nicht neu koppeln. Eigenen Roboter auswählen, bis seine Seite sichtbar ist.
3. Den Export **zeitnah** ausführen. Das Werkzeug liest den begrenzten Android-Protokollpuffer, nicht dauerhaft einen Mitschnitt. Alte Meldungen können bereits verdrängt worden sein.

Bei der geprüften App-Version stand ein JSON-Objekt mit `devId` und `localKey` in Diagnosemeldungen der angemeldeten App. Diese Ausgabe ist eine Eigenschaft dieser App-Version, kein zugesicherter Hersteller-Export. Die App zeigt den Schlüssel nicht automatisch im Einstellungsmenü an.

### 4. Schlüsseldatei erzeugen

PowerShell öffnen. Den Pfad zum entpackten Werkzeug, die tatsächliche ADB-Kennung und die eigene Roboter-ID einsetzen:

```powershell
py -3 'C:\Tools\hacs-beatbot-aquasense2-local-main\tools\export_beatbot_key.py' `
  --adb 'C:\Android\platform-tools\adb.exe' `
  --serial '127.0.0.1:5555' `
  --device-id 'DEINE_ROBOTER_ID' `
  --output 'C:\Beatbot-private\MeinRoboter.beatbot-key.json'
```

Die PowerShell-Backticks am Zeilenende dienen nur der Fortsetzung; dahinter kein Leerzeichen setzen. Alternativ den Befehl in einer Zeile eingeben. `DEINE_ROBOTER_ID` ist ein Platzhalter, keine gültige Beispiel-ID.

**Erfolg:** Das Werkzeug meldet `Private HA-Schlüsseldatei erstellt: ...`. Es druckt keinen Schlüssel. Die Datei ist unmittelbar für den HA-Import geeignet. Es liest die Rohmeldungen nur im Arbeitsspeicher, sucht exakt die angegebene `devId` und exportiert genau einen eindeutigen 16-Zeichen-Schlüssel. Es speichert keine Rohlogs oder Konto-/Cloud-Token.

**Fehlschlag:** Kein eindeutiger Schlüssel, ADB-Fehler, falsche ID, vorhandene Zieldatei oder Ausgabe in einem Git-Ordner führen zu einer neutralen Fehlermeldung. Diese verrät absichtlich nicht den Loginhalt. Die [Fehlerhilfe](#fehlerhilfe) unten verwenden. Keine Rohlogs an Issues anhängen.

### 5. In Home Assistant importieren

1. Integration installieren und HA neu starten; [Installation im README](../README.md#installation-und-einrichtung).
2. Roboter wach halten, außerhalb des Wassers und im lokalen Netz erreichbar. Falls nötig über deine Ladestation aufwecken. Keine Reinigung für die Einrichtung starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Beatbot AquaSense 2 Local → Schlüsseldatei importieren**.
4. `MeinRoboter.beatbot-key.json` auswählen, optional einen eigenen Namen vergeben und bei Bedarf die aktuelle Roboter-LAN-IP ergänzen. Die App-Roboter-ID steckt bereits in der Datei.
5. Die Integration prüft Format/Modell/Schlüssel und eine echte lokale Antwort. Ein Dateiexport allein beweist noch nicht, dass der Schlüssel zur aktuellen Kopplung passt.
6. Optional die vorhandene Ladesteckdose zuordnen. ADB anschließend wieder deaktivieren, Emulator bei Bedarf schließen. Die App/BlueStacks muss für den lokalen HA-Betrieb nicht weiterlaufen.

## Weg B: Export aus einer bereits eingerichteten HA-Integration

Dies **beschafft keinen neuen Schlüssel**, sondern sichert den, den du vorher in dieser Integration gespeichert hast. Dafür ist administrativer Dateizugriff auf deine HA-Konfiguration nötig. Die HA-Oberfläche bietet hier keinen frei zugänglichen Schlüssel-Endpunkt.

In einer Umgebung mit Python und Zugriff auf die tatsächliche Konfigurationsdatei, beispielsweise einer entsprechend eingerichteten administrativen Shell:

```sh
python3 /PFAD/ZUM/REPOSITORY/tools/export_beatbot_key.py \
  --ha-config /config/.storage/core.config_entries \
  --device-id DEINE_ROBOTER_ID \
  --output /config/MeinRoboter.beatbot-key.json
```

`/config` ist der typische HA-Pfad, nicht auf jeder Installation oder in jedem Terminal-Add-on vorhanden. Das Skript muss dort selbst erreichbar sein; nicht jedes HA-OS-Terminal enthält Python. Alternativ eine **private lokale Kopie** der Konfigurationsdatei auf dem PC mit `--ha-config` lesen. Die Quelldatei nicht verändern und nicht in Git ablegen. Sie enthält auch Geheimnisse anderer Integrationen und gehört niemals in einen Issue, Chat-Anhang oder öffentlichen Ordner. Das Werkzeug wählt nur den passenden `beatbot_aquasense2_local`-Eintrag anhand der Roboter-ID aus.

## Optional: KeePass-Import zusätzlich erzeugen

Dem jeweiligen Exportbefehl hinzufügen:

```text
--keepass "C:\Beatbot-private\MeinRoboter.keepass.xml"
```

Für Linux entsprechend einen privaten lokalen Ausgabepfad wählen. In KeePass **Datei → Importieren → KeePass XML (2.x)** verwenden, die Datei wählen und die Datenbank speichern. Der Eintrag enthält Roboter-ID als Benutzername, lokalen Schlüssel als Passwort und die HA-JSON-Datei als Anhang. Dieser Anhang lässt sich später erneut für HA exportieren. Es ist keine Master-Schlüsseldatei und kein Ersatz für das KeePass-Master-Passwort. [Offizielle KeePass-Dokumentation](https://keepass.info/help/base/importexport.html).

JSON und XML sind vor dem Import **unverschlüsselt**. Nach geprüftem Import in HA/KeePass und gesicherter verschlüsselter Datenbank lose Kopien gezielt entfernen. Cloud-Synchronisierung, Backups und Papierkorb können Kopien behalten. Das Werkzeug überschreibt keine vorhandene Datei; für einen neuen Export einen neuen Dateinamen wählen. Schlüssel nie in Screenshots, Konsolenausgaben, Git oder Issues veröffentlichen.

## Fehlerhilfe

| Beobachtung | Prüfen / nächster Schritt |
|---|---|
| `py` oder Python nicht gefunden | Python installieren; `py -3 --version` bzw. `python --version` prüfen. |
| `adb.exe` nicht gefunden | Platform-Tools entpacken und den vollständigen tatsächlichen Pfad verwenden. |
| `adb devices` ist leer | Emulator läuft? ADB in genau dieser Instanz aktiviert? Richtiger Port? Bei USB: Datenkabel/Debugging/Treiber prüfen. |
| `unauthorized` | Telefon/Android entsperren und Freigabe für den eigenen PC bestätigen. |
| `offline` oder Verbindung abgelehnt | ADB-Port/Instanz prüfen, Verbindung zum korrekten Ziel erneut aufbauen. Nicht die Roboter-IP als ADB-Ziel verwenden. |
| Mehrere Android-Geräte | Mit `--serial` genau die Kennung aus `adb devices` wählen, auf der die angemeldete Beatbot-App läuft. |
| Export schlägt trotz ADB-Status `device` fehl | Roboter-ID statt UUID/SN? Ziel neu und außerhalb Git? App angemeldet, Roboter sichtbar, gerade neu geöffnet? App-Version notieren. |
| Nach Neu-Kopplung mehrere alte Schlüssel im Logpuffer | Nur wenn du die bisherigen Android-Diagnoselogs nicht mehr brauchst: mit `adb -s KENNUNG logcat -c` den Puffer dieses eigenen Geräts leeren, dann die App neu öffnen und in eine neue Datei exportieren. Dies löscht Diagnosemeldungen, nicht App-Daten. |
| Frischer Export weiterhin erfolglos | Die App-Version protokolliert den Schlüssel möglicherweise nicht mehr oder in einem anderen Format. Kein Erfolg garantiert; keine Passwörter raten, nicht allein deshalb neu koppeln. |
| HA meldet „Roboter antwortet lokal nicht“ | Wach/erreichbar? Richtige LAN-IP? Gleiches Netz oder erlaubtes Routing? Schlüssel noch aktuell? Andere lokale Tuya-Abfrager testweise beenden; gleichzeitige Verbindungen können stören. |
| HA findet keinen Roboter | Roboter aufwecken; LAN/VLAN/Container-Netz und Broadcast-Erreichbarkeit prüfen, bekannte LAN-IP manuell versuchen. Manuelle IP ersetzt nicht die für das Modell erforderliche Erkennung/Prüfung. |
| Schlüsseldatei ungültig | Vom Exportwerkzeug erzeugte `.beatbot-key.json` wählen, nicht KeePass-XML, APK/XAPK, Logdatei oder fremdes JSON. Nicht von Hand Zeichen am Schlüssel entfernen. |
| Export erfolgreich, nach Neu-Kopplung keine Verbindung | Tuya-Schlüssel können sich durch erneutes Pairing ändern. Aktuellen Schlüssel erneut beschaffen und HA-Konfiguration entsprechend aktualisieren. |

### Warum nicht einfach Tuya IoT / Smart Life?

TinyTuya dokumentiert einen Cloud-Wizard für Geräte, die mit einem passenden eigenen Tuya-Projekt/App-Konto verknüpft sind. **Dass ein Beatbot-Konto damit ohne Weiteres verknüpft werden kann, ist hier nicht nachgewiesen.** Daher ist das keine zugesicherte Alternative für Beatbot-Nutzer und kein Grund, die bestehende Beatbot-Kopplung aufzulösen. Hintergrund: [TinyTuya-Key-Dokumentation](https://github.com/jasonacox/tinytuya#setup-wizard---getting-local-keys).

Wenn du einen Fehler meldest, genügen zunächst HA-/Integrationsversion, Beatbot-App-Version, Android-/Emulator-Variante, ob ADB `device` meldet und die neutrale Fehlermeldung. Keine Schlüssel, Passwörter, privaten Exporte oder vollständigen Logs posten.
