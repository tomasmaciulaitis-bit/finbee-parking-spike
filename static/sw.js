// finbee parkavimas service worker. It shows every push as a notification (iOS requires it),
// opens the app where a tapped notification points, and lets the app open with no connection,
// as underground in the garage: each page is saved as last loaded, and a page never loaded
// shows a plain offline page. Changes still need the server, so nothing is booked offline.
var PAGES = 'pages-v1';  // pages as last loaded; app.js empties it once nobody is signed in
var FILES = 'files-v1';  // versioned static files, which never change, and the offline page
var SAVED = /^\/(diena\/|mano$|profilis$|admin\/)/;

self.addEventListener('install', function (event) {
  event.waitUntil(caches.open(FILES).then(function (cache) {
    return cache.add('/offline');
  }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (event) {
  event.waitUntil(caches.keys().then(function (names) {
    return Promise.all(names.filter(function (name) { return name !== PAGES && name !== FILES; })
      .map(function (name) { return caches.delete(name); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (event) {
  var request = event.request, url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    event.respondWith(openPage(request, url));
  } else if (url.pathname.indexOf('/static/') === 0 && url.searchParams.has('v')) {
    event.respondWith(staticFile(request, url));
  }
});

// A page comes fresh from the server whenever it can, and is saved. With no connection, or
// while the server is down (a deploy), the saved copy is marked so the page says it may be old.
function openPage(request, url) {
  return fetch(request).then(function (response) {
    if (response.status >= 500) return savedOr(url, response);
    if (response.status === 200 && SAVED.test(url.pathname)) {
      var copy = response.clone();
      caches.open(PAGES).then(function (cache) { return cache.put(url.pathname, copy); });
    }
    return response;  // a redirect passes through as is, and the browser follows it
  }).catch(function () {
    return savedOr(url, null);
  });
}

function savedOr(url, otherwise) {
  return savedPage(url).then(function (saved) {
    if (!saved) return otherwise || caches.match('/offline');
    return saved.text().then(function (html) {
      return new Response(html.replace('<body', '<body data-offline="1"'),
                          { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
    });
  });
}

// The page itself; for the app's start, today's day or My Bookings, where the Space number is.
function savedPage(url) {
  return caches.open(PAGES).then(function (cache) {
    var start = url.pathname === '/' || url.pathname === '/diena';
    var paths = [url.pathname].concat(start ? ['/diena/' + today(), '/mano'] : []);
    return paths.reduce(function (found, path) {
      return found.then(function (hit) { return hit || cache.match(path); });
    }, Promise.resolve(undefined));
  });
}

function today() {
  var d = new Date();
  return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
}

// A versioned file never changes, so the saved copy serves; a new version replaces the old one.
function staticFile(request, url) {
  return caches.match(request).then(function (hit) {
    return hit || fetch(request).then(function (response) {
      if (response.status === 200) {
        var copy = response.clone();
        caches.open(FILES).then(function (cache) {
          return cache.keys().then(function (keys) {
            return Promise.all(keys.filter(function (key) { return new URL(key.url).pathname === url.pathname; })
              .map(function (key) { return cache.delete(key); }));
          }).then(function () { return cache.put(request, copy); });
        });
      }
      return response;
    });
  });
}

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
