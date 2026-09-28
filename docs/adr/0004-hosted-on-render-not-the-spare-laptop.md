# Hosted on Render, not on the spare laptop

Every other finbee tool runs on the spare laptop behind Tailscale Funnel; this one runs on
Render: one always-on Starter web service with a small persistent disk, in the Frankfurt
region, deployed from its own GitHub repository, for about €7 a month.

The spare had no Funnel port left. The app can't share an address with Argos or the
credit pilot, because they hold borrower data and because a Home Screen web app's push
subscriptions and service worker belong to its address. And a laptop that needs a desktop
login after every reboot is a poor single point of failure for something colleagues use
every morning.

Render was rejected for Argos because it would have put borrower data on a third-party
host. This app holds only colleagues' names, email addresses, Number Plates and Bookings,
so that objection doesn't apply here. Render's free tier was rejected for two reasons. It
sleeps after 15 minutes, and the evening Reminder and instant Promotions need a server that
is always awake. And since 2025-09-26 it blocks outbound SMTP (ports 25, 465 and 587), so
the sign-in codes could not be sent at all: the iPhone spike hit exactly this ("OSError" on
the first code). Paid instances allow 465 and 587, so never move this app to the free plan.

## Consequences

- The app sends its email through the shared finbeeverslui.lt mailbox that Eudora already
  uses, with its own app password named "parking" so that either can be revoked without
  breaking the other. An app password can read that mailbox as well as send from it, and
  its Sent folder holds every perks email sent to customers, so Render does hold one
  credential that reaches customer data. Making the mailbox send-only (IMAP and POP off)
  was considered and declined on 2026-09-28. If the Render service is ever compromised,
  revoke the "parking" app password first.
