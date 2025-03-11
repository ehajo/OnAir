import json
import time
import board
import neopixel
import wifi
import ssl
import socketpool
import adafruit_requests

# JSON-Dateien laden
def load_json(filename):
    with open(filename, "r") as file:
        return json.load(file)

# Zugangsdaten laden
secrets = load_json("secrets.json")
config = load_json("config.json")

# NeoPixel-Setup
pixel_pin = board.GP2
num_pixels = 50  # Anzahl der LEDs
pixels = neopixel.NeoPixel(pixel_pin, num_pixels, auto_write=False)

# Buchstabenbereiche definieren
letters = {
    "O": range(0, 10),   # LED1-LED10
    "N": range(10, 23),  # LED11-LED23
    "A": range(23, 33),  # LED24-LED33
    "I": range(33, 38),  # LED34-LED38
    "R": range(38, 50)   # LED39-LED50
}

# Twitch-Status speichern
last_online_channel = None

# Fehlerzustand: LEDs blinken rot
def error_effect():
    print("Error detected!")
    for _ in range(5):  # 2.5 Sekunden (5 Blinks à 0.5 Sekunden)
        pixels.fill([255, 0, 0])  # Rot
        pixels.show()
        time.sleep(0.25)
        pixels.fill([0, 0, 0])  # Aus
        pixels.show()
        time.sleep(0.25)

