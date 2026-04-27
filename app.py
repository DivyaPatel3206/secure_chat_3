"""
CipherChat — Python Flask Backend
===================================
Serves the index.html frontend and exposes REST API endpoints that
simulate backend behaviour (auth tokens, geo data, attack metrics,
sniffer stats).  Everything is still simulated — no real database,
no real network sniffing — but the logic now lives in Python rather
than the browser, making the architecture easy to extend.

Run:
    python app.py
Then open:
    http://localhost:5000
"""

import random
import string
import base64
import json
import math
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_cors import CORS

app = Flask(__name__, template_folder=".", static_folder="static")
CORS(app)  # Allow frontend JS to call the API freely during development

# ─────────────────────────────────────────────────────────────────────
# In-memory state (resets on server restart — intentional for demo)
# ─────────────────────────────────────────────────────────────────────
rooms: dict[str, dict] = {}          # room_id -> room state
sessions: dict[str, dict] = {}       # session_id -> session state
messages: list[dict] = []            # global message log
server_start: float = time.time()


# ═════════════════════════════════════════════════════════════════════
# AUTH ENGINE
# ═════════════════════════════════════════════════════════════════════

def _b64(data: str) -> str:
    """URL-safe base-64 encode a string (no padding)."""
    return base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")


def generate_jwt(user_id: str, room_id: str) -> str:
    """Generate a fake JWT-like token (not cryptographically signed)."""
    header  = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}))
    payload = _b64(json.dumps({
        "sub": user_id,
        "room": room_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "jti": _random_hex(16),
    }))
    signature = _random_hex(32)
    return f"{header}.{payload}.{_b64(signature)}"


def generate_username() -> str:
    """Random cyber-style username."""
    adj  = ["Alpha","Cipher","Dark","Echo","Phantom","Ghost","Rogue","Null","Void","Zeta"]
    noun = ["Net","Hax","Node","Byte","Mesh","Core","Root","Link","Port","Trace"]
    return random.choice(adj) + random.choice(noun) + str(random.randint(100, 999))


def generate_session_id() -> str:
    return "SID-" + _random_hex(4).upper()


def mask_token(token: str) -> str:
    return "*" * 12 + token[-6:]


def _random_hex(n: int) -> str:
    return "".join(random.choices(string.hexdigits[:16], k=n))


# ═════════════════════════════════════════════════════════════════════
# GEO ENGINE
# ═════════════════════════════════════════════════════════════════════

GEO_LOCATIONS = [
    {"city": "MOSCOW",     "country": "RU", "flag": "🇷🇺", "lat": 55.7558,  "lon":  37.6173},
    {"city": "BEIJING",    "country": "CN", "flag": "🇨🇳", "lat": 39.9042,  "lon": 116.4074},
    {"city": "PYONGYANG",  "country": "KP", "flag": "🇰🇵", "lat": 39.0392,  "lon": 125.7625},
    {"city": "TEHRAN",     "country": "IR", "flag": "🇮🇷", "lat": 35.6892,  "lon":  51.3890},
    {"city": "BUCHAREST",  "country": "RO", "flag": "🇷🇴", "lat": 44.4268,  "lon":  26.1025},
    {"city": "LAGOS",      "country": "NG", "flag": "🇳🇬", "lat":  6.5244,  "lon":   3.3792},
    {"city": "CARACAS",    "country": "VE", "flag": "🇻🇪", "lat": 10.4806,  "lon": -66.9036},
    {"city": "MINSK",      "country": "BY", "flag": "🇧🇾", "lat": 53.9045,  "lon":  27.5615},
]


def get_random_geo() -> dict:
    """Return a geo location with slight coordinate jitter."""
    loc = random.choice(GEO_LOCATIONS).copy()
    loc["lat"] = round(loc["lat"] + random.uniform(-0.5, 0.5), 4)
    loc["lon"] = round(loc["lon"] + random.uniform(-0.5, 0.5), 4)
    return loc


# ═════════════════════════════════════════════════════════════════════
# SIMULATION ENGINE helpers
# ═════════════════════════════════════════════════════════════════════

BOT_NAMES = [
    "AlphaNet442","GhostByte771","NullRoot998","CipherMesh303",
    "VoidNode556","EchoTrace211","DarkPort888","ZetaCore127",
    "PhantomLink064","RogueHax519",
]

BOT_MESSAGES = [
    "anyone else seeing weird packets?",
    "sniffer is hot tonight",
    "rotation complete, new vectors loaded",
    "mask up, they're watching port 443",
    "traffic spike on mesh layer 3",
    "tunnel established, relaying now",
    "keep it tight, exposure is climbing",
    "who opened the UDP socket?",
    "proxy chain holding, 7 hops",
    "anyone got the new cipher key?",
    "firewall bypass successful",
    "signal clean on this end",
    "switching to backup route now",
    "latency spike — possible intercept",
    "node rotation in 30s",
    "all clear on my subnet",
    "got flagged, switching identity",
    "who leaked the handshake?",
    "layer 7 inspection active, go dark",
    "running steganography on payload",
]


