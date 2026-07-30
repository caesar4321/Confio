// App-level feature kill-switches.
//
// CUSD_CONVERSION_UI_ENABLED — entry points for the in-app cUSD ↔ cUSD+
// conversion (ConvertAhorro / RetirarAhorro). Disabled 2026-07: the
// conversion leg rode Allbridge Core, which is sunsetting after the July
// exploit, and running the swap ourselves would expose Confío as a
// principal exchange dealer. The screens stay registered in MainNavigator
// so flipping this back on restores the flow; only the UI entry points
// are hidden. On/off ramps that hit the savings chain directly (bank,
// USDT-BSC receive/sell) are unaffected.
export const CUSD_CONVERSION_UI_ENABLED = false;
