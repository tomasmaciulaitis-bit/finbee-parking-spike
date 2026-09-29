# Charging comes before best fit

Some Spaces have chargers for electric cars. That breaks the assumption behind ADR-0001 that
Shared Spaces are interchangeable, so the app's choice of Space now starts with charging.

Asking for a Charging Space is a preference, not a condition. Whoever asks gets a free
Charging Space if one fits the period, even where a plain Space would fit better, and a plain
Space otherwise, so asking never costs a Colleague their parking. Everyone else gets a Charging
Space only when no plain Space fits: a charger isn't used up while another Space would do, and
no Space stands empty because it has a charger.

Nothing moves to make room for a charger, because a Booking keeps its Space (ADR-0001). So on a
busy day a Colleague who didn't ask can take the last free Charging Space before one who asks
later. Booking early is the way to be sure of a charger.
