// App-level feature kill-switches.
//
// CUSD_CONVERSION_UI_ENABLED — entry points for the in-app cUSD ↔ cUSD+
// conversion (ConvertSavings / WithdrawSavings). Disabled 2026-07: the
// conversion leg rode Allbridge Core, which is sunsetting after the July
// exploit, and running the swap ourselves would expose Confío as a
// principal exchange dealer. The screens stay registered in MainNavigator
// so flipping this back on restores the flow; only the UI entry points
// are hidden. On/off ramps that hit the savings chain directly (bank,
// USDT-BSC receive/sell) are unaffected.
export const CUSD_CONVERSION_UI_ENABLED = false;

// STOCKS_TRADING_UI_ENABLED — the Comprar/Vender entry points on the
// stocks surfaces (StockDetail CTAs + Buy/SellStock screens). OFF because
// the execution layer is still a happy-path stub (onConfirm fakes success;
// quotes are a hardcoded placeholder) and the Ondo GM delivery model is
// unresolved. The server's stocksEnabled flag only gates VISIBILITY of the
// stocks surfaces — it must be able to come back on (view-only: prices,
// charts, positions) without exposing a fake trade flow in builds like
// this one. Flip to true ONLY in a build where quotes and onConfirm are
// wired to the real backend.
export const STOCKS_TRADING_UI_ENABLED = false;
