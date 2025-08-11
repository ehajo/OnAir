import json
import time
import errno
import board
import neopixel
import wifi
import ssl
import socketpool
import adafruit_requests
from adafruit_httpserver import Server, Request, Response, JSONResponse, POST, GET

# =========================
#   Konfiguration
# =========================
HTTP_TIMEOUT = 5         # Sekunden Timeout für HTTP-Requests
CHECK_INTERVAL = 60      # Sekunden zwischen Twitch-Abfragen

# =========================
#   JSON laden/speichern
# =========================
def load_json(filename):
    with open(filename, "r") as f:
        return json.load(f)

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)

# Zugangsdaten + Konfiguration
secrets = load_json("secrets.json")
config = load_json("config.json")

# =========================
#   NeoPixel-Setup
# =========================
pixel_pin = board.GP2
num_pixels = 50
pixels = neopixel.NeoPixel(pixel_pin, num_pixels, auto_write=False)

# Feste Buchstabenbereiche (Hardware ist fix)
letters = {
    "O": range(0, 10),
    "N": range(10, 23),
    "A": range(23, 33),
    "I": range(33, 38),
    "R": range(38, 50),
}

last_online_channel = None

# =========================
#   LED-Effekte
# =========================
def error_effect():
    for _ in range(3):
        pixels.fill([255, 0, 0])
        pixels.show()
        time.sleep(0.2)
        pixels.fill([0, 0, 0])
        pixels.show()
        time.sleep(0.2)

