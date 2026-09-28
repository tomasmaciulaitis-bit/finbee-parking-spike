import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from garage import Garage, Refused  # noqa: E402

VILNIUS = ZoneInfo("Europe/Vilnius")
MONDAY = date(2026, 10, 5)
TUESDAY = date(2026, 10, 6)


class Clock:
    def __init__(self, day, hhmm):
        self.set(day, hhmm)

    def __call__(self):
        return self.when

    def set(self, day, hhmm):
        hour, minute = map(int, hhmm.split(":"))
        self.when = datetime(day.year, day.month, day.day, hour, minute, tzinfo=VILNIUS)


class GarageTest(unittest.TestCase):
    """Default Booking Rules: 7-day window opening at 09:00, hours 07:00-20:00, limit 2.
    The clock starts on Monday 2026-10-05 at 10:00."""

    def setUp(self):
        self.clock = Clock(MONDAY, "10:00")
        self.garage = Garage(":memory:", now=self.clock, first_admin_email="admin@finbeeverslui.lt")
        self.admin = self.garage.register("admin@finbeeverslui.lt", "Admin", [])

    def colleague(self, name):
        return self.garage.register("%s@finbeeverslui.lt" % name.lower(), name, [])

    def spaces(self, *numbers):
        for number in numbers:
            self.garage.add_space(self.admin, number)


class BookingTest(GarageTest):
    def test_a_whole_day_booking_gets_a_space_for_all_bookable_hours(self):
        self.spaces("12")
        booking = self.garage.book(self.colleague("Ona"), TUESDAY)
        self.assertEqual((booking.space, booking.start, booking.end), ("12", "07:00", "20:00"))

    def test_part_day_bookings_are_packed_so_a_whole_day_booking_still_fits(self):
        self.spaces("4", "5")
        morning = self.garage.book(self.colleague("Ona"), TUESDAY, "09:00", "12:00")
        afternoon = self.garage.book(self.colleague("Jonas"), TUESDAY, "13:00", "17:00")
        whole_day = self.garage.book(self.colleague("Rūta"), TUESDAY)
        self.assertEqual({morning.space, afternoon.space, whole_day.space}, {"4", "5"})

    def test_a_part_day_booking_must_be_an_hour_or_more_in_half_hours_within_bookable_hours(self):
        self.spaces("12")
        ona = self.colleague("Ona")
        for start, end in [("09:00", "09:30"), ("09:15", "11:00"), ("06:30", "09:00"),
                           ("18:00", "20:30"), ("12:00", "11:00")]:
            with self.subTest(period=(start, end)):
                with self.assertRaises(Refused) as refused:
                    self.garage.book(ona, TUESDAY, start, end)
                self.assertEqual(refused.exception.code, "bad_period")

    def test_a_colleague_holds_at_most_one_booking_a_day(self):
        self.spaces("4", "5")
        ona = self.colleague("Ona")
        self.garage.book(ona, TUESDAY, "09:00", "12:00")
        with self.assertRaises(Refused) as refused:
            self.garage.book(ona, TUESDAY, "13:00", "17:00")
        self.assertEqual(refused.exception.code, "one_per_day")


class DayPickerTest(GarageTest):
    def test_the_days_on_offer_are_today_and_the_window_with_closed_days_marked(self):
        self.garage.close_day(self.admin, date(2026, 10, 8))
        days = [(d.day.day, d.closed) for d in self.garage.open_days()]
        self.assertEqual(days, [(5, False), (6, False), (7, False), (8, True), (9, False),
                                (10, True), (11, True), (12, False)])


class PushSubscriptionTest(GarageTest):
    def test_a_colleagues_push_subscriptions_can_be_added_and_dropped(self):
        ona = self.colleague("Ona")
        self.garage.add_push_subscription(ona, "https://web.push.apple.com/a", {"p256dh": "k", "auth": "s"})
        self.garage.add_push_subscription(ona, "https://web.push.apple.com/b", {"p256dh": "k", "auth": "s"})
        self.garage.drop_push_subscription("https://web.push.apple.com/a")
        self.assertEqual([s["endpoint"] for s in self.garage.push_subscriptions(ona.id)],
                         ["https://web.push.apple.com/b"])


