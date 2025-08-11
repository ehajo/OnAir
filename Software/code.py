import json
import time
import board
import neopixel
import wifi
import ssl
import socketpool
import adafruit_requests

# ---------- Hilfsfunktionen: JSON laden ----------
def load_json(filename):
    with open(filename, "r") as file:
        return json.load(file)

# Zugangsdaten laden
secrets = load_json("secrets.json")
config = load_json("config.json")

# ---------- NeoPixel-Setup ----------
pixel_pin = board.GP2
num_pixels = 50  # Anzahl der LEDs
pixels = neopixel.NeoPixel(pixel_pin, num_pixels, auto_write=False)

# Feste Buchstabenbereiche (Hardware ist fix)
letters = {
    "O": range(0, 10),   # LED1-LED10
    "N": range(10, 23),  # LED11-LED23
    "A": range(23, 33),  # LED24-LED33
    "I": range(33, 38),  # LED34-LED38
    "R": range(38, 50)   # LED39-LED50
}

# Twitch-Status speichern
last_online_channel = None

# ---------- LED-Effekte ----------
def error_effect():
    print("Error detected!")
    for _ in range(5):
        pixels.fill([255, 0, 0])  # Rot
        pixels.show()
        time.sleep(0.25)
        pixels.fill([0, 0, 0])    # Aus
        pixels.show()
        time.sleep(0.25)

