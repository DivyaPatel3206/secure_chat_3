"""
CipherChat v2 — Production Backend
=====================================
Real-time multi-user QR chat with WebSocket broadcast.

Run locally:
    pip install -r requirements.txt
    python app.py

Production (Render / Railway / Fly.io):
    gunicorn -k eventlet -w 1 --bind 0.0.0.0:$PORT app:app

Environment variables:
    PORT         Server port          (default 5000)
    SECRET_KEY   Flask secret key     (set a strong value in prod!)
    DEBUG        "true" for dev mode  (default "false")
    MAX_MSG      Messages kept / room (default 200)
"""

import os, random, string, base64, json, math, time, io
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, join_room, leave_room, emit
import qrcode, qrcode.image.svg

# ─────────────────────────────────────────────────────────────────────
# App & extensions
# ─────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"))
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", os.urandom(24).hex())

CORS(app, resources={r"/api/*": {"origins": "*"}})

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="eventlet",
    ping_timeout=20,
    ping_interval=10,
    logger=False,
    engineio_logger=False,
)

# ─────────────────────────────────────────────────────────────────────
# In-memory state
# ─────────────────────────────────────────────────────────────────────
rooms: dict     = {}
sessions: dict  = {}
all_msgs: list  = []
server_start    = time.time()
MAX_MSG         = int(os.environ.get("MAX_MSG", 200))

# ═════════════════════════════════════════════════════════════════════
# AUTH ENGINE
# ═════════════════════════════════════════════════════════════════════

def _b64(s): return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")
def _hex(n): return "".join(random.choices("0123456789abcdef", k=n))

def make_token(uid, rid):
    h = _b64(json.dumps({"alg":"HS256","typ":"JWT"}))
    p = _b64(json.dumps({"sub":uid,"room":rid,"iat":int(time.time()),"exp":int(time.time())+3600,"jti":_hex(16)}))
    return f"{h}.{p}.{_b64(_hex(32))}"

def make_username():
    adj  = ["Alpha","Cipher","Dark","Echo","Phantom","Ghost","Rogue","Null","Void","Zeta","Binary","Neon"]
    noun = ["Net","Hax","Node","Byte","Mesh","Core","Root","Link","Port","Trace","Flux","Pulse"]
    return random.choice(adj) + random.choice(noun) + str(random.randint(100,999))

def make_sid():   return "SID-" + _hex(8).upper()
def mask_tok(t):  return "●"*12 + t[-6:]

# ═════════════════════════════════════════════════════════════════════
# QR ENGINE — generates a real scannable SVG QR code
# ═════════════════════════════════════════════════════════════════════

