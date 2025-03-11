# Twitch "ON AIR" LED-Anzeige

Dieses Projekt steuert eine WS2812-LED-Anzeige (NeoPixel) mit einem Raspberry Pi Pico W, um den Text "ON AIR" anzuzeigen, wenn ein konfigurierter Twitch-Streamer online geht. Die LEDs leuchten in einstellbaren Farben und Helligkeiten, basierend auf dem Status eines Twitch-Kanals, der über die Twitch-API abgefragt wird. Im Offline-Modus pulsiert die Anzeige in einer sanften grauen Farbe.

Dieses Repository enthält den Code, die Konfigurationsdateien und eine Anleitung zur Inbetriebnahme. Die Platine mit dem Raspberry Pi Pico W und der WS2812-LED-Streifen kann als fertiges Produkt erworben werden.
## Funktionen
- **ON AIR Anzeige**: Leuchtet, wenn ein konfigurierter Twitch-Streamer live ist.
- **Farbkonfiguration**: Jeder Buchstabe ("O", "N", "A", "I", "R") kann individuell mit Farbe und Helligkeit angepasst werden.
- **Effekte**:
  - Verbindungsaufnahme: LEDs pulsieren gelb.
  - Standby-Modus: LEDs pulsieren langsam in Grau.
  - Kanalwechsel: "Knight Rider"-Effekt in Rot.
  - Fehler: LEDs blinken rot.
- **Automatische Wiederverbindung**: Stellt die WLAN-Verbindung bei Ausfall automatisch wieder her.
## Hardware
- **Raspberry Pi Pico W**: Mikrocontroller mit WLAN-Funktion.
- **WS2812 LED-Streifen**: 50 LEDs, angeschlossen an Pin GP2 des Pico W.
- **Stromversorgung**: 5V über USB oder externe Quelle (abhängig von der Platine).

## Voraussetzungen
- Ein Computer (Windows, macOS oder Linux) zum Einrichten.
- Ein WLAN-Netzwerk mit Internetzugang.
- Ein Twitch-Entwicklerkonto zur Erstellung eines OAuth-Tokens.
---

## Einrichtung und Inbetriebnahme

