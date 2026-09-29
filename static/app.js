// finbee parkavimas: the little the pages need beyond plain forms.
(function () {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(function () {});
  }

  // Whole day or chosen hours: the time pickers only show for a Part-Day request.
  document.querySelectorAll('form[data-period]').forEach(function (form) {
    function sync() {
      var picked = form.querySelector('input[name=kind]:checked');
      var part = picked && picked.value === 'part';
      form.querySelectorAll('[data-part]').forEach(function (el) { el.hidden = !part; });
    }
    form.addEventListener('change', sync);
    sync();
  });

  // Number Plates: one field each; "+ Pridėti dar vieną numerį" adds another.
  document.querySelectorAll('[data-plates]').forEach(function (set) {
    var add = set.querySelector('[data-add-plate]');
    add.hidden = false;
    add.addEventListener('click', function () {
      var fields = set.querySelectorAll('input[name=plates]');
      var field = fields[fields.length - 1].cloneNode();
      field.value = '';
      add.before(field);
      field.focus();
    });
  });
})();

// Notifications on this device: the profile page's switch, and the banner at the top of the
// other pages that asks for them.
(function () {
  var supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  function keyBytes(b64) {
    var s = atob(b64.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - b64.length % 4) % 4));
    return Uint8Array.from(s, function (c) { return c.charCodeAt(0); });
  }
  function send(subscription) {
    return fetch('/api/push', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(subscription.toJSON())
    }).then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
    });
  }
  // 'on', 'off' or 'blocked'. Never settles where no service worker becomes ready. With `sync`
  // it also re-sends this device's subscription, in case the server lost it.
  function state(sync) {
    return navigator.serviceWorker.ready.then(function (reg) {
      return reg.pushManager.getSubscription();
    }).then(function (existing) {
      if (existing && Notification.permission === 'granted') {
        if (sync) send(existing).catch(function () {});
        return 'on';
      }
      return Notification.permission === 'denied' ? 'blocked' : 'off';
    });
  }
  function syncDue() {  // once a day is enough to heal a lost copy; every page would be waste
    try {
      var last = Number(localStorage.getItem('pushSyncedAt')) || 0;
      if (Date.now() - last < 24 * 3600 * 1000) return false;
      localStorage.setItem('pushSyncedAt', String(Date.now()));
    } catch (e) {}
    return true;
  }
  // Must run from a tap: Safari only asks for permission then.
  function enable(key) {
    return Notification.requestPermission().then(function (permission) {
      if (permission !== 'granted') return permission === 'denied' ? 'blocked' : 'off';
      return navigator.serviceWorker.ready.then(function (reg) {
        return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
      }).then(send).then(function () { return 'on'; });
    });
  }

  var button = document.getElementById('enable-push');
  var status = document.getElementById('push-status');
  if (button && status) {
    var words = {
      on: 'Pranešimai šiame įrenginyje įjungti.',
      off: 'Pranešimai šiame įrenginyje neįjungti.',
      blocked: 'Pranešimai užblokuoti. Įjunkite juos telefono nustatymuose.'
    };
    var show = function (s) { status.textContent = words[s]; button.hidden = s !== 'off'; };
    if (!supported) {
      status.textContent = 'Šiame įrenginyje pranešimai neveikia. iPhone: pirmiausia pridėkite programėlę prie pradžios ekrano.';
      button.hidden = true;
    } else {
      setTimeout(function () {  // no service worker ever became ready (blocked or failed)
        if (status.textContent === 'Tikrinama…') status.textContent = 'Šiame įrenginyje pranešimai neveikia.';
      }, 3000);
      state(true).then(show);
      button.addEventListener('click', function () {
        enable(button.dataset.key).then(function (s) {
          if (s === 'off') status.textContent = 'Leidimas nesuteiktas.'; else show(s);
        }).catch(function (e) { status.textContent = 'Nepavyko įjungti: ' + e.message; });
      });
    }
  }

  var nudge = document.getElementById('push-nudge');
  if (!nudge) return;
  var reachable = nudge.dataset.reachable === 'yes';  // the server can push to them somewhere
  var phone = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
  var standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  function offer(s) {  // shows the banner's part for that state; 'on' hides it
    var any = false;
    nudge.querySelectorAll('[data-when]').forEach(function (el) {
      el.hidden = el.dataset.when !== s;
      any = any || !el.hidden;
    });
    nudge.hidden = !any;
  }
  if (reachable && !phone) return;  // a computer, while notifications already reach them elsewhere
  if (!supported) {
    if (/iPhone|iPod/.test(navigator.userAgent) && !standalone && !reachable) offer('install');
    return;
  }
  state(!reachable || syncDue()).then(offer);
  var enableButton = nudge.querySelector('[data-enable]');
  var error = nudge.querySelector('[data-error]');
  enableButton.addEventListener('click', function () {
    enableButton.disabled = true;
    error.hidden = true;
    enable(enableButton.dataset.key).then(offer, function (e) {
      error.textContent = 'Nepavyko įjungti: ' + e.message;
      error.hidden = false;
    }).then(function () { enableButton.disabled = false; });
  });
})();