def make_qr(room_id: str, base_url: str):
    """
    Returns (svg_string, join_url).
    Scanning the QR with a phone camera navigates directly to the room.
    """
    join_url = f"{base_url.rstrip('/')}/join/{room_id}"
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6, border=2,
        image_factory=qrcode.image.svg.SvgPathImage,
    )
    qr.add_data(join_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#00e090", back_color="transparent")
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode()
    if svg.startswith("<?xml"):
        svg = svg[svg.index("<svg"):]
    return svg, join_url

# ═════════════════════════════════════════════════════════════════════
# GEO ENGINE
# ═════════════════════════════════════════════════════════════════════

GEOS = [
    {"city":"MOSCOW",    "country":"RU","flag":"🇷🇺","lat":55.7558, "lon":37.6173},
    {"city":"BEIJING",   "country":"CN","flag":"🇨🇳","lat":39.9042, "lon":116.4074},
    {"city":"PYONGYANG", "country":"KP","flag":"🇰🇵","lat":39.0392, "lon":125.7625},
    {"city":"TEHRAN",    "country":"IR","flag":"🇮🇷","lat":35.6892, "lon":51.3890},
    {"city":"BUCHAREST", "country":"RO","flag":"🇷🇴","lat":44.4268, "lon":26.1025},
    {"city":"LAGOS",     "country":"NG","flag":"🇳🇬","lat":6.5244,  "lon":3.3792},
    {"city":"CARACAS",   "country":"VE","flag":"🇻🇪","lat":10.4806, "lon":-66.9036},
    {"city":"MINSK",     "country":"BY","flag":"🇧🇾","lat":53.9045, "lon":27.5615},
    {"city":"KABUL",     "country":"AF","flag":"🇦🇫","lat":34.5260, "lon":69.1761},
    {"city":"HAVANA",    "country":"CU","flag":"🇨🇺","lat":23.1136, "lon":-82.3666},
]
def rand_geo():
    g = random.choice(GEOS).copy()
    g["lat"] = round(g["lat"] + random.uniform(-0.5,0.5),4)
    g["lon"] = round(g["lon"] + random.uniform(-0.5,0.5),4)
    return g

# ═════════════════════════════════════════════════════════════════════
# SIMULATION ENGINE
# ═════════════════════════════════════════════════════════════════════

BOT_NAMES = ["AlphaNet442","GhostByte771","NullRoot998","CipherMesh303",
             "VoidNode556","EchoTrace211","DarkPort888","ZetaCore127",
             "PhantomLink064","RogueHax519","ShadowBit221","XorFrame007"]

BOT_MSGS  = ["anyone else seeing weird packets?","sniffer is hot tonight",
             "rotation complete, new vectors loaded","mask up, they're watching port 443",
             "traffic spike on mesh layer 3","tunnel established, relaying now",
             "keep it tight, exposure is climbing","who opened the UDP socket?",
             "proxy chain holding, 7 hops","anyone got the new cipher key?",
             "firewall bypass successful","signal clean on this end",
             "switching to backup route now","latency spike — possible intercept",
             "node rotation in 30s","all clear on my subnet",
             "got flagged, switching identity","who leaked the handshake?",
             "layer 7 inspection active, go dark","running steganography on payload",
             "null byte injection blocked upstream","honeypot triggered on node 4",
             "new relay online — route through delta","checksum mismatch on last packet"]

def intercept_chance(room):
    return random.random() < (0.22 + (0.15 if room.get("under_attack") else 0))

def security_score(room):
    t = room.get("total_messages", 0)
    if t == 0: return 100
    return max(50, min(100, math.floor(100 - (room.get("intercepted_messages",0)/t)*35 - room.get("attack_attempts",0)*1.5)))

def get_room(rid):
    if rid not in rooms:
        rooms[rid] = {
            "id":rid, "created_at":datetime.now(timezone.utc).isoformat(),
            "total_messages":0,"intercepted_messages":0,"blocked_packets":0,
            "attack_attempts":0,"rps":120,"server_load":12,"latency":14,
            "packets_per_sec":100,"under_attack":False,"attack_until":0,
            "online_users":0,"geo":rand_geo(),"connected_sids":set(),
        }
    return rooms[rid]

def ddos_tick(room):
    if random.random() < 0.10:
        room.update({"under_attack":True,"rps":random.randint(3000,12000),
                     "server_load":min(100,room["server_load"]+random.randint(15,45)),
                     "latency":random.randint(90,300),
                     "attack_until":time.time()+random.uniform(3,8)})
        room["attack_attempts"] += 1
    elif room.get("attack_until",0) < time.time():
        room.update({"under_attack":False,"rps":random.randint(80,600),
                     "server_load":max(12,room["server_load"]-random.randint(5,18)),
                     "latency":random.randint(8,30)})
    else:
        room["rps"] = random.randint(500,8000)
    room["packets_per_sec"] = int(room["rps"]*random.uniform(0.8,1.2))
    return room

# ═════════════════════════════════════════════════════════════════════
# BACKGROUND BROADCAST GREENLET
# ═════════════════════════════════════════════════════════════════════

def broadcast_loop():
    """Pushes metrics + bot messages to all active rooms every ~1.5 s."""
    next_bot: dict = {}   # room_id -> timestamp of next bot message
    while True:
        socketio.sleep(1.5)
        for rid, room in list(rooms.items()):
            if not room.get("connected_sids"):
                continue

            ddos_tick(room)

            # Geo rotation
            if random.random() < 0.03:
                room["geo"] = rand_geo()
                socketio.emit("geo_update", room["geo"], room=rid)

            room["online_users"]   = len(room["connected_sids"])
            room["security_score"] = security_score(room)
            room["exposure_pct"]   = (
                round(room["intercepted_messages"]/room["total_messages"]*100)
                if room["total_messages"] > 0 else 0
            )

            # Metrics push (excludes non-serialisable set)
            socketio.emit("metrics", {k:v for k,v in room.items()
                                      if k not in ("connected_sids","attack_until")}, room=rid)

            # Rare session attack signal
            if random.random() < 0.015:
                socketio.emit("session_attack",
                              {"message":"Session hijack attempt detected — rotating token"}, room=rid)

            # Bot message
            now = time.time()
            if now >= next_bot.get(rid, 0):
                next_bot[rid] = now + random.uniform(3,7)
                intercepted   = intercept_chance(room)
                msg = {"id":len(all_msgs)+1,"room_id":rid,
                       "username":random.choice(BOT_NAMES),
                       "content":random.choice(BOT_MSGS),
                       "timestamp":datetime.now(timezone.utc).isoformat(),
                       "intercepted":intercepted,"is_bot":True}
                all_msgs.append(msg)
                # Keep memory bounded
                while len(all_msgs) > MAX_MSG * max(len(rooms),1):
                    all_msgs.pop(0)
                room["total_messages"] += 1
                if intercepted: room["intercepted_messages"] += 1
                socketio.emit("new_message", msg, room=rid)

# ═════════════════════════════════════════════════════════════════════
# REST ENDPOINTS
# ═════════════════════════════════════════════════════════════════════

@app.route("/")
@app.route("/join/<room_id>")
def serve_ui(room_id=None):
    return send_from_directory(app.static_folder, "index.html")

@app.route("/api/status")
def api_status():
    up = int(time.time()-server_start)
    h,r = divmod(up,3600); m,s = divmod(r,60)
    return jsonify({"ok":True,"server":"CipherChat","version":"2.0.0",
                    "uptime":f"{h:02d}:{m:02d}:{s:02d}",
                    "rooms":len(rooms),"messages":len(all_msgs),
                    "ts":datetime.now(timezone.utc).isoformat()})

@app.route("/api/room/<room_id>/qr")
def api_qr(room_id):
    rid  = room_id.upper()
    svg, url = make_qr(rid, request.host_url)
    return jsonify({"ok":True,"room_id":rid,"svg":svg,"join_url":url})

@app.route("/api/join", methods=["POST"])
def api_join():
    data   = request.get_json(force=True, silent=True) or {}
    rid    = str(data.get("room_id","ROOM-DEFAULT")).upper()
    if not rid.startswith("ROOM-"): rid = "ROOM-"+rid
    uid    = make_username()
    tok    = make_token(uid, rid)
    sid    = make_sid()
    get_room(rid)
    sessions[sid] = {"session_id":sid,"username":uid,"token":tok,"room_id":rid,
                     "joined_at":time.time(),"compromised":False}
    svg, url = make_qr(rid, request.host_url)
    return jsonify({"ok":True,"room_id":rid,"username":uid,"session_id":sid,
                    "token":tok,"masked_token":mask_tok(tok),"qr_svg":svg,"join_url":url})

@app.route("/api/room/<room_id>/messages", methods=["GET"])
def api_get_msgs(room_id):
    rid   = room_id.upper()
    since = request.args.get("since", 0, type=int)
    msgs  = [m for m in all_msgs if m["room_id"]==rid and m["id"]>since]
    return jsonify({"ok":True,"messages":msgs[-100:]})

@app.route("/api/room/<room_id>/messages", methods=["POST"])
def api_post_msg(room_id):
    data  = request.get_json(force=True, silent=True) or {}
    sid   = data.get("session_id","")
    text  = str(data.get("content","")).strip()[:200]
    if not text: return jsonify({"ok":False,"error":"empty"}), 400
    sess  = sessions.get(sid)
    if not sess: return jsonify({"ok":False,"error":"invalid session"}), 401
    rid   = room_id.upper()
    room  = get_room(rid)
    hit   = intercept_chance(room)
    msg   = {"id":len(all_msgs)+1,"room_id":rid,"username":sess["username"],
             "content":text,"timestamp":datetime.now(timezone.utc).isoformat(),
             "intercepted":hit,"is_bot":False}
    all_msgs.append(msg)
    room["total_messages"] += 1
    if hit:
        room["intercepted_messages"] += 1
        room["blocked_packets"]      += random.randint(1,5)
    socketio.emit("new_message", msg, room=rid)
    return jsonify({"ok":True,"message":msg})

@app.route("/api/session/<session_id>/check")
def api_session_check(session_id):
    sess = sessions.get(session_id)
    if not sess: return jsonify({"ok":False,"error":"unknown"}), 404
    hit = random.random() < 0.07
    if hit:
        sess["token"] = make_token(sess["username"], sess["room_id"])
        new_sid = make_sid()
        sessions[new_sid] = sess
        sess["session_id"] = new_sid
    return jsonify({"ok":True,"compromised":hit,
                    "masked_token":mask_tok(sess["token"]),
                    "session_id":sess.get("session_id", session_id)})

# ═════════════════════════════════════════════════════════════════════
# SOCKET.IO EVENTS
# ═════════════════════════════════════════════════════════════════════

@socketio.on("join_room")
def ws_join(data):
    rid  = str(data.get("room_id","")).upper()
    sid  = str(data.get("session_id",""))
    sess = sessions.get(sid)
    if not sess or sess["room_id"] != rid:
        emit("error", {"message":"Invalid session"}); return
    room = get_room(rid)
    join_room(rid)
    room["connected_sids"].add(request.sid)
    room["online_users"] = len(room["connected_sids"])
    history = [m for m in all_msgs if m["room_id"]==rid][-50:]
    emit("room_joined", {"room_id":rid,"username":sess["username"],
                         "history":history,"online":room["online_users"]})
    emit("user_joined", {"username":sess["username"],"online":room["online_users"]},
         room=rid, include_self=False)

@socketio.on("send_message")
def ws_send(data):
    sid  = str(data.get("session_id",""))
    rid  = str(data.get("room_id","")).upper()
    text = str(data.get("content","")).strip()[:200]
    sess = sessions.get(sid)
    if not sess or not text: return
    room = get_room(rid)
    hit  = intercept_chance(room)
    msg  = {"id":len(all_msgs)+1,"room_id":rid,"username":sess["username"],
            "content":text,"timestamp":datetime.now(timezone.utc).isoformat(),
            "intercepted":hit,"is_bot":False}
    all_msgs.append(msg)
    room["total_messages"] += 1
    if hit:
        room["intercepted_messages"] += 1
        room["blocked_packets"]      += random.randint(1,5)
    emit("new_message", msg, room=rid)

@socketio.on("disconnect")
def ws_disconnect():
    for rid, room in rooms.items():
        if request.sid in room.get("connected_sids", set()):
            room["connected_sids"].discard(request.sid)
            room["online_users"] = len(room["connected_sids"])
            socketio.emit("user_left", {"online":room["online_users"]}, room=rid)

# ═════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG","false").lower() == "true"
    socketio.start_background_task(broadcast_loop)
    print("="*56)
    print(f"  CipherChat v2  ▸  http://localhost:{port}")
    print(f"  WebSockets : ENABLED (eventlet)")
    print(f"  QR codes   : REAL (qrcode library)")
    print("="*56)
    socketio.run(app, host="0.0.0.0", port=port, debug=debug)
