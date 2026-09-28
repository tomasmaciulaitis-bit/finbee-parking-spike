"""The Garage: finbee's office parking rules, in the words of CONTEXT.md.

Every public method is one thing a Colleague or an Admin does, and each runs as a single
SQLite transaction under one lock, so two people booking the last Space at the same moment
can never both get it.
"""
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, timedelta

import lt

SCHEMA = """
CREATE TABLE IF NOT EXISTS colleagues (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    phone TEXT
);
CREATE TABLE IF NOT EXISTS plates (
    colleague_id INTEGER NOT NULL REFERENCES colleagues(id),
    plate TEXT NOT NULL,
    PRIMARY KEY (colleague_id, plate)
);
CREATE TABLE IF NOT EXISTS spaces (
    id INTEGER PRIMARY KEY,
    number TEXT UNIQUE NOT NULL,
    owner_id INTEGER REFERENCES colleagues(id)
);
CREATE TABLE IF NOT EXISTS closed_days (
    day TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS blocks (
    id INTEGER PRIMARY KEY,
    space_id INTEGER NOT NULL REFERENCES spaces(id),
    first_day TEXT NOT NULL,
    last_day TEXT
);
CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY,
    space_id INTEGER NOT NULL REFERENCES spaces(id),
    day TEXT NOT NULL,
    start_min INTEGER NOT NULL,
    end_min INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY,
    colleague_id INTEGER NOT NULL REFERENCES colleagues(id),
    space_id INTEGER NOT NULL REFERENCES spaces(id),
    day TEXT NOT NULL,
    start_min INTEGER NOT NULL,
    end_min INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS waitlist (
    id INTEGER PRIMARY KEY,
    colleague_id INTEGER NOT NULL REFERENCES colleagues(id),
    day TEXT NOT NULL,
    start_min INTEGER NOT NULL,
    end_min INTEGER NOT NULL,
    joined_at TEXT NOT NULL,
    front INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    window_days INTEGER NOT NULL,
    opening_min INTEGER NOT NULL,
    hours_start_min INTEGER NOT NULL,
    hours_end_min INTEGER NOT NULL,
    booking_limit INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    colleague_id INTEGER NOT NULL REFERENCES colleagues(id),
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders_sent (
    day TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    colleague_id INTEGER NOT NULL REFERENCES colleagues(id),
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    by_email INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    failures INTEGER NOT NULL DEFAULT 0
);
"""

REMINDER_TIME = 18 * 60  # the evening before a Booking
HISTORY_DAYS = 365       # past Bookings are kept this long, then forgotten

# The Booking Rules a new garage starts with; an Admin changes them from then on.
DEFAULT_RULES = {"window_days": 7, "opening_min": 9 * 60, "hours_start_min": 7 * 60,
                 "hours_end_min": 20 * 60, "booking_limit": 2}


def hhmm(minutes):
    return "%02d:%02d" % divmod(minutes, 60)


def to_minutes(text):
    hours, mins = map(int, text.split(":"))
    return hours * 60 + mins


def free_gaps(window, taken):
    """The parts of `window` (start, end) that none of the `taken` periods cover."""
    gaps, cursor = [], window[0]
    for start, end in sorted(taken):
        if start > cursor:
            gaps.append((cursor, min(start, window[1])))
        cursor = max(cursor, end)
    if cursor < window[1]:
        gaps.append((cursor, window[1]))
    return [(start, end) for start, end in gaps if start < end]


def normal_plate(text):
    """'abc 123', 'ABC-123' and 'ABC123' are the same Number Plate."""
    return "".join(ch for ch in text.upper() if ch.isalnum())


def normal_phone(text):
    """'+370 612 34567', '8 612 34567' and '0037061234567' are the same Phone Number,
    '+37061234567'. None when the text isn't a phone number."""
    text = (text or "").strip()
    if not text or "+" in text[1:] or any(ch not in "0123456789+ -()." for ch in text):
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if text.startswith("+"):
        number = "+" + digits
    elif digits.startswith("00"):
        number = "+" + digits[2:]
    elif len(digits) == 9 and digits.startswith("8"):
        number = "+370" + digits[1:]
    elif len(digits) == 8 and digits.startswith("6"):
        number = "+370" + digits
    else:
        return None
    if number.startswith("+370"):
        return number if len(number) == 12 else None
    return number if 9 <= len(number) <= 16 else None


def number_order(number):
    return (0, int(number), "") if number.isdigit() else (1, 0, number)


def choose_space(candidates, start, end):
    """Best fit (ADR-0001): of the Spaces with a free gap around the period, take the one whose
    gap is smallest, so Part-Day Bookings pack together and whole Spaces stay free for
    Whole-Day Bookings. Between equal fits a Shared Space goes before a Released one, which
    leaves the Owner free to Reclaim. `candidates` is [(space_id, number, gaps, owned)]."""
    best = None
    for space_id, number, gaps, owned in candidates:
        for gap_start, gap_end in gaps:
            if gap_start <= start and end <= gap_end:
                key = (gap_end - gap_start, owned, number_order(number))
                if best is None or key < best[0]:
                    best = (key, (space_id, number))
    return best[1] if best else None


@dataclass(frozen=True)
class Colleague:
    id: int
    email: str
    name: str
    is_admin: bool = False
    active: bool = True
    phone: object = None    # '+37061234567'; None only for a Colleague from before Phone Numbers


