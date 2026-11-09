import { gql, useQuery } from '@apollo/client';
import { formatDecimal } from '../utils/numberLocale';

/** Referral commission: half of the 0.9% Confío fee an invited friend pays,
 *  paid on-chain as cUSD (cusd_plus/fee_referral.py). A SEPARATE query on
 *  purpose: against an older server without the field it only means "no
 *  commission copy", never a broken invite screen. */
export const FEE_REFERRAL_SUMMARY = gql`
  query FeeReferralSummary {
    feeReferralSummary {
      enabled
      shareBps
      feeBps
      windowDays
      viewerVerified
      monthTotalUsd
      totalEarnedUsd
      friendCount
      waitingCount
      friends {
        referralId
        displayName
        status
        endsAt
        canRemind
      }
    }
  }
`;

export type FeeReferralFriendStatus =
  | 'earning'
  | 'needs_friend_verification'
  | 'needs_your_verification'
  | 'ended'
  | 'unavailable';

export interface FeeReferralFriend {
  referralId: string;
  canRemind: boolean;
  displayName: string;
  status: FeeReferralFriendStatus | string;
  endsAt?: string | null;
}

export interface FeeReferralSummary {
  enabled: boolean;
  shareBps: number;
  feeBps: number;
  windowDays: number;
  viewerVerified: boolean;
  monthTotalUsd: string;
  totalEarnedUsd: string;
  /** All invitations (the `friends` list is capped, newest first). */
  friendCount: number;
  waitingCount: number;
  friends: FeeReferralFriend[];
}

/** This member's commission summary, or null while loading / unavailable.
 *  The app build that has these screens ships only once the commission is
 *  live, so screens never gate on `enabled`: they render the program and
 *  use the summary only for numbers. */
export const useFeeReferralSummary = (skip = false): FeeReferralSummary | null => {
  const { data } = useQuery(FEE_REFERRAL_SUMMARY, {
    skip,
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'ignore',
  });
  return data?.feeReferralSummary ?? null;
};

/** The published terms, used until the server's summary arrives. */
export const DEFAULT_TERMS = { shareBps: 5000, feeBps: 90, windowDays: 365 };

/** "50%" and "0.45%" (locale decimal mark) from the server's numbers. */
export const commissionPercents = (summary: Pick<FeeReferralSummary, 'shareBps' | 'feeBps'>) => {
  const share = summary.shareBps / 100;
  const ofVolume = (summary.feeBps * summary.shareBps) / 1_000_000;
  const pct = (n: number) => {
    const rounded = Number(n.toFixed(4));
    const decimals = (String(rounded).split('.')[1] || '').length;
    return `${formatDecimal(rounded, { decimals, minDecimals: decimals })}%`;
  };
  return { sharePct: pct(share), volumePct: pct(ofVolume), feePct: pct(summary.feeBps / 100) };
};

/** The commission year in words: existing invitations count from launch. */
export const windowRule = (days: number): string =>
  `Dura ${windowLabel(days)} desde que tu amigo se une (si ya lo habías invitado antes, desde el lanzamiento)`;

/** "1 año" for 365 days, else "N días". */
export const windowLabel = (days: number): string =>
  days === 365 ? '1 año' : days % 365 === 0 ? `${days / 365} años` : `${days} días`;