def should_intercept(room: dict) -> bool:
    """Probability of interception grows with active attacks."""
    base = 0.22
    bonus = 0.15 if room.get("under_attack", False) else 0.0
    return random.random() < (base + bonus)


def calc_security_score(room: dict) -> int:
    total = room.get("total_messages", 0)
    if total == 0:
        return 100
    ratio = room.get("intercepted_messages", 0) / total
    penalty = room.get("attack_attempts", 0) * 1.5
    score = 100 - (ratio * 35) - penalty
    return max(50, min(100, math.floor(score)))


def simulate_ddos_tick(room: dict) -> dict:
    """Mutate room state to simulate a DDoS tick."""
    spike = random.random() < 0.12
    if spike:
        room["under_attack"]   = True
        room["rps"]            = random.randint(3000, 11000)
        room["server_load"]    = min(100, room.get("server_load", 20) + random.randint(15, 45))
        room["attack_attempts"] = room.get("attack_attempts", 0) + 1
        room["latency"]        = random.randint(80, 280)
        room["attack_until"]   = time.time() + random.uniform(3, 7)
    else:
        # Decay attack if timed out
        if room.get("attack_until", 0) < time.time():
            room["under_attack"]  = False
            room["rps"]           = random.randint(80, 680)
            room["server_load"]   = max(12, room.get("server_load", 20) - random.randint(5, 20))
            room["latency"]       = random.randint(8, 30)
        else:
            room["rps"] = random.randint(80, 680)

    room["packets_per_sec"] = int(room.get("rps", 100) * random.uniform(0.8, 1.2))
    return room


def get_or_create_room(room_id: str) -> dict:
    if room_id not in rooms:
        rooms[room_id] = {
            "id": room_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "total_messages": 0,
            "intercepted_messages": 0,
            "blocked_packets": 0,
            "attack_attempts": 0,
            "rps": 120,
            "server_load": 12,
            "latency": 14,
            "packets_per_sec": 100,
            "under_attack": False,
            "attack_until": 0,
            "online_users": 1,
            "geo": get_random_geo(),
        }
    return rooms[room_id]


# ═════════════════════════════════════════════════════════════════════
# API ROUTES
# ═════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """Serve the frontend HTML file."""
    return render_template("index.html")


# ── /api/join ───────────────────────────────────────────────────────
@app.route("/api/join", methods=["POST"])
def api_join():
    """
    Join or create a room.
    Body: { "room_id": "ROOM-ALPHA7X" }
    Returns: username, token, session_id, masked_token
    """
    data    = request.get_json(force=True, silent=True) or {}
    room_id = str(data.get("room_id", "ROOM-DEFAULT")).upper()

    username   = generate_username()
    token      = generate_jwt(username, room_id)
    session_id = generate_session_id()
    room       = get_or_create_room(room_id)
    room["online_users"] = room.get("online_users", 0) + 1

    session_data = {
        "session_id": session_id,
        "username":   username,
        "token":      token,
        "room_id":    room_id,
        "joined_at":  time.time(),
        "compromised": False,
    }
    sessions[session_id] = session_data

    return jsonify({
        "ok":           True,
        "room_id":      room_id,
        "username":     username,
        "session_id":   session_id,
        "token":        token,
        "masked_token": mask_token(token),
    })


# ── /api/room/<room_id>/metrics ─────────────────────────────────────
@app.route("/api/room/<room_id>/metrics", methods=["GET"])
def api_metrics(room_id: str):
    """
    Return live simulated metrics for the room.
    The frontend polls this every ~1–2 seconds to update the dashboard.
    """
    room = get_or_create_room(room_id.upper())
    room = simulate_ddos_tick(room)
    room["security_score"]  = calc_security_score(room)
    room["exposure_pct"]    = (
        round(room["intercepted_messages"] / room["total_messages"] * 100)
        if room["total_messages"] > 0 else 0
    )
    # Randomly rotate geo
    if random.random() < 0.04:
        room["geo"] = get_random_geo()

    # Randomly fluctuate online count
    room["online_users"] = max(1, room.get("online_users", 1) + random.randint(-1, 2))

    return jsonify({
        "ok":                  True,
        "room_id":             room_id,
        "rps":                 room["rps"],
        "server_load":         round(room["server_load"]),
        "latency":             room["latency"],
        "packets_per_sec":     room["packets_per_sec"],
        "blocked_packets":     room["blocked_packets"],
        "under_attack":        room["under_attack"],
        "attack_attempts":     room["attack_attempts"],
        "total_messages":      room["total_messages"],
        "intercepted_messages": room["intercepted_messages"],
        "exposure_pct":        room["exposure_pct"],
        "security_score":      room["security_score"],
        "online_users":        room["online_users"],
        "geo":                 room["geo"],
    })


