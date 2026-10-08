// Paid-offer probes (Confío IA+, Cuenta inteligente): which doors this person
// sees, the server price and their waitlist state. Waitlists only: nothing is
// sold, charged or unlocked. Its own query (errorPolicy 'ignore'), so a server
// without these fields can never break the screens that ask for them.
import { gql, useQuery } from '@apollo/client';
import { AnalyticsService } from './analyticsService';

export type PaidOfferKey = 'ia_plus' | 'smart_account';
export type PaidOfferDoor = 'billeteras' | 'assistant_header' | 'chip';

export type PaidOffer = {
  product: PaidOfferKey;
  available: boolean;
  rowVisible: boolean;
  monthlyPriceUsd: string | null;
  onWaitlist: boolean;
  waitlistedAt: string | null;
  wouldPay: 'yes' | 'no' | null;
  volumeRange: string | null;
};

export const GET_PAID_OFFERS = gql`
  query PaidOffers {
    paidOffers {
      product
      available
      rowVisible
      monthlyPriceUsd
      onWaitlist
      waitlistedAt
      wouldPay
      volumeRange
    }
  }
`;

export const JOIN_PAID_OFFER_WAITLIST = gql`
  mutation JoinPaidOfferWaitlist($product: String!, $door: String!, $trigger: String) {
    joinPaidOfferWaitlist(product: $product, door: $door, trigger: $trigger) {
      success
      error
      waitlistedAt
      alreadyListed
    }
  }
`;

export const ANSWER_PAID_OFFER = gql`
  mutation AnswerPaidOffer($product: String!, $wouldPay: String, $volumeRange: String) {
    answerPaidOffer(product: $product, wouldPay: $wouldPay, volumeRange: $volumeRange) {
      success
      error
    }
  }
`;

export function usePaidOffers(): Partial<Record<PaidOfferKey, PaidOffer>> {
  const { data } = useQuery(GET_PAID_OFFERS, { fetchPolicy: 'cache-and-network', errorPolicy: 'ignore' });
  const out: Partial<Record<PaidOfferKey, PaidOffer>> = {};
  for (const offer of (data?.paidOffers ?? []) as PaidOffer[]) {
    out[offer.product] = offer;
  }
  return out;
}

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

export function logOfferStep(offer: PaidOfferKey, stage: 'detail_opened' | 'solo_miraba', door: string, trigger: string) {
  void AnalyticsService.logFunnelEvent('paid_offer_interest', { stage, offer, door, trigger }, { sourceType: offer });
}
