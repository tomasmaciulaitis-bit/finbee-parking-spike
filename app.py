"""PROTOTYPE - throwaway iPhone spike for parking-app. Not the real app; delete once answered.

The question (ADR-0002): on a real iPhone, does an installable web app
  1. open standalone from the Home Screen,
  2. receive web push notifications once allowed, even while it is closed, and
  3. keep an email-code sign-in across closing and reopening it?

Run:  ./run.sh   -> http://127.0.0.1:5090
State lives in memory. Only the secret behind the session cookie and the VAPID key must survive
restarts, or every sign-in and push subscription breaks: it comes from PROTOTYPE_SECRET_KEY, or
locally from PROTOTYPE-wipe-me.json.

Env (.env next to this file; set_app_password.py writes the mail pair):
  PARKING_SENDER_EMAIL, PARKING_SENDER_APP_PASSWORD  Eudora's shared mailbox, "parking" app password
  PROTOTYPE_SECRET_KEY     long random string (Render generates it from render.yaml)
  PROTOTYPE_PRINT_CODES=1  log sign-in codes instead of emailing them (local testing only)
  PROTOTYPE_HTTPS=1        behind an HTTPS proxy (Render, Funnel): Secure cookie, trust X-Forwarded-*
  HOST, PORT               bind address (Render sets PORT; use HOST=0.0.0.0 there)
"""
import base64
import hashlib
import json
import os
import pathlib
import secrets
import smtplib
import struct
import threading
import time
import zlib
from datetime import timedelta
from email.message import EmailMessage

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory, session
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from werkzeug.middleware.proxy_fix import ProxyFix

HERE = pathlib.Path(__file__).resolve().parent
ALLOWED_DOMAINS = ("finbeeverslui.lt", "finbee.lt", "finbee.com")
CODE_TTL_SECONDS = 10 * 60
P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def load_env():
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def load_keys():
    secret = os.environ.get("PROTOTYPE_SECRET_KEY")
    if not secret:
        path = HERE / "PROTOTYPE-wipe-me.json"
        if path.exists():
            secret = json.loads(path.read_text())["secret_key"]
        else:
            secret = secrets.token_hex(32)
            path.write_text(json.dumps({"secret_key": secret}))
            path.chmod(0o600)
    # The VAPID key is derived from the secret so that one value survives restarts: Render's
    # free tier has no disk, and a new key would silently break every push subscription.
    scalar = int.from_bytes(hashlib.sha256(("vapid:" + secret).encode()).digest(), "big") % P256_ORDER
    private = ec.derive_private_key(scalar, ec.SECP256R1())
    vapid = Vapid.from_pem(private.private_bytes(serialization.Encoding.PEM,
                                                 serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption()))
    raw = vapid.public_key.public_bytes(serialization.Encoding.X962,
                                        serialization.PublicFormat.UncompressedPoint)
    return vapid, base64.urlsafe_b64encode(raw).rstrip(b"=").decode(), secret


def solid_png(size, rgb=(0xFD, 0xB8, 0x13)):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    pixels = (b"\x00" + bytes(rgb) * size) * size
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels, 9)) + chunk(b"IEND", b""))


load_env()
VAPID, VAPID_PUBLIC, SECRET_KEY = load_keys()
VAPID_SUB = "mailto:" + (os.environ.get("PARKING_SENDER_EMAIL") or "parking-prototype@finbeeverslui.lt")
HTTPS = os.environ.get("PROTOTYPE_HTTPS") == "1"
PRINT_CODES = os.environ.get("PROTOTYPE_PRINT_CODES") == "1"

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(PERMANENT_SESSION_LIFETIME=timedelta(days=90),
                  SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=HTTPS)
if HTTPS:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

ICONS = {180: solid_png(180), 512: solid_png(512)}
CODES = {}    # email -> (code, expires_at)
SUBS = {}     # browser id -> push subscription
EVENTS = []   # (time, browser id, text)
LOCK = threading.Lock()


def browser_id():
    if "sid" not in session:
        session["sid"] = secrets.token_hex(4)
        session.permanent = True
    return session["sid"]


def log(sid, text):
    with LOCK:
        EVENTS.append((time.strftime("%H:%M:%S"), sid, text))
        del EVENTS[:-300]
    print("[%s] %s" % (sid, text), flush=True)


def state():
    sid = browser_id()
    sub = SUBS.get(sid)
    return {
        "sid": sid,
        "email": session.get("email"),
        "signed_in_at": session.get("signed_in_at"),
        "signed_in_in": session.get("signed_in_in"),
        "subscription": sub["endpoint"].split("/")[2] if sub else None,
        "mail_configured": PRINT_CODES or bool(os.environ.get("PARKING_SENDER_APP_PASSWORD")),
        "events": ["%s %s" % (t, text) for t, s, text in EVENTS if s == sid][-15:],
    }