class SameDayTest(GarageTest):
    def test_a_whole_day_booking_made_during_the_day_covers_the_rest_of_it(self):
        self.spaces("12")
        self.clock.set(MONDAY, "10:10")
        booking = self.garage.book(self.colleague("Ona"), MONDAY)
        self.assertEqual((booking.start, booking.end), ("10:00", "20:00"))

    def test_todays_availability_starts_now(self):
        self.spaces("12")
        self.clock.set(MONDAY, "10:10")
        view = self.garage.day_view(MONDAY, self.colleague("Ona"))
        self.assertEqual([(f.start, f.end) for f in view.availability], [("10:00", "20:00")])


class BookingWindowTest(GarageTest):
    def test_the_day_a_week_ahead_opens_at_the_opening_time(self):
        self.spaces("12")
        ona = self.colleague("Ona")
        next_monday = date(2026, 10, 12)
        self.clock.set(MONDAY, "08:59")
        with self.assertRaises(Refused) as refused:
            self.garage.book(ona, next_monday)
        self.assertEqual(refused.exception.code, "outside_window")
        self.clock.set(MONDAY, "09:00")
        self.assertEqual(self.garage.book(ona, next_monday).day, next_monday)

    def test_past_days_and_days_beyond_the_window_are_refused(self):
        self.spaces("12")
        ona = self.colleague("Ona")
        for day in (date(2026, 10, 2), date(2026, 10, 13)):
            with self.subTest(day=day):
                with self.assertRaises(Refused) as refused:
                    self.garage.book(ona, day)
                self.assertEqual(refused.exception.code, "outside_window")


class BookingLimitTest(GarageTest):
    def test_a_third_upcoming_booking_is_refused(self):
        self.spaces("12")
        ona = self.colleague("Ona")
        self.garage.book(ona, TUESDAY)
        self.garage.book(ona, date(2026, 10, 7))
        with self.assertRaises(Refused) as refused:
            self.garage.book(ona, date(2026, 10, 8))
        self.assertEqual(refused.exception.code, "limit")

    def test_a_booking_that_has_ended_no_longer_counts(self):
        self.spaces("12")
        ona = self.colleague("Ona")
        self.garage.book(ona, TUESDAY)
        self.garage.book(ona, date(2026, 10, 7))
        self.clock.set(TUESDAY, "20:00")
        self.assertEqual(self.garage.book(ona, date(2026, 10, 8)).day, date(2026, 10, 8))

    def test_waitlist_entries_count_toward_the_limit(self):
        self.spaces("12")
        ona, jonas = self.colleague("Ona"), self.colleague("Jonas")
        self.garage.book(jonas, TUESDAY)
        self.garage.book(ona, date(2026, 10, 7))
        self.garage.join_waitlist(ona, TUESDAY)
        with self.assertRaises(Refused) as refused:
            self.garage.book(ona, date(2026, 10, 8))
        self.assertEqual(refused.exception.code, "limit")


class CancellationTest(GarageTest):
    def test_cancelling_before_the_start_frees_the_space(self):
        self.spaces("12")
        ona, jonas = self.colleague("Ona"), self.colleague("Jonas")
        booking = self.garage.book(ona, TUESDAY)
        self.garage.cancel(ona, booking.id)
        self.assertEqual(self.garage.book(jonas, TUESDAY).space, "12")

    def test_cancelling_after_the_start_means_leaving_at_the_next_half_hour(self):
        self.spaces("12")
        ona = self.colleague("Ona")
        booking = self.garage.book(ona, TUESDAY)
        self.clock.set(TUESDAY, "10:10")
        self.garage.cancel(ona, booking.id)
        [kept] = self.garage.my_bookings(ona).upcoming
        self.assertEqual((kept.start, kept.end), ("07:00", "10:30"))


