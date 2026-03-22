import { initializeApp } from 'firebase/app';
import { getMessaging, getToken, deleteToken, onMessage } from 'firebase/messaging';

const firebaseConfig = {
  apiKey: process.env.REACT_APP_FIREBASE_API_KEY,
  authDomain: process.env.REACT_APP_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.REACT_APP_FIREBASE_PROJECT_ID,
  storageBucket: process.env.REACT_APP_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.REACT_APP_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.REACT_APP_FIREBASE_APP_ID,
};

const VAPID_KEY = process.env.REACT_APP_FIREBASE_VAPID_KEY;

let app = null;
let messaging = null;

function isFirebaseConfigured() {
  return Boolean(firebaseConfig.apiKey && firebaseConfig.projectId && firebaseConfig.messagingSenderId);
}

function getFirebaseApp() {
  if (!app && isFirebaseConfigured()) {
    app = initializeApp(firebaseConfig);
  }
  return app;
}

function getFirebaseMessaging() {
  if (!messaging) {
    const firebaseApp = getFirebaseApp();
    if (!firebaseApp) {
      return null;
    }
    try {
      messaging = getMessaging(firebaseApp);
    } catch (error) {
      console.warn('Firebase Messaging not supported in this browser:', error.message);
      return null;
    }
  }
  return messaging;
}

export async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) {
    return null;
  }
  try {
    const swUrl = `${process.env.PUBLIC_URL || ''}/firebase-messaging-sw.js`;

    const existingRegistration = await navigator.serviceWorker.getRegistration(swUrl);
    if (existingRegistration) {
      await existingRegistration.update();
      return existingRegistration;
    }

    const registration = await navigator.serviceWorker.register(swUrl);
    return registration;
  } catch (error) {
    console.warn('Service worker registration failed:', error);
    return null;
  }
}

export async function requestNotificationPermission() {
  if (!('Notification' in window)) {
    return 'unsupported';
  }
  if (Notification.permission === 'granted') {
    return 'granted';
  }
  if (Notification.permission === 'denied') {
    return 'denied';
  }
  const result = await Notification.requestPermission();
  return result;
}

export async function getFCMToken() {
  if (!isFirebaseConfigured() || !VAPID_KEY) {
    return null;
  }

  const msg = getFirebaseMessaging();
  if (!msg) {
    return null;
  }

  try {
    const registration = await registerServiceWorker();
    // Delete any stale token and get a fresh one
    try {
      await deleteToken(msg);
    } catch (_) {
      // No existing token to delete — that's fine
    }
    const token = await getToken(msg, {
      vapidKey: VAPID_KEY,
      serviceWorkerRegistration: registration || undefined,
    });
    return token;
  } catch (error) {
    console.warn('Failed to get FCM token:', error);
    return null;
  }
}

export function onForegroundMessage(callback) {
  const msg = getFirebaseMessaging();
  if (!msg) {
    return () => {};
  }
  return onMessage(msg, callback);
}

export { isFirebaseConfigured };
