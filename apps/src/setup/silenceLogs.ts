// silenceLogs.ts
// Global console guard to reduce render/bridge overhead in development.
// Enables verbose logs only when explicitly requested.

(() => {
  try {
    // Allow enabling verbose logs via env or a global runtime flag
    const env = (typeof process !== 'undefined' ? (process as any).env : undefined) || {};
    const verboseEnv = String(env.EXPO_PUBLIC_VERBOSE_LOGS || env.VERBOSE_LOGS || '')
      .toLowerCase();
    const verboseFlag = (global as any).__CONFIO_VERBOSE_LOGS__ === true;
    const verbose = verboseFlag || verboseEnv === '1' || verboseEnv === 'true' || verboseEnv === 'yes';

    if (__DEV__ && !verbose) {
      const noop = () => {};
      // Keep errors and warnings; silence info/debug/log
      // Avoid clobbering if already wrapped
      if ((console as any).__silenced__ !== true) {
        console.debug = noop as any;
        console.info = noop as any;
        console.log = noop as any;
        (console as any).__silenced__ = true;
      }
    }
  } catch (e) {
    // Do not break app if something goes wrong here
  }
})();