class WaitlistTest(GarageTest):
    def test_freed_time_goes_to_the_first_entry_whose_whole_period_fits(self):
        self.spaces("12")
        ona, jonas, ruta, tomas = (self.colleague(n) for n in ("Ona", "Jonas", "Ruta", "Tomas"))
        self.garage.book(ona, TUESDAY, "09:00", "13:00")
        afternoon = self.garage.book(jonas, TUESDAY, "13:00", "17:00")
        self.garage.join_waitlist(ruta, TUESDAY)
        self.garage.join_waitlist(tomas, TUESDAY, "13:30", "16:30")
        self.garage.cancel(jonas, afternoon.id)
        promoted = [(b.space, b.start, b.end) for b in self.garage.my_bookings(tomas).upcoming]
        self.assertEqual(promoted, [("12", "13:30", "16:30")])

    def test_leaving_the_waitlist_gives_the_place_to_the_next_in_line(self):
        self.spaces("12")
        ona = self.colleague("Ona")
        booking = self.garage.book(ona, TUESDAY)
        jonas, ruta = self.colleague("Jonas"), self.colleague("Ruta")
        entry = self.garage.join_waitlist(jonas, TUESDAY)
        self.garage.join_waitlist(ruta, TUESDAY)
        self.garage.leave_waitlist(jonas, entry.id)
        self.garage.cancel(ona, booking.id)
        self.assertEqual(([b.space for b in self.garage.my_bookings(ruta).upcoming],
                          self.garage.my_bookings(jonas).waiting), (["12"], []))

    def test_joining_is_refused_while_a_space_would_fit(self):
        self.spaces("12")
        with self.assertRaises(Refused) as refused:
            self.garage.join_waitlist(self.colleague("Ona"), TUESDAY)
        self.assertEqual(refused.exception.code, "space_free")

    def test_a_colleague_waiting_for_a_day_cannot_also_book_it(self):
        self.spaces("12")
        ona, jonas = self.colleague("Ona"), self.colleague("Jonas")
        self.garage.book(jonas, TUESDAY, "09:00", "20:00")
        self.garage.join_waitlist(ona, TUESDAY)
        with self.assertRaises(Refused) as refused:
            self.garage.book(ona, TUESDAY, "07:00", "09:00")
        self.assertEqual(refused.exception.code, "one_per_day")

    def test_an_entry_lapses_once_its_period_starts(self):
        self.spaces("12")
        ona, jonas = self.colleague("Ona"), self.colleague("Jonas")
        self.garage.book(jonas, TUESDAY)
        entry = self.garage.join_waitlist(ona, TUESDAY, "09:00", "12:00")
        self.clock.set(TUESDAY, "08:59")
        self.assertEqual(self.garage.my_bookings(ona).waiting, [entry])
        self.clock.set(TUESDAY, "09:00")
        self.assertEqual(self.garage.my_bookings(ona).waiting, [])

    def test_a_promotion_never_books_time_that_has_already_started(self):
        self.spaces("5")
        ona, jonas = self.colleague("Ona"), self.colleague("Jonas")
        self.garage.book(jonas, TUESDAY)
        self.garage.join_waitlist(ona, TUESDAY, "09:00", "12:00")
        self.clock.set(TUESDAY, "09:10")
        self.garage.add_space(self.admin, "7")
        self.assertEqual(self.garage.my_bookings(ona).upcoming, [])

    def test_a_promotion_tells_the_colleague_by_push_and_email(self):
        self.spaces("12")
        ona, jonas = self.colleague("Ona"), self.colleague("Jonas")
        booking = self.garage.book(jonas, TUESDAY)
        self.garage.join_waitlist(ona, TUESDAY)
        self.garage.cancel(jonas, booking.id)
        [note] = self.garage.pending_notifications()
        self.assertEqual((note.colleague_id, note.title, note.body, note.by_email),
                         (ona.id, "Gavote vietą Nr. 12",
                          "Antradienis, spalio 6 d., 07:00–20:00. Buvote laukiančiųjų sąraše.", True))


