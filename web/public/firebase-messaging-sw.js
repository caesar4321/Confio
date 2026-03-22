/* eslint-disable no-restricted-globals */
importScripts('https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.12.0/firebase-messaging-compat.js');

firebase.initializeApp({
  apiKey: 'AIzaSyD-6TIsDCMgW41OS9pp38A8_faap7B9fHw',
  authDomain: 'confio-abbda.firebaseapp.com',
  projectId: 'confio-abbda',
  storageBucket: 'confio-abbda.firebasestorage.app',
  messagingSenderId: '730050241347',
  appId: '1:730050241347:web:d591bc62f114b7959f45f6',
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
  const title = payload.notification?.title || 'Confío Portal';
  const options = {
    body: payload.notification?.body || '',
    icon: '/images/$CONFIO.png',
    badge: '/images/$CONFIO.png',
    tag: payload.data?.tag || 'portal-notification',
    data: payload.data || {},
  };
  self.registration.showNotification(title, options);
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes('/portal') && 'focus' in client) {
          return client.focus();
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow('/portal');
      }
    })
  );
});
