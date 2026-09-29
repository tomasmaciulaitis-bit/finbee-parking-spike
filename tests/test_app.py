import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as parking  # noqa: E402
from tests.test_garage import Clock  # noqa: E402

IPHONE_SAFARI = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 "
                 "(KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1")
ANDROID_CHROME = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0.0.0 Mobile Safari/537.36")
# Safari 26 freezes the OS in its user agent at 18_6; only the Version token tells it apart.
IPHONE_SAFARI_26 = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 "
                    "(KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1")


class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.clock = Clock(date(2026, 10, 5), "10:00")
        self.codes = []
        self.app = parking.create_app(
            self.tmp, now=self.clock, first_admin_email="admin@finbeeverslui.lt",
            send_code=lambda email, code: self.codes.append((email, code)),
            send_push=lambda *args: None, send_email=lambda *args: None, background=False)
        self.app.testing = True
        self.garage = self.app.config["GARAGE"]
        self.admin = self.garage.register("admin@finbeeverslui.lt", "Admin", [], phone="+370 600 00000")
        self.garage.add_space(self.admin, "12")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def signed_in(self, email, name=None):
        client = self.app.test_client()
        client.post("/kodas", data={"email": email})
        code = [c for to, c in self.codes if to == email][-1]
        client.post("/prisijungti", data={"code": code})
        if name:
            client.post("/registracija", data={"name": name, "phone": "+370 612 34567", "plates": "ABC 123"})
        return client

    def test_a_colleague_signs_in_registers_and_books_through_the_pages(self):
        client = self.signed_in("ona@finbeeverslui.lt", name="Ona")
        client.post("/rezervuoti", data={"day": "2026-10-06", "kind": "whole"})
        self.assertIn("Nr. 12", client.get("/mano").get_data(as_text=True))

    def test_admin_pages_are_only_for_admins(self):
        colleague = self.signed_in("ona@finbeeverslui.lt", name="Ona")
        admin = self.signed_in("admin@finbeeverslui.lt")
        pages = ["/admin/diena/2026-10-06", "/admin/vietos", "/admin/taisykles", "/admin/dienos",
                 "/admin/kolegos"]
        self.assertEqual(([colleague.get(p).status_code for p in pages], [admin.get(p).status_code for p in pages]),
                         ([403] * 5, [200] * 5))

    def test_an_iphone_safari_tab_is_asked_to_add_the_app_to_the_home_screen_first(self):
        client = self.app.test_client()
        in_safari = client.get("/", headers={"User-Agent": IPHONE_SAFARI}).get_data(as_text=True)
        in_the_app = client.get("/?app=1", headers={"User-Agent": IPHONE_SAFARI}).get_data(as_text=True)
        again = client.get("/", headers={"User-Agent": IPHONE_SAFARI}).get_data(as_text=True)
        self.assertEqual(("Pridėkite prie pradžios ekrano" in in_safari, 'name="email"' in in_the_app,
                          'name="email"' in again), (True, True, True))

    def test_the_install_animation_follows_the_iphones_safari(self):
        def variant(agent):
            page = self.app.test_client().get("/", headers={"User-Agent": agent}).get_data(as_text=True)
            return page.split('data-variant="', 1)[1].split('"', 1)[0]
        self.assertEqual((variant(IPHONE_SAFARI_26), variant(IPHONE_SAFARI)), ("menu", "toolbar"))

    def test_an_android_visitors_install_guide_follows_chromes_menu(self):
        page = self.app.test_client().get("/idiegti", headers={"User-Agent": ANDROID_CHROME}).get_data(as_text=True)
        self.assertEqual(page.split('data-variant="', 1)[1].split('"', 1)[0], "android")

    def test_android_is_not_made_to_install_first(self):
        page = self.app.test_client().get("/", headers={"User-Agent": ANDROID_CHROME}).get_data(as_text=True)
        self.assertEqual(('name="email"' in page, 'id="install-banner"' in page), (True, True))

    def test_a_booking_refused_for_lack_of_space_offers_the_waitlist(self):
        jonas = self.garage.register("jonas@finbeeverslui.lt", "Jonas", [])
        self.garage.book(jonas, date(2026, 10, 6))
        client = self.signed_in("ona@finbeeverslui.lt", name="Ona")
        page = client.post("/rezervuoti", data={"day": "2026-10-06", "kind": "part", "start": "09:00",
                                                "end": "12:00"}, follow_redirects=True).get_data(as_text=True)
        client.post("/laukti", data={"day": "2026-10-06", "kind": "part", "start": "09:00", "end": "12:00"})
        waiting = self.garage.my_bookings(self.garage.colleague_by_email("ona@finbeeverslui.lt")).waiting
        self.assertEqual(('action="/laukti"' in page, [(w.start, w.end) for w in waiting]),
                         (True, [("09:00", "12:00")]))

    def verified(self, email):
        """Signed in with a code, but not registered yet."""
        client = self.app.test_client()
        client.post("/kodas", data={"email": email})
        client.post("/prisijungti", data={"code": [c for to, c in self.codes if to == email][-1]})
        return client

    def test_registering_needs_a_phone_number(self):
        client = self.verified("ona@finbeeverslui.lt")
        page = client.post("/registracija", data={"name": "Ona", "plates": "ABC 123"}).get_data(as_text=True)
        without = self.garage.colleague_by_email("ona@finbeeverslui.lt")
        client.post("/registracija", data={"name": "Ona", "phone": "8 612 34567", "plates": "ABC 123"})
        ona = self.garage.colleague_by_email("ona@finbeeverslui.lt")
        self.assertEqual((without, "telefono numerį" in page, ona.phone), (None, True, "+37061234567"))

    def test_each_plate_field_is_its_own_number_plate(self):
        client = self.verified("ona@finbeeverslui.lt")
        client.post("/registracija", data={"name": "Ona", "phone": "861234567",
                                           "plates": ["ABC 123", "DEF 456, GHI 789", "KLM 012 ir NOP 345", ""]})
        ona = self.garage.colleague_by_email("ona@finbeeverslui.lt")
        self.assertEqual(self.garage.plates(ona), ["ABC123", "DEF456", "GHI789", "KLM012", "NOP345"])

    def test_a_plate_search_shows_the_drivers_phone_number_to_call(self):
        self.garage.register("jonas@finbeeverslui.lt", "Jonas", ["KLM 456"], phone="8 699 11223")
        client = self.signed_in("ona@finbeeverslui.lt", name="Ona")
        page = client.get("/diena/2026-10-06?numeris=klm456").get_data(as_text=True)
        self.assertEqual(('href="tel:+37069911223"' in page, "+370 699 11223" in page), (True, True))

    def test_a_colleague_from_before_phone_numbers_gives_one_first(self):
        self.garage.register("ona@finbeeverslui.lt", "Ona", ["ABC 123"])
        client = self.signed_in("ona@finbeeverslui.lt")
        first = client.get("/diena/2026-10-06")
        client.post("/telefonas", data={"phone": "+370 612 34567"})
        after = client.get("/diena/2026-10-06")
        self.assertEqual((first.status_code, first.location.endswith("/telefonas"), after.status_code),
                         (302, True, 200))

    def test_the_notifications_banner_knows_whether_notifications_reach_the_colleague_anywhere(self):
        client = self.signed_in("ona@finbeeverslui.lt", name="Ona")
        before = client.get("/diena/2026-10-06").get_data(as_text=True)
        ona = self.garage.colleague_by_email("ona@finbeeverslui.lt")
        self.garage.add_push_subscription(ona, "https://push.example/1", {"p256dh": "key", "auth": "secret"})
        after = client.get("/diena/2026-10-06").get_data(as_text=True)
        profile = client.get("/profilis").get_data(as_text=True)
        self.assertEqual(('data-reachable="no"' in before, 'data-reachable="yes"' in after,
                          'id="push-nudge"' in profile), (True, True, False))

    def test_the_phone_field_takes_the_number_after_a_fixed_370(self):
        client = self.verified("ona@finbeeverslui.lt")
        page = client.get("/registracija").get_data(as_text=True)
        client.post("/registracija", data={"name": "Ona", "phone": "612 34567", "plates": "ABC 123"})
        profile = client.get("/profilis").get_data(as_text=True)
        self.assertEqual(('class="phone-prefix">+370<' in page,
                          self.garage.colleague_by_email("ona@finbeeverslui.lt").phone,
                          'value="612 34567"' in profile), (True, "+37061234567", True))

    def test_an_admin_books_a_space_for_a_guest_and_colleagues_see_it(self):
        admin = self.signed_in("admin@finbeeverslui.lt")
        admin.post("/admin/sveciai", data={"day": "2026-10-06", "kind": "whole", "guest": "UAB Klientas",
                                           "plate": "GST 001"})
        guests = admin.get("/admin/sveciai").get_data(as_text=True)
        day = self.signed_in("ona@finbeeverslui.lt", name="Ona").get("/diena/2026-10-06").get_data(as_text=True)
        self.assertEqual(("UAB Klientas" in guests, "GST001" in guests, "Svečias – UAB Klientas" in day),
                         (True, True, True))

    def test_only_admins_book_for_guests(self):
        client = self.signed_in("ona@finbeeverslui.lt", name="Ona")
        response = client.post("/admin/sveciai", data={"day": "2026-10-06", "kind": "whole", "guest": "X"})
        self.assertEqual((response.status_code, self.garage.guest_bookings()), (403, []))

    def test_the_plate_search_finds_a_guests_car_and_the_admin_to_call(self):
        self.garage.book_guest(self.admin, date(2026, 10, 6), "UAB Klientas", plate="GST 001")
        client = self.signed_in("ona@finbeeverslui.lt", name="Ona")
        page = client.get("/diena/2026-10-06?numeris=gst001").get_data(as_text=True)
        self.assertEqual(("UAB Klientas" in page, 'href="tel:+37060000000"' in page), (True, True))

    def test_after_leaving_the_day_no_longer_shows_the_booking_to_leave_again(self):
        client = self.signed_in("ona@finbeeverslui.lt", name="Ona")
        client.post("/rezervuoti", data={"day": "2026-10-05", "kind": "whole"})
        ona = self.garage.colleague_by_email("ona@finbeeverslui.lt")
        [booking] = self.garage.my_bookings(ona).upcoming
        self.clock.set(date(2026, 10, 5), "10:10")
        before = client.get("/diena/2026-10-05").get_data(as_text=True)
        client.post("/atsaukti/%d" % booking.id)
        after = client.get("/diena/2026-10-05").get_data(as_text=True)
        self.assertEqual(("Išvažiuoju" in before, "Išvažiuoju" in after, "Jūsų rezervacija" in after),
                         (True, False, False))

    def test_an_admin_renames_and_deletes_spaces_on_the_spaces_page(self):
        admin = self.signed_in("admin@finbeeverslui.lt")
        admin.post("/admin/vietos/12/pervadinti", data={"new_number": "21"})
        admin.post("/admin/vietos", data={"number": "99"})
        admin.post("/admin/vietos/99/istrinti")
        page = admin.get("/admin/vietos").get_data(as_text=True)
        self.assertEqual(([s.number for s in self.garage.spaces()], "Pervadinti" in page), (["21"], True))

    def test_only_admins_rename_or_delete_spaces(self):
        client = self.signed_in("ona@finbeeverslui.lt", name="Ona")
        codes = [client.post("/admin/vietos/12/pervadinti", data={"new_number": "21"}).status_code,
                 client.post("/admin/vietos/12/istrinti").status_code]
        self.assertEqual((codes, [s.number for s in self.garage.spaces()]), ([403, 403], ["12"]))

    def test_the_phone_keeps_a_versioned_file_until_the_next_update_and_rechecks_the_rest(self):
        page = self.app.test_client().get("/").get_data(as_text=True)
        version = page.split('href="/static/app.css?v=', 1)[1].split('"', 1)[0]
        client = self.app.test_client()
        kept = client.get("/static/app.css?v=" + version).headers.get("Cache-Control", "")
        checked = client.get("/static/app.css").headers.get("Cache-Control", "")
        self.assertEqual(("max-age=31536000" in kept, checked), (True, "no-cache"))

    def test_an_admin_marks_a_charging_space_and_a_colleague_asks_for_it(self):
        self.garage.add_space(self.admin, "7")
        self.signed_in("admin@finbeeverslui.lt").post("/admin/vietos/7/ikrovimas", data={"ev": "1"})
        client = self.signed_in("ona@finbeeverslui.lt", name="Ona")
        page = client.get("/diena/2026-10-06").get_data(as_text=True)
        done = client.post("/rezervuoti", data={"day": "2026-10-06", "kind": "whole", "ev": "1"},
                           follow_redirects=True).get_data(as_text=True)
        [booking] = self.garage.my_bookings(self.garage.colleague_by_email("ona@finbeeverslui.lt")).upcoming
        self.assertEqual(('name="ev"' in page, booking.space, "su įkrovimu" in done), (True, "7", True))

    def test_the_charging_choice_shows_only_when_a_charging_space_exists(self):
        page = self.signed_in("ona@finbeeverslui.lt", name="Ona").get("/diena/2026-10-06").get_data(as_text=True)
        self.assertNotIn('name="ev"', page)

    def test_after_cancelling_everything_a_colleague_can_book_today_again(self):
        self.clock.set(date(2026, 10, 5), "08:05")
        client = self.signed_in("ona@finbeeverslui.lt", name="Ona")
        client.post("/rezervuoti", data={"day": "2026-10-05", "kind": "whole"})
        ona = self.garage.colleague_by_email("ona@finbeeverslui.lt")
        [booking] = self.garage.my_bookings(ona).upcoming
        self.clock.set(date(2026, 10, 5), "10:10")
        client.post("/atsaukti/%d" % booking.id)
        page = client.post("/rezervuoti", data={"day": "2026-10-05", "kind": "whole"},
                           follow_redirects=True).get_data(as_text=True)
        self.assertEqual(("Rezervuota" in page, "jau turite rezervaciją" in page), (True, False))

    def test_a_form_posted_from_another_site_is_refused(self):
        client = self.signed_in("ona@finbeeverslui.lt", name="Ona")
        response = client.post("/rezervuoti", data={"day": "2026-10-06", "kind": "whole"},
                               headers={"Origin": "https://evil.example"})
        self.assertEqual((response.status_code, self.garage.my_bookings(
            self.garage.colleague_by_email("ona@finbeeverslui.lt")).upcoming), (403, []))


if __name__ == "__main__":
    unittest.main()