class OwnedSpaceTest(GarageTest):
    def setUp(self):
        super().setUp()
        self.spaces("1")
        self.ceo = self.colleague("Ceo")
        self.garage.set_owner(self.admin, "1", self.ceo)

    def test_an_owned_space_is_not_shared(self):
        with self.assertRaises(Refused) as refused:
            self.garage.book(self.colleague("Ona"), TUESDAY)
        self.assertEqual(refused.exception.code, "no_space")

    def test_a_release_makes_the_owned_space_bookable_for_that_period(self):
        self.garage.release(self.ceo, TUESDAY, "12:00", "20:00")
        self.assertEqual(self.garage.book(self.colleague("Ona"), TUESDAY, "13:00", "17:00").space, "1")

    def test_a_release_promotes_a_waiting_colleague(self):
        ona = self.colleague("Ona")
        self.garage.join_waitlist(ona, TUESDAY)
        self.garage.release(self.ceo, TUESDAY)
        self.assertEqual([b.space for b in self.garage.my_bookings(ona).upcoming], ["1"])

    def test_an_owner_can_reclaim_a_release_nobody_has_booked(self):
        release = self.garage.release(self.ceo, TUESDAY)
        self.garage.reclaim(self.ceo, release.id)
        with self.assertRaises(Refused) as refused:
            self.garage.book(self.colleague("Ona"), TUESDAY)
        self.assertEqual(refused.exception.code, "no_space")

    def test_a_release_someone_booked_cannot_be_reclaimed(self):
        release = self.garage.release(self.ceo, TUESDAY)
        self.garage.book(self.colleague("Ona"), TUESDAY, "09:00", "12:00")
        with self.assertRaises(Refused) as refused:
            self.garage.reclaim(self.ceo, release.id)
        self.assertEqual(refused.exception.code, "booked")

    def test_an_owner_cannot_book_while_holding_their_own_space(self):
        self.spaces("12")
        with self.assertRaises(Refused) as refused:
            self.garage.book(self.ceo, TUESDAY)
        self.assertEqual(refused.exception.code, "owner_holds")

    def test_a_released_space_is_used_only_when_no_shared_space_fits(self):
        self.spaces("12")
        self.garage.release(self.ceo, TUESDAY)
        self.assertEqual(self.garage.book(self.colleague("Ona"), TUESDAY).space, "12")

    def test_an_owner_whose_released_space_was_taken_can_book_a_shared_one(self):
        self.spaces("12")
        jonas = self.colleague("Jonas")
        jonas_booking = self.garage.book(jonas, TUESDAY)
        self.garage.release(self.ceo, TUESDAY)
        self.garage.book(self.colleague("Ona"), TUESDAY)
        self.garage.cancel(jonas, jonas_booking.id)
        self.assertEqual(self.garage.book(self.ceo, TUESDAY).space, "12")

    def test_releases_cannot_overlap_or_fall_on_closed_or_past_days(self):
        self.garage.release(self.ceo, TUESDAY, "09:00", "13:00")
        cases = {"already_released": (TUESDAY, "12:00", "15:00"),
                 "closed_day": (date(2026, 10, 10), None, None),
                 "past_day": (date(2026, 10, 2), None, None)}
        for code, (day, start, end) in cases.items():
            with self.subTest(code=code):
                with self.assertRaises(Refused) as refused:
                    self.garage.release(self.ceo, day, start, end)
                self.assertEqual(refused.exception.code, code)

    def test_an_owner_sees_their_space_upcoming_releases_and_which_are_booked(self):
        wednesday = date(2026, 10, 7)
        self.garage.release(self.ceo, TUESDAY, "07:00", "12:00")
        self.garage.release(self.ceo, wednesday)
        self.garage.book(self.colleague("Ona"), wednesday, "09:00", "12:00")
        mine = self.garage.my_space(self.ceo)
        self.assertEqual((mine.number, [(r.day, r.start, r.end, r.booked) for r in mine.releases]),
                         ("1", [(TUESDAY, "07:00", "12:00", False), (wednesday, "07:00", "20:00", True)]))

    def test_an_admin_can_release_on_the_owners_behalf(self):
        self.garage.release(self.admin, TUESDAY, space="1")
        self.assertEqual(self.garage.book(self.colleague("Ona"), TUESDAY).space, "1")

    def test_only_the_owner_or_an_admin_can_release_a_space(self):
        with self.assertRaises(Refused) as refused:
            self.garage.release(self.colleague("Ona"), TUESDAY, space="1")
        self.assertEqual(refused.exception.code, "not_allowed")


class OwnershipChangeTest(GarageTest):
    def test_bookings_on_a_space_that_becomes_owned_move_to_a_free_one(self):
        self.spaces("5", "6")
        ona = self.colleague("Ona")
        self.garage.book(ona, TUESDAY)
        self.garage.set_owner(self.admin, "5", self.colleague("Ceo"))
        self.assertEqual([b.space for b in self.garage.my_bookings(ona).upcoming], ["6"])

    def test_a_colleague_owns_at_most_one_space(self):
        self.spaces("5", "6")
        ceo = self.colleague("Ceo")
        self.garage.set_owner(self.admin, "5", ceo)
        with self.assertRaises(Refused) as refused:
            self.garage.set_owner(self.admin, "6", ceo)
        self.assertEqual(refused.exception.code, "owns_one")


