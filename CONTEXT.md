# Office Parking

Sharing finbee's underground parking at the new office among colleagues. Far more
colleagues want a Space on a busy day than there are Spaces, so the rules exist to ration
Spaces fairly, not only to stop two people heading for the same one.

The app is in Lithuanian only. Each term's _LT_ line is the word the screens, notifications
and emails use for it, every time.

## Language

### Spaces

**Space**:
One numbered parking bay in the office's underground garage that finbee allocates,
identified by the number painted on it. Nine today. An Admin can change a Space's number to
match what's painted, and whoever holds or owns it is told; the Space itself, and its
Bookings, stay the same. A Space added by mistake can be deleted only if it was never booked
and isn't an Owned Space; any other Space that goes is retired by Blocking it.
_LT_: vieta
_Avoid_: spot, slot, bay, place

**Shared Space**:
A Space that is not an Owned Space. Shared Spaces are interchangeable, which is why a
Colleague books "a Space" rather than a particular one.
_LT_: bendra vieta
_Avoid_: pool space, free space, general space

**Owned Space**:
A Space permanently assigned to one Colleague, its Owner, instead of being shared,
except for periods the Owner has Released. At least two today, held by the CEOs.
_LT_: nuolatinė vieta (never rezervuota vieta, which collides with rezervacija, nor
priskirta vieta, which is what the app does to every Booking)
_Avoid_: reserved space, dedicated space, fixed space

### People

**Colleague**:
A finbee employee using the app. Any of the 50+ employees could be one; only some drive.
_LT_: kolega
_Avoid_: user, employee, driver, member

