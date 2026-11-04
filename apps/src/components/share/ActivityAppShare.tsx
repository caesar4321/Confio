// Two small buttons under "Compartir en Comunidad": the same investment, as
// the dark-green venue card, sent straight to WhatsApp or Instagram. The
// card is rendered off screen and captured on tap; Confío never posts it.

import React, { useEffect, useRef, useState } from 'react';
import { Alert, StyleSheet, View } from 'react-native';
import ViewShot from 'react-native-view-shot';

import { CryptoAssetMark } from '../CryptoAssetMark';
import { PerpMarketMark } from '../futures/PerpMarketMark';
import { TickerLogo } from '../TickerLogo';
import { cryptoCategoryOf, type ActivityShare } from '../ActivitySummary';
import { VenueShareCard } from './VenueShareCard';
import { ShareAppButtons, type ShareApp } from './ShareAppButtons';
import { activityCardContent, type ActivityCardContent } from '../../utils/activityShareCard';
import { tickerColor } from '../../utils/perpsPresentation';
import { useShareCardDelivery } from '../../hooks/useShareCardDelivery';

const CARD_WIDTH = 340;

export function InvestmentCard({ content, category }: { content: ActivityCardContent; category?: string | null }) {
  const mark = content.kind === 'perps'
    ? <PerpMarketMark ticker={content.ticker} size={44} />
    : content.kind === 'crypto'
      ? <CryptoAssetMark ticker={content.ticker} category={category ?? null} size={44} />
      : <TickerLogo ticker={content.ticker} color={tickerColor(content.ticker)} size={44} />;
  return (
    <VenueShareCard
      testID="investment-share-card"
      product={content.product}
      venue={content.venue}
      mark={mark}
      ticker={content.ticker}
      name={content.name}
      tag={content.tag}
      kindLabel={content.kindLabel}
      headline={content.headline}
      headlineValue={content.headlineValue}
      headlineIsText={content.headlineIsText}
      usdLine={content.usdLine}
      rows={content.rows}
    />
  );
}

/** Off screen at a fixed width, so every captured image looks the same. */
export function OffscreenCard({ shot, children }: { shot: React.RefObject<ViewShot | null>; children: React.ReactNode }) {
  return (
    <View style={styles.offscreen} pointerEvents="none" collapsable={false}>
      <ViewShot ref={shot} options={{ format: 'png', quality: 1 }}>{children}</ViewShot>
    </View>
  );
}

export function ActivityAppShare({ activity, reference, showAmount, disabled }: {
  activity: ActivityShare;
  /** The share sheet's movement key (group:reference), for the tap log. */
  reference?: string;
  showAmount: boolean;
  disabled?: boolean;
}) {
  const content = activityCardContent(activity, showAmount);
  const shot = useRef<ViewShot>(null);
  const [busy, setBusy] = useState<ShareApp | null>(null);
  const { deliver } = useShareCardDelivery('activity');
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  if (!content) return null;

  const go = async (app: ShareApp) => {
    if (busy) return;
    setBusy(app);
    try {
      await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
      const uri = await shot.current?.capture?.();
      if (!uri) throw new Error('capture');
      await deliver(app, uri, {
        lead: content.lead, product: content.kind, filename: `Confio_${content.ticker}`,
        ticker: content.ticker, reference, showAmount,
      });
    } catch {
      if (alive.current) Alert.alert('No pudimos compartir', 'Inténtalo de nuevo en un momento.');
    } finally {
      if (alive.current) setBusy(null);
    }
  };

  return (
    <View>
      <ShareAppButtons onPress={(app) => { void go(app); }} busy={busy} disabled={disabled}
        testIDPrefix="activity-app-share" />
      <OffscreenCard shot={shot}>
        <InvestmentCard content={content} category={cryptoCategoryOf(activity)} />
      </OffscreenCard>
    </View>
  );
}

const styles = StyleSheet.create({
  offscreen: { position: 'absolute', left: -10000, top: 0, width: CARD_WIDTH },
});
