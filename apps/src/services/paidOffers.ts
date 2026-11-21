// Funnel events of the Cuenta inteligente doors and offer. The old waitlist
// probe (PaidOfferScreen) is gone from this build: every door opens the real
// offer, so only the event names and stages remain here.
import { AnalyticsService } from './analyticsService';

export type PaidOfferKey = 'ia_plus' | 'smart_account';
export type PaidOfferDoor = 'billeteras' | 'assistant_header' | 'chip';

function today() {
  return new Date().toISOString().slice(0, 10);
}

// One "door shown" per person, door and day (the server dedupes on the key).
export function logDoorShown(offer: PaidOfferKey, door: PaidOfferDoor) {
  void AnalyticsService.logFunnelEvent(
    'paid_offer_interest',
    { stage: 'door_shown', offer, door, dedupe_key: `${offer}:${door}:${today()}` },
    { sourceType: offer },
  );
}

export type SmartAccountClientStage = 'subscribe_opened' | 'subscribe_signed';

/** Client stages of the paid Cuenta inteligente funnel (event `smart_account_funnel`). */
export function logSmartAccountFunnel(stage: SmartAccountClientStage, plan?: string) {
  void AnalyticsService.logFunnelEvent(
    'smart_account_funnel',
    { stage, plan: plan === 'annual' || plan === 'monthly' ? plan : '' },
    { sourceType: 'smart_account' },
  );
}

export function logOfferStep(offer: PaidOfferKey, stage: 'detail_opened' | 'solo_miraba', door: string, trigger: string) {
  void AnalyticsService.logFunnelEvent('paid_offer_interest', { stage, offer, door, trigger }, { sourceType: offer });
}
