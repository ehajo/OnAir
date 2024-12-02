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

# WLAN-Verbindung herstellen
print(f"Connecting to WiFi: {secrets['wifi']['ssid']}...")
wifi.radio.connect(secrets["wifi"]["ssid"], secrets["wifi"]["password"])
print("Connected to WiFi!")

# NeoPixel-Setup
pixel_pin = board.GP2
num_pixels = 8  # Anzahl der LEDs
pixels = neopixel.NeoPixel(pixel_pin, num_pixels, brightness=0.5, auto_write=False)

# Socketpool und SSL-Kontext einrichten
pool = socketpool.SocketPool(wifi.radio)
ssl_context = ssl.create_default_context()
requests = adafruit_requests.Session(pool, ssl_context)

# Twitch-Status speichern
last_online_channel = None

# Schnelles Fading zwischen zwei Farben
def fade_between_colors(start_color, end_color, steps, duration):
    step_duration = duration / steps  # Zeit pro Schritt
    for step in range(steps):
        r = int(start_color[0] + (end_color[0] - start_color[0]) * (step / steps))
        g = int(start_color[1] + (end_color[1] - start_color[1]) * (step / steps))
        b = int(start_color[2] + (end_color[2] - start_color[2]) * (step / steps))
        pixels.fill((r, g, b))
        pixels.show()
        time.sleep(step_duration)

# Spezialeffekt für den Wechsel von Offline zu Online
def on_air_effect(online_color, offline_color):
    print("On-Air Effekt!")
    steps = 20  # Weniger Schritte für schnelleres Fading
    duration = 0.5  # Kürzere Dauer für einen Durchlauf (0.5 Sekunden)
    effect_duration = 5  # Gesamtdauer des Effekts (30 Sekunden)
    cycles = int(effect_duration / (duration * 2))  # Anzahl der Fading-Zyklen
    for _ in range(cycles):
        fade_between_colors(offline_color, online_color, steps, duration)
        fade_between_colors(online_color, offline_color, steps, duration)
    pixels.fill(online_color)
    pixels.show()

# Twitch API-Endpunkt und Header
def is_channel_online(channel_name):
    url = f"https://api.twitch.tv/helix/streams?user_login={channel_name}"
    headers = {
        "Client-ID": secrets["twitch"]["client_id"],
        "Authorization": f"Bearer {secrets['twitch']['access_token']}"
    }
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        return "data" in data and len(data["data"]) > 0
    except Exception as e:
        print(f"Error checking Twitch channel: {e}")
        return False

# Hauptprogramm
while True:
    try:
        current_online_channel = None
        for channel in config["channels"]:
            if is_channel_online(channel["name"]):
                current_online_channel = channel
                break

        if current_online_channel:
            if current_online_channel != last_online_channel:
                # Wechsel zu einem neuen Kanal
                on_air_effect(current_online_channel["color"], config["offline_color"])
            else:
                # Normale Anzeige
                pixels.fill(current_online_channel["color"])
        else:
            # Kein Kanal online
            pixels.fill(config["offline_color"])

        pixels.show()
        last_online_channel = current_online_channel
    except Exception as e:
        print(f"Error: {e}")
        pixels.fill([255, 255, 0])  # Fehler: Gelb
        pixels.show()
    time.sleep(60)  # Status alle 60 Sekunden prüfen
