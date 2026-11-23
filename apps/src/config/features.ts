// App-level feature kill-switches.
//
// DEX_TRADING_UI_ENABLED — every PancakeSwap (Oro y Bitcoin) and Hyperliquid
// (Futuros) surface: the Invertir cards, the seven trading screens, hooks,
// deep links and copy-a-play entry points. OFF in the iOS binary: Apple
// requires per-country licensing evidence for exchange services (guideline
// 3.1.5(iii)), and a dormant surface a server flag could wake after review
// is exactly what guideline 2.3.1 forbids. Compile-time on purpose — iOS
// never renders these surfaces nor sends their market or trading queries,
// so nothing can flash while a network answer is awaited, and turning iOS
// back on means shipping a new build through review. What a member already
// holds (crypto holdings, open positions) is still read so Home's total
// stays whole; it shows as "otros". The server keeps its own per-request iOS
// gates (PERPS_IOS_ENABLED / CRYPTO_IOS_ENABLED) for older builds, direct
// API calls and server-written content (assistant, feeds, notices). The
// Emergency Exit path stays on: money is never trapped.
import { Platform } from 'react-native';

export const DEX_TRADING_UI_ENABLED = Platform.OS !== 'ios';
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
// stocks surfaces (StockDetail CTAs + Buy/SellStock screens). The compiled
// capability is ON; the server's stocksTradingEnabled / stocksBuyEnabled
// fields remain the operational and jurisdiction-aware kill switches.
export const STOCKS_TRADING_UI_ENABLED = true;

// CRYPTO_TRADING_UI_ENABLED — the Comprar/Vender entry points for Bitcoin &
// gold (CryptoDetail CTAs + Buy/SellCrypto screens). Compiled ON like
// stocks; the server's cryptoCapabilities (enabled / tradingEnabled /
// buyEnabled) stay the operational and country-aware switches.
export const CRYPTO_TRADING_UI_ENABLED = true;

// CONVERSATION_HOME_ENABLED — the tab-less home
// (docs/designs/ai-assistant-first-redesign.md, section 7): Inicio is the
// assistant conversation, Pagar is the composer's primary button, and
// Invertir / Comunidad / Comprar / Perfil open from a drawer. ON (founder,
// 2026-11-22): the next build ships it. The five-tab navigator stays in the
// code for one release (rollback: set this to false). The assistant's map of
// this layout and the "a step rests on a tap" rule live on the server and
// are picked by the X-Confio-Home header this build sends: the server side
// (assistant/, users/funnel_schema.py) must be deployed before the build.
export const CONVERSATION_HOME_ENABLED = true;
