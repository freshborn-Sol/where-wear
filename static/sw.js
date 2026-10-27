// where:wear 직원 알림 — 잠금화면에도 뜨는 신고 접수 알림 (기본 알림음)
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('push', e => {
  let d = {}; try { d = e.data ? e.data.json() : {}; } catch (_) { d = { title: '새 신고', body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || 'where:wear 신고 접수', {
    body: d.body || '', tag: d.tag || 'ww', renotify: true, requireInteraction: true,
    icon: '/static/logo/icon-192.png?v=g2', badge: '/static/logo/icon-192.png?v=g2',
    vibrate: [200, 100, 200], data: { url: d.url || '/staff/reports' }
  }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/staff/reports';
  e.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    for (const c of list) if (c.url.includes('/staff')) { c.navigate(url); return c.focus(); }
    return clients.openWindow(url);
  }));
});
