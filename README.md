# finbee parkavimas

Booking the new office's underground parking: 9 Spaces, far more colleagues than Spaces on a
busy day. An installable web app in Lithuanian: colleagues add it to their iPhone's Home Screen.

- The words: [CONTEXT.md](CONTEXT.md). Every page, notification and email uses them.
- The decisions: [docs/adr/](docs/adr/). They cover the app assigning the Space (0001), a web app
  rather than native iOS (0002), no connection to the building's system (0003), and Render (0004).

## Code

| File | What it is |
| --- | --- |
| `garage.py` | The Booking Rules. Every action is one SQLite transaction under one lock. |
| `signin.py` | One-time codes emailed to finbee addresses. |
| `notify.py` | Sends queued notifications by push and email, plus the Gmail and Web Push adapters. |
| `app.py` | The Flask pages, the Home Screen app files, and the background loop. |
| `lt.py` | Lithuanian date wording. |

## Run it locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python tools/seed_demo.py /tmp/parking-demo
```

```bash
PARKING_DEV=1 DATA_DIR=/tmp/parking-demo FIRST_ADMIN_EMAIL=demo.admin@finbeeverslui.lt .venv/bin/python app.py
```

Open http://127.0.0.1:5095. With `PARKING_DEV=1`, sign-in codes, emails and pushes go to the
terminal instead of being sent.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

The tests sit at four points: the Garage (most of them), sign-in, notification delivery, and a
few end-to-end page checks. The clock, the mail sender and the push service are the only fakes.

## Deploy (Render)

1. Push this folder to its own GitHub repository.
2. In Render, choose **New → Blueprint** and pick the repository. Render reads `render.yaml`
   (Starter, Frankfurt, 1 GB disk) and asks for:
   - `FIRST_ADMIN_EMAIL`: who becomes the first Admin on registering.
   - `PARKING_SENDER_EMAIL` and `PARKING_SENDER_APP_PASSWORD`: Eudora's shared mailbox and its
     own **"parking"** app password.
   - `APP_URL`: the address Render gives, for links in emails.
3. Keep it on **one worker** and on a **paid plan**. The free plan blocks outbound SMTP, so no
   code could be sent (ADR-0004).

The data (SQLite, the Web Push key) lives on the disk at `/var/data`. Losing
`vapid_private.pem` silently breaks every colleague's push subscription.
