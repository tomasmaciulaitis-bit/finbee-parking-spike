import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from garage import Garage, Refused  # noqa: E402
from signin import SignIn  # noqa: E402
from tests.test_garage import Clock  # noqa: E402


class SignInTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(date(2026, 10, 5), "10:00")
        self.garage = Garage(":memory:", now=self.clock, first_admin_email="admin@finbeeverslui.lt")
        self.sent = []
        self.signin = SignIn(self.garage, send_code=lambda email, code: self.sent.append((email, code)),
                             now=self.clock)

    def code_for(self, email):
        return [code for to, code in self.sent if to == email][-1]

    def test_only_finbee_addresses_get_a_code(self):
        for email in ("ona@finbeeverslui.lt", "Jonas@Finbee.lt ", "ruta@finbee.com"):
            self.signin.request_code(email)
        with self.assertRaises(Refused) as refused:
            self.signin.request_code("someone@gmail.com")
        self.assertEqual(([to for to, _ in self.sent], refused.exception.code),
                         (["ona@finbeeverslui.lt", "jonas@finbee.lt", "ruta@finbee.com"], "not_finbee"))

    def test_the_right_code_signs_a_registered_colleague_in(self):
        ona = self.garage.register("ona@finbeeverslui.lt", "Ona", [])
        self.signin.request_code("ona@finbeeverslui.lt")
        self.assertEqual(self.signin.verify("ona@finbeeverslui.lt", self.code_for("ona@finbeeverslui.lt")), ona)

    def test_a_new_address_is_verified_but_not_yet_registered(self):
        self.signin.request_code("new@finbee.lt")
        self.assertIsNone(self.signin.verify("new@finbee.lt", self.code_for("new@finbee.lt")))

    def test_a_wrong_code_is_refused(self):
        self.signin.request_code("ona@finbeeverslui.lt")
        wrong = "111111" if self.code_for("ona@finbeeverslui.lt") != "111111" else "222222"
        with self.assertRaises(Refused) as refused:
            self.signin.verify("ona@finbeeverslui.lt", wrong)
        self.assertEqual(refused.exception.code, "wrong_code")

    def test_a_code_expires_after_ten_minutes(self):
        self.signin.request_code("ona@finbeeverslui.lt")
        self.clock.set(date(2026, 10, 5), "10:10")
        with self.assertRaises(Refused) as refused:
            self.signin.verify("ona@finbeeverslui.lt", self.code_for("ona@finbeeverslui.lt"))
        self.assertEqual(refused.exception.code, "expired")

    def test_after_five_wrong_tries_the_code_stops_working(self):
        self.signin.request_code("ona@finbeeverslui.lt")
        right = self.code_for("ona@finbeeverslui.lt")
        wrong = "111111" if right != "111111" else "222222"
        for _ in range(5):
            with self.assertRaises(Refused):
                self.signin.verify("ona@finbeeverslui.lt", wrong)
        with self.assertRaises(Refused) as refused:
            self.signin.verify("ona@finbeeverslui.lt", right)
        self.assertEqual(refused.exception.code, "too_many_tries")

    def test_a_second_code_within_a_minute_is_refused(self):
        self.signin.request_code("ona@finbeeverslui.lt")
        with self.assertRaises(Refused) as refused:
            self.signin.request_code("ona@finbeeverslui.lt")
        self.clock.set(date(2026, 10, 5), "10:01")
        self.signin.request_code("ona@finbeeverslui.lt")
        self.assertEqual((refused.exception.code, len(self.sent)), ("too_soon", 2))

    def test_a_deactivated_colleague_gets_no_code(self):
        admin = self.garage.register("admin@finbeeverslui.lt", "Admin", [])
        ona = self.garage.register("ona@finbeeverslui.lt", "Ona", [])
        self.garage.deactivate(admin, ona)
        with self.assertRaises(Refused) as refused:
            self.signin.request_code("ona@finbeeverslui.lt")
        self.assertEqual((refused.exception.code, self.sent), ("inactive", []))

    def test_a_colleague_deactivated_after_asking_for_a_code_cannot_use_it(self):
        admin = self.garage.register("admin@finbeeverslui.lt", "Admin", [])
        ona = self.garage.register("ona@finbeeverslui.lt", "Ona", [])
        self.signin.request_code("ona@finbeeverslui.lt")
        self.garage.deactivate(admin, ona)
        with self.assertRaises(Refused) as refused:
            self.signin.verify("ona@finbeeverslui.lt", self.code_for("ona@finbeeverslui.lt"))
        self.assertEqual(refused.exception.code, "inactive")


if __name__ == "__main__":
    unittest.main()
