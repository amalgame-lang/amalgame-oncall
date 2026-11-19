// oncall-sw.js — the phone's side of amalgame-oncall : a Web Push service worker.
//
// Register it from the app's page (same origin, HTTPS) :
//   navigator.serviceWorker.register('oncall-sw.js?sub=' + encodeURIComponent('/api/oncall/subscribe'))
// `sub` is where a renewed subscription is posted (pushsubscriptionchange).
//
// On a push (the payload Pager.PushTo builds) :
//   - confirms the arrival to `rx` with the push id : the server's delivery
//     receipt, so a push that does not arrive is known and goes by SMS ;
//   - shows the notification : an alarm stays until touched, vibrates,
//     replaces the previous one of the same incident (tag), and offers
//     "take it" (posts the signed take token to `takeUrl`, no session
//     needed : works from the lock screen) and "open".
// iOS shows no notification buttons : touching opens the page.
'use strict';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

function post(url, body, withCookies) {
  return fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
    credentials: withCookies ? 'same-origin' : 'omit',
  });
}

self.addEventListener('push', (event) => {
  let p = {};
  try {
    p = event.data ? event.data.json() : {};
  } catch (e) {
    p = {title: event.data ? event.data.text() : ''};
  }
  const alarm = p.kind === 'alarm';
  const tasks = [];
  if (p.id && p.rx) tasks.push(post(p.rx, {id: p.id}, false).catch(() => {}));
  tasks.push(self.registration.showNotification(p.title || 'On-call', {
    body: p.body || '',
    tag: p.tag || 'oncall',
    renotify: true,
    requireInteraction: alarm,
    vibrate: alarm ? [500, 200, 500, 200, 1000] : [120],
    timestamp: Date.now(),
    icon: p.icon || undefined,
    badge: p.badge || undefined,
    data: p,
    actions: alarm && p.take ? [
      {action: 'take', title: p.takeLabel || 'Take it'},
      {action: 'open', title: p.openLabel || 'Open'},
    ] : [],
  }));
  event.waitUntil(Promise.all(tasks));
});

self.addEventListener('notificationclick', (event) => {
  const p = event.notification.data || {};
  event.notification.close();
  if (event.action === 'take' && p.take && p.takeUrl) {
    // The server answers {title, body} (or {error}) : shown in place of the alarm.
    event.waitUntil(post(p.takeUrl, {token: p.take}, false)
      .then((r) => r.json().catch(() => ({})).then((j) => ({ok: r.ok, j})))
      .then(({ok, j}) => self.registration.showNotification(
        (ok ? j.title : j.error) || (ok ? '✓' : '✗'),
        {body: (ok ? j.body : p.title) || '', tag: p.tag, data: Object.assign({}, p, {kind: 'info'})}))
      .catch(() => self.registration.showNotification(p.offlineLabel || 'Not sent : no network',
        {body: p.title || '', tag: p.tag, requireInteraction: true, data: p,
          actions: [{action: 'take', title: p.takeLabel || 'Take it'}]})));
    return;
  }
  const url = new URL(p.url || './', self.registration.scope).href;
  event.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then((wins) => {
    for (const w of wins) {
      if (w.url.split('#')[0] === url.split('#')[0] && 'focus' in w) {
        return w.focus().then((f) => (f && f.navigate ? f.navigate(url) : f));
      }
    }
    return self.clients.openWindow(url);
  }));
});

// The push service renewed the subscription : give the new one to the server.
self.addEventListener('pushsubscriptionchange', (event) => {
  const sub = new URL(self.location.href).searchParams.get('sub');
  const old = event.oldSubscription;
  if (!sub || !old || !old.options) return;
  event.waitUntil(self.registration.pushManager.subscribe(old.options).then((s) => {
    const j = s.toJSON();
    return post(sub, {endpoint: j.endpoint, p256dh: j.keys.p256dh, auth: j.keys.auth, device: 'renewed', replaces: old.endpoint}, true);
  }).catch(() => {}));
});
