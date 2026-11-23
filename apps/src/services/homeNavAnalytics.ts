// Which doors of Inicio people use (docs/designs/ai-assistant-first-redesign.md
// 7.8, 9): the tab bar, the two verbs, the wallet rows and the header in the
// five-tab app; the menu, the composer's main button and the floating one in
// the conversation home. Compared two weeks before and after the new home.
//
// One event per door per app run per day: the question is how many people
// use each door, not how many times, so a person tapping a tab all day costs
// one row and one request.
import { CONVERSATION_HOME_ENABLED } from '../config/features';
import { AnalyticsService } from './analyticsService';

export type HomeNavSurface = 'tabs' | 'home' | 'header' | 'drawer' | 'composer' | 'floating';

const seen = new Set<string>();

export function logHomeNav(surface: HomeNavSurface, target: string) {
  const key = `${new Date().toISOString().slice(0, 10)}:${surface}:${target}`;
  if (seen.has(key)) {
    return;
  }
  seen.add(key);
  void AnalyticsService.logFunnelEvent('home_nav_tapped', {
    surface,
    target,
    home: CONVERSATION_HOME_ENABLED ? 'conversation' : 'tabs',
  }).catch(() => undefined);
}

/** Tests only. */
export function resetHomeNavSeen() {
  seen.clear();
}