@dataclass(frozen=True)
class Booking:
    id: int
    space: str
    day: date
    start: str
    end: str


@dataclass(frozen=True)
class WaitlistEntry:
    id: int
    day: date
    start: str
    end: str


@dataclass(frozen=True)
class Rules:
    window_days: int
    opening_time: str
    hours_start: str
    hours_end: str
    booking_limit: int


@dataclass(frozen=True)
class Block:
    id: int
    space: str
    first_day: date
    last_day: object  # a date, or None when the Space is retired from first_day onwards


@dataclass(frozen=True)
class Release:
    id: int
    day: date
    start: str
    end: str
    booked: bool = False  # someone holds part of it, so it can no longer be Reclaimed


@dataclass(frozen=True)
class MySpace:
    """An Owner's view of their Owned Space."""
    number: str
    releases: list  # [Release] from today on


@dataclass(frozen=True)
class Notification:
    """A message the app owes a Colleague. Push always; email too when `by_email`."""
    id: int
    colleague_id: int
    email: str
    title: str
    body: str
    by_email: bool
    failures: int = 0  # rounds in which the email could not be sent


@dataclass(frozen=True)
class HeldTime:
    """Someone's Booking as the Day View shows it to every Colleague."""
    id: int
    name: str
    start: str
    end: str
    mine: bool


@dataclass(frozen=True)
class SpaceDay:
    number: str
    owner: object        # the Owner's name for an Owned Space, else None
    blocked: bool
    released: list       # [(start, end)] an Owned Space's Released periods
    bookings: list       # [HeldTime]


@dataclass(frozen=True)
class Free:
    """A stretch of a day on which `spaces` Spaces could still take a new Booking."""
    start: str
    end: str
    spaces: int


@dataclass(frozen=True)
class DayView:
    day: date
    spaces: list         # [SpaceDay] in Space-number order
    availability: list   # [Free] by start time
    waiting: int         # how many Waitlist Entries the day has; never whose
    my_place: object     # the viewer's place on the Waitlist (1 = next), else None


@dataclass(frozen=True)
class SpaceInfo:
    """A Space as the Admin pages list it."""
    number: str
    owner: object   # the Owner's name, or None for a Shared Space
    blocks: list    # [Block] that haven't ended


@dataclass(frozen=True)
class ColleagueInfo:
    id: int
    name: str
    email: str
    is_admin: bool
    active: bool
    plates: list
    phone: object


@dataclass(frozen=True)
class Waiting:
    """A Waitlist Entry as only Admins see it."""
    name: str
    start: str
    end: str


@dataclass(frozen=True)
class DayOption:
    day: date
    closed: bool


@dataclass(frozen=True)
class MyBookings:
    upcoming: list
    past: list
    waiting: list


