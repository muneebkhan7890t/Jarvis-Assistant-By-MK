'use strict';
// No caching or credentials: all private data remains behind signed requests.
self.addEventListener('push', event => {
  event.waitUntil(self.registration.showNotification('MARK LIV', {
    body: 'A task result is ready. Open your private inbox.',
    tag: 'mark-liv-results', data: {url: '/remote#notifications'}
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil((async () => {
    const url = new URL('/remote#notifications', self.location.origin).href;
    const windows = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
    for (const client of windows) {
      if (new URL(client.url).pathname === '/remote') {
        await client.navigate(url);
        return client.focus();
      }
    }
    return self.clients.openWindow(url);
  })());
});
