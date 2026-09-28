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
        self.admin = self.garage.register("admin@finbeeverslui.lt", "Admin", [])
        self.garage.add_space(self.admin, "12")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def signed_in(self, email, name=None):
        client = self.app.test_client()
        client.post("/kodas", data={"email": email})
        code = [c for to, c in self.codes if to == email][-1]
        client.post("/prisijungti", data={"code": code})
        if name:
            client.post("/registracija", data={"name": name, "plates": "ABC 123"})
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

    def test_a_form_posted_from_another_site_is_refused(self):
        client = self.signed_in("ona@finbeeverslui.lt", name="Ona")
        response = client.post("/rezervuoti", data={"day": "2026-10-06", "kind": "whole"},
                               headers={"Origin": "https://evil.example"})
        self.assertEqual((response.status_code, self.garage.my_bookings(
            self.garage.colleague_by_email("ona@finbeeverslui.lt")).upcoming), (403, []))


if __name__ == "__main__":
    unittest.main()