class Refused(Exception):
    """A request the Booking Rules don't allow; `code` says which rule."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Garage:
    def __init__(self, db_path, now, first_admin_email=None):
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        if "phone" not in {row["name"] for row in self._db.execute("PRAGMA table_info(colleagues)")}:
            with self._db:  # a garage from before Phone Numbers
                self._db.execute("ALTER TABLE colleagues ADD COLUMN phone TEXT")
        with self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO rules (id, window_days, opening_min, hours_start_min, "
                "hours_end_min, booking_limit) VALUES (1, :window_days, :opening_min, "
                ":hours_start_min, :hours_end_min, :booking_limit)", DEFAULT_RULES)
        self._now = now
        self._first_admin_email = first_admin_email
        self._lock = threading.RLock()

    def register(self, email, name, plates, phone=None):
        """`phone` is required on the Registration page; None is left for older callers."""
        number = normal_phone(phone) if phone is not None else None
        if phone is not None and number is None:
            raise Refused("bad_phone")
        email = email.strip().lower()
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO colleagues (email, name, is_admin, phone) VALUES (?, ?, ?, ?)",
                (email, name.strip(), int(email == (self._first_admin_email or "").lower()), number))
            self._store_plates(cur.lastrowid, plates)
            return self._colleague("id", cur.lastrowid)

    def colleague(self, colleague_id):
        with self._lock:
            return self._colleague("id", colleague_id)

    def colleague_by_email(self, email):
        with self._lock:
            return self._colleague("email", email.strip().lower())

    def _colleague(self, column, value):
        row = self._db.execute("SELECT * FROM colleagues WHERE %s = ?" % column, (value,)).fetchone()
        return row and Colleague(row["id"], row["email"], row["name"], bool(row["is_admin"]),
                                 bool(row["active"]), row["phone"])

    def set_plates(self, who, plates):
        with self._lock, self._db:
            self._db.execute("DELETE FROM plates WHERE colleague_id = ?", (who.id,))
            self._store_plates(who.id, plates)

    def plates(self, who):
        with self._lock:
            return [row["plate"] for row in self._db.execute(
                "SELECT plate FROM plates WHERE colleague_id = ? ORDER BY plate", (who.id,))]

    def set_phone(self, who, phone):
        number = normal_phone(phone)
        if number is None:
            raise Refused("bad_phone")
        with self._lock, self._db:
            self._db.execute("UPDATE colleagues SET phone = ? WHERE id = ?", (number, who.id))

    def whose_plate(self, plate):
        """The active Colleague who drives the car with this Number Plate, if any: their name,
        and their Phone Number to call them on."""
        with self._lock:
            row = self._db.execute(
                "SELECT c.id FROM plates p JOIN colleagues c ON c.id = p.colleague_id "
                "WHERE p.plate = ? AND c.active = 1", (normal_plate(plate),)).fetchone()
            return self._colleague("id", row["id"]) if row else None

    def _store_plates(self, colleague_id, plates):
        for plate in {normal_plate(plate) for plate in plates} - {""}:
            self._db.execute("INSERT INTO plates (colleague_id, plate) VALUES (?, ?)",
                             (colleague_id, plate))

    def add_space(self, actor, number):
        with self._lock, self._db:
            self._require_admin(actor)
            self._db.execute("INSERT INTO spaces (number) VALUES (?)", (number,))
            for day in self._open_days():
                self._promote(day)

    def set_owner(self, actor, number, owner):
        """Make a Space an Owned Space held by `owner`, or a Shared Space again with None. A new
        Owner starts with no Releases, so upcoming Bookings on the Space have to move."""
        with self._lock, self._db:
            self._require_admin(actor)
            space = self._db.execute("SELECT id FROM spaces WHERE number = ?", (number,)).fetchone()
            if space is None:
                raise Refused("not_found")
            if owner is not None and self._db.execute(
                    "SELECT 1 FROM spaces WHERE owner_id = ? AND id != ?",
                    (owner.id, space["id"])).fetchone():
                raise Refused("owns_one")
            today = self._now().date()
            self._db.execute("UPDATE spaces SET owner_id = ? WHERE id = ?",
                             (owner.id if owner else None, space["id"]))
            self._db.execute("DELETE FROM releases WHERE space_id = ? AND day >= ?",
                             (space["id"], today.isoformat()))
            if owner is not None:
                self._displace(space["id"], number, today, None)
            else:
                for day in self._open_days():
                    self._promote(day)

    def release(self, who, day, start=None, end=None, space=None):
        """The Owner makes their Owned Space bookable for a whole day or part of one. An Admin
        can do it on the Owner's behalf by naming the `space`."""
        with self._lock, self._db:
            start_min, end_min = self._period(start, end, day)
            if space is None:
                space = self._db.execute("SELECT id, owner_id FROM spaces WHERE owner_id = ?",
                                         (who.id,)).fetchone()
            else:
                space = self._db.execute("SELECT id, owner_id FROM spaces WHERE number = ?",
                                         (space,)).fetchone()
            if space is None or space["owner_id"] is None or (
                    space["owner_id"] != who.id and not self._is_admin(who)):
                raise Refused("not_allowed")
            if day < self._now().date():
                raise Refused("past_day")
            if self._is_closed(day):
                raise Refused("closed_day")
            if self._db.execute(
                    "SELECT 1 FROM releases WHERE space_id = ? AND day = ? "
                    "AND start_min < ? AND end_min > ?",
                    (space["id"], day.isoformat(), end_min, start_min)).fetchone():
                raise Refused("already_released")
            release_id = self._db.execute(
                "INSERT INTO releases (space_id, day, start_min, end_min) VALUES (?, ?, ?, ?)",
                (space["id"], day.isoformat(), start_min, end_min)).lastrowid
            self._promote(day)
            return Release(release_id, day, hhmm(start_min), hhmm(end_min))

    def my_space(self, who):
        """The Owner's Owned Space and its upcoming Releases; None for everyone else."""
        with self._lock:
            space = self._db.execute("SELECT id, number FROM spaces WHERE owner_id = ?",
                                     (who.id,)).fetchone()
            if space is None:
                return None
            releases = []
            for row in self._db.execute(
                    "SELECT * FROM releases WHERE space_id = ? AND day >= ? ORDER BY day, start_min",
                    (space["id"], self._now().date().isoformat())).fetchall():
                booked = self._db.execute(
                    "SELECT 1 FROM bookings WHERE space_id = ? AND day = ? "
                    "AND start_min < ? AND end_min > ?",
                    (space["id"], row["day"], row["end_min"], row["start_min"])).fetchone() is not None
                releases.append(Release(row["id"], date.fromisoformat(row["day"]),
                                        hhmm(row["start_min"]), hhmm(row["end_min"]), booked))
            return MySpace(space["number"], releases)

    def reclaim(self, who, release_id):
        """The Owner takes back a Released period, but only while nobody has booked any of it:
        nobody is ever bumped from a Booking."""
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT r.* FROM releases r JOIN spaces s ON s.id = r.space_id "
                "WHERE r.id = ? AND s.owner_id = ?", (release_id, who.id)).fetchone()
            if row is None:
                raise Refused("not_found")
            if self._db.execute(
                    "SELECT 1 FROM bookings WHERE space_id = ? AND day = ? "
                    "AND start_min < ? AND end_min > ?",
                    (row["space_id"], row["day"], row["end_min"], row["start_min"])).fetchone():
                raise Refused("booked")
            self._db.execute("DELETE FROM releases WHERE id = ?", (release_id,))

    def block_space(self, actor, number, first_day, last_day=None):
        """Take a Space out of use for some dates, or from `first_day` onwards to retire it.
        Its Bookings that haven't started move to another free Space; where none fits, the
        Booking is cancelled and its Colleague goes to the front of that day's Waitlist."""
        with self._lock, self._db:
            self._require_admin(actor)
            space = self._db.execute("SELECT id FROM spaces WHERE number = ?", (number,)).fetchone()
            block_id = self._db.execute(
                "INSERT INTO blocks (space_id, first_day, last_day) VALUES (?, ?, ?)",
                (space["id"], first_day.isoformat(), last_day and last_day.isoformat())).lastrowid
            self._displace(space["id"], number, first_day, last_day)
            return Block(block_id, number, first_day, last_day)

    def _displace(self, space_id, number, first_day, last_day):
        """Bookings on a Space that can no longer take them, and that haven't started, move to
        another free Space; where none fits, the Booking is cancelled and its Colleague goes to
        the front of that day's Waitlist. Either way the Colleague is told."""
        today, now_min = self._today()
        affected = self._db.execute(
            "SELECT * FROM bookings WHERE space_id = :space AND day >= :first "
            "AND (:last IS NULL OR day <= :last) "
            "AND (day > :today OR (day = :today AND start_min > :now)) ORDER BY id",
            {"space": space_id, "first": first_day.isoformat(),
             "last": last_day and last_day.isoformat(), "today": today, "now": now_min}).fetchall()
        for booking in affected:
            day = date.fromisoformat(booking["day"])
            chosen = choose_space(self._candidates(day), booking["start_min"], booking["end_min"])
            when = "%s, %s" % (lt.sentence(lt.day_label(day)), self._times(booking))
            if chosen is not None:
                self._db.execute("UPDATE bookings SET space_id = ? WHERE id = ?",
                                 (chosen[0], booking["id"]))
                self._notify(booking["colleague_id"], "Jūsų vieta pakeista",
                             "%s: vieta Nr. %s nenaudojama, jūsų nauja vieta – Nr. %s." % (
                                 when, number, chosen[1]))
                continue
            self._db.execute("DELETE FROM bookings WHERE id = ?", (booking["id"],))
            self._db.execute(
                "INSERT INTO waitlist (colleague_id, day, start_min, end_min, joined_at, front) "
                "VALUES (?, ?, ?, ?, ?, 1)", (booking["colleague_id"], booking["day"],
                                              booking["start_min"], booking["end_min"],
                                              self._now().isoformat()))
            self._notify(booking["colleague_id"], "Jūsų rezervacija atšaukta",
                         "%s: vieta Nr. %s nenaudojama, o laisvų vietų nėra. "
                         "Esate pirmas laukiančiųjų sąraše." % (when, number))

    def unblock(self, actor, block_id):
        """End a Block; the Space's time goes straight to the Waitlist."""
        with self._lock, self._db:
            self._require_admin(actor)
            block = self._db.execute("SELECT * FROM blocks WHERE id = ?", (block_id,)).fetchone()
            if block is None:
                raise Refused("not_found")
            self._db.execute("DELETE FROM blocks WHERE id = ?", (block_id,))
            for day in self._open_days():
                if block["first_day"] <= day.isoformat() and (
                        block["last_day"] is None or day.isoformat() <= block["last_day"]):
                    self._promote(day)

    def close_day(self, actor, day):
        """A Closure reaches back: the day's Bookings and Waitlist Entries are cancelled and
        their Colleagues told."""
        with self._lock, self._db:
            self._require_admin(actor)
            self._db.execute("INSERT OR IGNORE INTO closed_days (day) VALUES (?)", (day.isoformat(),))
            label = lt.sentence(lt.day_label(day))
            for table, what in (("bookings", "jūsų rezervacija (%s) atšaukta"),
                                ("waitlist", "jūsų užsirašymas į laukiančiųjų sąrašą (%s) atšauktas")):
                for row in self._db.execute("SELECT * FROM %s WHERE day = ?" % table,
                                            (day.isoformat(),)).fetchall():
                    self._notify(row["colleague_id"], "Diena uždaryta",
                                 "%s: garažas neveiks, %s." % (label, what % self._times(row)))
                self._db.execute("DELETE FROM %s WHERE day = ?" % table, (day.isoformat(),))

    def book(self, who, day, start=None, end=None):
        with self._lock, self._db:
            start_min, end_min = self._period(start, end, day)
            self._check_request(who, day, start_min, end_min)
            chosen = choose_space(self._candidates(day), start_min, end_min)
            if chosen is None:
                raise Refused("no_space")
            space_id, number = chosen
            booking_id = self._insert_booking(who.id, space_id, day, start_min, end_min)
            return Booking(booking_id, number, day, hhmm(start_min), hhmm(end_min))

    def join_waitlist(self, who, day, start=None, end=None):
        with self._lock, self._db:
            start_min, end_min = self._period(start, end, day)
            self._check_request(who, day, start_min, end_min)
            if choose_space(self._candidates(day), start_min, end_min) is not None:
                raise Refused("space_free")
            cur = self._db.execute(
                "INSERT INTO waitlist (colleague_id, day, start_min, end_min, joined_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (who.id, day.isoformat(), start_min, end_min, self._now().isoformat()))
            return WaitlistEntry(cur.lastrowid, day, hhmm(start_min), hhmm(end_min))

    def leave_waitlist(self, who, entry_id):
        with self._lock, self._db:
            if self._db.execute("DELETE FROM waitlist WHERE id = ? AND colleague_id = ?",
                                (entry_id, who.id)).rowcount == 0:
                raise Refused("not_found")

    def _check_request(self, who, day, start_min, end_min):
        """The Booking Rules a new Booking or Waitlist Entry must pass before any Space is sought."""
        if not self._db.execute("SELECT active FROM colleagues WHERE id = ?",
                                (who.id,)).fetchone()["active"]:
            raise Refused("inactive")
        self._check_window(day)
        if self._is_closed(day):
            raise Refused("closed_day")
        owned = self._db.execute("SELECT id FROM spaces WHERE owner_id = ?", (who.id,)).fetchone()
        if owned is not None and not self._is_blocked(owned["id"], day):
            released = [(r["start_min"], r["end_min"]) for r in self._db.execute(
                "SELECT start_min, end_min FROM releases WHERE space_id = ? AND day = ?",
                (owned["id"], day.isoformat()))]
            if free_gaps((start_min, end_min), released):
                raise Refused("owner_holds")
        if self._db.execute(
                "SELECT 1 FROM bookings WHERE colleague_id = :who AND day = :day UNION ALL "
                "SELECT 1 FROM waitlist WHERE colleague_id = :who AND day = :day",
                {"who": who.id, "day": day.isoformat()}).fetchone():
            raise Refused("one_per_day")
        today, now_min = self._today()
        held = self._db.execute(
            "SELECT (SELECT COUNT(*) FROM bookings WHERE colleague_id = :who "
            "        AND (day > :today OR (day = :today AND end_min > :now))) + "
            "       (SELECT COUNT(*) FROM waitlist WHERE colleague_id = :who "
            "        AND (day > :today OR (day = :today AND start_min > :now)))",
            {"who": who.id, "today": today, "now": now_min}).fetchone()[0]
        if held >= self._rules()["booking_limit"]:
            raise Refused("limit")

    def _insert_booking(self, colleague_id, space_id, day, start_min, end_min):
        return self._db.execute(
            "INSERT INTO bookings (colleague_id, space_id, day, start_min, end_min) "
            "VALUES (?, ?, ?, ?, ?)",
            (colleague_id, space_id, day.isoformat(), start_min, end_min)).lastrowid

    def _promote(self, day):
        """Hand freed time to the Waitlist: each Entry in order gets a Booking if its whole
        period fits, with no partial matches, so nobody races for the freed Space."""
        for entry in self._waitlist(day):
            chosen = choose_space(self._candidates(day), entry["start_min"], entry["end_min"])
            if chosen is None:
                continue
            self._insert_booking(entry["colleague_id"], chosen[0], day, entry["start_min"], entry["end_min"])
            self._db.execute("DELETE FROM waitlist WHERE id = ?", (entry["id"],))
            self._notify(entry["colleague_id"], "Gavote vietą Nr. %s" % chosen[1],
                         "%s, %s. Buvote laukiančiųjų sąraše." % (
                             lt.sentence(lt.day_label(day)), self._times(entry)))

    @staticmethod
    def _times(row):
        return "%s–%s" % (hhmm(row["start_min"]), hhmm(row["end_min"]))

    def _notify(self, colleague_id, title, body, by_email=True):
        self._db.execute(
            "INSERT INTO outbox (colleague_id, title, body, by_email, created_at) VALUES (?, ?, ?, ?, ?)",
            (colleague_id, title, body, int(by_email), self._now().isoformat()))

    def queue_reminders(self):
        """From REMINDER_TIME on, nudge everyone booked for tomorrow, once, by push only: it
        asks them to cancel if they won't come, and never cancels anything by itself."""
        with self._lock, self._db:
            now = self._now()
            if now.hour * 60 + now.minute < REMINDER_TIME:
                return
            tomorrow = (now.date() + timedelta(days=1)).isoformat()
            if self._db.execute("INSERT OR IGNORE INTO reminders_sent (day) VALUES (?)",
                                (tomorrow,)).rowcount == 0:
                return
            for row in self._db.execute(
                    "SELECT b.*, s.number FROM bookings b JOIN spaces s ON s.id = b.space_id "
                    "WHERE b.day = ?", (tomorrow,)).fetchall():
                self._notify(row["colleague_id"], "Rytoj turite vietą Nr. %s" % row["number"],
                             "%s. Nevažiuosite? Atšaukite, kad vietą gautų kitas." % self._times(row),
                             by_email=False)

    def forget_old_bookings(self):
        """Past Bookings are kept for a year after their day, then deleted."""
        with self._lock, self._db:
            cutoff = self._now().date() - timedelta(days=HISTORY_DAYS)
            self._db.execute("DELETE FROM bookings WHERE day < ?", (cutoff.isoformat(),))

    def spaces(self):
        with self._lock:
            today = self._now().date().isoformat()
            blocks = {}
            for row in self._db.execute(
                    "SELECT b.*, s.number FROM blocks b JOIN spaces s ON s.id = b.space_id "
                    "WHERE b.last_day IS NULL OR b.last_day >= ? ORDER BY b.first_day", (today,)):
                blocks.setdefault(row["space_id"], []).append(Block(
                    row["id"], row["number"], date.fromisoformat(row["first_day"]),
                    row["last_day"] and date.fromisoformat(row["last_day"])))
            spaces = [SpaceInfo(row["number"], row["owner"], blocks.get(row["id"], []))
                      for row in self._db.execute(
                          "SELECT s.id, s.number, c.name AS owner FROM spaces s "
                          "LEFT JOIN colleagues c ON c.id = s.owner_id")]
            return sorted(spaces, key=lambda s: number_order(s.number))

    def colleagues(self):
        with self._lock:
            plates = {}
            for row in self._db.execute("SELECT * FROM plates ORDER BY plate"):
                plates.setdefault(row["colleague_id"], []).append(row["plate"])
            return [ColleagueInfo(row["id"], row["name"], row["email"], bool(row["is_admin"]),
                                  bool(row["active"]), plates.get(row["id"], []), row["phone"])
                    for row in self._db.execute("SELECT * FROM colleagues ORDER BY active DESC, name")]

    def waiting_names(self, actor, day):
        """Who is waiting for `day`, in Promotion order. Only Admins see names."""
        with self._lock:
            self._require_admin(actor)
            names = {row["id"]: row["name"] for row in self._db.execute("SELECT id, name FROM colleagues")}
            return [Waiting(names[row["colleague_id"]], hhmm(row["start_min"]), hhmm(row["end_min"]))
                    for row in self._waitlist(day)]

    def closed_days(self):
        """The dates an Admin closed, from today on (weekends are always closed)."""
        with self._lock:
            return [date.fromisoformat(row["day"]) for row in self._db.execute(
                "SELECT day FROM closed_days WHERE day >= ? ORDER BY day",
                (self._now().date().isoformat(),))]

    def reopen_day(self, actor, day):
        """Undo a Closure. The Bookings it cancelled stay cancelled."""
        with self._lock, self._db:
            self._require_admin(actor)
            self._db.execute("DELETE FROM closed_days WHERE day = ?", (day.isoformat(),))

    def open_days(self):
        """The days a Colleague can pick: today and the Booking Window's, Closed Days marked."""
        with self._lock:
            return [DayOption(day, self._is_closed(day)) for day in self._open_days()]

    def add_push_subscription(self, who, endpoint, keys):
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO push_subscriptions (endpoint, colleague_id, p256dh, auth) "
                "VALUES (?, ?, ?, ?)", (endpoint, who.id, keys["p256dh"], keys["auth"]))

    def drop_push_subscription(self, endpoint):
        with self._lock, self._db:
            self._db.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))

    def push_subscriptions(self, colleague_id):
        """In the shape the Web Push library takes."""
        with self._lock:
            return [{"endpoint": row["endpoint"], "keys": {"p256dh": row["p256dh"], "auth": row["auth"]}}
                    for row in self._db.execute(
                        "SELECT * FROM push_subscriptions WHERE colleague_id = ? ORDER BY endpoint",
                        (colleague_id,))]

    def pending_notifications(self):
        with self._lock:
            return [Notification(row["id"], row["colleague_id"], row["email"], row["title"],
                                 row["body"], bool(row["by_email"]), row["failures"])
                    for row in self._db.execute(
                        "SELECT o.*, c.email FROM outbox o JOIN colleagues c ON c.id = o.colleague_id "
                        "WHERE o.sent_at IS NULL ORDER BY o.id")]

    def note_failure(self, notification_id):
        with self._lock, self._db:
            self._db.execute("UPDATE outbox SET failures = failures + 1 WHERE id = ?",
                             (notification_id,))

    def mark_sent(self, notification_id):
        with self._lock, self._db:
            self._db.execute("UPDATE outbox SET sent_at = ? WHERE id = ?",
                             (self._now().isoformat(), notification_id))

    def set_admin(self, actor, colleague, is_admin):
        """Any Admin can make another Colleague an Admin or take the role away, but there is
        always at least one Admin."""
        with self._lock, self._db:
            self._require_admin(actor)
            if not is_admin and self._db.execute(
                    "SELECT COUNT(*) FROM colleagues WHERE is_admin = 1 AND id != ?",
                    (colleague.id,)).fetchone()[0] == 0:
                raise Refused("last_admin")
            self._db.execute("UPDATE colleagues SET is_admin = ? WHERE id = ?",
                             (int(is_admin), colleague.id))

    def deactivate(self, actor, colleague):
        """End a Colleague's access at once. Their Bookings that haven't started and their
        Waitlist Entries are cancelled, and an Owned Space they held becomes a Shared Space."""
        with self._lock, self._db:
            self._require_admin(actor)
            if self._db.execute("SELECT is_admin FROM colleagues WHERE id = ?",
                                (colleague.id,)).fetchone()["is_admin"] and self._db.execute(
                    "SELECT COUNT(*) FROM colleagues WHERE is_admin = 1 AND id != ?",
                    (colleague.id,)).fetchone()[0] == 0:
                raise Refused("last_admin")
            today, now_min = self._today()
            upcoming = {"who": colleague.id, "today": today, "now": now_min}
            self._db.execute("DELETE FROM bookings WHERE colleague_id = :who AND "
                             "(day > :today OR (day = :today AND start_min > :now))", upcoming)
            self._db.execute("DELETE FROM waitlist WHERE colleague_id = :who", upcoming)
            self._db.execute("UPDATE spaces SET owner_id = NULL WHERE owner_id = ?", (colleague.id,))
            self._db.execute("DELETE FROM push_subscriptions WHERE colleague_id = ?", (colleague.id,))
            self._db.execute("UPDATE colleagues SET active = 0, is_admin = 0 WHERE id = ?",
                             (colleague.id,))
            for day in self._open_days():
                self._promote(day)

    def _require_admin(self, who):
        if not self._is_admin(who):
            raise Refused("not_allowed")

    def _is_admin(self, who):
        row = self._db.execute("SELECT is_admin FROM colleagues WHERE id = ?", (who.id,)).fetchone()
        return bool(row and row["is_admin"])

    def _rules(self):
        return self._db.execute("SELECT * FROM rules WHERE id = 1").fetchone()

    def _hours(self):
        rules = self._rules()
        return rules["hours_start_min"], rules["hours_end_min"]

    def rules(self):
        with self._lock:
            row = self._rules()
            return Rules(row["window_days"], hhmm(row["opening_min"]), hhmm(row["hours_start_min"]),
                         hhmm(row["hours_end_min"]), row["booking_limit"])

    def set_rules(self, actor, window_days, opening_time, hours_start, hours_end, booking_limit):
        """Change the Booking Rules. Only new Bookings follow them; existing Bookings stand."""
        with self._lock, self._db:
            self._require_admin(actor)
            try:
                values = {"window_days": int(window_days), "opening_min": to_minutes(opening_time),
                          "hours_start_min": to_minutes(hours_start),
                          "hours_end_min": to_minutes(hours_end), "booking_limit": int(booking_limit)}
            except (AttributeError, TypeError, ValueError):
                raise Refused("bad_rules")
            if not (1 <= values["window_days"] <= 60 and 1 <= values["booking_limit"] <= 20
                    and all(values[k] % 30 == 0 and 0 <= values[k] <= 24 * 60
                            for k in ("opening_min", "hours_start_min", "hours_end_min"))
                    and values["hours_end_min"] - values["hours_start_min"] >= 60):
                raise Refused("bad_rules")
            self._db.execute(
                "UPDATE rules SET window_days = :window_days, opening_min = :opening_min, "
                "hours_start_min = :hours_start_min, hours_end_min = :hours_end_min, "
                "booking_limit = :booking_limit WHERE id = 1", values)

    def _today(self):
        """Today as stored ('YYYY-MM-DD') and the current minute of the day."""
        now = self._now()
        return now.date().isoformat(), now.hour * 60 + now.minute

    def _last_open_day(self):
        now = self._now()
        rules = self._rules()
        opened = now.hour * 60 + now.minute >= rules["opening_min"]
        return now.date() + timedelta(days=rules["window_days"] - (0 if opened else 1))

    def _open_days(self):
        """Today and every later day already in the Booking Window."""
        today = self._now().date()
        return [today + timedelta(days=n) for n in range((self._last_open_day() - today).days + 1)]

    def _check_window(self, day):
        """Today and the Booking Window's days after it; the furthest day opens at Opening Time."""
        if not self._now().date() <= day <= self._last_open_day():
            raise Refused("outside_window")

    def _is_blocked(self, space_id, day):
        return self._db.execute(
            "SELECT 1 FROM blocks WHERE space_id = :space AND first_day <= :day "
            "AND (last_day IS NULL OR last_day >= :day)",
            {"space": space_id, "day": day.isoformat()}).fetchone() is not None

    def _is_closed(self, day):
        """Every Saturday and Sunday, plus any date an Admin closed."""
        return day.weekday() >= 5 or self._db.execute(
            "SELECT 1 FROM closed_days WHERE day = ?", (day.isoformat(),)).fetchone() is not None

    def _period(self, start, end, day):
        """A Whole-Day period when no times are given, else a valid Part-Day one. On the day
        itself the period starts no earlier than the current half hour."""
        opens, closes = self._hours()
        if start is None:
            start_min, end_min = opens, closes
        else:
            try:
                start_min, end_min = to_minutes(start), to_minutes(end)
            except (AttributeError, ValueError):
                raise Refused("bad_period")
            if start_min % 30 or end_min % 30 or start_min < opens or end_min > closes:
                raise Refused("bad_period")
        start_min = max(start_min, self._earliest_start(day))
        if end_min - start_min < 60:
            raise Refused("bad_period")
        return start_min, end_min

    def _earliest_start(self, day):
        """The current half hour on `day` itself; no limit on later days."""
        today, now_min = self._today()
        return now_min // 30 * 30 if day.isoformat() == today else 0

    def cancel(self, who, booking_id):
        """Before the start the Booking goes; once started it means leaving, so it ends at the
        next half hour and the rest of the period is freed. An Admin can cancel anyone's
        Booking, and that Colleague is told."""
        with self._lock, self._db:
            row = self._db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
            by_admin = row is not None and row["colleague_id"] != who.id and self._is_admin(who)
            if row is None or (row["colleague_id"] != who.id and not by_admin):
                raise Refused("not_found")
            if by_admin:
                self._notify(row["colleague_id"], "Jūsų rezervacija atšaukta",
                             "%s, %s: rezervaciją atšaukė administratorius." % (
                                 lt.sentence(lt.day_label(date.fromisoformat(row["day"]))),
                                 self._times(row)))
            today, now_min = self._today()
            started = row["day"] < today or (row["day"] == today and row["start_min"] <= now_min)
            if not started:
                self._db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
            else:
                leaving_at = -(-now_min // 30) * 30
                if row["day"] < today or row["end_min"] <= now_min:
                    raise Refused("ended")
                if leaving_at < row["end_min"]:
                    self._db.execute("UPDATE bookings SET end_min = ? WHERE id = ?",
                                     (leaving_at, booking_id))
            self._promote(date.fromisoformat(row["day"]))

    def my_bookings(self, who):
        with self._lock:
            today, now_min = self._today()
            upcoming, past = [], []
            for row in self._db.execute(
                    "SELECT b.*, s.number FROM bookings b JOIN spaces s ON s.id = b.space_id "
                    "WHERE b.colleague_id = ? ORDER BY b.day, b.start_min", (who.id,)):
                ended = row["day"] < today or (row["day"] == today and row["end_min"] <= now_min)
                (past if ended else upcoming).append(self._booking(row))
            waiting = [WaitlistEntry(row["id"], date.fromisoformat(row["day"]),
                                     hhmm(row["start_min"]), hhmm(row["end_min"]))
                       for row in self._db.execute(
                           "SELECT * FROM waitlist WHERE colleague_id = :who "
                           "AND (day > :today OR (day = :today AND start_min > :now)) "
                           "ORDER BY day, start_min", {"who": who.id, "today": today, "now": now_min})]
            return MyBookings(upcoming=upcoming, past=past[::-1], waiting=waiting)

    def day_view(self, day, viewer):
        """What every Colleague sees for a day: each Space, who holds it and when."""
        with self._lock:
            iso = day.isoformat()
            held, released = {}, {}
            for row in self._db.execute(
                    "SELECT b.*, c.name FROM bookings b JOIN colleagues c ON c.id = b.colleague_id "
                    "WHERE b.day = ? ORDER BY b.start_min", (iso,)):
                held.setdefault(row["space_id"], []).append(HeldTime(
                    row["id"], row["name"], hhmm(row["start_min"]), hhmm(row["end_min"]),
                    row["colleague_id"] == viewer.id))
            for row in self._db.execute(
                    "SELECT * FROM releases WHERE day = ? ORDER BY start_min", (iso,)):
                released.setdefault(row["space_id"], []).append(
                    (hhmm(row["start_min"]), hhmm(row["end_min"])))
            spaces = [SpaceDay(row["number"], row["owner"], self._is_blocked(row["id"], day),
                               released.get(row["id"], []), held.get(row["id"], []))
                      for row in self._db.execute(
                          "SELECT s.id, s.number, c.name AS owner FROM spaces s "
                          "LEFT JOIN colleagues c ON c.id = s.owner_id")]
            queue = [row["colleague_id"] for row in self._waitlist(day)]
            return DayView(day, sorted(spaces, key=lambda s: number_order(s.number)),
                           self._availability(day), len(queue),
                           queue.index(viewer.id) + 1 if viewer.id in queue else None)

    def _waitlist(self, day):
        """The day's open Waitlist Entries in Promotion order; lapsed ones are left out."""
        today, now_min = self._today()
        return [row for row in self._db.execute(
            "SELECT * FROM waitlist WHERE day = ? ORDER BY front DESC, joined_at, id",
            (day.isoformat(),)).fetchall()
            if not (row["day"] < today or (row["day"] == today and row["start_min"] <= now_min))]

    def _availability(self, day):
        counts = {}
        for _, _, gaps, _ in self._candidates(day):
            for gap in gaps:
                if gap[1] - gap[0] >= 60:
                    counts[gap] = counts.get(gap, 0) + 1
        return [Free(hhmm(start), hhmm(end), n) for (start, end), n in sorted(counts.items())]

    @staticmethod
    def _booking(row):
        return Booking(row["id"], row["number"], date.fromisoformat(row["day"]),
                       hhmm(row["start_min"]), hhmm(row["end_min"]))

    def _candidates(self, day):
        """Every Space's free gaps on `day`: a Shared Space is open for the Bookable Hours, an
        Owned Space only for the periods its Owner Released."""
        taken, released = {}, {}
        for row in self._db.execute(
                "SELECT space_id, start_min, end_min FROM bookings WHERE day = ?", (day.isoformat(),)):
            taken.setdefault(row["space_id"], []).append((row["start_min"], row["end_min"]))
        for row in self._db.execute(
                "SELECT space_id, start_min, end_min FROM releases WHERE day = ?", (day.isoformat(),)):
            released.setdefault(row["space_id"], []).append((row["start_min"], row["end_min"]))
        candidates = []
        for row in self._db.execute(
                "SELECT id, number, owner_id FROM spaces WHERE id NOT IN (SELECT space_id FROM blocks "
                "WHERE first_day <= :day AND (last_day IS NULL OR last_day >= :day))",
                {"day": day.isoformat()}):
            windows = [self._hours()] if row["owner_id"] is None else released.get(row["id"], [])
            cut = self._earliest_start(day)
            windows = [(max(start, cut), end) for start, end in windows if end > cut]
            gaps = [gap for window in windows for gap in free_gaps(window, taken.get(row["id"], []))]
            candidates.append((row["id"], row["number"], gaps, row["owner_id"] is not None))
        return candidates
