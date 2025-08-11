import json
import time
import errno
import os
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
HTTP_TIMEOUT = 2              # kürzerer Timeout -> Webserver bleibt reaktionsfähig
CHECK_INTERVAL = 60           # Sekunden zwischen Twitch-Zyklen
STARTUP_GRACE_SEC = 10        # reine Zeit-Schonfrist nach Boot (ohne UI-Abhängigkeit)
WEB_LOCK_DURATION_SEC = 20    # Twitch-Pause nach JEDEM Webrequest

# =========================
#   JSON laden/speichern
# =========================
def load_json(filename):
    with open(filename, "r") as f:
        return json.load(f)

def save_json(filename, data):
    tmp = filename + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)  # ohne indent => kompatibler & schneller
        try:
            os.rename(tmp, filename)
        except AttributeError:
            with open(filename, "w") as f:
                json.dump(data, f)
        return True
    except OSError as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        print("save_json Fehler:", e)
        return False

# Zugangsdaten + Konfiguration
secrets = load_json("secrets.json")
config = load_json("config.json")
if "ui" not in config:
    config["ui"] = {"theme": "light"}

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

# Start-/Steuer-Flags
boot_time = 0.0
ui_config_seen = True          # >>> NEU: direkt True, damit Twitch auch ohne Webaufruf startet
web_lock_until = 0.0           # wird bei Webzugriff gesetzt

# =========================
#   LED-Effekte
# =========================
def error_effect():
    for _ in range(2):
        pixels.fill([255, 0, 0]); pixels.show(); time.sleep(0.15)
        pixels.fill([0, 0, 0]);   pixels.show(); time.sleep(0.15)