def connecting_effect():
    for _ in range(2):
        for b in range(0, 256, 12):
            pixels.fill([b // 4, b // 4, 0])
            pixels.show()
            time.sleep(0.01)
        for b in range(255, -1, -12):
            pixels.fill([b // 4, b // 4, 0])
            pixels.show()
            time.sleep(0.01)

def standby_effect(offline_color):
    base_b = 0.2
    pulse = 0.2
    steps = 40
    for s in range(0, steps):
        b = base_b + pulse * (s / steps)
        col = [int(c * b) for c in offline_color]
        pixels.fill(col)
        pixels.show()
        time.sleep(0.005)

def set_letter_colors(channel_cfg):
    for letter_key, idxs in letters.items():
        lc = channel_cfg["letters"].get(letter_key, {})
        color = lc.get("color", [0, 0, 0])
        bright = lc.get("brightness", 0.5)
        adj = [int(c * bright) for c in color]
        for i in idxs:
            pixels[i] = adj
    pixels.show()

def knight_rider_effect(color, cycles=2):
    keys = ["O", "N", "A", "I", "R"]
    for _ in range(cycles):
        for k in keys + list(reversed(keys)):
            pixels.fill([0, 0, 0])
            for i in letters[k]:
                pixels[i] = color
            pixels.show()
            time.sleep(0.05)

# =========================
#   Netzwerk/WiFi
# =========================
def connect_to_wifi(max_retries=5, retry_delay=3):
    for attempt in range(1, max_retries + 1):
        try:
            print(f"WiFi verbinden: {secrets['wifi']['ssid']} (Versuch {attempt}/{max_retries})")
            wifi.radio.connect(secrets["wifi"]["ssid"], secrets["wifi"]["password"])
            print("WiFi verbunden.")
            return True
        except Exception as e:
            print("WiFi-Fehler:", e)
            error_effect()
            time.sleep(retry_delay)
    return False

# =========================
#   Twitch API / Token
# =========================
TWITCH_OAUTH_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_STREAMS_URL = "https://api.twitch.tv/helix/streams"

_access_token = None
_token_expiry_epoch = 0

def _now():
    return time.time()

def get_app_access_token(requests):
    global _access_token, _token_expiry_epoch
    payload = {
        "client_id": secrets["twitch"]["client_id"],
        "client_secret": secrets["twitch"]["client_secret"],
        "grant_type": "client_credentials",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    print("Hole neues Twitch App Access Token...")
    resp = requests.post(TWITCH_OAUTH_URL, data=payload, headers=headers, timeout=HTTP_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError("OAuth fehlgeschlagen: " + str(resp.status_code) + " " + resp.text)
    data = resp.json()
    _access_token = data.get("access_token")
    expires_in = int(data.get("expires_in", 0))
    _token_expiry_epoch = _now() + max(0, expires_in - 60)  # 60s Sicherheits-Puffer
    print("Token OK; gültig ~", expires_in, "s (mit Puffer).")

def ensure_token(requests):
    if (_access_token is None) or (_now() >= _token_expiry_epoch):
        get_app_access_token(requests)
    return _access_token

def is_channel_online(channel_name, requests, server=None):
    def _call(retried=False):
        token = ensure_token(requests)
        headers = {
            "Client-ID": secrets["twitch"]["client_id"],
            "Authorization": "Bearer " + token,
        }
        url = f"{TWITCH_STREAMS_URL}?user_login={channel_name}"

        # Zwischen-„Atmen“, damit der Webserver responsiv bleibt
        if server:
            try:
                server.poll()
            except Exception as e:
                print("Server poll vor Request:", e)

        r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        if r.status_code == 200:
            d = r.json()
            return True, ("data" in d and len(d["data"]) > 0)
        if r.status_code == 401 and not retried:
            print("401 → Token erneuern…")
            get_app_access_token(requests)
            return _call(retried=True)
        if r.status_code == 429:
            print("Rate limit (429).")
            return True, False
        print("Twitch HTTP", r.status_code)
        return True, False

    try:
        ok, res = _call()
        return res if ok else False
    except OSError as e:
        # typische Netzfehler: als „offline“ behandeln und sofort weiter
        if getattr(e, "errno", None) in (errno.ECONNABORTED, errno.ETIMEDOUT):
            print(f"Twitch-Fehler {channel_name}: {e} → offline weiter.")
            return False
        print(f"Twitch-Fehler unerwartet {channel_name}: {e}")
        return False
    except Exception as e:
        print(f"Twitch-Fehler {channel_name}: {e}")
        return False

# =========================
#   Farb-Utilities
# =========================
def hex_to_rgb_list(hx):
    hx = hx.strip()
    if hx.startswith("#") and len(hx) == 7:
        r = int(hx[1:3], 16)
        g = int(hx[3:5], 16)
        b = int(hx[5:7], 16)
        return [r, g, b]
    return [0, 0, 0]

def rgb_list_to_hex(rgb):
    r, g, b = rgb
    return "#{:02X}{:02X}{:02X}".format(int(r), int(g), int(b))

# =========================
#   Web UI (HTML)
# =========================
HTML_PAGE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ONAIR LED – Konfiguration</title>
<style>
body{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:980px;margin:0 auto;padding:16px}
h1{font-size:1.4rem}
.card{border:1px solid #ddd;border-radius:12px;padding:12px;margin:12px 0}
.row{display:flex;gap:12px;flex-wrap:wrap}
.col{flex:1 1 220px}
label{display:block;font-size:.9rem;margin:.4rem 0 .2rem}
input[type="text"]{width:100%;padding:8px;border-radius:8px;border:1px solid #ccc}
input[type="color"]{width:52px;height:36px;border:none;background:none;padding:0}
input[type="range"]{width:140px}
button{padding:8px 14px;border:0;border-radius:10px;cursor:pointer}
button.primary{background:#4a67ff;color:white}
button.danger{background:#d33;color:white}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;background:#eee;margin-left:6px}
.grid{display:grid;grid-template-columns:repeat(5,minmax(160px,1fr));gap:8px}
.small{font-size:.85rem;color:#666}
hr{border:0;border-top:1px solid #eee;margin:14px 0}
</style>
</head>
<body>
<h1>ONAIR LED – Konfiguration<span id="status" class="badge">lädt…</span></h1>

<div class="card">
  <h3>Streamer</h3>
  <div id="channels"></div>
  <hr>
  <div class="row">
    <div class="col">
      <h4>Neuen Streamer hinzufügen</h4>
      <label>Login-Name</label>
      <input id="newname" type="text" placeholder="twitch_username">
      <div class="small">Standardfarben werden gesetzt; danach anpassen.</div>
      <div style="margin-top:8px">
        <button class="primary" onclick="addChannel()">Hinzufügen</button>
      </div>
    </div>
    <div class="col">
      <h4>Offline-Farbe</h4>
      <div class="row">
        <input id="offlineColor" type="color">
        <button onclick="saveOfflineColor()">Speichern</button>
      </div>
      <div class="small">Wirkt im Standby-Puls.</div>
    </div>
  </div>
</div>

<script>
const letters = ["O","N","A","I","R"];
let cfg = null;

function rgbToHex(rgb){const [r,g,b]=rgb;return "#"+[r,g,b].map(v=>v.toString(16).padStart(2,"0")).join("").toUpperCase();}
function hexToRgb(h){return [parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16)];}

async function loadConfig(){
  const r = await fetch("/config");
  cfg = await r.json();
  document.getElementById("status").textContent = "geladen";
  renderChannels();
  document.getElementById("offlineColor").value = rgbToHex(cfg.offline_color || [50,50,50]);
}

function renderChannels(){
  const wrap = document.getElementById("channels");
  wrap.innerHTML = "";
  cfg.channels.forEach((ch, idx) => {
    const div = document.createElement("div");
    div.className = "card";
    div.innerHTML = `
      <div class="row" style="align-items:center;justify-content:space-between">
        <h4 style="margin:4px 0">${idx+1}. ${ch.name}</h4>
        <div>
          <button class="danger" onclick="delChannel('${ch.name}')">Löschen</button>
          <button class="primary" onclick="saveChannel('${ch.name}')">Speichern</button>
        </div>
      </div>
      <div class="grid">
        ${letters.map(L => {
          const data = (ch.letters && ch.letters[L]) ? ch.letters[L] : {color:[0,0,0],brightness:0.5};
          const hex = rgbToHex(data.color);
          const br = data.brightness ?? 0.5;
          return `
            <div>
              <label><strong>${L}</strong> Farbe</label>
              <input id="${ch.name}_${L}_color" type="color" value="${hex}">
              <label>Helligkeit</label>
              <input id="${ch.name}_${L}_bri" type="range" min="0" max="1" step="0.05" value="${br}">
              <span id="${ch.name}_${L}_bri_val" class="small">${br}</span>
            </div>
          `;
        }).join("")}
      </div>
    `;
    wrap.appendChild(div);
    letters.forEach(L => {
      const el = document.getElementById(`${ch.name}_${L}_bri`);
      const lab = document.getElementById(`${ch.name}_${L}_bri_val`);
      el.addEventListener("input",()=>lab.textContent = el.value);
    });
  });
}

async function saveChannel(name){
  const payload = { name, letters:{} };
  letters.forEach(L => {
    const hex = document.getElementById(`${name}_${L}_color`).value;
    const bri = parseFloat(document.getElementById(`${name}_${L}_bri`).value);
    payload.letters[L] = { color: hexToRgb(hex), brightness: bri };
  });
  const r = await fetch("/save_channel", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)});
  if(r.ok){ await loadConfig(); }
}

async function addChannel(){
  const name = (document.getElementById("newname").value||"").trim();
  if(!name){ alert("Bitte Twitch-Login-Name eingeben."); return; }
  const r = await fetch("/add_channel", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({name})});
  if(r.ok){ document.getElementById("newname").value=""; await loadConfig(); }
}

async function delChannel(name){
  if(!confirm(`Streamer „${name}“ wirklich löschen?`)) return;
  const r = await fetch("/delete_channel", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({name})});
  if(r.ok){ await loadConfig(); }
}

async function saveOfflineColor(){
  const hex = document.getElementById("offlineColor").value;
  const r = await fetch("/set_offline_color", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({color: hexToRgb(hex)})});
  if(r.ok){ await loadConfig(); }
}

loadConfig();
</script>
</body>
</html>
"""

# =========================
#   Webserver-Handler
# =========================
def build_server(pool):
    srv = Server(pool, debug=False)

    @srv.route("/", GET)
    def index(request: Request):
        return Response(request, content_type="text/html", body=HTML_PAGE)

    @srv.route("/config", GET)
    def get_config(request: Request):
        data = {
            "channels": config.get("channels", []),
            "offline_color": config.get("offline_color", [50, 50, 50]),
        }
        return JSONResponse(request, data)

    @srv.route("/save_channel", POST)
    def save_channel(request: Request):
        try:
            body = request.json()
            name = body.get("name", "").strip()
            new_letters = body.get("letters", {})
            if not name:
                return JSONResponse(request, {"ok": False, "err": "name missing"}, status=400)

            found = None
            for ch in config["channels"]:
                if ch["name"] == name:
                    found = ch
                    break
            if not found:
                return JSONResponse(request, {"ok": False, "err": "channel not found"}, status=404)

            found_letters = found.setdefault("letters", {})
            for L in ["O", "N", "A", "I", "R"]:
                v = new_letters.get(L, {})
                color = v.get("color", [0, 0, 0])
                bri = float(v.get("brightness", 0.5))
                found_letters[L] = {
                    "color": [int(color[0]), int(color[1]), int(color[2])],
                    "brightness": bri
                }

            save_json("config.json", config)

            global last_online_channel
            if last_online_channel and last_online_channel.get("name") == name:
                set_letter_colors(found)

            return JSONResponse(request, {"ok": True})
        except Exception as e:
            print("save_channel Fehler:", e)
            return JSONResponse(request, {"ok": False, "err": "exception"}, status=500)

    @srv.route("/add_channel", POST)
    def add_channel(request: Request):
        try:
            body = request.json()
            name = body.get("name", "").strip()
            if not name:
                return JSONResponse(request, {"ok": False, "err": "name missing"}, status=400)

            for ch in config["channels"]:
                if ch["name"] == name:
                    return JSONResponse(request, {"ok": False, "err": "exists"}, status=409)

            default = {"color": [0, 117, 179], "brightness": 0.3}
            new_ch = {
                "name": name,
                "letters": {L: dict(default) for L in ["O", "N", "A", "I", "R"]}
            }
            config["channels"].append(new_ch)
            save_json("config.json", config)
            return JSONResponse(request, {"ok": True})
        except Exception as e:
            print("add_channel Fehler:", e)
            return JSONResponse(request, {"ok": False, "err": "exception"}, status=500)

    @srv.route("/delete_channel", POST)
    def delete_channel(request: Request):
        try:
            body = request.json()
            name = body.get("name", "").strip()
            if not name:
                return JSONResponse(request, {"ok": False, "err": "name missing"}, status=400)

            before = len(config["channels"])
            config["channels"] = [c for c in config["channels"] if c.get("name") != name]
            if len(config["channels"]) == before:
                return JSONResponse(request, {"ok": False, "err": "not found"}, status=404)

            save_json("config.json", config)
            return JSONResponse(request, {"ok": True})
        except Exception as e:
            print("delete_channel Fehler:", e)
            return JSONResponse(request, {"ok": False, "err": "exception"}, status=500)

    @srv.route("/set_offline_color", POST)
    def set_offline_color(request: Request):
        try:
            body = request.json()
            color = body.get("color", [50, 50, 50])
            config["offline_color"] = [int(color[0]), int(color[1]), int(color[2])]
            save_json("config.json", config)
            return JSONResponse(request, {"ok": True})
        except Exception as e:
            print("set_offline_color Fehler:", e)
            return JSONResponse(request, {"ok": False, "err": "exception"}, status=500)

    return srv

# =========================
#   Hauptprogramm
# =========================
def main():
    global last_online_channel

    connecting_effect()
    if not connect_to_wifi():
        # offline standby (rot) – UI ist offline
        while True:
            standby_effect([50, 0, 0])

    # gemeinsame Netzwerkressourcen
    pool = socketpool.SocketPool(wifi.radio)
    ssl_context = ssl.create_default_context()
    requests = adafruit_requests.Session(pool, ssl_context)

    # Webserver starten
    server = build_server(pool)
    server.start(str(wifi.radio.ipv4_address))
    print("Webserver läuft auf http://%s/" % wifi.radio.ipv4_address)
    print("Ready to check Twitch status!")

    last_check = 0
    while True:
        # Webserver-Events abarbeiten (nicht-blockierend)
        try:
            server.poll()
        except Exception as e:
            print("Server poll Fehler:", e)

        now = time.monotonic()
        if now - last_check >= CHECK_INTERVAL:
            last_check = now
            try:
                current_online_channel = None
                for ch in config.get("channels", []):
                    if is_channel_online(ch["name"], requests, server=server):
                        current_online_channel = ch
                        break
                    # Zwischen jedem Kanal kurz den Server bedienen
                    try:
                        server.poll()
                    except Exception as e:
                        print("Server poll innerhalb Twitch-Schleife:", e)

                if current_online_channel:
                    if (not last_online_channel) or (current_online_channel.get("name") != last_online_channel.get("name")):
                        knight_rider_effect([255, 0, 0], cycles=2)
                    set_letter_colors(current_online_channel)
                else:
                    standby_effect(config.get("offline_color", [50, 50, 50]))

                last_online_channel = current_online_channel

            except Exception as e:
                print("Main loop Fehler:", e)
                error_effect()
                # WiFi Reconnect versuchen, ohne hart zu blockieren
                if not wifi.radio.connected:
                    connect_to_wifi()

        # Mini-Schlaf, damit CPU atmet
        time.sleep(0.01)

# Start
main()