class BlockedSpaceTest(GarageTest):
    def test_blocking_a_space_moves_its_bookings_to_a_free_one(self):
        self.spaces("5", "6")
        ona = self.colleague("Ona")
        self.garage.book(ona, TUESDAY)
        self.garage.block_space(self.admin, "5", TUESDAY, TUESDAY)
        [moved] = self.garage.my_bookings(ona).upcoming
        [note] = self.garage.pending_notifications()
        self.assertEqual((moved.space, note.title), ("6", "Jūsų vieta pakeista"))

    def test_a_booking_that_cannot_move_puts_its_colleague_first_in_line(self):
        self.spaces("5")
        ona, jonas = self.colleague("Ona"), self.colleague("Jonas")
        self.garage.book(ona, TUESDAY)
        self.garage.join_waitlist(jonas, TUESDAY)
        self.garage.block_space(self.admin, "5", TUESDAY, TUESDAY)
        self.garage.add_space(self.admin, "7")
        self.assertEqual([b.space for b in self.garage.my_bookings(ona).upcoming], ["7"])

    def test_ending_a_block_promotes_waiting_colleagues(self):
        self.spaces("5")
        block = self.garage.block_space(self.admin, "5", TUESDAY)
        ona = self.colleague("Ona")
        self.garage.join_waitlist(ona, TUESDAY)
        self.garage.unblock(self.admin, block.id)
        self.assertEqual([b.space for b in self.garage.my_bookings(ona).upcoming], ["5"])

    def test_an_owner_whose_space_is_blocked_can_book_a_shared_one(self):
        self.spaces("1", "12")
        ceo = self.colleague("Ceo")
        self.garage.set_owner(self.admin, "1", ceo)
        self.garage.block_space(self.admin, "1", TUESDAY, TUESDAY)
        self.assertEqual(self.garage.book(ceo, TUESDAY).space, "12")


class BookingRulesTest(GarageTest):
    def rules(self, **changes):
        rules = dict(window_days=7, opening_time="09:00", hours_start="07:00", hours_end="20:00",
                     booking_limit=2)
        rules.update(changes)
        self.garage.set_rules(self.admin, **rules)

    def test_new_bookable_hours_shape_new_whole_day_bookings(self):
        self.spaces("12")
        self.rules(hours_start="08:00", hours_end="18:00")
        booking = self.garage.book(self.colleague("Ona"), TUESDAY)
        self.assertEqual((booking.start, booking.end), ("08:00", "18:00"))

    def test_a_lower_limit_leaves_existing_bookings_standing_but_refuses_new_ones(self):
        self.spaces("12")
        ona = self.colleague("Ona")
        self.garage.book(ona, TUESDAY)
        self.garage.book(ona, date(2026, 10, 7))
        self.rules(booking_limit=1)
        with self.assertRaises(Refused) as refused:
            self.garage.book(ona, date(2026, 10, 8))
        self.assertEqual((len(self.garage.my_bookings(ona).upcoming), refused.exception.code), (2, "limit"))

    def test_a_longer_window_lets_colleagues_book_further_ahead(self):
        self.spaces("12")
        self.rules(window_days=14)
        far = date(2026, 10, 15)
        self.assertEqual(self.garage.book(self.colleague("Ona"), far).day, far)


class AdminTest(GarageTest):
    def test_only_admins_can_manage_the_garage(self):
        self.spaces("7")
        ona = self.colleague("Ona")
        actions = {"add_space": lambda: self.garage.add_space(ona, "8"),
                   "set_owner": lambda: self.garage.set_owner(ona, "7", ona),
                   "close_day": lambda: self.garage.close_day(ona, TUESDAY),
                   "block_space": lambda: self.garage.block_space(ona, "7", TUESDAY),
                   "set_rules": lambda: self.garage.set_rules(ona, 7, "09:00", "07:00", "20:00", 5)}
        for name, action in actions.items():
            with self.subTest(action=name):
                with self.assertRaises(Refused) as refused:
                    action()
                self.assertEqual(refused.exception.code, "not_allowed")


