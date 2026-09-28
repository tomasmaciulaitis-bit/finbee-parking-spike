# An installable web app, not a native iOS app

The brief was an iOS app. We are building a mobile-first web app that colleagues add to
their Home Screen (a PWA), with the admin pages in the same app. Native iOS would have
needed Xcode, an Apple Developer Program membership (about €99 a year, properly finbee's
rather than a personal one), TestFlight builds that expire every 90 days or App Store
review, and a server for the shared data anyway. It would also have left out colleagues on
Android. The web app fits the existing Flask stack, runs on iPhone, Android and desktop,
and every update is live at once.

## Consequences

- Push notifications on iPhone (iOS 16.4+) work only once the app is on the Home Screen
  and the colleague has allowed notifications, never from a Safari tab. Getting colleagues
  through that first-run step is part of the product.
- iOS push subscriptions are known to drop occasionally, so a notification is never the
  only record of anything: what the app shows is the truth.
- Sign in with Google is unreliable inside an installed iPhone web app: the Google page
  opens in a Safari sheet and the login often lands there, outside the app. So colleagues
  sign in with a one-time code emailed to their finbee address instead, even though every
  finbee domain is on Google Workspace. Don't "upgrade" to Google sign-in without proving
  the iPhone flow first.
- Push needs a public HTTPS address, which constrains where the app can be hosted.
- If a native app is ever wanted, the server side stays as it is and a native shell can be
  put in front of it.

## Verified on an iPhone (2026-09-28)

A throwaway spike (`github.com/tomasmaciulaitis-bit/finbee-parking-spike`, on Render Starter)
confirmed all three things this decision depends on. The app opens standalone from the Home
Screen. Web push arrives both while the app is open and while it is closed with the phone
locked. An email-code sign-in, sent through Eudora's mailbox with the "parking" app password,
survives closing and reopening the app.

It also confirmed that a sign-in made in Safari does not carry over to the Home Screen app,
which keeps its own storage. So the first-run flow must be: add to the Home Screen first, then
sign in inside the installed app. When opened in a Safari tab, the app should say that rather
than offer sign-in.