// The "add to Home Screen" animation (install page): each step shows a screen, moves the finger to
// its button and taps it; the matching written step is highlighted as it goes.
(function () {
  var demo = document.querySelector('.demo');
  if (!demo) return;
  var screen = demo.querySelector('.screen');
  var finger = demo.querySelector('.finger');
  // [screen to show, button the finger taps, written step to highlight]
  var ios = [['sheet', null, 'add'], ['add', 'add', 'add'], ['dialog', 'confirm', 'confirm'], ['home', 'open', 'open']];
  var steps = {
    menu: [['start', 'dots', 'dots'], ['menu', 'share', 'share']].concat(ios),
    toolbar: [['start', 'share', 'share']].concat(ios),
    android: [['start', 'kebab', 'kebab'], ['amenu', 'aadd', 'aadd'], ['adialog', 'ainstall', 'ainstall'],
              ['home', 'open', 'open']]
  }[demo.dataset.variant];
  var items = document.querySelectorAll('.steps li[data-step]');
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    demo.dataset.scene = demo.dataset.variant === 'android' ? 'adialog' : 'dialog';
    return;
  }
  function mark(step) {
    items.forEach(function (li) { li.classList.toggle('now', li.dataset.step === step); });
  }
  function point(target) {
    var box = screen.getBoundingClientRect(), r = target.getBoundingClientRect();
    finger.style.left = (r.left - box.left + r.width / 2) + 'px';
    finger.style.top = (r.top - box.top + r.height / 2) + 'px';
  }
  var i = 0;
  function run() {
    var scene = steps[i][0], targetName = steps[i][1], step = steps[i][2];
    demo.dataset.scene = scene;
    mark(step);
    demo.querySelectorAll('.hl').forEach(function (el) { el.classList.remove('hl'); });
    var target = targetName && demo.querySelector('[data-target="' + targetName + '"]');
    setTimeout(function () {
      if (target) point(target);
      setTimeout(function () {
        if (target) {
          target.classList.add('hl');
          finger.classList.remove('tap');
          void finger.offsetWidth;  // restart the tap animation
          finger.classList.add('tap');
        }
        i = (i + 1) % steps.length;
        setTimeout(run, i === 0 ? 2200 : target ? 650 : 250);
      }, target ? 700 : 350);
    }, 550);
  }
  run();
})();

// The Android install banner: only in an Android browser tab, never inside the installed app.
// "Įdiegti" opens the browser's own install window when it offers one, else the animated guide.
(function () {
  var banner = document.getElementById('install-banner');
  if (!banner) return;
  var standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  var hiddenUntil = 0;
  try { hiddenUntil = Number(localStorage.getItem('installBannerHiddenUntil')) || 0; } catch (e) {}
  if (!/Android/i.test(navigator.userAgent) || standalone || Date.now() < hiddenUntil) return;
  var offer = null;
  window.addEventListener('beforeinstallprompt', function (event) { event.preventDefault(); offer = event; });
  window.addEventListener('appinstalled', function () { banner.hidden = true; });
  banner.hidden = false;
  banner.querySelector('[data-install]').addEventListener('click', function () {
    if (!offer) { window.location.href = '/idiegti'; return; }
    offer.prompt();
    offer.userChoice.then(function (choice) { if (choice.outcome === 'accepted') banner.hidden = true; });
    offer = null;
  });
  banner.querySelector('[data-dismiss]').addEventListener('click', function () {
    banner.hidden = true;
    try { localStorage.setItem('installBannerHiddenUntil', String(Date.now() + 30 * 24 * 3600 * 1000)); } catch (e) {}
  });
})();

// Pull to refresh, for the installed app only: a Home Screen app has no reload button and no
// pull-to-refresh of its own, while a browser tab keeps the browser's. Every listener is
// passive: it only watches the finger, so scrolling never waits for this script (on iPhone
// the page's own bounce moves the content down while the badge shows).
(function () {
  var READY = 70, MOST = 110;
  var indicator = null, startX = 0, startY = 0, pull = 0, tracking = false, pulling = false;
  function installed() {  // asked at each touch, so nothing is decided before the page is used
    return navigator.standalone === true || window.matchMedia('(display-mode: standalone)').matches;
  }
  function show(distance) {
    if (!indicator) {
      indicator = document.createElement('div');
      indicator.className = 'ptr';
      indicator.setAttribute('aria-hidden', 'true');
      indicator.innerHTML = '<svg viewBox="0 0 24 24"><path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4h-4"/></svg>';
      document.body.appendChild(indicator);
    }
    indicator.classList.add('dragging');
    indicator.classList.toggle('ready', distance >= READY);
    indicator.style.opacity = String(Math.min(1, distance / READY));
    indicator.style.transform = 'translate(-50%, ' + distance + 'px) rotate(' + distance * 3 + 'deg)';
  }
  function hide() {
    if (!indicator) return;
    indicator.classList.remove('dragging', 'ready');
    indicator.style.opacity = '0';
    indicator.style.transform = '';
  }
  document.addEventListener('touchstart', function (e) {
    tracking = e.touches.length === 1 && window.scrollY <= 0 && installed();
    pulling = false;
    pull = 0;
    if (tracking) { startX = e.touches[0].clientX; startY = e.touches[0].clientY; }
  }, { passive: true });
  document.addEventListener('touchmove', function (e) {
    if (!tracking) return;
    var dx = e.touches[0].clientX - startX, dy = e.touches[0].clientY - startY;
    if (!pulling) {
      if (dy < 0 || Math.abs(dx) > dy) {  // scrolling up or sideways (the day chips), not pulling
        if (dy < -8 || Math.abs(dx) > 8) tracking = false;
        return;
      }
      if (dy < 10 || window.scrollY > 0) return;
      pulling = true;
    }
    pull = Math.min(MOST, (dy - 10) * 0.55);
    show(pull);
  }, { passive: true });
  document.addEventListener('touchend', function () {
    tracking = false;
    if (!pulling) return;
    pulling = false;
    if (pull >= READY) {
      indicator.classList.remove('dragging');
      indicator.classList.add('spinning');
      location.replace(location.href.split('#')[0]);  // a fresh GET, never a re-sent form
    } else {
      hide();
    }
  }, { passive: true });
  document.addEventListener('touchcancel', function () { tracking = pulling = false; hide(); }, { passive: true });
})();
