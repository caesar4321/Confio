// Share a holding later, from its own page (like Futuros' "Compartir mi
// posición"): the venue card with the return since the purchase, the same
// figure the member's investor profile shows. Percent by default; dollars
// only when they turn them on. Confío never posts it.

import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, Modal, Pressable, StyleSheet, Switch, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import ViewShot from 'react-native-view-shot';
import { useQuery } from '@apollo/client';

import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import { GET_COMMUNITY_MEMBER_PORTFOLIO } from '../../apollo/queries';
import { useAuth } from '../../contexts/AuthContext';
import { useShareCardDelivery, type ShareTarget } from '../../hooks/useShareCardDelivery';
import { holdingCardContent, type ActivityCardContent } from '../../utils/activityShareCard';
import { InvestmentCard } from './ActivityAppShare';
import { ShareAppButtons } from './ShareAppButtons';

type OpenPosition = { ticker: string; symbol: string; name: string; valueUsd?: string | null; pnlUsd?: string | null; pnlPct?: string | null };

export function HoldingShareSheet({ visible, onClose, kind, ticker, name, category, valueUsd }: {
  visible: boolean;
  onClose: () => void;
  kind: 'stock' | 'crypto';
  ticker: string;
  name?: string | null;
  /** Bitcoin & gold mark: 'crypto' | 'metal'. */
  category?: string | null;
  /** The value the page shows, when the profile has no figure for it. */
  valueUsd?: number | null;
}) {
  const { userProfile } = useAuth() as any;
  const userId = userProfile?.id ? String(userProfile.id) : null;
  const { data, loading } = useQuery(GET_COMMUNITY_MEMBER_PORTFOLIO, {
    variables: { userId },
    skip: !visible || !userId,
    fetchPolicy: 'cache-and-network',
  });
  const positions: OpenPosition[] = data?.communityMemberPortfolio?.openPositions ?? [];
  const want = ticker.toUpperCase();
  const held = positions.find((p) => (p.ticker || '').toUpperCase() === want || (p.symbol || '').toUpperCase() === want);

  const [showUsd, setShowUsd] = useState(false);
  const [busy, setBusy] = useState<ShareTarget | null>(null);
  const [savedCard, setSavedCard] = useState<string | null>(null);
  const shot = useRef<ViewShot>(null);
  const { deliver } = useShareCardDelivery('holding');
  const run = useRef(0);
  useEffect(() => {
    if (visible) return undefined;
    run.current += 1;
    setBusy(null);
    setSavedCard(null);
    return undefined;
  }, [visible]);
  useEffect(() => () => { run.current += 1; }, []);

  const content: ActivityCardContent | null = holdingCardContent({
    kind, ticker, name: held?.name || name,
    pnlPct: held?.pnlPct, pnlUsd: held?.pnlUsd, valueUsd: held?.valueUsd ?? valueUsd,
  }, showUsd);
  const saved = content != null && savedCard === JSON.stringify(content);
  // Wait for the profile's figure: a card without it would say less than it can.
  const waiting = loading && !held;

  const send = async (target: ShareTarget) => {
    if (!content || busy) return;
    const ticket = ++run.current;
    const alive = () => run.current === ticket;
    const snapshot = content;
    setBusy(target);
    try {
      await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
      const uri = alive() ? await shot.current?.capture?.() : undefined;
      if (!alive()) return;
      if (!uri) throw new Error('capture');
      await deliver(target, uri, {
        lead: snapshot.lead, product: kind, filename: `Confio_${snapshot.ticker}`,
        title: `Mi inversión en ${snapshot.ticker}`, ticker: snapshot.ticker, showAmount: showUsd,
      });
      if (target === 'save' && alive()) setSavedCard(JSON.stringify(snapshot));
    } catch {
      if (alive()) {
        Alert.alert(target === 'save' ? 'No pudimos guardar la imagen' : 'No pudimos compartir',
          target === 'save' ? 'Revisa el permiso de la galería e inténtalo de nuevo.' : 'Inténtalo de nuevo o elige otra app.');
      }
    } finally {
      if (alive()) setBusy(null);
    }
  };

  const blocked = !content || waiting || busy !== null;
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={sheet.backdrop} onPress={onClose} />
      <View style={sheet.body} testID="holding-share-sheet">
        <Text style={sheet.title}>Compartir tu inversión</Text>
        <Text style={sheet.sub}>Tú decides dónde publicarla. Confío no publica nada por ti.</Text>
        {waiting ? (
          <View style={sheet.loading}><ActivityIndicator color={colors.primaryDark} /></View>
        ) : content ? (
          <ViewShot ref={shot} options={{ format: 'png', quality: 1 }}>
            <InvestmentCard content={content} category={category} />
          </ViewShot>
        ) : null}
        <View style={sheet.toggle}>
          <View style={{ flex: 1 }}>
            <Text style={sheet.toggleTitle}>Mostrar el monto en dólares</Text>
            <Text style={sheet.toggleSub}>Si lo apagas, solo se ve el porcentaje.</Text>
          </View>
          <Switch value={showUsd} onValueChange={setShowUsd} disabled={busy !== null} testID="holding-share-usd"
            trackColor={{ true: colors.primaryDark, false: '#D1D5DB' }} />
        </View>
        <View style={sheet.actions}>
          <Pressable style={[sheet.secondary, blocked && sheet.disabled]} disabled={blocked}
            onPress={() => { void send('save'); }} testID="holding-share-save" accessibilityRole="button">
            <Icon name={saved ? 'check' : 'download'} size={18} color={colors.primaryDark} />
            <Text style={sheet.secondaryText}>{busy === 'save' ? 'Guardando…' : saved ? 'Guardada' : 'Guardar imagen'}</Text>
          </Pressable>
          <Pressable style={[sheet.primary, blocked && sheet.disabled]} disabled={blocked}
            onPress={() => { void send('system'); }} testID="holding-share-go" accessibilityRole="button">
            <Icon name="share-2" size={18} color={colors.white} />
            <Text style={sheet.primaryText}>{busy === 'system' ? 'Preparando…' : 'Compartir'}</Text>
          </Pressable>
        </View>
        <ShareAppButtons onPress={(app) => { void send(app); }} busy={busy} disabled={!content || waiting}
          testIDPrefix="holding-share-app" />
      </View>
    </Modal>
  );
}

const sheet = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.4)' },
  body: { backgroundColor: colors.white, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20, paddingBottom: 34, gap: 14 },
  title: { fontSize: 18, fontWeight: '800', color: colors.dark },
  sub: { fontSize: 13, color: colors.text.secondary, marginTop: -8 },
  loading: { height: 260, alignItems: 'center', justifyContent: 'center' },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  toggleTitle: { fontSize: 14, fontWeight: '700', color: colors.dark },
  toggleSub: { fontSize: 12, color: colors.text.light },
  actions: { flexDirection: 'row', gap: 10 },
  primary: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: colors.primaryDark, borderRadius: 14, paddingVertical: 14 },
  secondary: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, borderWidth: 1.5, borderColor: colors.primaryDark, borderRadius: 14, paddingVertical: 14 },
  secondaryText: { fontSize: 16, fontWeight: '700', color: colors.primaryDark },
  primaryText: { fontSize: 16, fontWeight: '700', color: colors.white },
  disabled: { opacity: 0.5 },
});