**Owner**:
The Colleague an Owned Space is assigned to. A Colleague holds at most one Owned Space, and
while holding it can't also book a Shared Space for the same time.
_LT_: nuolatinės vietos turėtojas
_Avoid_: savininkas (the Space isn't theirs to own)

**Admin**:
A Colleague who also manages the Spaces, the Owners, the Booking Rules and the Closures,
and can act on an Owner's behalf. Any Admin can make another Colleague an Admin or take
the role away, but there is always at least one Admin.
_LT_: administratorius
_Avoid_: manager, office manager (job titles, not a role in the app)

**Registration**:
A finbee employee becoming a Colleague by proving they hold a finbee email address
(finbeeverslui.lt, finbee.lt or finbee.com) and giving their name, Phone Number and Number
Plates. No Admin approves it.
_LT_: registracija
_Avoid_: sign-up, account creation, onboarding

**Deactivation**:
An Admin ending a Colleague's access at once, typically when they leave finbee. Their
future Bookings and Waitlist Entries are cancelled, and an Owned Space they held becomes a
Shared Space.
_LT_: paskyros deaktyvavimas
_Avoid_: delete, ban, remove

**Number Plate**:
The registration number of a car a Colleague drives; a Colleague may have several and can
change them later. The garage entrance has a camera that admits cars by Number Plate, but
the app has nothing to do with it: in the app a Number Plate only tells people whose car
is whose. Any Colleague can look up whose car a Number Plate belongs to, and sees the
driver's Phone Number to call them. Each Number Plate is typed in its own field, so two never
run together into one.
_LT_: valstybinis numeris
_Avoid_: licence plate, car registration (collides with Registration), vehicle

**Phone Number**:
The Lithuanian (+370) number a Colleague can be called on, required at Registration and
changeable later; the field fixes +370, so only the rest is typed.
Whoever looks up one of their Number Plates sees it next to their name, to call them, say,
to move the car. A Colleague who registered before Phone Numbers existed gives theirs
before anything else on their next visit.
_LT_: telefono numeris
_Avoid_: contact, mobile, phone (alone)

**Guest**:
Someone from outside finbee coming to the office by car. A Guest never uses the app: an
Admin books a Space for them (a Guest Booking).
_LT_: svečias
_Avoid_: visitor, lankytojas

### Bookings

**Booking**:
A Colleague's claim on a Space for a period within a single day: either a Whole-Day
Booking or a Part-Day Booking. The Colleague chooses the day and period; the app chooses
the Space, and that choice never changes afterwards unless an Admin Blocks the Space.
Never spans midnight. A Colleague holds at most one Booking or Waitlist Entry for any day.
A Booking can't be changed: a different day or period means a Cancellation and a new
Booking, and the freed time may be Promoted to someone else in between. On the day itself a
Booking starts no earlier than the current half hour.
_LT_: rezervacija (in Lithuanian it doesn't collide with nuolatinė vieta)
_Avoid_: reservation, reserved (collides with Owned Space)

**Whole-Day Booking**:
A Booking covering all of one day's Bookable Hours.
_LT_: visos dienos rezervacija
_Avoid_: full-day reservation, all-day

**Part-Day Booking**:
A Booking for part of one day's Bookable Hours, at least one hour long, with start and
end times in 30-minute steps.
_LT_: rezervacija valandoms
_Avoid_: slot, time slot, hourly booking

**Guest Booking**:
A Booking an Admin makes for a Guest, with the Guest's name (or company) and, if known,
their Number Plate. The Admin who made it holds it and is told of any change to it. Admins
make as many as they need, on any open day from today on: the Booking Limit, the one-a-day
rule and the Booking Window don't apply, and there is no Reminder. It takes only a free
Space, so nobody is bumped, and a Guest never waits on the Waitlist. Every Colleague sees
it in the Day View, and looking up its Number Plate that day shows the Guest and who booked.
_LT_: svečio rezervacija
_Avoid_: visitor booking, guest reservation

**Cancellation**:
A Colleague giving up a Booking, allowed at any time before it ends. Once the Booking has
started, it means leaving: the Booking ends at once, cut back to the current half hour
(the earliest a new Booking that day may start), and one begun this half hour goes
entirely. Either way the freed time goes to Promotion at once and the Colleague's place
under the Booking Limit comes back. There is no penalty for cancelling late. An Admin can cancel anyone's Booking, and that
Colleague is told.
_LT_: atšaukimas (never atlaisvinimas, which is Release)
_Avoid_: release (collides with Release), delete, drop

**Reminder**:
The evening-before nudge to a Colleague with a Booking the next day, offering a one-tap
Cancellation. It asks; it never cancels anything by itself.
_LT_: priminimas
_Avoid_: confirmation, check-in

**No-show**:
A Booking nobody turned up for. The app neither detects nor penalises No-shows; the
Reminder is the only defence against them.
_LT_: neatvykimas
_Avoid_: absence, missed booking

### Seeing Bookings

**Availability**:
The periods on a day for which the app could still fit a new Booking.
_LT_: laisvos vietos
_Avoid_: free spaces, capacity, vacancy

**Day View**:
What every Colleague sees for today or an upcoming day: each Space, who holds it and
when, and the Availability left. Of that day's Waitlist it shows only the length and the
Colleague's own place.
_LT_: dienos užimtumas
_Avoid_: calendar, schedule, board

**My Bookings**:
A Colleague's own Bookings and Waitlist Entries, upcoming and past. Past Bookings are
visible only here, to the Colleague who held them, and are forgotten a year after their day.
_LT_: mano rezervacijos
_Avoid_: my reservations, history

### Booking Rules

**Booking Rules**:
The limits on Bookings that an Admin sets and can change at any time. A change applies to
new Bookings only; existing Bookings stand.
_LT_: rezervavimo taisyklės
_Avoid_: settings, config, policy

**Booking Window**:
How far ahead a Colleague can book: today and a number of days after it, set by an Admin.
Owners can Release any future date; the Booking Window limits only Bookings.
_LT_: išankstinio rezervavimo laikotarpis
_Avoid_: horizon, lead time, advance limit

**Opening Time**:
The time of day at which the next day enters the Booking Window.
_LT_: rezervacijų atidarymo laikas
_Avoid_: release time (collides with Release)

**Bookable Hours**:
The hours of each day within which every Booking falls.
_LT_: rezervavimo valandos
_Avoid_: opening hours (collides with Opening Time), garage hours

**Booking Limit**:
The most upcoming Bookings and Waitlist Entries a Colleague can hold at once, set by an
Admin. Whole-Day and Part-Day Bookings count the same; Guest Bookings don't count.
_LT_: rezervacijų limitas
_Avoid_: quota, cap, allowance

### Closures

Unlike a change to the Booking Rules, a Closure reaches back and affects Bookings that
already exist.

**Closed Day**:
A day on which nobody can park: every Saturday and Sunday, plus any date an Admin closes.
Closing a date cancels the Bookings and Waitlist Entries already on it, and their
Colleagues are told. Public holidays are not Closed Days unless an Admin closes them.
_LT_: uždaryta diena (never nedarbo diena: public holidays aren't Closed Days)
_Avoid_: holiday, blackout day, day off

**Blocked Space**:
A Space an Admin has taken out of use for some dates, or from a date onwards to retire it.
Its Bookings move to another free Space where one fits; where none does, the Booking is
cancelled and its Colleague goes to the front of that day's Waitlist.
_LT_: užblokuota vieta
_Avoid_: disabled, inactive, out of order

### Releases

**Release**:
An Owner making their Owned Space bookable for a whole day or part of a day, in the same
shapes as a Booking. An Admin can Release on the Owner's behalf. Releasing is optional;
an Owned Space nobody Releases simply stays with its Owner. A Released Space is given out only
when no Shared Space fits as well, which keeps the Owner's chance to Reclaim it.
_LT_: atlaisvinimas
_Avoid_: free up, lend, give away, share

**Reclaim**:
An Owner taking back a Released period that nobody has booked yet. A booked period can't
be Reclaimed: nobody is ever bumped from a Booking.
_LT_: susigrąžinimas
_Avoid_: cancel the release, revoke, bump

### Waitlist

**Waitlist Entry**:
A Colleague's request for a Booking the app couldn't fit: a day and a whole-day or
part-day period, shaped like a Booking. Lapses once its period starts.
_LT_: užsirašymas į laukiančiųjų sąrašą; a Colleague's place in it is eilė, never vieta
(which is a Space)
_Avoid_: request, standby, queue position

**Waitlist**:
All open Waitlist Entries for one day, in the order they were joined, except that a
Colleague who lost a Booking to a Blocked Space goes to the front.
_LT_: laukiančiųjų sąrašas
_Avoid_: queue

**Promotion**:
The app turning a Waitlist Entry into a Booking when a Space becomes free for a period
(a Cancellation, a Release, a new or unblocked Space) and telling the Colleague. It goes
to the first Entry on the Waitlist whose whole period fits; there are no partial matches,
and nobody races for the freed Space.
_LT_: not named on screen; the Colleague is told "Gavote vietą"
_Avoid_: offer, match, first to book wins
