import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from garage import Garage  # noqa: E402
from notify import Notifier, PushGone  # noqa: E402
from tests.test_garage import Clock  # noqa: E402

TUESDAY = date(2026, 10, 6)
KEYS = {"p256dh": "key", "auth": "secret"}


class NotifierTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(date(2026, 10, 5), "10:00")
        self.garage = Garage(":memory:", now=self.clock, first_admin_email="admin@finbeeverslui.lt")
        self.admin = self.garage.register("admin@finbeeverslui.lt", "Admin", [])
        self.garage.add_space(self.admin, "12")
        self.ona = self.garage.register("ona@finbeeverslui.lt", "Ona", [])
        self.jonas = self.garage.register("jonas@finbeeverslui.lt", "Jonas", [])
        self.pushes, self.emails = [], []
        self.gone, self.email_fails = set(), 0
        self.notifier = Notifier(self.garage, send_push=self.push, send_email=self.email)

    def push(self, subscription, title, body):
        if subscription["endpoint"] in self.gone:
            raise PushGone(subscription["endpoint"])
        self.pushes.append((subscription["endpoint"], title))

    def email(self, to, subject, body):
        if self.email_fails:
            self.email_fails -= 1
            raise OSError("smtp down")
        self.emails.append((to, subject))

    def promote_ona(self):
        booking = self.garage.book(self.jonas, TUESDAY)
        self.garage.join_waitlist(self.ona, TUESDAY)
        self.garage.cancel(self.jonas, booking.id)

    def test_a_promotion_reaches_every_device_by_push_and_the_inbox_by_email(self):
        self.garage.add_push_subscription(self.ona, "https://push/phone", KEYS)
        self.garage.add_push_subscription(self.ona, "https://push/laptop", KEYS)
        self.promote_ona()
        self.notifier.deliver_pending()
        self.assertEqual((sorted(self.pushes), self.emails, self.garage.pending_notifications()),
                         ([("https://push/laptop", "Gavote vietą Nr. 12"),
                           ("https://push/phone", "Gavote vietą Nr. 12")],
                          [("ona@finbeeverslui.lt", "Gavote vietą Nr. 12")], []))

    def test_a_push_subscription_the_push_service_calls_gone_is_dropped(self):
        self.garage.add_push_subscription(self.ona, "https://push/old-phone", KEYS)
        self.gone.add("https://push/old-phone")
        self.promote_ona()
        self.notifier.deliver_pending()
        self.assertEqual((self.garage.push_subscriptions(self.ona.id), len(self.emails)), ([], 1))

    def test_a_failed_email_is_retried_next_round_without_repeating_the_push(self):
        self.garage.add_push_subscription(self.ona, "https://push/phone", KEYS)
        self.email_fails = 1
        self.promote_ona()
        self.notifier.deliver_pending()
        self.notifier.deliver_pending()
        self.assertEqual((len(self.pushes), len(self.emails)), (1, 1))

    def test_an_email_that_keeps_failing_is_given_up_after_five_rounds_and_the_push_goes(self):
        self.garage.add_push_subscription(self.ona, "https://push/phone", KEYS)
        self.email_fails = 99
        self.promote_ona()
        for _ in range(6):
            self.notifier.deliver_pending()
        self.assertEqual((len(self.pushes), self.garage.pending_notifications()), (1, []))


if __name__ == "__main__":
    unittest.main()