# ── /api/room/<room_id>/messages ────────────────────────────────────
@app.route("/api/room/<room_id>/messages", methods=["GET"])
def api_get_messages(room_id: str):
    """Return all messages for a room (newest 100)."""
    room_msgs = [m for m in messages if m["room_id"] == room_id.upper()]
    return jsonify({"ok": True, "messages": room_msgs[-100:]})


@app.route("/api/room/<room_id>/messages", methods=["POST"])
def api_post_message(room_id: str):
    """
    Post a user message.
    Body: { "session_id": "SID-XXXX", "content": "hello" }
    Returns: the saved message object (with intercepted flag).
    """
    data       = request.get_json(force=True, silent=True) or {}
    session_id = data.get("session_id", "")
    content    = str(data.get("content", "")).strip()[:200]

    if not content:
        return jsonify({"ok": False, "error": "empty message"}), 400

    session = sessions.get(session_id)
    if not session:
        return jsonify({"ok": False, "error": "invalid session"}), 401

    rid  = room_id.upper()
    room = get_or_create_room(rid)
    intercepted = should_intercept(room)

    msg = {
        "id":          len(messages) + 1,
        "room_id":     rid,
        "username":    session["username"],
        "content":     content,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "intercepted": intercepted,
        "is_bot":      False,
    }
    messages.append(msg)
    room["total_messages"]       += 1
    if intercepted:
        room["intercepted_messages"] += 1
        room["blocked_packets"]      += random.randint(1, 5)

    return jsonify({"ok": True, "message": msg})


# ── /api/room/<room_id>/bot-message ─────────────────────────────────
@app.route("/api/room/<room_id>/bot-message", methods=["POST"])
def api_bot_message(room_id: str):
    """
    Generate and store a simulated bot message.
    The frontend calls this on a timer to simulate multi-user chat.
    """
    rid  = room_id.upper()
    room = get_or_create_room(rid)
    intercepted = should_intercept(room)

    msg = {
        "id":          len(messages) + 1,
        "room_id":     rid,
        "username":    random.choice(BOT_NAMES),
        "content":     random.choice(BOT_MESSAGES),
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "intercepted": intercepted,
        "is_bot":      True,
    }
    messages.append(msg)
    room["total_messages"]       += 1
    if intercepted:
        room["intercepted_messages"] += 1

    return jsonify({"ok": True, "message": msg})


# ── /api/session/<session_id>/check ─────────────────────────────────
@app.route("/api/session/<session_id>/check", methods=["GET"])
def api_session_check(session_id: str):
    """
    Simulate a session security check.
    Randomly marks the session as compromised then auto-recovers.
    """
    session = sessions.get(session_id)
    if not session:
        return jsonify({"ok": False, "error": "unknown session"}), 404

    # Small chance of simulated compromise on each check
    if random.random() < 0.07:
        session["compromised"] = True
        # Auto-recover: rotate token
        session["token"]       = generate_jwt(session["username"], session["room_id"])
        session["session_id"]  = generate_session_id()
        sessions[session["session_id"]] = session
        compromised = True
    else:
        session["compromised"] = False
        compromised = False

    return jsonify({
        "ok":          True,
        "compromised": compromised,
        "masked_token": mask_token(session["token"]),
        "session_id":  session["session_id"],
    })


# ── /api/geo/rotate ─────────────────────────────────────────────────
@app.route("/api/geo/rotate", methods=["GET"])
def api_geo_rotate():
    """Return a fresh random attacker geolocation."""
    return jsonify({"ok": True, "geo": get_random_geo()})


# ── /api/status ─────────────────────────────────────────────────────
@app.route("/api/status", methods=["GET"])
def api_status():
    """Server health / uptime endpoint."""
    uptime_s = int(time.time() - server_start)
    h, rem   = divmod(uptime_s, 3600)
    m, s     = divmod(rem, 60)
    return jsonify({
        "ok":          True,
        "server":      "CipherChat Backend",
        "version":     "1.0.0",
        "uptime":      f"{h:02d}:{m:02d}:{s:02d}",
        "rooms_active": len(rooms),
        "total_messages": len(messages),
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    })


# ═════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 56)
    print("  CipherChat Backend  —  http://localhost:5000")
    print("=" * 56)
    # debug=True gives auto-reload during development; set to False for prod
    app.run(host="0.0.0.0", port=5000, debug=True)
