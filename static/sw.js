// finbee parkavimas service worker: shows every push as a notification (iOS requires it) and
// opens the app where the notification points when it is tapped.
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (event) { event.waitUntil(self.clients.claim()); });

self.addEventListener('push', function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || 'Parkavimas', {
    body: data.body || '', icon: '/static/icon-192.png', data: { url: data.url || '/' }
  }));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (windows) {
    for (var i = 0; i < windows.length; i++) {
      if ('navigate' in windows[i]) { return windows[i].navigate(url).then(function (w) { return w && w.focus(); }); }
    }
    return self.clients.openWindow(url);
  }));
});