def connecting_effect():
    for _ in range(2):
        for b in range(0, 256, 16):
            pixels.fill([b // 4, b // 4, 0]); pixels.show(); time.sleep(0.008)
        for b in range(255, -1, -16):
            pixels.fill([b // 4, b // 4, 0]); pixels.show(); time.sleep(0.008)

def standby_effect(offline_color):
    base_b = 0.2; pulse = 0.2; steps = 30
    for s in range(0, steps):
        b = base_b + pulse * (s / steps)
        col = [int(c * b) for c in offline_color]
        pixels.fill(col); pixels.show()
        time.sleep(0.004)

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
            time.sleep(0.04)

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
#   Twitch API / Token mit Backoff
# =========================
TWITCH_OAUTH_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_STREAMS_URL = "https://api.twitch.tv/helix/streams"

_access_token = None
_token_expiry_epoch = 0
_token_retry_after = 0.0  # Backoff bei Token-Fehlern

def _now_epoch():
    return time.time()

def _now_mono():
    return time.monotonic()

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
    _token_expiry_epoch = _now_epoch() + max(0, expires_in - 60)  # 60s Puffer
    print("Token OK; gültig ~", expires_in, "s (mit Puffer).")

def ensure_token(requests):
    global _token_retry_after
    if (_access_token is not None) and (_now_epoch() < _token_expiry_epoch):
        return _access_token
    if _now_mono() < _token_retry_after:
        return None
    try:
        get_app_access_token(requests)
        return _access_token
    except Exception as e:
        print("Token holen fehlgeschlagen:", e)
        _token_retry_after = _now_mono() + 30.0  # 30 s pausieren
        return None

def is_channel_online(channel_name, requests, server=None, token_cached=None):
    def _call(retried=False):
        token = token_cached if token_cached else ensure_token(requests)
        if not token:
            return True, False

        headers = {
            "Client-ID": secrets["twitch"]["client_id"],
            "Authorization": "Bearer " + token,
        }
        url = f"{TWITCH_STREAMS_URL}?user_login={channel_name}"

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
        if getattr(e, "errno", None) in (errno.ECONNABORTED, errno.ETIMEDOUT, errno.EINPROGRESS):
            print(f"Twitch-Fehler {channel_name}: {e} → offline weiter.")
            return False
        print(f"Twitch-Fehler unerwartet {channel_name}: {e}")
        return False
    except Exception as e:
        print(f"Twitch-Fehler {channel_name}: {e}")
        return False

# =========================
#   Web UI (HTML) – Dark Mode mit Persistenz
# =========================
HTML_PAGE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ONAIR LED – Konfiguration</title>
<style>
:root{
  --bg:#ffffff; --fg:#111111; --card:#f7f7f7; --border:#dddddd; --badge:#eeeeee;
  --primary:#4a67ff; --danger:#d33; --muted:#666666;
}
body[data-theme="dark"]{
  --bg:#0b0f14; --fg:#e6eaf0; --card:#111827; --border:#213244; --badge:#1b2836;
  --primary:#7aa2ff; --danger:#ff6b6b; --muted:#9aa7b3;
}
html,body{height:100%}
body{background:var(--bg);color:var(--fg);font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:980px;margin:0 auto;padding:16px}
h1{font-size:1.4rem;margin:0 0 12px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:12px;margin:12px 0}
.row{display:flex;gap:12px;flex-wrap:wrap}
.col{flex:1 1 220px}
label{display:block;font-size:.9rem;margin:.4rem 0 .2rem}
input[type="text"]{width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:transparent;color:var(--fg)}
input[type="color"]{width:52px;height:36px;border:none;background:none;padding:0}
input[type="range"]{width:140px}
button{padding:8px 14px;border:0;border-radius:10px;cursor:pointer}
button.primary{background:var(--primary);color:white}
button.danger{background:var(--danger);color:white}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;background:var(--badge);margin-left:6px}
.grid{display:grid;grid-template-columns:repeat(5,minmax(160px,1fr));gap:8px}
.small{font-size:.85rem;color:var(--muted)}
hr{border:0;border-top:1px solid var(--border);margin:14px 0}
.switch{position:relative;display:inline-block;width:54px;height:28px;vertical-align:middle}
.switch input{opacity:0;width:0;height:0}
.slider{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:#bbb;transition:.2s;border-radius:999px}
.slider:before{position:absolute;content:"";height:22px;width:22px;left:3px;bottom:3px;background:white;transition:.2s;border-radius:50%}
input:checked + .slider{background:var(--primary)}
input:checked + .slider:before{transform:translateX(26px)}
.notice{margin-left:8px}
</style>
</head>
<body data-theme="light">
<h1>
  ONAIR LED – Konfiguration
  <span id="status" class="badge">geladen</span>
  <span class="badge notice">Theme</span>
  <label class="switch" title="Dark Mode">
    <input id="themeToggle" type="checkbox" onchange="toggleTheme()">
    <span class="slider"></span>
  </label>
</h1>

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

function applyTheme(theme){
  document.body.setAttribute("data-theme", theme === "dark" ? "dark" : "light");
  document.getElementById("themeToggle").checked = (theme === "dark");
}

async function loadConfig(){
  const r = await fetch("/config"); // wird direkt bedient (keine Twitch-Abhängigkeit)
  cfg = await r.json();
  applyTheme((cfg.ui && cfg.ui.theme) ? cfg.ui.theme : "light");
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

async function toggleTheme(){
  const enabled = document.getElementById("themeToggle").checked;
  const theme = enabled ? "dark" : "light";
  applyTheme(theme);
  const r = await fetch("/set_ui_theme", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({theme})});
  const js = await r.json();
  if(!js.ok){ alert("Speichern fehlgeschlagen (evtl. Dateisystem read-only)."); }
}

async function saveChannel(name){
  const payload = { name, letters:{} };
  letters.forEach(L => {
    const hex = document.getElementById(`${name}_${L}_color`).value;
    const bri = parseFloat(document.getElementById(`${name}_${L}_bri`).value);
    payload.letters[L] = { color: hexToRgb(hex), brightness: bri };
  });
  const r = await fetch("/save_channel", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)});
  const js = await r.json();
  if(!js.ok){ alert("Speichern fehlgeschlagen (evtl. Dateisystem read-only)."); }
  await loadConfig();
}

async function addChannel(){
  const name = (document.getElementById("newname").value||"").trim();
  if(!name){ alert("Bitte Twitch-Login-Name eingeben."); return; }
  const r = await fetch("/add_channel", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({name})});
  const js = await r.json();
  if(!js.ok){ alert("Speichern fehlgeschlagen (evtl. Dateisystem read-only)."); return; }
  document.getElementById("newname").value="";
  await loadConfig();
}

async function delChannel(name){
  if(!confirm(`Streamer „${name}“ wirklich löschen?`)) return;
  const r = await fetch("/delete_channel", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({name})});
  const js = await r.json();
  if(!js.ok){ alert("Löschen fehlgeschlagen (evtl. Dateisystem read-only)."); return; }
  await loadConfig();
}

