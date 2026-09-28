"""Fill a scratch data folder with made-up colleagues and Bookings, to look at the pages.

    python tools/seed_demo.py /path/to/scratch/data

Never point it at the real data folder.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from garage import Garage, Refused  # noqa: E402

data = Path(sys.argv[1])
data.mkdir(parents=True, exist_ok=True)
garage = Garage(str(data / "parking.sqlite3"), now=lambda: datetime.now(ZoneInfo("Europe/Vilnius")),
                first_admin_email="demo.admin@finbeeverslui.lt")
admin = garage.register("demo.admin@finbeeverslui.lt", "Demo Administratorius", ["ADM 001"],
                        phone="+370 600 00000")
for number in map(str, range(1, 10)):
    garage.add_space(admin, number)
heads = [garage.register("vadovas.%d@finbeeverslui.lt" % n, "Vadovas %s" % l, ["VAD 00%d" % n],
                         phone="+370 600 0000%d" % n)
         for n, l in ((1, "A"), (2, "B"))]
garage.set_owner(admin, "1", heads[0])
garage.set_owner(admin, "2", heads[1])
names = ["Ona", "Jonas", "Rūta", "Tomas", "Eglė", "Mantas", "Aistė", "Lukas", "Greta", "Paulius"]
people = [garage.register("demo.%d@finbeeverslui.lt" % i, "%s D." % name, ["DEM %03d" % i],
                          phone="+370 600 001%02d" % i)
          for i, name in enumerate(names)]
days = [option.day for option in garage.open_days() if not option.closed][:4]
shapes = [(None, None), ("09:00", "13:00"), ("13:00", "18:00"), (None, None), ("08:00", "12:00")]
for i, person in enumerate(people):
    for d, day in enumerate(days[1:3]):
        start, end = shapes[(i + d) % len(shapes)]
        try:
            garage.book(person, day, start, end)
        except Refused:
            try:
                garage.join_waitlist(person, day, start, end)
            except Refused:
                pass
if len(days) > 1:
    garage.release(heads[1], days[1], "12:00", "20:00")
print("seeded", data, "for", ", ".join(d.isoformat() for d in days[1:3]))
