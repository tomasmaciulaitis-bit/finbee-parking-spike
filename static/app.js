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