async function saveOfflineColor(){
  const hex = document.getElementById("offlineColor").value;
  const r = await fetch("/set_offline_color", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({color: hexToRgb(hex)})});
  const js = await r.json();
  if(!js.ok){ alert("Speichern fehlgeschlagen (evtl. Dateisystem read-only)."); }
  await loadConfig();
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

    def touch_http_activity():
        global web_lock_until
        web_lock_until = time.monotonic() + WEB_LOCK_DURATION_SEC

    @srv.route("/", GET)
    def index(request: Request):
        touch_http_activity()
        return Response(request, content_type="text/html", body=HTML_PAGE)

    @srv.route("/config", GET)
    def get_config(request: Request):
        touch_http_activity()
        data = {
            "channels": config.get("channels", []),
            "offline_color": config.get("offline_color", [50, 50, 50]),
            "ui": config.get("ui", {"theme": "light"}),
        }
        return JSONResponse(request, data)

    @srv.route("/set_ui_theme", POST)
    def set_ui_theme(request: Request):
        touch_http_activity()
        try:
            body = request.json()
            theme = body.get("theme", "light")
            if "ui" not in config:
                config["ui"] = {}
            config["ui"]["theme"] = "dark" if str(theme).lower() == "dark" else "light"
            ok = save_json("config.json", config)
            if not ok:
                return JSONResponse(request, {"ok": False, "err": "read_only_fs"})
            return JSONResponse(request, {"ok": True, "theme": config["ui"]["theme"]})
        except Exception as e:
            print("set_ui_theme Fehler:", e)
            return JSONResponse(request, {"ok": False, "err": "exception"})

    @srv.route("/save_channel", POST)
    def save_channel(request: Request):
        touch_http_activity()
        try:
            body = request.json()
            name = body.get("name", "").strip()
            new_letters = body.get("letters", {})
            if not name:
                return JSONResponse(request, {"ok": False, "err": "name missing"})

            found = None
            for ch in config["channels"]:
                if ch["name"] == name:
                    found = ch
                    break
            if not found:
                return JSONResponse(request, {"ok": False, "err": "channel not found"})

            found_letters = found.setdefault("letters", {})
            for L in ["O", "N", "A", "I", "R"]:
                v = new_letters.get(L, {})
                color = v.get("color", [0, 0, 0])
                bri = float(v.get("brightness", 0.5))
                found_letters[L] = {
                    "color": [int(color[0]), int(color[1]), int(color[2])],
                    "brightness": bri
                }

            ok = save_json("config.json", config)
            if not ok:
                return JSONResponse(request, {"ok": False, "err": "read_only_fs"})

            global last_online_channel
            if last_online_channel and last_online_channel.get("name") == name:
                set_letter_colors(found)

            return JSONResponse(request, {"ok": True})
        except Exception as e:
            print("save_channel Fehler:", e)
            return JSONResponse(request, {"ok": False, "err": "exception"})

    @srv.route("/add_channel", POST)
    def add_channel(request: Request):
        touch_http_activity()
        try:
            body = request.json()
            name = body.get("name", "").strip()
            if not name:
                return JSONResponse(request, {"ok": False, "err": "name missing"})

            for ch in config["channels"]:
                if ch["name"] == name:
                    return JSONResponse(request, {"ok": False, "err": "exists"})

            default = {"color": [0, 117, 179], "brightness": 0.3}
            new_ch = {"name": name, "letters": {L: dict(default) for L in ["O", "N", "A", "I", "R"]}}
            config["channels"].append(new_ch)

            ok = save_json("config.json", config)
            if not ok:
                return JSONResponse(request, {"ok": False, "err": "read_only_fs"})

            return JSONResponse(request, {"ok": True})
        except Exception as e:
            print("add_channel Fehler:", e)
            return JSONResponse(request, {"ok": False, "err": "exception"})

    @srv.route("/delete_channel", POST)
    def delete_channel(request: Request):
        touch_http_activity()
        try:
            body = request.json()
            name = body.get("name", "").strip()
            if not name:
                return JSONResponse(request, {"ok": False, "err": "name missing"})

            before = len(config["channels"])
            config["channels"] = [c for c in config["channels"] if c.get("name") != name]
            if len(config["channels"]) == before:
                return JSONResponse(request, {"ok": False, "err": "not found"})

            ok = save_json("config.json", config)
            if not ok:
                return JSONResponse(request, {"ok": False, "err": "read_only_fs"})

            return JSONResponse(request, {"ok": True})
        except Exception as e:
            print("delete_channel Fehler:", e)
            return JSONResponse(request, {"ok": False, "err": "exception"})

    @srv.route("/set_offline_color", POST)
    def set_offline_color(request: Request):
        touch_http_activity()
        try:
            body = request.json()
            color = body.get("color", [50, 50, 50])
            config["offline_color"] = [int(color[0]), int(color[1]), int(color[2])]

            ok = save_json("config.json", config)
            if not ok:
                return JSONResponse(request, {"ok": False, "err": "read_only_fs"})

            return JSONResponse(request, {"ok": True})
        except Exception as e:
            print("set_offline_color Fehler:", e)
            return JSONResponse(request, {"ok": False, "err": "exception"})

    return srv

