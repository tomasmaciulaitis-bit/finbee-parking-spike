# The installed app opens offline, with pages as last loaded

The garage is underground, often without a mobile signal, and that is where a Colleague opens
the app to see their Space number. So the service worker saves each page a signed-in Colleague
opens (their days, My Bookings, their profile, the Admin pages) and, with no connection, shows
the saved copy instead of the browser's error. A note at the top says it's as last loaded and
when; for the app's start it falls back to today's day, then My Bookings. A page never opened
online gets a plain offline page.

Nothing changes offline. Booking, cancelling, leaving and joining the Waitlist need the server,
which decides everything, so offline the forms say a connection is needed instead of failing.
A page always comes from the server when it can, so a saved copy never hides a newer one.

The saved pages hold the Colleague's own bookings and the Day View's names, so they're deleted
as soon as nobody is signed in on that phone, at sign-out or when a session ends.