class AdminOverviewTest(GarageTest):
    def test_the_admin_sees_every_space_with_its_owner_and_blocks(self):
        self.spaces("1", "12")
        self.garage.set_owner(self.admin, "1", self.colleague("Ceo"))
        self.garage.block_space(self.admin, "12", TUESDAY, date(2026, 10, 7))
        self.assertEqual([(s.number, s.owner, [(b.first_day, b.last_day) for b in s.blocks])
                          for s in self.garage.spaces()],
                         [("1", "Ceo", []), ("12", None, [(TUESDAY, date(2026, 10, 7))])])

    def test_the_admin_sees_every_colleague_with_their_plates(self):
        self.garage.register("ona@finbee.lt", "Ona", ["ABC123"])
        self.assertEqual([(c.name, c.is_admin, c.plates) for c in self.garage.colleagues()],
                         [("Admin", True, []), ("Ona", False, ["ABC123"])])

    def test_only_admins_see_whos_waiting_in_order(self):
        self.spaces("12")
        self.garage.book(self.colleague("Ona"), TUESDAY)
        jonas, ruta = self.colleague("Jonas"), self.colleague("Ruta")
        self.garage.join_waitlist(jonas, TUESDAY, "13:00", "17:00")
        self.garage.join_waitlist(ruta, TUESDAY)
        with self.assertRaises(Refused) as refused:
            self.garage.waiting_names(jonas, TUESDAY)
        self.assertEqual(([(w.name, w.start, w.end) for w in self.garage.waiting_names(self.admin, TUESDAY)],
                          refused.exception.code),
                         ([("Jonas", "13:00", "17:00"), ("Ruta", "07:00", "20:00")], "not_allowed"))

    def test_the_admin_sees_the_closed_days_ahead_and_can_reopen_one(self):
        self.spaces("12")
        self.garage.close_day(self.admin, date(2026, 10, 8))
        self.garage.close_day(self.admin, date(2026, 10, 9))
        self.garage.reopen_day(self.admin, date(2026, 10, 9))
        self.assertEqual((self.garage.closed_days(),
                          self.garage.book(self.colleague("Ona"), date(2026, 10, 9)).space),
                         ([date(2026, 10, 8)], "12"))


class ColleagueRecordTest(GarageTest):
    def test_a_colleagues_record_says_whether_they_are_an_admin_and_still_active(self):
        ona = self.colleague("Ona")
        self.garage.deactivate(self.admin, ona)
        found = [(c.name, c.is_admin, c.active) for c in (
            self.garage.colleague_by_email("admin@finbeeverslui.lt"), self.garage.colleague(ona.id))]
        self.assertEqual((found, self.garage.colleague_by_email("nobody@finbeeverslui.lt")),
                         ([("Admin", True, True), ("Ona", False, False)], None))


class ColleagueAdminTest(GarageTest):
    def test_an_admin_can_cancel_anyones_booking_and_the_colleague_is_told(self):
        self.spaces("12")
        ona = self.colleague("Ona")
        booking = self.garage.book(ona, TUESDAY)
        self.garage.cancel(self.admin, booking.id)
        [note] = self.garage.pending_notifications()
        self.assertEqual((self.garage.my_bookings(ona).upcoming, note.colleague_id, note.title),
                         ([], ona.id, "Jūsų rezervacija atšaukta"))

    def test_a_colleague_cannot_cancel_someone_elses_booking(self):
        self.spaces("12")
        booking = self.garage.book(self.colleague("Ona"), TUESDAY)
        with self.assertRaises(Refused) as refused:
            self.garage.cancel(self.colleague("Jonas"), booking.id)
        self.assertEqual(refused.exception.code, "not_found")

    def test_admins_can_appoint_admins_but_the_last_one_cannot_step_down(self):
        ona = self.colleague("Ona")
        self.garage.set_admin(self.admin, ona, True)
        self.garage.set_admin(ona, self.admin, False)
        with self.assertRaises(Refused) as refused:
            self.garage.set_admin(ona, ona, False)
        self.assertEqual(refused.exception.code, "last_admin")

    def test_deactivation_cancels_future_bookings_and_hands_the_time_on(self):
        self.spaces("12")
        ona, jonas = self.colleague("Ona"), self.colleague("Jonas")
        self.garage.book(ona, TUESDAY)
        self.garage.join_waitlist(jonas, TUESDAY)
        self.garage.deactivate(self.admin, ona)
        self.assertEqual(([b.space for b in self.garage.my_bookings(jonas).upcoming],
                          self.garage.my_bookings(ona).upcoming), (["12"], []))

    def test_a_deactivated_colleague_cannot_book(self):
        self.spaces("12")
        ona = self.colleague("Ona")
        self.garage.deactivate(self.admin, ona)
        with self.assertRaises(Refused) as refused:
            self.garage.book(ona, TUESDAY)
        self.assertEqual(refused.exception.code, "inactive")

    def test_a_deactivated_owners_space_becomes_shared(self):
        self.spaces("1")
        ceo = self.colleague("Ceo")
        self.garage.set_owner(self.admin, "1", ceo)
        self.garage.deactivate(self.admin, ceo)
        self.assertEqual(self.garage.book(self.colleague("Ona"), TUESDAY).space, "1")

    def test_the_last_admin_cannot_be_deactivated(self):
        with self.assertRaises(Refused) as refused:
            self.garage.deactivate(self.admin, self.admin)
        self.assertEqual(refused.exception.code, "last_admin")


