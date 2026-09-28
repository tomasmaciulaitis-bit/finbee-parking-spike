"""Sign-in by a one-time code emailed to a finbee address (ADR-0002: Google sign-in is
unreliable inside an installed iPhone web app).

Codes live in memory only: a restart just means asking for a new one.
"""
import secrets
import threading
from dataclasses import dataclass
from datetime import timedelta

from garage import Refused

ALLOWED_DOMAINS = ("finbeeverslui.lt", "finbee.lt", "finbee.com")
CODE_LIFETIME = timedelta(minutes=10)
MAX_TRIES = 5
RESEND_AFTER = timedelta(minutes=1)


def normal_email(email):
    return email.strip().lower()


@dataclass
class _Code:
    code: str
    sent_at: object
    wrong_tries: int = 0


class SignIn:
    def __init__(self, garage, send_code, now, allowed_domains=ALLOWED_DOMAINS):
        self._garage = garage
        self._send_code = send_code
        self._now = now
        self._allowed = allowed_domains
        self._codes = {}  # email -> _Code
        self._lock = threading.Lock()

    def request_code(self, email):
        email = normal_email(email)
        local, _, domain = email.rpartition("@")
        if not local or domain not in self._allowed:
            raise Refused("not_finbee")
        colleague = self._garage.colleague_by_email(email)
        if colleague is not None and not colleague.active:
            raise Refused("inactive")
        code = "%06d" % secrets.randbelow(10 ** 6)
        with self._lock:
            previous = self._codes.get(email)
            if previous is not None and self._now() - previous.sent_at < RESEND_AFTER:
                raise Refused("too_soon")
            self._codes[email] = _Code(code, self._now())
        self._send_code(email, code)

    def verify(self, email, code):
        """The Colleague the code proves, or None for a finbee address not yet registered."""
        email = normal_email(email)
        with self._lock:
            pending = self._codes.get(email)
            if pending is None:
                raise Refused("wrong_code")
            if pending.wrong_tries >= MAX_TRIES:
                raise Refused("too_many_tries")
            if self._now() - pending.sent_at >= CODE_LIFETIME:
                del self._codes[email]
                raise Refused("expired")
            if not secrets.compare_digest(pending.code, code.strip()):
                pending.wrong_tries += 1
                raise Refused("wrong_code")
            del self._codes[email]
        colleague = self._garage.colleague_by_email(email)
        if colleague is not None and not colleague.active:
            raise Refused("inactive")
        return colleague
