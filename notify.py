"""Delivers the notifications the Garage queues: a push to every device the Colleague allowed
notifications on, and an email as well for anything that changed their Bookings without them
(ADR-0002: a push can silently fail, so it is never the only record of anything)."""
import base64
import json
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger("parking.notify")
MAX_EMAIL_ROUNDS = 5
PUSH_TTL_SECONDS = 12 * 3600  # the default of 0 lets the push service drop it if the phone sleeps


class PushGone(Exception):
    """The push service says this subscription no longer exists (HTTP 404 or 410)."""


class Notifier:
    def __init__(self, garage, send_push, send_email):
        self._garage = garage
        self._send_push = send_push
        self._send_email = send_email

    def deliver_pending(self):
        """Email goes first because it must arrive: if it fails the notification stays queued
        for the next round, and the push waits with it so nobody gets it twice."""
        for note in self._garage.pending_notifications():
            if note.by_email:
                try:
                    self._send_email(note.email, note.title, note.body)
                except Exception:
                    if note.failures + 1 < MAX_EMAIL_ROUNDS:
                        log.exception("email to colleague %s failed; will retry", note.colleague_id)
                        self._garage.note_failure(note.id)
                        continue
                    log.exception("email to colleague %s failed %d times; giving up",
                                  note.colleague_id, MAX_EMAIL_ROUNDS)
            for subscription in self._garage.push_subscriptions(note.colleague_id):
                try:
                    self._send_push(subscription, note.title, note.body)
                except PushGone:
                    self._garage.drop_push_subscription(subscription["endpoint"])
                except Exception:  # a push is best effort; the app itself is the record
                    log.exception("push to colleague %s failed", note.colleague_id)
            self._garage.mark_sent(note.id)


def load_vapid(data_dir):
    """The server's Web Push key pair, made once and kept on the data disk: a new key would
    silently break every Colleague's push subscription. Returns (key, public key for browsers)."""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    path = Path(data_dir) / "vapid_private.pem"
    if not path.exists():
        fresh = Vapid()
        fresh.generate_keys()
        path.write_bytes(fresh.private_pem())
        path.chmod(0o600)
    vapid = Vapid.from_pem(path.read_bytes())
    raw = vapid.public_key.public_bytes(serialization.Encoding.X962,
                                        serialization.PublicFormat.UncompressedPoint)
    return vapid, base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def web_push_sender(vapid, contact_email):
    from pywebpush import WebPushException, webpush

    def send(subscription, title, body):
        payload = json.dumps({"title": title, "body": body, "url": "/mano"}, ensure_ascii=False)
        try:
            webpush(subscription, payload, vapid_private_key=vapid,
                    vapid_claims={"sub": "mailto:" + contact_email}, ttl=PUSH_TTL_SECONDS)
        except WebPushException as error:
            if error.response is not None and error.response.status_code in (404, 410):
                raise PushGone(subscription["endpoint"])
            raise
    return send


def gmail_sender(address, app_password, display_name="finbee parkavimas"):
    """Sends through Gmail with an app password. Needs a paid Render instance: the free plan
    blocks outbound SMTP (ADR-0004)."""
    def send(to, subject, body):
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = "%s <%s>" % (display_name, address)
        message["To"] = to
        message.set_content(body)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(address, app_password)
            smtp.send_message(message)
    return send