def connecting_effect():
    print("Connecting to network...")
    for _ in range(3):
        for brightness in range(0, 256, 10):
            pixels.fill([brightness // 4, brightness // 4, 0])  # Gelb
            pixels.show()
            time.sleep(0.01)
        for brightness in range(255, -1, -10):
            pixels.fill([brightness // 4, brightness // 4, 0])  # Gelb
            pixels.show()
            time.sleep(0.01)

def standby_effect(offline_color):
    base_brightness = 0.2
    pulse_range = 0.2
    steps = 50
    delay = 0.05

    start_brightness = base_brightness
    adjusted_color = [int(c * start_brightness) for c in offline_color]
    pixels.fill(adjusted_color)
    pixels.show()

    for brightness_factor in list(range(0, steps)) + list(range(steps, 0, -1)):
        brightness = base_brightness + pulse_range * (brightness_factor / steps)
        adjusted_color = [int(c * brightness) for c in offline_color]
        pixels.fill(adjusted_color)
        pixels.show()
        time.sleep(delay)

    adjusted_color = [int(c * base_brightness) for c in offline_color]
    pixels.fill(adjusted_color)
    pixels.show()

def knight_rider_effect(letters_ranges, color, cycles=4):
    print("Knight Rider Effekt (Buchstaben)!")
    letter_keys = ["O", "N", "A", "I", "R"]  # Feste Reihenfolge
    for _ in range(cycles):
        for key in letter_keys:  # vorwärts
            pixels.fill([0, 0, 0])
            for i in letters_ranges[key]:
                pixels[i] = color
            pixels.show()
            time.sleep(0.06)
        for key in reversed(letter_keys):  # rückwärts
            pixels.fill([0, 0, 0])
            for i in letters_ranges[key]:
                pixels[i] = color
            pixels.show()
            time.sleep(0.06)

def set_letter_colors(channel_config):
    for letter, indices in letters.items():
        color = channel_config["letters"].get(letter, {}).get("color", [0, 0, 0])
        brightness = channel_config["letters"].get(letter, {}).get("brightness", 0.5)
        adjusted_color = [int(c * brightness) for c in color]
        for i in indices:
            pixels[i] = adjusted_color
    pixels.show()

# ---------- WiFi ----------
def connect_to_wifi(max_retries=5, retry_delay=5):
    attempt = 0
    while attempt < max_retries:
        try:
            print(f"Connecting to WiFi: {secrets['wifi']['ssid']} (Attempt {attempt + 1}/{max_retries})...")
            wifi.radio.connect(secrets["wifi"]["ssid"], secrets["wifi"]["password"])
            print("Connected to WiFi!")
            return True
        except Exception as e:
            print(f"WiFi connection failed: {e}")
            attempt += 1
            if attempt < max_retries:
                print(f"Retrying in {retry_delay} seconds...")
                error_effect()
                time.sleep(retry_delay)
            else:
                print("Max retries reached. Could not connect to WiFi.")
                return False

# ---------- Twitch Token Management ----------
# Wir nutzen den Client-Credentials-Flow und speichern das App-Token inkl. Ablaufzeit.
TWITCH_OAUTH_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_STREAMS_URL = "https://api.twitch.tv/helix/streams"

_access_token = None
_token_expiry_epoch = 0  # Zeitpunkt, ab dem neu geholt werden muss

def _now():
    return time.time()

def get_app_access_token(requests):
    """
    Holt ein neues App Access Token (Client Credentials Flow) und setzt Ablaufzeit.
    """
    global _access_token, _token_expiry_epoch

    payload = {
        "client_id": secrets["twitch"]["client_id"],
        "client_secret": secrets["twitch"]["client_secret"],
        "grant_type": "client_credentials"
    }

    # Twitch möchte application/x-www-form-urlencoded
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    print("Requesting new Twitch App Access Token...")
    resp = requests.post(TWITCH_OAUTH_URL, data=payload, headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"OAuth token request failed: HTTP {resp.status_code} {resp.text}")

    data = resp.json()
    _access_token = data.get("access_token", None)
    expires_in = data.get("expires_in", 0)  # Sekunden
    if not _access_token:
        raise RuntimeError("No access_token in OAuth response")

    # Einen kleinen Puffer abziehen (z. B. 60 s), damit wir nicht genau auf der Kante sind
    _token_expiry_epoch = _now() + max(0, int(expires_in) - 60)
    print("New token acquired; valid for ~", int(expires_in), "seconds (minus safety buffer).")

def ensure_token(requests):
    """
    Stellt sicher, dass ein gültiges Token vorhanden ist (holt ggf. ein neues).
    """
    if (_access_token is None) or (_now() >= _token_expiry_epoch):
        get_app_access_token(requests)
    return _access_token

def is_channel_online(channel_name, requests):
    """
    Fragt den Online-Status ab. Bei 401 wird das Token einmal erneuert und der Call wiederholt.
    """
    def _call(with_retry=False):
        token = ensure_token(requests)
        headers = {
            "Client-ID": secrets["twitch"]["client_id"],
            "Authorization": "Bearer " + token
        }
        url = f"{TWITCH_STREAMS_URL}?user_login={channel_name}"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return True, ("data" in data and len(data["data"]) > 0)
        elif response.status_code == 401 and not with_retry:
            # Token vermutlich abgelaufen/ungültig -> neu holen und einmal retry
            print(f"Twitch 401 for {channel_name}: refreshing token and retrying once...")
            get_app_access_token(requests)
            return _call(with_retry=True)
        elif response.status_code == 429:
            print(f"Twitch API error for {channel_name}: Rate limit exceeded (429)")
            return True, False
        else:
            print(f"Twitch API error for {channel_name}: HTTP {response.status_code}")
            return True, False

    try:
        ok, result = _call()
        return result if ok else False
    except Exception as e:
        print(f"Error checking Twitch channel {channel_name}: {e}")
        return False

# ---------- Hauptprogramm ----------
def main():
    global last_online_channel

    # WLAN-Verbindung
    connecting_effect()
    if not connect_to_wifi():
        while True:
            print("Error-Modus")
            standby_effect([50, 0, 0])
            time.sleep(5)

    # HTTP-Session
    pool = socketpool.SocketPool(wifi.radio)
    ssl_context = ssl.create_default_context()
    requests = adafruit_requests.Session(pool, ssl_context)
    print("Ready to check Twitch status!")

    # Hauptloop: alle 60 Sekunden prüfen (schont Rate Limits)
    while True:
        try:
            current_online_channel = None

            # Priorität: Reihenfolge in config["channels"]
            for channel in config["channels"]:
                if is_channel_online(channel["name"], requests):
                    current_online_channel = channel
                    break

            if current_online_channel:
                if current_online_channel is not last_online_channel:
                    knight_rider_effect(letters, [255, 0, 0])  # Übergang
                    set_letter_colors(current_online_channel)
                else:
                    set_letter_colors(current_online_channel)
            else:
                print("Standby-Modus")
                standby_effect(config["offline_color"])

            last_online_channel = current_online_channel
            time.sleep(60)  # 1 Minute

        except Exception as e:
            print(f"Error in main loop: {e}")
            error_effect()
            time.sleep(5)
            if not wifi.radio.connected:
                print("WiFi disconnected. Attempting to reconnect...")
                if not connect_to_wifi():
                    print("Reconnection failed. Continuing in offline mode...")

# Programm starten
main()