# Verbindungsaufnahme: LEDs leuchten langsam auf und ab in Gelb
def connecting_effect():
    print("Connecting to network...")
    for _ in range(3):  # Effekt für 3 Sekunden
        for brightness in range(0, 256, 10):  # Hochdimmen
            pixels.fill([brightness // 4, brightness // 4, 0])  # Gelb
            pixels.show()
            time.sleep(0.01)
        for brightness in range(255, -1, -10):  # Abdimmen
            pixels.fill([brightness // 4, brightness // 4, 0])  # Gelb
            pixels.show()
            time.sleep(0.01)

# Standby-Modus: Alle LEDs langsam faden
def standby_effect(offline_color):
    base_brightness = 0.2  # Grundhelligkeit (20 % der Offline-Farbe)
    pulse_range = 0.2  # Pulsieren um +/-20 % der Grundhelligkeit
    steps = 50  # Anzahl der Schritte pro Puls
    delay = 0.05  # Verzögerung zwischen den Schritten

    # Berechne einmalig die Starthelligkeit
    start_brightness = base_brightness
    adjusted_color = [int(c * start_brightness) for c in offline_color]
    pixels.fill(adjusted_color)
    pixels.show()

    # Puls-Schleife
    for brightness_factor in list(range(0, steps)) + list(range(steps, 0, -1)):
        brightness = base_brightness + pulse_range * (brightness_factor / steps)
        adjusted_color = [int(c * brightness) for c in offline_color]
        pixels.fill(adjusted_color)
        pixels.show()
        time.sleep(delay)

    # Setze die LEDs am Ende explizit auf die Starthelligkeit zurück
    adjusted_color = [int(c * base_brightness) for c in offline_color]
    pixels.fill(adjusted_color)
    pixels.show()

# Knight Rider Effekt für Buchstaben
def knight_rider_effect(letters, color, cycles=4):
    print("Knight Rider Effekt (Buchstaben)!")
    letter_keys = ["O", "N", "A", "I", "R"]  # Feste Reihenfolge der Buchstaben

    for _ in range(cycles):
        # Vorwärts durch die Buchstaben
        for key in letter_keys:
            pixels.fill([0, 0, 0])  # Alles aus
            for i in letters[key]:
                pixels[i] = color  # Buchstabe einschalten
            pixels.show()
            time.sleep(0.06)

        # Rückwärts durch die Buchstaben
        for key in reversed(letter_keys):
            pixels.fill([0, 0, 0])  # Alles aus
            for i in letters[key]:
                pixels[i] = color  # Buchstabe einschalten
            pixels.show()
            time.sleep(0.06)

# Twitch API-Endpunkt und Header
def is_channel_online(channel_name, requests):
    url = f"https://api.twitch.tv/helix/streams?user_login={channel_name}"
    headers = {
        "Client-ID": secrets["twitch"]["client_id"],
        "Authorization": f"Bearer {secrets['twitch']['access_token']}"
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return "data" in data and len(data["data"]) > 0
        elif response.status_code == 401:
            print(f"Twitch API error for {channel_name}: Invalid or expired access token (401)")
            return False
        elif response.status_code == 429:
            print(f"Twitch API error for {channel_name}: Rate limit exceeded (429)")
            return False
        else:
            print(f"Twitch API error for {channel_name}: Unexpected status code {response.status_code}")
            return False
    except Exception as e:
        print(f"Error checking Twitch channel {channel_name}: {e}")
        return False

# Setze die LEDs für die Buchstaben basierend auf der Konfiguration
def set_letter_colors(channel_config):
    for letter, indices in letters.items():
        color = channel_config["letters"].get(letter, {}).get("color", [0, 0, 0])
        brightness = channel_config["letters"].get(letter, {}).get("brightness", 0.5)
        for i in indices:
            # Passe Helligkeit an
            adjusted_color = [int(c * brightness) for c in color]
            pixels[i] = adjusted_color
    pixels.show()

# Funktion für Wiederholungsversuche der WLAN-Verbindung
def connect_to_wifi(max_retries=5, retry_delay=5):
    attempt = 0
    while attempt < max_retries:
        try:
            print(f"Connecting to WiFi: {secrets['wifi']['ssid']} (Attempt {attempt + 1}/{max_retries})...")
            wifi.radio.connect(secrets["wifi"]["ssid"], secrets["wifi"]["password"])
            print("Connected to WiFi!")
            return True  # Erfolgreich verbunden
        except Exception as e:
            print(f"WiFi connection failed: {e}")
            attempt += 1
            if attempt < max_retries:
                print(f"Retrying in {retry_delay} seconds...")
                error_effect()  # Zeige Fehlerzustand
                time.sleep(retry_delay)
            else:
                print("Max retries reached. Could not connect to WiFi.")
                return False  # Verbindung endgültig fehlgeschlagen

# Hauptprogramm
def main():
    global last_online_channel
    
    # WLAN-Verbindung mit Wiederholungslogik herstellen
    connecting_effect()  # Zeige Verbindungsaufnahme-Effekt EINMAL
    if not connect_to_wifi():
        # Wenn die Verbindung nach max_retries fehlschlägt, endlos im Fehlerzustand bleiben
        while True:
            print("Error-Modus")
            standby_effect([50, 0, 0])  # Standby-Modus
            time.sleep(5)
    
    # Socketpool und SSL-Kontext einrichten
    pool = socketpool.SocketPool(wifi.radio)
    ssl_context = ssl.create_default_context()
    requests = adafruit_requests.Session(pool, ssl_context)
    print("Ready to check Twitch status!")

    # Hauptloop
    while True:
        try:
            current_online_channel = None
            for channel in config["channels"]:
                if is_channel_online(channel["name"], requests):
                    current_online_channel = channel
                    break

            if current_online_channel:
                if current_online_channel != last_online_channel:
                    # Wechsel zu einem neuen Kanal
                    knight_rider_effect(letters, [255, 0, 0])  # Knight Rider Effekt in Rot
                    set_letter_colors(current_online_channel)  # Setze Farben und Helligkeit
                else:
                    set_letter_colors(current_online_channel)  # Halte die Farben aufrecht
            else:
                print("Standby-Modus")
                standby_effect(config["offline_color"])  # Standby-Modus

            last_online_channel = current_online_channel
            time.sleep(5)  # Verkürzte Pause für reaktionsschnelle Updates

        except Exception as e:
            print(f"Error in main loop: {e}")
            error_effect()  # Zeige Fehlerzustand
            time.sleep(5)  # Warte kurz vor erneutem Versuch
            # Prüfe WLAN-Verbindung und versuche Wiederverbindung
            if not wifi.radio.connected:
                print("WiFi disconnected. Attempting to reconnect...")
                if not connect_to_wifi():
                    print("Reconnection failed. Continuing in offline mode...")

# Programm starten
main()