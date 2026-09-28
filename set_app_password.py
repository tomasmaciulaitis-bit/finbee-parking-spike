#!/usr/bin/env python3
"""PROTOTYPE: store the "parking" Gmail app password for the spike. Prompts without echo.

    python3 set_app_password.py

The sender is Eudora's shared mailbox, read from Eudora's own .env so nobody retypes it. The
password is the separate app password named "parking" on that mailbox, so revoking it never
breaks Eudora. Paste it exactly as Google shows it, spaces and all.

Nothing is printed back beyond the length and first two characters.
"""
import getpass
import pathlib
import sys

EUDORA_ENV = pathlib.Path.home() / "finbee-agents" / "perks-email-agent" / ".env"
HERE_ENV = pathlib.Path(__file__).resolve().parent / ".env"


def read_env(path):
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def main():
    sender = read_env(EUDORA_ENV).get("PERKS_SENDER_EMAIL")
    if not sender:
        sender = input("Eudora's sender address was not found; type the mailbox address: ").strip()
    pw = getpass.getpass('App password named "parking" (hidden): ').strip()
    if not pw:
        print("empty - nothing written", file=sys.stderr)
        return 1
    if pw != getpass.getpass("Again, to be sure: ").strip():
        print("the two did not match - nothing written", file=sys.stderr)
        return 1

    values = read_env(HERE_ENV)
    values["PARKING_SENDER_EMAIL"] = sender
    values["PARKING_SENDER_APP_PASSWORD"] = pw
    HERE_ENV.write_text("".join("%s=%s\n" % kv for kv in values.items()))
    HERE_ENV.chmod(0o600)
    print("written: sender on %s, password %d chars, %s..." % (sender.rpartition("@")[2], len(pw), pw[:2]))
    print("Restart the spike (./run.sh) so it picks this up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
