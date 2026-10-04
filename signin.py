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
# Per hour: wrong codes before an address is locked for the hour, codes one address can get (so
# nobody's inbox is flooded), and codes in all (so the shared mailbox stays under Gmail's limit).
HOUR = timedelta(hours=1)
WRONG_PER_ADDRESS = 10
CODES_PER_ADDRESS = 5
CODES_IN_ALL = 40


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
        self._sent = {}   # email -> when codes went out, within the hour
        self._all_sent = []
        self._wrong = {}  # email -> when wrong codes were tried, within the hour
        self._lock = threading.Lock()

    def _within_hour(self, times):
        since = self._now() - HOUR
        return [when for when in times if when > since]

    def _locked(self, email):
        self._wrong[email] = self._within_hour(self._wrong.get(email, []))
        return len(self._wrong[email]) >= WRONG_PER_ADDRESS

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
            if self._locked(email):
                raise Refused("locked")
            previous = self._codes.get(email)
            if previous is not None and self._now() - previous.sent_at < RESEND_AFTER:
                raise Refused("too_soon")
            sent = self._sent[email] = self._within_hour(self._sent.get(email, []))
            if len(sent) >= CODES_PER_ADDRESS:
                raise Refused("too_many_codes")
            self._all_sent = self._within_hour(self._all_sent)
            if len(self._all_sent) >= CODES_IN_ALL:
                raise Refused("busy")
            sent.append(self._now())
            self._all_sent.append(self._now())
            self._codes[email] = _Code(code, self._now())
        self._send_code(email, code)

    def verify(self, email, code):
        """The Colleague the code proves, or None for a finbee address not yet registered."""
        email = normal_email(email)
        with self._lock:
            if self._locked(email):
                raise Refused("locked")
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
                self._wrong.setdefault(email, []).append(self._now())
                raise Refused("wrong_code")
            del self._codes[email]
        colleague = self._garage.colleague_by_email(email)
        if colleague is not None and not colleague.active:
            raise Refused("inactive")
        return colleague