class DayViewTest(GarageTest):
    def test_it_shows_who_holds_each_space_and_when(self):
        self.spaces("4", "5")
        self.garage.book(self.colleague("Ona"), TUESDAY, "09:00", "12:00")
        self.garage.book(self.colleague("Jonas"), TUESDAY, "13:00", "17:00")
        view = self.garage.day_view(TUESDAY, self.colleague("Ruta"))
        self.assertEqual([(s.number, [(b.name, b.start, b.end) for b in s.bookings]) for s in view.spaces],
                         [("4", [("Ona", "09:00", "12:00"), ("Jonas", "13:00", "17:00")]), ("5", [])])

    def test_availability_lists_the_time_a_new_booking_could_still_fit(self):
        self.spaces("4", "5")
        self.garage.book(self.colleague("Ona"), TUESDAY, "07:30", "12:00")
        self.garage.book(self.colleague("Jonas"), TUESDAY)
        view = self.garage.day_view(TUESDAY, self.colleague("Ruta"))
        self.assertEqual([(f.start, f.end, f.spaces) for f in view.availability], [("12:00", "20:00", 1)])

    def test_the_waitlist_shows_only_its_length_and_your_own_place(self):
        self.spaces("4")
        self.garage.book(self.colleague("Ona"), TUESDAY)
        jonas, ruta = self.colleague("Jonas"), self.colleague("Ruta")
        self.garage.join_waitlist(jonas, TUESDAY)
        self.garage.join_waitlist(ruta, TUESDAY)
        view = self.garage.day_view(TUESDAY, ruta)
        self.assertEqual((view.waiting, view.my_place), (2, 2))


class ReminderTest(GarageTest):
    def test_the_evening_reminder_goes_once_by_push_only_to_everyone_booked_tomorrow(self):
        self.spaces("12", "13")
        ona, jonas = self.colleague("Ona"), self.colleague("Jonas")
        self.garage.book(ona, TUESDAY)
        self.garage.book(jonas, date(2026, 10, 7))
        self.clock.set(MONDAY, "17:59")
        self.garage.queue_reminders()
        self.clock.set(MONDAY, "18:00")
        self.garage.queue_reminders()
        self.garage.queue_reminders()
        told = [(n.colleague_id, n.title, n.by_email) for n in self.garage.pending_notifications()]
        self.assertEqual(told, [(ona.id, "Rytoj turite vietą Nr. 12", False)])


class HistoryTest(GarageTest):
    def test_bookings_are_forgotten_a_year_after_their_day(self):
        self.spaces("12")
        ona = self.colleague("Ona")
        self.garage.book(ona, TUESDAY)
        self.clock.set(date(2027, 10, 6), "10:00")
        self.garage.forget_old_bookings()
        kept = len(self.garage.my_bookings(ona).past)
        self.clock.set(date(2027, 10, 7), "10:00")
        self.garage.forget_old_bookings()
        self.assertEqual((kept, self.garage.my_bookings(ona).past), (1, []))


