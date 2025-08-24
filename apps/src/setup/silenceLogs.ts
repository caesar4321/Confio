// silenceLogs.ts
// Global console guard to reduce render/bridge overhead in development.
// Enables verbose logs only when explicitly requested.

(() => {
  try {
    // Preserve originals so we can toggle at runtime
    const original = {
      debug: console.debug.bind(console),
      info: console.info.bind(console),
      log: console.log.bind(console),
      warn: console.warn.bind(console),
      error: console.error.bind(console),
    };

    const noop = () => {};

    const setSilenced = (silenced: boolean) => {
      if (silenced) {
        console.debug = noop as any;
        console.info = noop as any;
        console.log = noop as any;
        (console as any).__silenced__ = true;
      } else {
        console.debug = original.debug as any;
        console.info = original.info as any;
        console.log = original.log as any;
        (console as any).__silenced__ = false;
      }
    };

    // Allow enabling verbose logs via env or a global runtime flag
    const env = (typeof process !== 'undefined' ? (process as any).env : undefined) || {};
    const verboseEnv = String(env.EXPO_PUBLIC_VERBOSE_LOGS || env.VERBOSE_LOGS || '')
      .toLowerCase();
    const verboseFlag = (global as any).__CONFIO_VERBOSE_LOGS__ === true;
    // Make verbose logs ON by default in development, can still be disabled via ConfioLogs.disable()
    const verbose = true || verboseFlag || verboseEnv === '1' || verboseEnv === 'true' || verboseEnv === 'yes';

    if (__DEV__) {
      setSilenced(!verbose);
      // Expose a simple runtime toggle for developers
      try {
        (global as any).ConfioLogs = {
          enable: () => {
            try { (global as any).__CONFIO_VERBOSE_LOGS__ = true; } catch {}
            setSilenced(false);
          },
          disable: () => {
            try { (global as any).__CONFIO_VERBOSE_LOGS__ = false; } catch {}
            setSilenced(true);
          },
          status: () => ({ silenced: (console as any).__silenced__ === true })
        };
      } catch {}
    }
  } catch (e) {
    // Do not break app if something goes wrong here
  }
})();