def send_code_email(to, code):
    sender = os.environ["PARKING_SENDER_EMAIL"]
    msg = EmailMessage()
    msg["Subject"] = "Parkavimo prisijungimo kodas: %s" % code
    msg["From"] = "finbee parkavimas <%s>" % sender
    msg["To"] = to
    msg.set_content("Jūsų prisijungimo kodas: %s\n\nKodas galioja 10 minučių.\n\n"
                    "Tai bandomasis parkavimo programėlės prototipas.\n" % code)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
        smtp.login(sender, os.environ["PARKING_SENDER_APP_PASSWORD"])
        smtp.send_message(msg)


def push(sid, sub):
    payload = {"title": "Gavote vietą Nr. 4", "body": "Ketvirtadienis, 13:00–17:00 (bandomasis pranešimas)"}
    try:
        # ttl: the default of 0 lets the push service drop it if the phone is asleep
        r = webpush(sub, json.dumps(payload, ensure_ascii=False), vapid_private_key=VAPID,
                    vapid_claims={"sub": VAPID_SUB}, ttl=3600)
        log(sid, "pranešimas išsiųstas, atsakymas %s" % r.status_code)
    except WebPushException as e:
        status = e.response.status_code if e.response is not None else "?"
        log(sid, "pranešimo klaida %s: %s" % (status, str(e)[:200]))


@app.get("/")
def index():
    browser_id()
    return render_template("index.html", vapid_public=VAPID_PUBLIC)


@app.get("/manifest.webmanifest")
def manifest():
    return Response(json.dumps({
        "name": "Parkavimas (prototipas)",
        "short_name": "Parkavimas",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#FDB813",
        "icons": [{"src": "/icon-180.png", "sizes": "180x180", "type": "image/png"},
                  {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }, ensure_ascii=False), mimetype="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    return send_from_directory(HERE / "static", "sw.js", mimetype="application/javascript", max_age=0)


@app.get("/icon-<int:size>.png")
def icon(size):
    if size not in ICONS:
        abort(404)
    return Response(ICONS[size], mimetype="image/png")


@app.get("/api/state")
def api_state():
    return jsonify(state())


@app.post("/api/send-code")
def send_code():
    email = (request.json or {}).get("email", "").strip().lower()
    if email.rpartition("@")[2] not in ALLOWED_DOMAINS:
        return jsonify(error="Tik finbee el. pašto adresai (finbeeverslui.lt, finbee.lt, finbee.com)."), 400
    code = "%06d" % secrets.randbelow(10 ** 6)
    CODES[email] = (code, time.time() + CODE_TTL_SECONDS)
    if PRINT_CODES:
        log(browser_id(), "kodas %s: %s (laiškas nesiųstas, PROTOTYPE_PRINT_CODES)" % (email, code))
    else:
        try:
            send_code_email(email, code)
        except Exception as e:
            log(browser_id(), "laiško klaida: %s: %s" % (type(e).__name__, e))
            return jsonify(error="Nepavyko išsiųsti laiško (%s)." % type(e).__name__), 502
        log(browser_id(), "kodas išsiųstas į %s" % email)
    return jsonify(state())


@app.post("/api/verify-code")
def verify_code():
    body = request.json or {}
    email = body.get("email", "").strip().lower()
    code, expires_at = CODES.get(email, (None, 0))
    if not code or time.time() > expires_at or body.get("code", "").strip() != code:
        return jsonify(error="Neteisingas arba pasibaigęs kodas."), 400
    del CODES[email]
    session.permanent = True
    session["email"] = email
    session["signed_in_at"] = time.strftime("%Y-%m-%d %H:%M")
    session["signed_in_in"] = body.get("display_mode")
    log(browser_id(), "prisijungta (%s)" % body.get("display_mode"))
    return jsonify(state())


@app.post("/api/sign-out")
def sign_out():
    sid = browser_id()
    session.clear()
    session["sid"] = sid
    session.permanent = True
    log(sid, "atsijungta")
    return jsonify(state())


@app.post("/api/subscribe")
def subscribe():
    sid = browser_id()
    SUBS[sid] = request.json
    log(sid, "prenumerata užregistruota (%s)" % request.json["endpoint"].split("/")[2])
    return jsonify(state())


@app.post("/api/test-push")
def test_push():
    sid = browser_id()
    sub = SUBS.get(sid)
    if not sub:
        return jsonify(error="Pirma įjunkite pranešimus."), 400
    delay = int((request.json or {}).get("delay", 0))
    if delay:
        threading.Timer(delay, push, args=(sid, sub)).start()
        log(sid, "pranešimas bus išsiųstas po %d s — uždarykite programėlę arba užrakinkite telefoną" % delay)
    else:
        push(sid, sub)
    return jsonify(state())


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5090")),
            threaded=True)