### Schritt 1: CircuitPython auf dem Raspberry Pi Pico W installieren
1. **CircuitPython herunterladen**:
   - Gehe zu [circuitpython.org](https://circuitpython.org/board/raspberry_pi_pico_w/).
   - Lade die neueste `.uf2`-Datei für den "Raspberry Pi Pico W" herunter (z. B. `adafruit-circuitpython-raspberry_pi_pico_w-en_US-8.x.x.uf2`).

2. **Pico W in den Bootloader-Modus versetzen**:
   - Halte die **BOOTSEL**-Taste am Pico W gedrückt.
   - Verbinde den Pico W über ein USB-Kabel mit deinem Computer, während du die Taste gedrückt hältst.
   - Lasse die Taste los. Ein neues Laufwerk namens `RPI-RP2` sollte auf deinem Computer erscheinen.

3. **CircuitPython installieren**:
   - Ziehe die heruntergeladene `.uf2`-Datei auf das `RPI-RP2`-Laufwerk.
   - Das Laufwerk wird kurz darauf ausgeworfen, und der Pico W startet mit CircuitPython. Ein neues Laufwerk namens `CIRCUITPY` erscheint.

### Schritt 2: Benötigte Bibliotheken installieren
1. **Bibliotheken herunterladen**:
   - Lade die CircuitPython-Bibliotheken von [Adafruit CircuitPython Bundle](https://github.com/adafruit/Adafruit_CircuitPython_Bundle/releases) herunter (z. B. `adafruit-circuitpython-bundle-8.x-mpy-YYYYMMDD.zip`).
   - Entpacke die ZIP-Datei.

2. **Erforderliche Bibliotheken kopieren**:
   - Die libs befinden sich im lib-Ordner auf Twitch und stellen den Stand von Adafruit dar, mit dem die Software funktioniert. Für aktuellere libs:
   - Öffne das entpackte Verzeichnis und navigiere zum `lib`-Ordner.
   - Kopiere die folgenden Dateien/Ordner auf das `CIRCUITPY`-Laufwerk in den `lib`-Ordner (falls dieser nicht existiert, erstelle ihn):
     - `adafruit_requests.mpy`
     - `neopixel.mpy`
     - `adafruit_pixelbuf.mpy` (wird von `neopixel` benötigt)
	 - `adafruit_connection_manager.mpy`
   - Beispiel: `CIRCUITPY/lib/adafruit_requests.mpy`

### Schritt 3: Twitch OAuth-Token erstellen
1. **Twitch-Entwicklerkonto einrichten**:
   - Gehe zu [dev.twitch.tv](https://dev.twitch.tv/) und melde dich mit deinem Twitch-Konto an.
   - Klicke auf **"Your Console"** > **"Applications"** > **"Register Your Application"**.
   - Fülle die Felder aus:
     - Name: z. B. "TwitchOnAirLED"
     - OAuth Redirect URI: `http://localhost` (wird hier nicht wirklich benötigt)
     - Category: "Other"
   - Klicke auf **"Create"** und notiere dir die **Client-ID**.

2. **Access Token generieren**:
   - Öffne einen Browser und füge diese URL ein (ersetze `DEINE_CLIENT_ID` durch deine Client-ID):
   - URL: https://id.twitch.tv/oauth2/authorize?client_id=DEINE_CLIENT_ID&redirect_uri=http://localhost&response_type=token&scope=
   - Drücke Enter, melde dich bei Twitch an und autorisiere die Anwendung.
   - Du wirst zu einer leeren Seite weitergeleitet. Kopiere den `access_token` aus der URL in der Adressleiste (z. B. `http://localhost/#access_token=DEIN_TOKEN_HIER&...`). Der Token sieht aus wie eine zufällige Zeichenfolge (z. B. `abc123def456...`).
   ### Schritt 4: Projekt-Dateien auf den Pico W kopieren
1. **Repository herunterladen**:
   - Lade dieses GitHub-Repository als ZIP-Datei herunter und entpacke es, oder klone es mit Git:
   - Befehl: git clone https://github.com/[DEIN_USERNAME]/[DEIN_REPOSITORY].git

2. **Dateien anpassen**:
   - Öffne `secrets.json` und fülle die Felder mit deinen Daten:
   - Inhalt:
```
{
    "wifi": {
        "ssid": "DEIN_WLAN_NAME",
        "password": "DEIN_WLAN_PASSWORT"
        },
    "twitch": {
        "client_id": "DEINE_CLIENT_ID",
        "access_token": "DEIN_ACCESS_TOKEN"
    }
}
 ```
   - Öffne `config.json`, um die Twitch-Kanäle und Farben anzupassen (optional, Standardwerte funktionieren bereits):
   - Inhalt:
```
{
	"channels": [
		{
		"name": "ehajo",
			"letters": {
				"O": {"color": [255, 112, 45], "brightness": 0.3},
                "N": {"color": [0, 117, 179], "brightness": 0.3},
                "A": {"color": [0, 117, 179], "brightness": 0.3},
                "I": {"color": [0, 117, 179], "brightness": 0.3},
                "R": {"color": [0, 117, 179], "brightness": 0.3}
                }
		}
    ],
    "offline_color": [50, 50, 50]
}
```

3. **Dateien auf den Pico W kopieren**:
   - Kopiere die folgenden Dateien auf das `CIRCUITPY`-Laufwerk:
     - `code.py` (umbenannt aus der Haupt-Python-Datei, damit sie automatisch startet)
     - `secrets.json`
     - `config.json`

### Schritt 5: Gerät starten
1. **USB trennen und wieder verbinden**:
   - Trenne den Pico W vom Computer und verbinde ihn erneut (oder schließe ihn an eine 5V-Stromquelle an).
   - Der Code startet automatisch und die LEDs zeigen den Verbindungsaufbau (gelb pulsierend) an.

2. **Funktion prüfen**:
   - Sobald das WLAN verbunden ist, überprüft das Gerät die Twitch-Kanäle.
   - Wenn ein Streamer online ist, leuchtet "ON AIR" in den konfigurierten Farben.
   - Wenn kein Streamer online ist, pulsiert die Anzeige in Grau.
   ---

## Fehlerbehebung
- **LEDs blinken rot**: Fehler (z. B. kein WLAN oder Twitch-API-Problem). Überprüfe `secrets.json`.
- **Keine Reaktion**: Stelle sicher, dass `code.py` auf dem Pico W ist und CircuitPython korrekt installiert wurde.
- **Token abgelaufen**: Erstelle einen neuen Token (Schritt 3) und aktualisiere `secrets.json`.

---

## Anpassungen
- **Weitere Streamer hinzufügen**: Füge neue Objekte im `channels`-Array von `config.json` hinzu.
- **Farben ändern**: Passe die RGB-Werte (`[R, G, B]`) und `brightness` (0.0 bis 1.0) in `config.json` an.

---

## Lizenz
Dieses Projekt ist unter der [MIT-Lizenz](LICENSE) veröffentlicht. Du kannst es frei nutzen, modifizieren und weitergeben.

## Kontakt
Bei Fragen oder Problemen erstelle ein [Issue](https://github.com/ehajo/OnAir/issues)!

Happy Streaming!
