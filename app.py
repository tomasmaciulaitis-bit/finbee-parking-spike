"""finbee office parking: the Lithuanian web app over the Garage.

An installable web app (ADR-0002) hosted on Render (ADR-0004). Run it with ONE worker process:
the background loop that sends notifications and the evening Reminder lives in the process.

    python app.py                       local run on http://127.0.0.1:5095
    gunicorn -w 1 --threads 8 'app:production()'
"""
import logging
import os
import re
import secrets
import threading
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import (Flask, abort, flash, g, jsonify, make_response, redirect, render_template,
                   request, send_from_directory, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix

import lt
import notify
from garage import Refused, Garage, hhmm, to_minutes
from signin import SignIn

HERE = Path(__file__).resolve().parent
VILNIUS = ZoneInfo("Europe/Vilnius")
log = logging.getLogger("parking")

MESSAGES = {
    "no_space": "Tuo laiku laisvų vietų nėra.",
    "outside_window": "Šios dienos rezervuoti negalima: ji už rezervavimo laikotarpio ribų.",
    "closed_day": "Tą dieną garažas uždarytas.",
    "bad_period": "Netinkamas laikas: rezervacija trunka bent valandą, 30 min. žingsniais, "
                  "rezervavimo valandomis.",
    "one_per_day": "Tą dieną jau turite rezervaciją arba laukiate eilėje.",
    "limit": "Pasiekėte rezervacijų limitą. Atšaukite kurią nors, kad galėtumėte rezervuoti naują.",
    "owner_holds": "Tuo metu turite savo nuolatinę vietą. Jei jos nereikia, atlaisvinkite ją.",
    "space_free": "Laisva vieta yra – tiesiog rezervuokite.",
    "not_found": "Nerasta.",
    "ended": "Ši rezervacija jau pasibaigė.",
    "not_allowed": "Neturite teisės to daryti.",
    "booked": "Dalis atlaisvinto laiko jau rezervuota – susigrąžinti negalima.",
    "already_released": "Šis laikas jau atlaisvintas.",
    "past_day": "Praėjusios dienos keisti negalima.",
    "last_admin": "Turi likti bent vienas administratorius.",
    "owns_one": "Šis kolega jau turi nuolatinę vietą.",
    "inactive": "Jūsų paskyra išjungta.",
    "bad_rules": "Patikrinkite taisykles: laikai 30 min. žingsniais, valandos bent 1 val., "
                 "limitas 1–20, laikotarpis 1–60 d.",
    "not_finbee": "Įveskite finbee el. pašto adresą (finbeeverslui.lt, finbee.lt arba finbee.com).",
    "wrong_code": "Neteisingas kodas.",
    "expired": "Kodas nebegalioja – paprašykite naujo.",
    "too_many_tries": "Per daug bandymų – paprašykite naujo kodo.",
    "too_soon": "Kodą ką tik išsiuntėme – palaukite minutę ir bandykite vėl.",
}
CODE_EMAIL = ("Jūsų parkavimo programėlės prisijungimo kodas: %s\n\n"
              "Kodas galioja 10 minučių. Jei jo neprašėte, šį laišką tiesiog ištrinkite.\n")
SHORT_WEEKDAYS = ("Pr", "An", "Tr", "Kt", "Pn", "Št", "Sk")


def vilnius_now():
    return datetime.now(VILNIUS)


def load_secret(data_dir):
    """A session secret kept on the data disk, so sign-ins survive restarts."""
    path = Path(data_dir) / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


def create_app(data_dir, now=vilnius_now, first_admin_email=None, send_code=None, send_push=None,
               send_email=None, background=True, secret_key=None, cookie_secure=False, app_url=""):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    garage = Garage(str(data_dir / "parking.sqlite3"), now=now, first_admin_email=first_admin_email)
    vapid, vapid_public = notify.load_vapid(data_dir)
    sender_email = os.environ.get("PARKING_SENDER_EMAIL", "")
    if send_email is None:
        send_email = notify.gmail_sender(sender_email, os.environ.get("PARKING_SENDER_APP_PASSWORD", ""))
    if send_push is None:
        send_push = notify.web_push_sender(vapid, sender_email or "parking@finbeeverslui.lt")
    if send_code is None:
        def send_code(email, code):
            send_email(email, "Prisijungimo kodas: %s" % code, CODE_EMAIL % code)
    footer = "\n\n—\nfinbee parkavimas%s\n" % ("\n" + app_url if app_url else "")
    signin = SignIn(garage, send_code=send_code, now=now)
    notifier = notify.Notifier(garage, send_push=send_push,
                               send_email=lambda to, subject, body: send_email(to, subject, body + footer))

    app = Flask(__name__)
    app.secret_key = secret_key or load_secret(data_dir)
    app.config.update(GARAGE=garage, PERMANENT_SESSION_LIFETIME=timedelta(days=90),
                      SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=cookie_secure,
                      SESSION_COOKIE_HTTPONLY=True)
    if cookie_secure:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    wake = threading.Event()

    # ---- helpers ---------------------------------------------------------------------------

    def refused(error):
        flash(MESSAGES.get(error.code, "Nepavyko (%s)." % error.code), "error")

    def signed_in(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if g.me is None:
                return redirect(url_for("start"))
            return view(*args, **kwargs)
        return wrapper

    def admin_only(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if g.me is None:
                return redirect(url_for("start"))
            if not g.me.is_admin:
                abort(403)
            return view(*args, **kwargs)
        return wrapper

    def parse_day(text):
        try:
            return date.fromisoformat(text or "")
        except ValueError:
            abort(404)

    def period_from(form):
        """(start, end) for a Part-Day request, or (None, None) for a Whole-Day one."""
        if form.get("kind") == "part":
            return form.get("start") or "", form.get("end") or ""
        return None, None

    def back(default):
        target = request.form.get("next") or ""
        return redirect(target if target.startswith("/") and not target.startswith("//") else default)

    def is_iphone():
        agent = request.headers.get("User-Agent", "")
        return "iPhone" in agent or "iPod" in agent

    def install_page():
        """The animated "add to Home Screen" steps. Android follows Chrome's ⋮ menu. On iPhone,
        Safari 26 hides Share behind "•••" while older Safari has it in the toolbar; Safari 26
        freezes the OS version in its user agent, so its Version token is what tells them apart."""
        agent = request.headers.get("User-Agent", "")
        forced = request.args.get("safari", "")
        if "Android" in agent and not forced:
            return render_template("install.html", variant="android", in_safari=True, host=request.host)
        version = re.search(r"Version/(\d+)", agent)
        major = int(forced) if forced.isdigit() else int(version.group(1)) if version else 26
        in_safari = bool(version) and not re.search(r"CriOS|FxiOS|EdgiOS|OPiOS", agent)
        return render_template("install.html", variant="menu" if major >= 26 else "toolbar",
                               in_safari=in_safari or bool(forced), host=request.host)

    def day_label_short(day):
        today = now().date()
        if day == today:
            return "Šiandien", ""
        if day == today + timedelta(days=1):
            return "Rytoj", ""
        return SHORT_WEEKDAYS[day.weekday()], str(day.day)

    def time_options(day=None):
        """Start and end times in 30-minute steps; on the day itself nothing already past."""
        rules = garage.rules()
        opens, closes = to_minutes(rules.hours_start), to_minutes(rules.hours_end)
        if day == now().date():
            opens = max(opens, (now().hour * 60 + now().minute) // 30 * 30)
        return ([hhmm(m) for m in range(opens, closes - 30, 30)],
                [hhmm(m) for m in range(opens + 60, closes + 1, 30)])

    def position(time_text):
        """Where a time sits across the Bookable Hours, in percent, for the timeline bars."""
        rules = garage.rules()
        opens, closes = to_minutes(rules.hours_start), to_minutes(rules.hours_end)
        return max(0.0, min(100.0, 100.0 * (to_minutes(time_text) - opens) / (closes - opens)))

    @app.before_request
    def load_colleague():
        g.me = None
        colleague_id = session.get("colleague_id")
        if colleague_id is not None:
            me = garage.colleague(colleague_id)
            if me is not None and me.active:
                g.me = me
            else:
                session.pop("colleague_id", None)
        if request.method == "POST" and not same_origin():
            abort(403)

    def same_origin():
        """Forms and fetches are only accepted from the app's own pages."""
        for header in ("Origin", "Referer"):
            value = request.headers.get(header)
            if value:
                return urlparse(value).netloc == request.host
        return True

    @app.after_request
    def after(response):
        if request.method == "POST":
            wake.set()  # deliver any notification the action queued without waiting a minute
        return response

    @app.context_processor
    def template_helpers():
        return {"me": g.get("me"), "lt": lt, "day_label_short": day_label_short,
                "position": position, "vapid_public": vapid_public, "today": now().date(),
                "now_hhmm": now().strftime("%H:%M")}

    # ---- the Home Screen app ---------------------------------------------------------------

    @app.get("/manifest.webmanifest")
    def manifest():
        response = jsonify({
            "id": "/", "name": "finbee parkavimas", "short_name": "Parkavimas", "lang": "lt",
            "description": "Rezervuokite vietą finbee biuro požeminiame garaže.",
            "start_url": "/?app=1", "scope": "/", "display": "standalone",
            "background_color": "#f2f2f2", "theme_color": "#f2f2f2",
            "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
                      {"src": "/static/icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
                       "purpose": "maskable"}]})
        response.mimetype = "application/manifest+json"
        return response

    @app.get("/sw.js")
    def service_worker():
        return send_from_directory(HERE / "static", "sw.js", mimetype="application/javascript",
                                   max_age=0)

    @app.post("/api/push")
    @signed_in
    def push_subscribe():
        subscription = request.get_json(silent=True) or {}
        keys = subscription.get("keys") or {}
        if not subscription.get("endpoint", "").startswith("https://") or not keys.get("p256dh") \
                or not keys.get("auth"):
            abort(400)
        garage.add_push_subscription(g.me, subscription["endpoint"], keys)
        return jsonify(ok=True)

    # ---- signing in ------------------------------------------------------------------------

    @app.get("/")
    def start():
        opened_as_app = request.args.get("app") == "1"
        if g.me is not None:
            response = redirect(url_for("today_page"))
        elif is_iphone() and not opened_as_app and request.cookies.get("app") != "1":
            response = make_response(install_page())
        else:
            response = make_response(render_template("signin.html",
                                                     pending_email=session.get("pending_email")))
        if opened_as_app:
            # Set inside the Home Screen app's own storage, so its later visits skip the
            # "add to Home Screen first" page (ADR-0002: Safari and the app don't share cookies).
            response.set_cookie("app", "1", max_age=10 * 365 * 24 * 3600, samesite="Lax",
                                secure=cookie_secure, httponly=True)
        return response

    @app.get("/idiegti")
    def install_help():
        """The same steps on demand, e.g. to re-add the app after its icon changes."""
        return install_page()

    @app.post("/kodas")
    def request_code():
        email = request.form.get("email", "")
        try:
            signin.request_code(email)
            session["pending_email"] = email.strip().lower()
        except Refused as error:
            refused(error)
        except Exception:
            log.exception("sending a sign-in code failed")
            flash("Nepavyko išsiųsti laiško. Pabandykite po kelių minučių.", "error")
        return redirect(url_for("start"))

    @app.post("/kodas/kitas-adresas")
    def change_email():
        session.pop("pending_email", None)
        return redirect(url_for("start"))

    @app.post("/prisijungti")
    def verify_code():
        email = session.get("pending_email")
        if not email:
            return redirect(url_for("start"))
        try:
            colleague = signin.verify(email, request.form.get("code", ""))
        except Refused as error:
            refused(error)
            return redirect(url_for("start"))
        session.pop("pending_email", None)
        session.permanent = True
        if colleague is None:
            session["verified_email"] = email
            return redirect(url_for("register"))
        session["colleague_id"] = colleague.id
        return redirect(url_for("today_page"))

    @app.route("/registracija", methods=["GET", "POST"])
    def register():
        email = session.get("verified_email")
        if not email:
            return redirect(url_for("start"))
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            plates = [p for p in request.form.get("plates", "").replace(";", ",").split(",") if p.strip()]
            if not name:
                flash("Įrašykite vardą ir pavardę.", "error")
                return render_template("register.html", email=email, form=request.form)
            colleague = garage.colleague_by_email(email) or garage.register(email, name, plates)
            session.pop("verified_email", None)
            session["colleague_id"] = colleague.id
            return redirect(url_for("today_page"))
        return render_template("register.html", email=email, form={})

    @app.post("/atsijungti")
    def sign_out():
        session.clear()
        return redirect(url_for("start"))

    # ---- booking ---------------------------------------------------------------------------

    @app.get("/diena")
    @signed_in
    def today_page():
        return redirect(url_for("day_page", iso=now().date().isoformat()))

    @app.get("/diena/<iso>")
    @signed_in
    def day_page(iso):
        day = parse_day(iso)
        days = garage.open_days()
        option = next((d for d in days if d.day == day), None)
        mine = garage.my_bookings(g.me)
        plate = request.args.get("numeris", "").strip()
        starts, ends = time_options(day)
        return render_template(
            "day.html", day=day, days=days, option=option, view=garage.day_view(day, g.me),
            my_booking=next((b for b in mine.upcoming if b.day == day), None),
            my_entry=next((w for w in mine.waiting if w.day == day), None),
            offer=request.args.get("laukti") == "1", offer_kind=request.args.get("kind", "whole"),
            offer_start=request.args.get("start", ""), offer_end=request.args.get("end", ""),
            starts=starts, ends=ends, rules=garage.rules(), plate=plate,
            plate_owner=garage.whose_plate(plate) if plate else None)

    @app.post("/rezervuoti")
    @signed_in
    def book():
        day = parse_day(request.form.get("day"))
        start, end = period_from(request.form)
        try:
            booking = garage.book(g.me, day, start, end)
            flash("Rezervuota: vieta Nr. %s, %s–%s." % (booking.space, booking.start, booking.end))
        except Refused as error:
            if error.code == "no_space":
                return redirect(url_for("day_page", iso=day.isoformat(), laukti=1,
                                        kind=request.form.get("kind", "whole"),
                                        start=start or "", end=end or ""))
            refused(error)
        return redirect(url_for("day_page", iso=day.isoformat()))

    @app.post("/laukti")
    @signed_in
    def join_waitlist():
        day = parse_day(request.form.get("day"))
        start, end = period_from(request.form)
        try:
            garage.join_waitlist(g.me, day, start, end)
            flash("Užsirašėte į laukiančiųjų sąrašą. Kai vieta atsiras, ją gausite automatiškai "
                  "ir jums pranešime.")
        except Refused as error:
            refused(error)
        return redirect(url_for("day_page", iso=day.isoformat()))

    @app.post("/atsaukti/<int:booking_id>")
    @signed_in
    def cancel(booking_id):
        try:
            garage.cancel(g.me, booking_id)
            flash("Rezervacija atšaukta. Ačiū – vietą gaus kitas.")
        except Refused as error:
            refused(error)
        return back(url_for("mine"))

    @app.post("/palikti/<int:entry_id>")
    @signed_in
    def leave_waitlist(entry_id):
        try:
            garage.leave_waitlist(g.me, entry_id)
            flash("Palikote laukiančiųjų sąrašą.")
        except Refused as error:
            refused(error)
        return back(url_for("mine"))

    @app.get("/mano")
    @signed_in
    def mine():
        starts, ends = time_options()
        return render_template("mine.html", mine=garage.my_bookings(g.me), my_space=garage.my_space(g.me),
                               starts=starts, ends=ends)

    @app.post("/atlaisvinti")
    @signed_in
    def release():
        day = parse_day(request.form.get("day"))
        start, end = period_from(request.form)
        space = request.form.get("space") or None
        try:
            done = garage.release(g.me, day, start, end, space=space)
            flash("Atlaisvinta: %s, %s–%s." % (lt.day_label(done.day), done.start, done.end))
        except Refused as error:
            refused(error)
        return back(url_for("mine"))

    @app.post("/susigrazinti/<int:release_id>")
    @signed_in
    def reclaim(release_id):
        try:
            garage.reclaim(g.me, release_id)
            flash("Vieta vėl jūsų.")
        except Refused as error:
            refused(error)
        return back(url_for("mine"))

    @app.route("/profilis", methods=["GET", "POST"])
    @signed_in
    def profile():
        if request.method == "POST":
            plates = [p for p in request.form.get("plates", "").replace(";", ",").split(",") if p.strip()]
            garage.set_plates(g.me, plates)
            flash("Valstybiniai numeriai išsaugoti.")
            return redirect(url_for("profile"))
        return render_template("profile.html", plates=", ".join(garage.plates(g.me)))

    # ---- administration --------------------------------------------------------------------

    @app.get("/admin")
    @admin_only
    def admin_home():
        return redirect(url_for("admin_day", iso=now().date().isoformat()))

    @app.get("/admin/diena/<iso>")
    @admin_only
    def admin_day(iso):
        day = parse_day(iso)
        return render_template("admin/day.html", day=day, days=garage.open_days(),
                               view=garage.day_view(day, g.me), waiting=garage.waiting_names(g.me, day))

    @app.post("/admin/atsaukti/<int:booking_id>")
    @admin_only
    def admin_cancel(booking_id):
        try:
            garage.cancel(g.me, booking_id)
            flash("Rezervacija atšaukta, kolegai pranešta.")
        except Refused as error:
            refused(error)
        return back(url_for("admin_home"))

    @app.route("/admin/vietos", methods=["GET", "POST"])
    @admin_only
    def admin_spaces():
        if request.method == "POST":
            number = request.form.get("number", "").strip()
            try:
                if not number:
                    raise Refused("not_found")
                garage.add_space(g.me, number)
                flash("Vieta Nr. %s pridėta." % number)
            except Refused as error:
                refused(error)
            except Exception:
                flash("Tokia vieta jau yra.", "error")
            return redirect(url_for("admin_spaces"))
        return render_template("admin/spaces.html", spaces=garage.spaces(),
                               colleagues=[c for c in garage.colleagues() if c.active])

    @app.post("/admin/vietos/<number>/turetojas")
    @admin_only
    def admin_set_owner(number):
        owner_id = request.form.get("owner_id") or None
        owner = garage.colleague(int(owner_id)) if owner_id else None
        try:
            garage.set_owner(g.me, number, owner)
            flash("Vieta Nr. %s: %s." % (number, "nuolatinė – " + owner.name if owner else "bendra"))
        except Refused as error:
            refused(error)
        return redirect(url_for("admin_spaces"))

    @app.post("/admin/vietos/<number>/blokuoti")
    @admin_only
    def admin_block(number):
        first = parse_day(request.form.get("first_day"))
        last = parse_day(request.form.get("last_day")) if request.form.get("last_day") else None
        try:
            garage.block_space(g.me, number, first, last)
            flash("Vieta Nr. %s užblokuota. Paveiktiems kolegoms pranešta." % number)
        except Refused as error:
            refused(error)
        return redirect(url_for("admin_spaces"))

    @app.post("/admin/blokai/<int:block_id>/baigti")
    @admin_only
    def admin_unblock(block_id):
        try:
            garage.unblock(g.me, block_id)
            flash("Blokavimas baigtas.")
        except Refused as error:
            refused(error)
        return redirect(url_for("admin_spaces"))

    @app.route("/admin/taisykles", methods=["GET", "POST"])
    @admin_only
    def admin_rules():
        if request.method == "POST":
            form = request.form
            try:
                garage.set_rules(g.me, form.get("window_days"), form.get("opening_time"),
                                 form.get("hours_start"), form.get("hours_end"), form.get("booking_limit"))
                flash("Taisyklės išsaugotos. Jos galioja naujoms rezervacijoms.")
            except Refused as error:
                refused(error)
            return redirect(url_for("admin_rules"))
        return render_template("admin/rules.html", rules=garage.rules(),
                               times=[hhmm(m) for m in range(0, 24 * 60 + 1, 30)])

    @app.route("/admin/dienos", methods=["GET", "POST"])
    @admin_only
    def admin_days():
        if request.method == "POST":
            day = parse_day(request.form.get("day"))
            try:
                garage.close_day(g.me, day)
                flash("%s uždaryta. Paveiktiems kolegoms pranešta." % lt.sentence(lt.day_label(day)))
            except Refused as error:
                refused(error)
            return redirect(url_for("admin_days"))
        return render_template("admin/days.html", closed=garage.closed_days())

    @app.post("/admin/dienos/<iso>/atidaryti")
    @admin_only
    def admin_reopen(iso):
        garage.reopen_day(g.me, parse_day(iso))
        flash("Diena vėl atidaryta.")
        return redirect(url_for("admin_days"))

    @app.get("/admin/kolegos")
    @admin_only
    def admin_colleagues():
        return render_template("admin/colleagues.html", colleagues=garage.colleagues())

    @app.post("/admin/kolegos/<int:colleague_id>/administratorius")
    @admin_only
    def admin_toggle_admin(colleague_id):
        colleague = garage.colleague(colleague_id) or abort(404)
        try:
            garage.set_admin(g.me, colleague, not colleague.is_admin)
        except Refused as error:
            refused(error)
        return redirect(url_for("admin_colleagues"))

    @app.post("/admin/kolegos/<int:colleague_id>/isjungti")
    @admin_only
    def admin_deactivate(colleague_id):
        colleague = garage.colleague(colleague_id) or abort(404)
        try:
            garage.deactivate(g.me, colleague)
            flash("%s paskyra išjungta." % colleague.name)
        except Refused as error:
            refused(error)
        return redirect(url_for("admin_colleagues"))

    # ---- the background loop ---------------------------------------------------------------

    def background_loop():
        last_cleanup = None
        while True:
            wake.wait(60)
            wake.clear()
            try:
                garage.queue_reminders()
                notifier.deliver_pending()
                if last_cleanup != now().date():
                    garage.forget_old_bookings()
                    last_cleanup = now().date()
            except Exception:
                log.exception("background round failed")

    if background:
        threading.Thread(target=background_loop, name="parking-background", daemon=True).start()
    app.config["NOTIFIER"] = notifier
    return app


def production():
    """The app as Render runs it. PARKING_DEV=1 writes codes, emails and pushes to the log
    instead of sending them, for trying the app locally."""
    logging.basicConfig(level=logging.INFO)
    senders = {}
    if os.environ.get("PARKING_DEV") == "1":
        senders = dict(
            send_code=lambda email, code: log.warning("DEV sign-in code for %s: %s", email, code),
            send_email=lambda to, subject, body: log.warning("DEV email to %s: %s | %s", to, subject, body),
            send_push=lambda subscription, title, body: log.warning("DEV push: %s | %s", title, body))
    return create_app(os.environ.get("DATA_DIR", str(HERE / "data")),
                      first_admin_email=os.environ.get("FIRST_ADMIN_EMAIL"),
                      secret_key=os.environ.get("SECRET_KEY"),
                      cookie_secure=os.environ.get("COOKIE_SECURE") == "1",
                      app_url=os.environ.get("APP_URL", ""), **senders)


if __name__ == "__main__":
    production().run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5095")),
                     threaded=True)
