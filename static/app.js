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

  // Notifications on this device (the profile page).
  var button = document.getElementById('enable-push');
  var status = document.getElementById('push-status');
  if (!button || !status) return;
  var supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  function say(text) { status.textContent = text; }
  function keyBytes(b64) {
    var s = atob(b64.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - b64.length % 4) % 4));
    return Uint8Array.from(s, function (c) { return c.charCodeAt(0); });
  }
  function send(subscription) {
    return fetch('/api/push', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(subscription.toJSON())
    });
  }
  if (!supported) {
    say('Šiame įrenginyje pranešimai neveikia. iPhone: pirmiausia pridėkite programėlę prie pradžios ekrano.');
    button.hidden = true;
    return;
  }
  setTimeout(function () {  // no service worker ever became ready (blocked or failed)
    if (status.textContent === 'Tikrinama…') say('Šiame įrenginyje pranešimai neveikia.');
  }, 3000);
  navigator.serviceWorker.ready.then(function (reg) {
    return reg.pushManager.getSubscription().then(function (existing) {
      if (existing && Notification.permission === 'granted') {
        send(existing);  // keeps the server's copy fresh
        say('Pranešimai šiame įrenginyje įjungti.');
        button.hidden = true;
      } else if (Notification.permission === 'denied') {
        say('Pranešimai užblokuoti. Įjunkite juos telefono nustatymuose.');
        button.hidden = true;
      } else {
        say('Pranešimai šiame įrenginyje neįjungti.');
      }
    });
  });
  button.addEventListener('click', function () {
    Notification.requestPermission().then(function (permission) {
      if (permission !== 'granted') { say('Leidimas nesuteiktas.'); return; }
      return navigator.serviceWorker.ready.then(function (reg) {
        return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(button.dataset.key) });
      }).then(send).then(function () {
        say('Pranešimai šiame įrenginyje įjungti.');
        button.hidden = true;
      });
    }).catch(function (e) { say('Nepavyko įjungti: ' + e.message); });
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