class NumberPlateTest(GarageTest):
    def test_anyone_can_look_up_whose_car_a_plate_belongs_to_however_it_is_typed(self):
        self.garage.register("ona@finbeeverslui.lt", "Ona", ["abc 123"])
        self.assertEqual((self.garage.whose_plate("ABC-123").name, self.garage.whose_plate("XYZ 999")),
                         ("Ona", None))

    def test_a_colleague_can_change_their_plates(self):
        ona = self.garage.register("ona@finbeeverslui.lt", "Ona", ["ABC123"])
        self.garage.set_plates(ona, ["KLM 456"])
        self.assertEqual((self.garage.whose_plate("ABC123"), self.garage.plates(ona)),
                         (None, ["KLM456"]))


class PhoneNumberTest(GarageTest):
    def test_looking_up_a_plate_gives_the_drivers_phone_number_to_call(self):
        self.garage.register("ona@finbeeverslui.lt", "Ona", ["ABC 123"], phone="8 612 34567")
        self.assertEqual(self.garage.whose_plate("abc123").phone, "+37061234567")

    def test_a_phone_number_is_stored_the_same_however_it_is_typed(self):
        ona = self.colleague("Ona")
        stored = []
        for typed in ("+370 612 34567", "861234567", "8 (612) 34-567", "0037061234567", "61234567",
                      "+371 2123 4567"):
            self.garage.set_phone(ona, typed)
            stored.append(self.garage.colleague(ona.id).phone)
        self.assertEqual(stored, ["+37061234567"] * 5 + ["+37121234567"])

    def test_a_number_that_is_not_a_phone_number_is_refused(self):
        ona = self.colleague("Ona")
        codes = []
        for typed in ("", "12345", "+370 612 3456", "+370 612 345678", "ABC 123"):
            try:
                self.garage.set_phone(ona, typed)
            except Refused as error:
                codes.append(error.code)
        self.assertEqual((codes, self.garage.colleague(ona.id).phone), (["bad_phone"] * 5, None))

    def test_registering_with_a_number_that_is_not_a_phone_number_is_refused(self):
        with self.assertRaises(Refused):
            self.garage.register("ona@finbeeverslui.lt", "Ona", [], phone="12345")
        self.assertIsNone(self.garage.colleague_by_email("ona@finbeeverslui.lt"))

    def test_a_garage_from_before_phone_numbers_keeps_its_colleagues_and_takes_numbers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "parking.sqlite3")
            old = sqlite3.connect(path)
            old.executescript(
                "CREATE TABLE colleagues (id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, "
                "name TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);"
                "INSERT INTO colleagues (email, name) VALUES ('ona@finbeeverslui.lt', 'Ona');")
            old.close()
            garage = Garage(path, now=self.clock)
            ona = garage.colleague_by_email("ona@finbeeverslui.lt")
            garage.set_phone(ona, "861234567")
            self.assertEqual((ona.phone, garage.colleague(ona.id).phone), (None, "+37061234567"))


class ClosedDayTest(GarageTest):
    def test_weekends_and_days_an_admin_closed_cannot_be_booked(self):
        self.spaces("12")
        ona = self.colleague("Ona")
        thursday = date(2026, 10, 8)
        self.garage.close_day(self.admin, thursday)
        for day in (date(2026, 10, 10), thursday):
            with self.subTest(day=day):
                with self.assertRaises(Refused) as refused:
                    self.garage.book(ona, day)
                self.assertEqual(refused.exception.code, "closed_day")

    def test_closing_a_day_cancels_its_bookings_and_entries_and_tells_the_colleagues(self):
        self.spaces("12")
        ona, jonas = self.colleague("Ona"), self.colleague("Jonas")
        self.garage.book(ona, TUESDAY)
        self.garage.join_waitlist(jonas, TUESDAY)
        self.garage.close_day(self.admin, TUESDAY)
        told = sorted((n.colleague_id, n.title) for n in self.garage.pending_notifications())
        self.assertEqual(
            (self.garage.my_bookings(ona).upcoming, self.garage.my_bookings(jonas).waiting, told),
            ([], [], [(ona.id, "Diena uždaryta"), (jonas.id, "Diena uždaryta")]))


if __name__ == "__main__":
    unittest.main()
