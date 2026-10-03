# Beatbot AquaSense 2 Local for Home Assistant

<p align="center">
  <img src="https://raw.githubusercontent.com/JS-DE-Tech/hacs-beatbot-aquasense2-local/main/docs/images/beatbot-aquasense2-dock.png"
       alt="Beatbot AquaSense 2 auf seiner Ladestation – freigestellte Produktillustration"
       width="420">
</p>

Lokale Home-Assistant-Integration für den **Beatbot AquaSense 2**: Reinigungsprogramme vorwählen, Status und Akku sehen, am Beckenrand parken, Laufzeiten lernen und die Ladestation steuern.

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-41BDF5?logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
[![HACS](https://img.shields.io/badge/HACS-Custom%20Repository-41BDF5)](https://hacs.xyz/)
[![Protocol](https://img.shields.io/badge/protocol-local%20Tuya%203.3-success)](#voraussetzungen-und-grenzen)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Support via PayPal](https://img.shields.io/badge/Support%20via-PayPal-0070BA?logo=paypal&logoColor=white)](https://paypal.me/JensSaffrich)

**Experimentelles Community-Projekt, keine offizielle Beatbot-Integration.** Die Verbindung zum Roboter nutzt das lokale Tuya-Protokoll 3.3; Beatbot-Cloud und Beatbot-App sind für den laufenden HA-Betrieb nicht erforderlich. Benachrichtigungen über Telegram/Smartphone benötigen ihre jeweiligen Dienste. Getestet wurde bislang **ein AquaSense 2** mit der Produktkennung `c64wbaic8jnkqgix`, nicht AquaSense 2 Pro/Ultra oder andere Modelle.

[Installation](#installation-und-einrichtung) · [Lokalen Schlüssel beschaffen](docs/LOCAL_KEY.md) · [Funktionen](#in-home-assistant) · [Telegram und Bilder](#telegram-und-eigenes-bild-ab-043) · [Statuszuordnung](#statusanzeige-ab-042) · [Changelog](CHANGELOG.md)

## Beispiel: Darstellung in Home Assistant

So kann eine eigene Dashboard-Karte mit den bereitgestellten Entitäten aussehen:

<p align="center">
  <a href="docs/images/homeassistant-dashboard.png">
    <img src="https://raw.githubusercontent.com/JS-DE-Tech/hacs-beatbot-aquasense2-local/main/docs/images/homeassistant-dashboard.png"
         alt="Home-Assistant-Beispielkarte: AquaSense 2, Akku, Ruhemodus, gelernte Laufzeit, Programme, Parken und Ladestation"
         width="420">
  </a>
</p>

**Beispielansicht, kein automatisch installiertes Dashboard.** Der Screenshot stammt aus einer persönlichen Installation. Name, Akkustand, gelernte 65 Minuten und zwei Läufe sind individuelle Werte, keine Vorgaben für andere Pools. Die Integration liefert die Entitäten; eine eigene Karte und deren Entitäts-IDs müssen separat eingerichtet werden. Das genaue Karten-YAML des Screenshots ist nicht Bestandteil dieses Repositories. Die Programmwahl startet keine Reinigung; deaktiviertes Parken im Boden-Modus ist beabsichtigt.

## Voraussetzungen und Grenzen

- Ein bereits in der Beatbot-App eingerichteter **AquaSense 2**, seine **Roboter-ID** und sein gerätespezifischer **lokaler Tuya-Schlüssel mit 16 Zeichen**. [Schritt-für-Schritt-Anleitung mit Fehlerhilfe](docs/LOCAL_KEY.md).
- Home Assistant und Roboter müssen sich lokal erreichen können. Die automatische Suche benötigt normalerweise dasselbe LAN/VLAN; bei getrennten Netzen Routing/Firewall und eine feste IP-Zuordnung prüfen. Keine Portfreigabe ins Internet, kein DNS-Umbiegen nötig.
- Der Roboter muss bei der Einrichtung wach und außerhalb des Wassers erreichbar sein. Unter Wasser sind WLAN-Lücken normal; letzte Werte bleiben mit Frischekennzeichnung erhalten.
- Optional: eine bereits in HA eingerichtete `switch.*`-Entität für die Ladestation, z. B. Shelly. Die Integration richtet diese Steckdose nicht selbst ein.
- Kein Reinigungs-Startknopf, kein bestätigter physischer Ausschaltbefehl und kein Rückruf während dauerhaft fehlender WLAN-Verbindung. „Ausgeschaltet“ ist unter den dokumentierten Bedingungen eine Ableitung.
- Der ADB-Schlüsselexport wurde mit Android-App **2.4.1** in BlueStacks nachgewiesen. Neuere App-Versionen können das benötigte Feld nicht mehr ausgeben; es gibt keinen garantierten universellen Schlüsselabruf und keinen belegten iOS-Exportweg.

## In Home Assistant

| Entität | Funktion |
| --- | --- |
| `select` Reinigungsmodus | Boden, Standard, Bereich, MultiZone, ECO vorwählen. Eine Auswahl startet keine Reinigung. |
| `sensor` Letzter Reinigungsmodus | Zuletzt lokal bestätigter Modus; bleibt bei Verbindungsverlust erhalten. |
| `sensor` Akkustand | Zuletzt gelesener Prozentwert; Attribut `stale` kennzeichnet ältere Werte. |
| `sensor` Reinigungsstatus | Deutsche Anzeige des Arbeitsstatus, einschließlich „Ruhemodus“ und „Lädt“, oder abgeleitet „Ausgeschaltet“. Vollständige Zuordnung siehe unten. Nach Abholung und gemeldetem `standby` außerhalb des Wassers wieder „Bereit“. |
| `sensor` Roboterstatus | Vom Roboter gemeldeter technischer Zustand, z. B. `sleep` oder `cleaning`. |
| `binary_sensor` Lokal erreichbar | Ob die letzte lokale Statusabfrage gelang. |
| `button` Parken | Merkt einen Parkauftrag vor und versucht ihn in kurzen WLAN-Fenstern zu senden. |
| `sensor` Parkauftrag | Zeigt, ob ein Auftrag wartet, gesendet, angenommen, abgeschlossen oder abgelaufen ist. |
| `select` Ladeziel | 80 % oder 100 %. |
| `sensor` Ladeüberwachung | Zeigt den Zustand der zugeordneten Ladesteckdose und Überwachung. |
| `select` Bereich Boden / Wand und Wasserlinie | Je x0, x1, x2; nicht beide x0. Acht getrennte Kombinationen. |
| `select` MultiZone Dauer | Max, 2h oder 1h. |
| `sensor` Geschätzte Programmdauer | Gelernte Dauer der aktuell vorgewählten Kombination in Minuten. |
| `sensor` Geschätzte Restzeit | Restzeit des laufenden Programms; läuft auch während WLAN-Lücken weiter. |
| `sensor` Geschätzter Akkuverbrauch | Gelernter Verbrauch der vorgewählten Kombination in Akku-Prozentpunkten; ab zwei verwertbaren Akku-Messpaaren. |
| `binary_sensor` Akku für Programm zu niedrig | Warnung bei frischem Akkustand unter dem bisherigen Maximalverbrauch plus fünf Prozentpunkten Reserve. Keine Startsperre. |
| `binary_sensor` Filterkorb fehlt | Lokale Filterkorb-Warnung aus DP107: 2 = fehlt, 0 = Warnung zurückgesetzt. Alte, fehlende oder unbekannte Meldungen sind nicht „OK“. |
| `binary_sensor` Filterkorb reinigen | Erinnerung nach bestätigtem Abschluss, auch nach manuellem Parken; zurückgesetzt bei erkanntem Entnehmen oder abgeleitetem Ausschalten. |
| `switch` Ladestation | Bedient direkt die hinterlegte Steckdose; Status wird von ihr übernommen. |
| `switch` Fertigmeldung | Optional an Smartphone oder Telegram; Telegram auch mit eigenem hochgeladenem Bild. Standardmäßig aus. |
| `sensor` Ladeplanung | Zwei Stunden Wartezeit ab Abschluss bei letztem Akkuwert unter dem Ladeziel, geplanter Ladestart und manueller Betrieb. |
| `sensor` Zeit bis Laden | Countdown im Format `02:00:00`, aktualisiert im normalen Abfragezyklus. |

„Parken“ meint das Parken des Roboters am Beckenrand, **nicht** die Rückkehr in eine Land-Ladestation. Ab 0.3.9 wird Parken frühestens **zehn Minuten nach dem lokal erkannten Reinigungsbeginn** (`cleaning`/`diving`) verfügbar. Die Grenze gilt auch für direkte Parkanfragen und das Senden des Befehls. Im Boden-, ECO- und Bereichsprogramm mit Wand x0 bleibt die Schaltfläche gesperrt. Ein Parkauftrag wird nur während eines gemeldeten aktiven Reinigungsvorgangs und mit einer Positionsmeldung „im Becken“ gesendet. Währenddessen fragt HA alle drei Sekunden lokal an; ein nicht bestätigter Befehl wird höchstens alle 15 Sekunden erneut gesendet. Der Auftrag endet bei einem expliziten `clean_done`-/`dock`-Status **oder einer frischen gemeinsamen Meldung `standby` und DP154 = 0 (Bereit außerhalb des Wassers)** und läuft nach acht Stunden ab. Der Status `auto_dock` hält weitere Sendungen zunächst an und wird als „Geparkt“ angezeigt.

Beim bestätigten trockenen „Bereit“ werden der offene Parkauftrag und seine Zeitstempel zurückgesetzt, die Programmauswahl wieder freigegeben und der Zustand gespeichert. Gespeicherte Altwerte, WLAN-Ausfall und `standby` im Wasser reichen dafür nicht aus. Eine erneute Modusauswahl ist kein Abbruchbefehl. Die Zehn-Minuten-Uhr ist unabhängig von der Lernhistorie und bleibt bei WLAN-Lücken/Pausen erhalten; bei gespeicherten aktiven Zuständen wird sie über Neustarts wiederhergestellt. Ohne bekannten Beginn wartet HA konservativ zehn Minuten ab der ersten neuen `cleaning`-/`diving`-Meldung. Ein neuer Lauf nach bestätigtem „Bereit“ beginnt mit neuer Wartezeit.

## Installation und Einrichtung

1. In **HACS → Benutzerdefinierte Repositories** `https://github.com/JS-DE-Tech/hacs-beatbot-aquasense2-local` mit Kategorie **Integration** hinzufügen. **Beatbot AquaSense 2 Local** herunterladen und HA vollständig neu starten. Alternativ das [Release-Paket](https://github.com/JS-DE-Tech/hacs-beatbot-aquasense2-local/releases/latest) entpacken und den vollständigen Ordner `custom_components/beatbot_aquasense2_local` in die HA-Konfiguration kopieren. Nicht den gesamten Repository-Ordner unter `custom_components` ablegen.
2. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **Beatbot AquaSense 2 Local** suchen.
3. Den Roboter eingeschaltet und im gleichen LAN/VLAN wie Home Assistant halten. Die Einrichtung sucht nach der belegten AquaSense-2-Produktkennung. Falls nötig, Roboter-ID und LAN-IP eingeben. Die ID ist in der Beatbot-App unter Roboter → Einstellung → Mehr sichtbar.
4. **Schlüsseldatei importieren** wählen und die eigene `.beatbot-key.json` hochladen, oder **Lokalen Schlüssel manuell eingeben** wählen. Der lokale Tuya-Schlüssel hat 16 Zeichen. Er ist ein Gerätegeheimnis, kein Beatbot-Kontopasswort. Der Schlüssel wird in der privaten Home-Assistant-Konfiguration gespeichert und gehört niemals ins Repository. Ohne diesen Schlüssel ist die lokale Steuerung nicht möglich; die LAN-Suche allein liefert ihn nicht. Beim Dateiimport werden Format, Modell und Schlüssel geprüft, dann wird die lokale Verbindung zum gefundenen Roboter getestet. Die temporäre Upload-Kopie wird nach dem Lesen gelöscht. Bei einer Verbindungsstörung kann derselbe Import im Dialog erneut geprüft werden.
5. In den Optionen dieser Integration bei Bedarf die vorhandene `switch.*`-Entität der Ladestation auswählen, etwa einen Shelly Plug. Jede Schalter-Entität lässt sich nur einem Roboter zuordnen.

Sobald HA sieht, dass die Steckdose eingeschaltet wurde, wartet die Ladeüberwachung auf einen *neuen* Akkustand des Roboters. Bei 80 % bzw. 100 % wird `switch.turn_off` auf genau diese Entität ausgeführt. Wenn der Roboter nicht erreichbar ist oder der Schalter `unavailable` meldet, bleibt die Steckdose eingeschaltet; ein alter gespeicherter Akkustand löst kein Abschalten aus. Die Ladeüberwachung prüft den HA-Schalterzustand, nicht die Leistungsmessung des Shelly.

## Schlüssel gewinnen, in KeePass aufbewahren und importieren

**Neu hier? Zuerst die vollständige [Anleitung zum lokalen Schlüssel](docs/LOCAL_KEY.md) lesen.** Sie erklärt Downloads, BlueStacks/Android, ADB-Verbindung, Roboter-ID, Export, HA-Import, KeePass und typische Fehler. Die folgenden Absätze sind die Kurzreferenz. Ein Beatbot-Kontopasswort, die UUID oder Seriennummer ersetzt den lokalen Schlüssel nicht.

Die Integration kann einen unbekannten Schlüssel nicht per LAN-Suche auslesen. Bei unserer getesteten Beatbot-Android-App 2.4.1 erschien `localKey` zusammen mit `devId` beim Start der angemeldeten App in Androids Diagnosemeldungen. Das ist kein offizieller Exportweg und kann bei anderen App-Versionen fehlen. Für den Nachweis wurde die vorhandene App in BlueStacks verwendet; erneutes Koppeln des Roboters ist dafür nicht erforderlich.

Für andere Nutzer: Android-App auf einem eigenen Gerät oder Emulator anmelden, das Gerät über ADB verbinden und die Debugging-Freigabe bestätigen. Die Roboter-ID steht in Beatbot unter Einstellungen → Mehr. App schließen und erneut öffnen, Roboter auswählen und zeitnah den Export ausführen: Die relevanten Meldungen können schnell aus dem Protokollpuffer verschwinden. `adb devices` zeigt die Gerätekennung. Das Werkzeug liest die Protokolle im Arbeitsspeicher und exportiert ausschließlich den Schlüssel der angegebenen Roboter-ID. Es speichert keine Rohprotokolle oder Kontotoken.

Beispiel mit Python 3 und Android Platform Tools, aus dem Projektordner gestartet; Pfade und ID ersetzen:

```text
python tools/export_beatbot_key.py --adb "C:\Android\platform-tools\adb.exe" --serial "127.0.0.1:5555" --device-id "ROBOTER_ID" --output "C:\Users\NAME\Downloads\Roboter.beatbot-key.json" --keepass "C:\Users\NAME\Downloads\Roboter.keepass.xml"
```

Die optionale KeePass-Datei wird über **Datei → Importieren → KeePass XML (2.x)** in die eigene entsperrte Datenbank importiert. Sie enthält einen Eintrag in der Gruppe „Beatbot“ mit Roboter-ID als Benutzername, lokalem Schlüssel als Passwort und der vollständigen HA-JSON-Datei als Anhang. Die JSON-Datei lässt sich später aus dem Anhang speichern und in HA importieren. Ein Master-Passwort wird für die Erstellung nicht benötigt. Das bestehende KeePass wird vom Exportwerkzeug nicht verändert. Die XML ist eine Eintrags-Importdatei, keine KeePass-Master-Schlüsseldatei.

Beide Exporte sind **unverschlüsselt**. Außerhalb von Git aufbewahren; nach erfolgreichem Import und Speichern der KeePass-Datenbank können die losen Exportdateien gelöscht werden. KeePass speichert Passwort und Anhang anschließend in seiner verschlüsselten Datenbank. Der Export verweigert vorhandene Zieldateien und Pfade innerhalb eines Git-Repositories. Die Dateiendungen sind zusätzlich in `.gitignore` gesperrt.

Wenn die lokale Integration bereits eingerichtet ist, liegt der eingegebene Schlüssel in deren privatem HA-Konfigurationseintrag. Mit administrativem Dateizugriff auf HA kann derselbe Export ihn auslesen, ohne ihn auf der Konsole anzuzeigen. Beispiel direkt in einer Umgebung mit Zugriff auf `/config` und Python:

```text
python tools/export_beatbot_key.py --ha-config /config/.storage/core.config_entries --device-id ROBOTER_ID --output /config/Roboter.beatbot-key.json --keepass /config/Roboter.keepass.xml
```

Die Datei `core.config_entries` enthält auch Zugangsdaten anderer Integrationen: nicht hochladen oder ins Repository kopieren. Das Werkzeug liest nur den passenden Beatbot-Eintrag. Es bietet keinen ungeschützten Web-Endpunkt für Schlüssel. Quellen: [KeePass Import/Export](https://keepass.info/help/base/importexport.html), [TinyTuya-Schlüsselbeschaffung und Änderungen beim erneuten Koppeln](https://github.com/jasonacox/tinytuya#setup-wizard---getting-local-keys).

## Filterkorb-Warnung

Ab 0.3.8 gibt es am Roboter eine zusätzliche Problem-Entität **„Filterkorb fehlt“**. Beim kontrollierten Vergleich am 2. Oktober 2026 zeigte die Beatbot-App mit entnommenem Korb „Filterkorb nicht eingesetzt“. Lokale, ausschließlich lesende Tuya-Abfragen bestätigten jeweils mehrfach **DP107 = 2** ohne Korb und **DP107 = 0** mit eingesetztem Korb. Zur Prüfung wurde keine Reinigung gestartet und kein Steuerbefehl gesendet.

Die Entität ist eingeschaltet bei 2 und ausgeschaltet bei 0. Andere Werte, kombinierte Fehlerflags oder falsche Datentypen werden nicht geraten und ergeben „nicht verfügbar“. Es ist noch nicht belegt, wie DP107 bei gleichzeitig auftretenden weiteren Fehlern kodiert wird. Ebenso wird bei Verbindungsverlust oder einem mehr als 90 Sekunden alten DP107-Wert kein aktuelles „OK“ angezeigt. Fehlendes DP107 in einer sonst erfolgreichen Statusantwort löscht die letzte Warnung nicht und erneuert ihre Zeit nicht.

Der letzte Rohcode und sein Zeitstempel werden gespeichert; die Attribute `raw_fault_code`, `last_known_filter_basket_missing`, `last_seen` und `stale` bleiben für die Diagnose verfügbar. Ein gespeicherter Code allein macht die Warnentität nach Neustart noch nicht verfügbar: Erst frische lokale Rückmeldung genügt. Die Filterkorb-Warnung startet/stoppt keine Reinigung, ändert keine Programmauswahl und schaltet nicht die Ladestation. Ein eigener Dashboard-Banner oder eine Push-Benachrichtigung muss diese Entität verwenden; das bestehende Dashboard wird nicht automatisch umgebaut.

## Automatisches Laden nach Abkühlzeit


Ab 0.4.0 löst ein erkannter Abschluss die Ladeplanung unabhängig vom Laufzeitlernen aus: `emerge` → `auto_dock` binnen zehn Minuten (auch nach HA-Parken und bei anderen Modi) oder `clean_done` nach beobachteter Aktivität. Ein kurzer `standby` im Wasser darf dazwischen liegen. Wiederholte Abschlussmeldungen und Neustarts lösen denselben Abschluss nicht nochmals aus. Ein einzelnes `auto_dock` ohne vorangehendes Auftauchen genügt nicht. Für das Lernen gelten weiterhin die strengeren, unten beschriebenen Bedingungen.

1. Den letzten bekannten Akkuwert mit dem gewählten Ladeziel **80 % oder 100 %** vergleichen. Bei einem bereits ausgeschalteten Roboter bleibt der gespeicherte Wert verwendbar. Ist überhaupt kein Wert bekannt, wartet die Planung darauf.
2. Liegt der Wert **unter dem Ladeziel**, sofort **zwei Stunden** Wartezeit starten. Eine Ruhe-/Ausschaltmeldung wird hierfür nicht benötigt. Bei fehlendem Akkuwert beginnen die vollen zwei Stunden erst, sobald die Prüfung möglich ist.
3. Anschließend die hinterlegte Ladesteckdose einschalten und mit **frischen** Akkuwerten bis zum gewählten Ladeziel überwachen; danach ausschalten. Es wird nicht geprüft, ob der Roboter physisch im Dock steht.

Der Sensor „Ladeplanung“ enthält `scheduled_start` und `remaining_seconds`; „Zeit bis Laden“ zeigt den Countdown als Stunden:Minuten:Sekunden. Die Prüfung erfolgt im normalen Abfragezyklus, deshalb kann das Einschalten etwas nach dem Termin erfolgen. Ein neu erkannter Reinigungslauf (`cleaning`, `diving`, `clean_wait`) verwirft den wartenden Plan. Erst dessen neuer Abschluss mit erneuter Akkuprüfung startet wieder die vollen zwei Stunden. Nach einem HA-Ausfall wird ein überfälliger, noch gültiger Plan beim nächsten Prüfen ausgeführt. Bei nicht erreichbarer Steckdose bleibt er wartend. Ein beim Neustart unklarer Einschaltbefehl (`start_uncertain`) wird nicht blind wiederholt. Beim Update werden alte Vier-Stunden-/Ruhemodus-Pläne verworfen, da ihnen der passende Abschlusszeitpunkt fehlt; der nächste erkannte Abschluss aktiviert die neue Planung.

„Ladestation“ kann jederzeit manuell ein- und ausgeschaltet werden und bedient ausschließlich den zugeordneten Schalter. Manuelle Befehle über diese Entität verwerfen einen wartenden Ladeplan; echte Ein-/Aus-Zustandswechsel der Steckdose ebenfalls. Ein erneuter Aus-Befehl direkt an eine bereits ausgeschaltete Originalsteckdose ist ohne Zustandswechsel nicht erkennbar: Zum sicheren Abbrechen den Beatbot-Ladestationsschalter verwenden. Beim manuellen Einschalten wird die Abkühlzeit bewusst übersprungen, das Ladeziel bleibt wirksam. Als Zuordnung ist die echte Steckdose zu wählen, niemals ein Beatbot-Proxy-Schalter.

## Filterkorb reinigen, Ausgeschaltet und Fertigmeldung

Ein bestätigter Abschluss setzt die persistente Erinnerung **Filterkorb reinigen**. Eine frische DP107-Meldung 2 (Korb entnommen) löscht sie. Alternativ wird sie gelöscht, wenn der Roboter als ausgeschaltet abgeleitet wird: mindestens fünf Minuten lang erfolglose Abfragen und zuletzt `standby`, `sleep`, `charge_done`, `clean_done`, `auto_dock` oder `dock`. Reinigen, Tauchen, Auftauchen, Pause und unbekannte Zustände sind ausgeschlossen. `sleep` allein ist keine Voraussetzung und setzt die Erinnerung noch nicht zurück.

Der vorhandene Sensor **Reinigungsstatus** zeigt dann „Ausgeschaltet“. Das ist eine Annahme aus Status und Erreichbarkeit; auch eine Netzwerkstörung kann sie auslösen. Die Attribute `inferred_off`, `inference` und `last_reported_status` machen das sichtbar; der technische Roboterstatus bleibt unverändert. Nach erfolgreicher Abfrage endet die Ableitung sofort. Nach HA-Neustart werden erneut fünf Minuten erfolglose Abfragen abgewartet.

Für Benachrichtigungen unter **Konfigurieren → Ladestation und Fertigmeldung** ein Smartphone (registrierter `notify.mobile_app_*`-Dienst der HA-App) oder **Telegram** auswählen und am Roboter den Schalter **Fertigmeldung** einschalten. Ab 0.4.3 lautet der Nachrichtentext für beide Ziele exakt:

```text
✅ Beatbot fertig.
AquaSense 2 - Gewähltes Programm beendet.
```

„Gewähltes Programm“ ist hier bewusst der gewünschte feste Text, kein Platzhalter. Akkuwert und Filterhinweis werden nicht mehr an die Nachricht angehängt; ihre Entitäten bleiben unverändert. Standardeinstellung des Schalters ist aus. Der Abschluss wird vor dem Senden gespeichert; Neustarts wiederholen die Nachricht nicht. Pro erkanntem Abschluss maximal ein Zustellversuch. Fehler werden ohne Empfänger-/Token-Daten protokolliert, nicht automatisch wiederholt. Kein Testversand beim Speichern oder Einschalten des Schalters; echte Zustellung nach Installation noch prüfen.

### Telegram und eigenes Bild (ab 0.4.3)

1. Die offizielle [Telegram-Bot-Integration](https://www.home-assistant.io/integrations/telegram_bot) in HA einrichten, den Bot in Telegram mit `/start` kontaktieren und die gewünschte Chat-ID beim Bot in HA freigeben. Der Bot-Token gehört ausschließlich in diese HA-Integration, nicht in Beatbot.
2. In den Beatbot-Optionen **Telegram** wählen und eine einzelne numerische **Chat-ID** einfügen. Negative Gruppen-IDs sind erlaubt. Bei genau einem eingerichteten Bot wird dieser ausgewählt; bei mehreren den richtigen Bot ausdrücklich wählen. Bot und Empfänger werden beim Senden explizit angegeben, niemals der erste/default Chat verwendet.
3. Optional unter **Eigenes Telegram-Bild hochladen / ersetzen** ein eigenes JPG/PNG auswählen (maximal 10 MiB). Kein neuer Upload behält das bisherige Bild. Das Feld **Gespeichertes Bild nicht mehr verwenden** schaltet zurück auf Textnachrichten. Nicht gleichzeitig hochladen und entfernen.
4. Speichern und **Fertigmeldung** einschalten. Mit Bild ruft die Integration [`telegram_bot.send_photo`](https://www.home-assistant.io/actions/telegram_bot.send_photo/) auf: eine Fotonachricht mit obigem Text als Bildunterschrift. Ohne Bild verwendet sie `telegram_bot.send_message`. `plain_text` verhindert unbeabsichtigte Markdown-Formatierung. Smartphone-Push bleibt eine Textbenachrichtigung; das Telegram-Bild wird dort nicht angehängt.

Der Upload wird mit Größen-/Dateisignaturprüfung im Executor verarbeitet und atomar unter `<HA-Konfigurationsordner>/beatbot_aquasense2_local/notification_images/` abgelegt. Er bleibt außerhalb des Integrationscodes, des GitHub-Repositories und öffentlich erreichbarer `www`-/HTTP-Pfade. Nur dieser dedizierte Bildordner wird beim Fotoversand für HA-Dateizugriff freigegeben; es ist keine manuelle globale `/config`-Freigabe nötig. Vor dem Senden werden Ablageort und Inhalts-Prüfsumme erneut geprüft. Telegram erhält das Bild erst bei aktivierter Fertigmeldung und erkanntem Abschluss. Bitte nur für Telegram bestimmte Bilder in diesem Ordner speichern.

Alte Bilder werden beim Ersetzen/Deaktivieren absichtlich nicht automatisch gelöscht (Rückfallsicherheit und mögliche gemeinsame Nutzung); die Optionen referenzieren nur das aktuell gewählte Bild. Sie bleiben in HA/Backups und können bei Bedarf gezielt als Dateien bereinigt werden. Für Umzug/Backup sowohl diesen privaten Ordner als auch die HA-Konfiguration sichern; beim Wechsel des Konfigurationspfads das Bild erneut hochladen. Fehlende/veränderte Dateien oder Versandfehler führen zu einer Warnung im Log, ohne zweiten Text-/Foto-Versuch oder anderen Empfänger. Ein beschädigtes Bild kann trotz passender Signatur von Telegram abgewiesen werden.

## Laufzeiten ansehen, bearbeiten, exportieren und importieren

**Konfigurieren → Laufzeiten ansehen und bearbeiten** zeigt alle 14 Kombinationen mit Anzahl der Zeitproben und aktueller Schätzung. Nach Auswahl einer Kombination lassen sich die letzten maximal zehn einzelnen Laufzeiten ändern: eine Minutenangabe pro Zeile, Dezimalstellen erlaubt, 1 bis 720 Minuten. Leeren löscht die Zeitproben dieser Kombination. Akku-Messwerte bleiben dabei erhalten.

Eine optionale **manuelle geschätzte Dauer** gilt sofort, auch ohne zwei Messläufe. Sie hat dauerhaft Vorrang, während neue Läufe weiter gesammelt werden. Das Feld leeren, um wieder die automatische Schätzung zu verwenden. Manuelle Schätzungen erzeugen keine fiktiven abgeschlossenen Läufe. Änderungen werden sofort gespeichert; während einer Reinigung oder beim Stop sind sie gesperrt.

**Laufzeiten exportieren** erzeugt einen authentifizierten Download-Link (fünf Minuten gültig, HA-Administrator erforderlich). Die JSON-Datei enthält alle Kombinationen, Zeit-/Akku-Proben, manuelle Schätzungen und Import-Deduplizierung, aber keinen lokalen Schlüssel. Die Roboter-ID dient der Zuordnung. Unter **Laufzeiten importieren** können ältere bestätigte Proben-Dateien weiterhin ergänzt werden. Ein vollständiger Export ersetzt nach expliziter Bestätigung die gesamte Lernhistorie dieses Roboters; deshalb vorher bei Bedarf exportieren. Andere Roboter-IDs, ungültige Zeiten oder unvollständige Backups werden abgewiesen. Export/Import und manuelle Bearbeitung ändern weder Ladesteckdose noch Push-Ziel und lösen keinen Reload aus.

## Laufzeitlernen und spätere App-ähnliche Darstellung

Jeder Roboter lernt getrennt für Boden, Standard, ECO, alle acht Bereich-Kombinationen und die drei MultiZone-Dauern – **14 Programmvarianten**. Bereich mit Wand x0 zählt auch für die Parksperre als reine Bodenreinigung. Änderungen an den Zusatzoptionen werden wie die Modusvorwahl erst im Ruhezustand gesendet und starten keine Reinigung. Die neuen Zusatz-Datenpunkte sind aus dem offiziellen App-Panel abgeleitet, aber noch nicht am Roboter live getestet.

Ab **zwei verwertbaren abgeschlossenen Läufen** erscheint eine vorläufige Schätzung, ab drei Läufen der Lernstatus `learned`. Grundlage ist der Median der letzten höchstens zehn Läufe dieser exakten Kombination; keine Übertragung auf bisher unbekannte Kombinationen. Die Auswahl zeigt ihre gelernte Gesamtdauer bereits vor dem nächsten Lauf. Der laufende Auftrag behält seine eigene Programmkennung, auch wenn bereits ein anderes Programm vorgewählt wird. Die Historie wird dauerhaft im privaten HA-Speicher pro Roboter gespeichert.

Wichtig: Die Integration muss Beginn, genaue Kombination und Abschluss verlässlich erkennen. Hierfür wird beim Start ein vollständiger Programmdatensatz benötigt (DP132; bei Bereich außerdem DP106/114/115, bei MultiZone DP131). Fehlt DP132 beim Start vollständig, darf eine höchstens 90 Sekunden alte vollständige lokale Bestätigung im selben HA-Betrieb verwendet werden. Eine bloße Vorwahl oder gespeicherte Auswahl genügt nicht. Ein Einstieg mitten im Lauf, ein HA-Neustart während des Laufs, Pausen, HA-Parkaufträge, unbekannte/wechselnde Programmdaten werden **nicht** als Trainingslauf gewertet. Vor Start und vor `clean_done` darf die jeweils letzte Statusbeobachtung höchstens 90 Sekunden zurückliegen. Längere WLAN-Lücken dazwischen sind zulässig. Die geräteseitige Laufzeit DP9 wird mangels Live-Verifikation ihres Lebenszyklus noch nicht verwendet.

**Neu in 0.3.7:** Bei den zwei beobachteten Bodenläufen vom 2. Oktober 2026 kam kein `clean_done`. Stattdessen wurde nach `cleaning`/`diving` zuerst `emerge` (Schwebend / schwimmt zum Rand) und dann `auto_dock` (Geparkt / hält am Rand) gemeldet. Nur für **Boden** beendet diese natürliche Folge einen bekannten, nicht unterbrochenen Trainingslauf. Das Ende liegt beim Empfang von `auto_dock`, nicht beim Herausheben oder späteren Ruhemodus. Ein kurzer `standby` im Wasser zwischen Auftauchen und Parken bleibt Teil desselben Laufs; `standby` außerhalb des Wassers zeigt danach „Bereit“. Das letzte Auftauchen muss innerhalb von zehn Minuten vor dem Parkstatus beobachtet worden sein. Diese konservative Plausibilitätsgrenze ist keine Herstellerangabe. `auto_dock` allein, WLAN-Ausfall und abgelaufene Restzeit sind kein Abschlussnachweis. Andere Modi behalten ihre bisherige Abschlussregel. Nicht beobachtete Unterbrechungen oder Parkbefehle außerhalb HA lassen sich nicht zuverlässig ausschließen.

### Bestätigte Messwerte importieren

Unter **Einstellungen → Geräte & Dienste → Beatbot AquaSense 2 Local → Konfigurieren → Laufzeiten importieren** lassen sich weiterhin bestätigte Einzelproben ergänzen. Nur im Ruhezustand importieren; der Import benötigt keinen Reload und verändert die Ladesteckdose nicht. Während einer erkannten Reinigung oder beim Stop wird er abgewiesen. Die Messwerte werden sofort gespeichert, nicht in die Konfigurationsoptionen geschrieben. Keine Dateien in `.storage` manuell ändern.

Format für ergänzende Proben (maximal 128 KiB, höchstens 100 Proben; `device_id` durch die eigene ID ersetzen):

```json
{
  "format": "beatbot-runtime-v1",
  "device_id": "EIGENE_ROBOTER_ID",
  "samples": [
    {
      "id": "eindeutiger-lauf-2026-10-02-1",
      "confirmed": true,
      "program": {"mode": "Boden"},
      "duration_seconds": 3600
    }
  ]
}
```

Die Datei enthält **keinen** lokalen Schlüssel und ist keine Schlüsseldatei. Der Import prüft die Roboter-ID, Programmoptionen, Grenzen und jede Probe vor dem Speichern. Gleiche Proben-IDs werden über Neustarts hinweg nicht doppelt gezählt; widersprüchliche IDs werden abgewiesen. Bereits vorhandene Lernhistorie bleibt erhalten. Bei Bereich müssen `floor` und `wall`, bei MultiZone `duration` ausdrücklich angegeben werden. Optional lassen sich **bestätigte** ganzzahlige `start_battery` und `end_battery` ergänzen (0–100, Ende nicht höher als Start). Fehlende Akkuwerte bleiben unbekannt.

Laufzeit und Verbrauch hängen unter anderem von Poolgröße, Form und Zustand ab. Deshalb enthält die Integration **keine vorbelegten Messwerte**. Jeder Nutzer lernt mit seinem eigenen Roboter und Pool oder importiert seine eigenen bestätigten Läufe. Die Beispieldauer oben ist nur eine Formatillustration. Beobachtungszeiten aus App-Aufzeichnungen können verzögert und damit ungenau sein. Fehlen verlässliche Akku-Messpaare, darf die persönliche Importdatei nur Zeitproben enthalten. Bei einem Wechsel des Pools sollte eine neue Lernhistorie begonnen werden. Der Editor löscht bei leeren Zeitfeldern nur Zeitproben/Schätzungen; Akku-Proben lassen sich über einen entsprechend angepassten vollständigen Export mit bestätigtem Ersetzen zurücksetzen.

### Akkuverbrauch und Warnschwelle

Ein verwertbarer Lauf lernt zusätzlich den Verbrauch, **wenn** Anfang und Ende einen frischen DP6-Wert liefern. Am Anfang ist auch ein höchstens 90 Sekunden alter Wert aus dem unmittelbar vorhergehenden Bereitschaftszustand zulässig. Fehlende oder steigende Werte werden nicht ergänzt; ein Lauf kann deshalb eine Zeitprobe, aber keine Akkuprobe liefern. Wartezeit am Rand, Abholung und Laden zählen nicht zum Verbrauch. Historie pro Roboter und Programmkombination: höchstens zehn Akku-Proben, persistent über Neustarts.

Ab zwei Akku-Proben zeigt „Geschätzter Akkuverbrauch“ deren Median in **Prozentpunkten** (nicht Wh). „Akku für Programm zu niedrig“ wird aktiv, wenn der frische Akkustand unter dem höchsten Verbrauch der letzten zehn passenden Proben plus **fünf Prozentpunkten Reserve** liegt. Bei zu wenigen Proben, unbekanntem Akkustand, WLAN-Ausfall oder einem mehr als 90 Sekunden alten Akkuwert ist diese Warnentität nicht verfügbar – nicht irreführend „aus“. Ein frischer anderer Status ohne DP6 erneuert die Akku-Frische nicht. Die Verbrauchsschätzung selbst bleibt offline sichtbar. „Keine Warnung“ ist keine Garantie ausreichender Laufzeit: Poolzustand, Akku-Alterung und Temperatur können den Verbrauch ändern. Die Warnung startet/stoppt weder Roboter noch Steckdose; Ladeziel und Abkühlregeln bleiben getrennt.

Die Restzeit ist eine **Schätzung**, keine Fertigmeldung. Bei Überschreitung bleibt sie bei 0 Minuten und setzt `overdue: true`; ein Abschluss erfordert weiterhin Rückmeldung vom Roboter. Bei einem unsicheren oder unterbrochenen Lauf bleibt die Restzeit unbekannt. Die Sensorattribute `program`, `sample_count`, `learning_state`, `min_seconds`, `max_seconds` und `robot_online` dienen der späteren Dashboard-Karte. Beispielkennung: `Bereich:floor=2:wall=1`. `learning_state` unterscheidet `learning`, `preliminary` und `learned`.

Die Auswahl- und Statusentitäten sind die Grundlage für die gewünschte App-ähnliche Karte mit ausklappbaren Modusoptionen. Das bestehende Pool-Dashboard wird durch diese Version noch nicht verändert.

## Statusanzeige ab 0.4.2

Der technische Sensor „Roboterstatus“ behält seine englischen Werte. „Reinigungsstatus“ zeigt folgende Bezeichnungen. Die Anzeige steuert weder Abschluss-Erkennung noch Laufzeitlernen, Parken oder Laden.

| Roboterstatus | Reinigungsstatus | Am Testroboter bestätigt |
|---|---|---|
| `standby` | Bereit | Ja |
| `sleep` | Ruhemodus | Ja |
| `charging` | Lädt | Ja |
| `charge_done` | Vollständig geladen | Nein |
| `goto_charge` | Laderückkehr – unbestätigt | Nein |
| `cleaning` | Reinigt | Ja |
| `diving` | Reinigt – taucht ab | Ja |
| `clean_wait` | Wartet auf Reinigung | Nein |
| `paused` | Pausiert | Nein |
| `return_trip` | Rückkehr läuft | Nein |
| `emerge` | Aufgetaucht – fährt zum Rand | Ja |
| `auto_dock` | Geparkt am Beckenrand | Ja |
| `clean_done` | Reinigung abgeschlossen | Nein |
| `dock` | Dockstatus – unbestätigt | Nein |
| `remote_control` | Manuelle Steuerung | Nein |
| `wifi_connect` | WLAN-Verbindung wird hergestellt | Nein |

Nicht bestätigte Bezeichnungen sind aus den Protokollnamen abgeleitet, nicht durch neue Gerätetests belegt. Insbesondere bestätigen `goto_charge` und `dock` **keine autonome Fahrt zur Land-Ladestation**. Das Attribut `status_mapping_verified` kennzeichnet, ob der zuletzt gemeldete technische Status am Testroboter bestätigt wurde; es ist kein Frischeindikator. Dafür dienen `stale` und `last_seen`.

Ein kurzzeitiges `standby` während des beobachteten Laufs/Auftauchens im Wasser überschreibt die laufende Anzeige nicht. Nach Abschluss bleibt die Abschluss-/Parkanzeige bei `standby` ohne aktuelle Bestätigung „außerhalb des Wassers“ erhalten. Eine frische Rückmeldung `sleep` zeigt dagegen immer „Ruhemodus“.

Nach fünf Minuten unerreichbar mit zuletzt bekanntem Ruhe-/Endstatus erscheint wie bisher **„Ausgeschaltet“ (abgeleitet)**. Laufende Reinigung, Tauchen, Auftauchen, Pause und Rückkehr sind davon ausgeschlossen. WLAN-Verlust ist kein bewiesenes Ausschalten; der Rohstatus bleibt erhalten. Gespeicherte Anzeigen werden beim Upgrade migriert und offline als alte Werte gekennzeichnet; dabei werden keine Abschlussereignisse nachträglich ausgelöst.

**Hinweis für bestehende Dashboards/Automationen:** Die Entitäts-IDs bleiben gleich, aber mehrere deutsche Zustandswerte ändern sich, beispielsweise „Schwebend“ → „Aufgetaucht – fährt zum Rand“, „Geparkt“ → „Geparkt am Beckenrand“ und „Fertig“ → „Reinigung abgeschlossen“ (bei `clean_done`). Exakte Textvergleiche entsprechend anpassen oder den unveränderten technischen Roboterstatus verwenden. Das persönliche HA-Dashboard wird nicht automatisch verändert.

## Bisher verifiziert und offen

Am 3. Oktober 2026 wurde DP165 = 2 (`charging`) nach Einschalten der Ladestation durch den Nutzer sowohl in frischen Meldungen der BlueStacks-App als auch in wiederholten LAN-Abfragen bei 97 % Akku bestätigt. Der technische Roboterstatus erkannte diesen Code bereits; ab 0.4.1 zeigt auch der Reinigungsstatus „Lädt“. Ein anschließender Akkuanstieg und der Status `charge_done` sind durch diesen Vergleich noch nicht nachgewiesen.

Version 0.3.1 korrigiert einen Verbindungsfehler: TinyTuya interpretiert das Socket-Retry-Limit als Anzahl der Verbindungsversuche. Bei 0 wird kein Socket geöffnet; die Integration verwendet jetzt 1. Einrichtung und laufende Statusabfrage wurden auf Home Assistant Dev 2026.8.3 am AquaSense 2 erfolgreich geprüft (Akku, Ruhemodus und lokale Erreichbarkeit).

Am Testgerät wurden lokale Statusabfragen, Akku (DP6), Arbeitsstatus (DP165) und die Modi Boden, Standard, Bereich sowie MultiZone (DP132) bestätigt. Nach den Tests war Standard wieder ausgewählt. ECO ist nur aus dem App-Code abgeleitet, weil ein Live-Test ein automatisches Wiederholungsprogramm aktivieren könnte. Der Parkbefehl DP152 = 1 und seine Statuswerte stammen aus dem offiziellen App-Panel; **ein Parkvorgang im Wasser wurde noch nicht live geprüft**. Der lokale Status liefert DP132 nicht bei jeder Abfrage, daher kann ein in der Beatbot-App geänderter Modus nicht immer sofort nach HA übernommen werden. Die letzte bestätigte HA-Auswahl bleibt sichtbar.

Der Roboter war nach einem Test mit dem allgemeinen Aus-Datenpunkt weiterhin lokal erreichbar und wurde in der App als „Ruhemodus“ angezeigt. Ein vollständiges lokales Ausschalten ist hier nicht implementiert. Diese Integration enthält ebenfalls keinen Startknopf für eine Reinigung; die Modusauswahl ist ausdrücklich eine Vorauswahl.

## Entwicklung

Änderungen und Installations-/Abnahmeschritte stehen im [Changelog](CHANGELOG.md). Die isolierte Testsuite (`python -m unittest discover -s tests -q`) umfasst 180 erfolgreiche Tests und prüft u. a. echte asyncio-Tasks und Executor-Threads mit simulierten HA-Schnittstellen. Abschluss-Erkennung, Zwei-Stunden-Ladeplanung, Offline-Ableitung, Filterhinweis, Smartphone-/Telegram-Aufrufe, private Bild-Uploads, Laufzeiten-Editor, geschützter Export/Import und alle 16 Statusanzeigen samt Neustart/Migration werden getestet. DP107 und `charging` wurden zuvor zusätzlich live lokal am Testroboter abgefragt. Ein vollständiger HA-Prozesstest, die gerenderte Optionen-Oberfläche, echte Telegram-/Push-Zustellung und ein Reinigungslauf mit Version 0.4.3 stehen nach Installation noch aus.

Das Integrationspaket liegt unter `custom_components/beatbot_aquasense2_local`. Reale Schlüssel, Zugangsdaten, Cloud-Token, persönliche Laufdateien und Benachrichtigungsbilder gehören nicht ins Repository. Tests verwenden synthetische Zugangsdaten. Für Fehlermeldungen bitte [ein Issue öffnen](https://github.com/JS-DE-Tech/hacs-beatbot-aquasense2-local/issues) und nur bereinigte Logs sowie Integrations-/HA-/App-Version angeben – keine Schlüsseldatei oder komplette `.storage`-Datei anhängen.

## Lizenz, Bilder und Unterstützung

Quellcode: [MIT](LICENSE). Beatbot und AquaSense sind Marken ihrer jeweiligen Rechteinhaber; dieses Projekt ist nicht mit dem Hersteller verbunden. Produktabbildungen und Marken unterliegen gegebenenfalls gesonderten Rechten und werden nicht als eigene Marken beansprucht. Das README-Produktbild wurde aus der bereitgestellten Vorlage mit dem integrierten Bildwerkzeug freigestellt/rekonstruiert; kleine Detailabweichungen sind möglich. Der Dashboard-Screenshot zeigt die bereitgestellte Beispielinstallation. Siehe [Bildnachweise](docs/images/README.md).

Wenn dir das Projekt hilft: [Unterstützung via PayPal](https://paypal.me/JensSaffrich). Danke!
