import React, { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { Helmet } from 'react-helmet';
import '../Verification/Verification.css';

const APP_STORE = 'https://apps.apple.com/app/id6472662314';
const PLAY_STORE = 'https://play.google.com/store/apps/details?id=com.Confio.Confio';
const COUNTRIES = { AR: 'Argentina', US: 'United States', GB: 'United Kingdom' };
const TOKEN_RE = /^[A-Za-z0-9_-]{20,128}$/;

/**
 * confio.lat/review?country=AR&k=<token>: the store-review link
 * (users/review_access.py) for wherever a confio:// link is not tappable.
 * Where the app claims /review it opens before this page loads; otherwise
 * this page hands it to the app, or to the store when the app is missing.
 * Written in English: its readers are App Review and Play reviewers.
 */
const androidIntent = (query) => `intent://review?${query}#Intent;scheme=confio;package=com.Confio.Confio;`
  + `S.browser_fallback_url=${encodeURIComponent(PLAY_STORE)};end`;

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

const ReviewLinkPage = () => {
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  const country = (params.get('country') || '').toUpperCase();
  const token = params.get('k') || '';
  const valid = Boolean(COUNTRIES[country]) && TOKEN_RE.test(token);
  const query = valid ? `country=${country}&k=${encodeURIComponent(token)}` : '';
  const appLink = valid ? `confio://review?${query}` : '';
  const isAndroid = /Android/i.test(navigator.userAgent);
  const isIos = /iPhone|iPad|iPod/i.test(navigator.userAgent);

  const open = () => {
    if (!valid) return;
    if (isAndroid) window.location.href = androidIntent(query);
    else if (isIos) tryAppThenStore(appLink, APP_STORE);
    else window.location.href = appLink;
  };

  // iOS asks before leaving Safari. Android only on a tap: Chrome refuses an
  // intent with no gesture and follows its Play fallback, app installed or not.
  useEffect(() => {
    if (valid && isIos) open();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="verification-container">
      <Helmet>
        <title>Review access | Confío</title>
        <meta name="robots" content="noindex" />
        <meta name="referrer" content="no-referrer" />
        <meta name="theme-color" content="#10B981" />
      </Helmet>
      <div className="verification-card" style={{ textAlign: 'center' }}>
        {!valid ? (
          <>
            <h1>Incomplete link</h1>
            <p className="verification-message">Open the review link exactly as it appears in the review notes.</p>
          </>
        ) : (
          <>
            <h1>Review access: {COUNTRIES[country]}</h1>
            <p className="verification-message">
              This switches your own Confío account to the {COUNTRIES[country]} experience for 14 days.
            </p>
            <button type="button" onClick={open} style={primary}>Open in Confío</button>
            <ol style={{ textAlign: 'left', fontSize: '14px', color: '#374151', lineHeight: 1.6, marginTop: '24px' }}>
              <li>Install Confío and sign in with any Google or Apple account.</li>
              <li>Open this link again on the same device and tap Open in Confío.</li>
              <li>A "Modo revisión" confirmation names the country. If you open the link before
                signing in, it is applied right after sign-in.</li>
            </ol>
            <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', marginTop: '8px' }}>
              {!isAndroid && <a href={APP_STORE} style={store}>App Store</a>}
              {!isIos && <a href={PLAY_STORE} style={store}>Google Play</a>}
            </div>
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
  background: '#10B981', color: 'white', padding: '12px 20px', borderRadius: '12px', border: 'none',
  fontWeight: 600, fontSize: '16px', cursor: 'pointer', width: '100%', marginTop: '20px',
};
const store = { color: '#065F46', fontWeight: 600, fontSize: '14px' };

export default ReviewLinkPage;