# =========================
#   Hauptprogramm
# =========================
def main():
    global last_online_channel, boot_time, web_lock_until, ui_config_seen

    connecting_effect()
    if not connect_to_wifi():
        while True:
            standby_effect([50, 0, 0])

    pool = socketpool.SocketPool(wifi.radio)
    ssl_context = ssl.create_default_context()
    requests = adafruit_requests.Session(pool, ssl_context)

    server = build_server(pool)
    server.start(str(wifi.radio.ipv4_address), port=8080)
    print("Webserver läuft auf http://%s:8080/" % wifi.radio.ipv4_address)
    print("Ready to check Twitch status!")

    # Sofort eine gedimmte Offline-Anzeige
    base_b = 0.2
    col = [int(c * base_b) for c in config.get("offline_color", [50, 50, 50])]
    pixels.fill(col); pixels.show()

    boot_time = time.monotonic()
    last_check = time.monotonic() - CHECK_INTERVAL  # erster Zyklus nach Schonfrist möglich

    while True:
        # Webserver-Events abarbeiten (nicht-blockierend)
        try:
            server.poll()
        except Exception as e:
            print("Server poll Fehler:", e)

        now = time.monotonic()

        # Twitch pausieren, wenn kürzlich Web aktiv war
        if now < web_lock_until:
            if not last_online_channel:
                standby_effect(config.get("offline_color", [50, 50, 50]))
            time.sleep(0.005)
            continue

        # Start-Schonfrist rein zeitbasiert
        if (now - boot_time) < STARTUP_GRACE_SEC:
            if not last_online_channel:
                standby_effect(config.get("offline_color", [50, 50, 50]))
            time.sleep(0.005)
            continue

        # Ein kompletter Twitch-Zyklus max. alle CHECK_INTERVAL Sekunden
        if now - last_check >= CHECK_INTERVAL:
            last_check = now
            try:
                # 1) Token EINMAL pro Zyklus sicherstellen
                token = ensure_token(requests)
                # Wenn Token nicht da (Backoff): Zyklus überspringen
                if not token:
                    print("Token nicht verfügbar (Backoff) → Zyklus überspringen.")
                    continue

                # 2) Channels in Prioritäts-Reihenfolge prüfen
                current_online_channel = None
                for ch in config.get("channels", []):
                    if is_channel_online(ch["name"], requests, server=server, token_cached=token):
                        current_online_channel = ch
                        break
                    # Nach jedem Call Server kurz bedienen
                    try:
                        server.poll()
                    except Exception as e:
                        print("Server poll innerhalb Twitch-Schleife:", e)

                # 3) LEDs setzen
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
                if not wifi.radio.connected:
                    connect_to_wifi()

        time.sleep(0.005)

# Start
main()
