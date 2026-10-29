import React, { useEffect, useState } from 'react';
import { useLocation, useParams } from 'react-router-dom';
import { Helmet } from 'react-helmet';
import '../Verification/Verification.css';

const APP_STORE = 'https://apps.apple.com/app/id6472662314';
const PLAY_STORE = 'https://play.google.com/store/apps/details?id=com.Confio.Confio';
const REF_RE = /^[0-9a-fA-F-]{36}$/;
const KEY_RE = /^#[0-9a-fA-F]{64}$/;

/**
 * confio.lat/r/<ref>#<key>: a link send (apps/src/services/linkSend.ts) opened
 * where the app did not take it. The key after '#' never reaches this server
 * and the page shows no amount or sender: it only gets the person into the
 * app, or tells them how to bring the link along after installing.
 */
// Chrome opens Confío when installed, else Google Play: no guessing. The key
// rides as ?k= (an intent's data cannot hold a '#'); it goes to the app on
// this phone only, never to a server.
const androidIntent = (ref, key) => `intent://r/${ref}?k=${key}#Intent;scheme=confio;package=com.Confio.Confio;`
  + `S.browser_fallback_url=${encodeURIComponent(PLAY_STORE)};end`;

// iOS has no fallback in the link itself: try Confío, and if the page is
// still in front after a moment, it is not installed: the App Store.
const tryAppThenStore = (appLink, storeUrl) => {
  let left = false;
  const onHide = () => { left = true; };
  document.addEventListener('visibilitychange', onHide, { once: true });
  window.addEventListener('pagehide', onHide, { once: true });
  window.location.href = appLink;
  setTimeout(() => {
    if (!left && document.visibilityState === 'visible') window.location.href = storeUrl;
  }, 1600);
};

const LinkSendPage = () => {
  const { ref } = useParams();
  const { hash } = useLocation();
  const [copied, setCopied] = useState(false);
  const valid = REF_RE.test(ref || '') && KEY_RE.test(hash || '');
  const appLink = valid ? `confio://r/${ref}${hash}` : '';
  const isAndroid = /Android/i.test(navigator.userAgent);
  const isIos = /iPhone|iPad|iPod/i.test(navigator.userAgent);

  // On a phone this page is not a destination: open Confío, else the store.
  // (Once the installed build lists /r/, the https link opens the app before
  // this page ever loads.) Browsers allow a clipboard copy only after a tap,
  // so after installing, tapping the WhatsApp link again opens it in Confío.
  useEffect(() => {
    if (!appLink) return;
    if (isAndroid) {
      window.location.href = androidIntent(ref, (hash || '').slice(1));
    } else if (isIos) {
      tryAppThenStore(appLink, APP_STORE);
    }
  }, [appLink, isAndroid, isIos, ref, hash]);

  // The app link does nothing when Confío is not installed: copy the link
  // first (it survives the install: Recibir → «Tengo un link de envío»),
  // try the app, and if the page is still in front after a moment, go to
  // the store. The key never travels through the store's referrer.
  const openApp = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
    } catch {
      // Clipboard blocked: the steps below still say how to bring the link.
    }
    if (isAndroid) {
      window.location.href = androidIntent(ref, (hash || '').slice(1));
      return;
    }
    if (isIos) {
      tryAppThenStore(appLink, APP_STORE);
      return;
    }
    window.location.href = appLink;
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="verification-container">
      <Helmet>
        <title>Te enviaron dinero | Confío</title>
        <meta name="robots" content="noindex" />
        <meta name="theme-color" content="#10B981" />
      </Helmet>
      <div className="verification-card" style={{ textAlign: 'center' }}>
        <div className="security-banner-web">
          <i className="fas fa-lock"></i> confio.lat <i className="fas fa-check-circle"></i>
        </div>
        {!valid ? (
          <>
            <h1>Link incompleto</h1>
            <p className="verification-message">
              Abre el link tal como te llegó por WhatsApp, completo.
            </p>
          </>
        ) : (
          <>
            <h1>Te enviaron dólares por Confío</h1>
            <p className="verification-message">Ábrelo en la app de Confío para recibirlo.</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '20px' }}>
              <button type="button" onClick={openApp} style={{ ...primary, border: 'none', fontSize: '16px', cursor: 'pointer' }}>
                Abrir en Confío
              </button>
              <button type="button" onClick={copy} style={secondary}>
                {copied ? 'Link copiado' : 'Copiar link'}
              </button>
            </div>
            <ol style={{ textAlign: 'left', fontSize: '14px', color: '#374151', lineHeight: 1.6, marginTop: '24px' }}>
              <li>Descarga Confío y crea tu cuenta.</li>
              <li>Vuelve a WhatsApp y toca el link otra vez: se abre en Confío.</li>
              <li>O copia el link y, en Recibir, toca «Tengo un link de envío».</li>
            </ol>
            <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', marginTop: '8px' }}>
              {!isAndroid && <a href={APP_STORE} style={store}>App Store</a>}
              {!isIos && <a href={PLAY_STORE} style={store}>Google Play</a>}
            </div>
            <p style={{ fontSize: '12px', color: '#6B7280', marginTop: '20px' }}>
              Si no lo recibes en 7 días, el dinero vuelve a quien te lo envió.
            </p>
          </>
        )}
        <div className="verification-footer">
          <p>Confío &copy; {new Date().getFullYear()}</p>
        </div>
      </div>
    </div>
  );
};

const primary = {
  background: '#10B981', color: 'white', padding: '12px 20px', borderRadius: '12px',
  textDecoration: 'none', fontWeight: 600, display: 'block',
};
const secondary = {
  background: 'white', color: '#065F46', padding: '12px 20px', borderRadius: '12px',
  border: '1px solid #A7F3D0', fontWeight: 600, fontSize: '16px', cursor: 'pointer',
};
const store = { color: '#065F46', fontWeight: 600, fontSize: '14px' };

export default LinkSendPage;
