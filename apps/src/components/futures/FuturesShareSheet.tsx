// The member shares their own Futuros position or realized result to their
// own social networks: an image card, through the phone's share sheet, or
// saved to their gallery (Android's share sheet has no "save" target).
// Confío never posts it. Percent by default; dollars only if they choose.

import React, { useEffect, useRef, useState } from 'react';
import { Alert, Modal, Pressable, StyleSheet, Switch, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import ViewShot from 'react-native-view-shot';

import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import { PerpMarketMark } from './PerpMarketMark';
import { VenueShareCard } from '../share/VenueShareCard';
import { ShareAppButtons } from '../share/ShareAppButtons';
import { useShareCardDelivery, type ShareTarget } from '../../hooks/useShareCardDelivery';
import type { PerpPosition } from '../../services/perps';
import { futuresShareContent, FuturesShareContent, FuturesShareKind } from '../../utils/futuresShare';

export function FuturesShareCard({ content }: { content: FuturesShareContent }) {
  return (
    <VenueShareCard
      testID="futures-share-card"
      product="Futuros"
      venue="hyperliquid"
      mark={<PerpMarketMark ticker={content.ticker} size={44} />}
      ticker={content.ticker}
      name={content.name}
      tag={{ icon: content.side === 'long' ? 'trending-up' : 'trending-down', text: content.sideLine }}
      kindLabel={content.kind === 'position' ? 'Posición abierta' : content.liquidated ? 'Liquidada' : 'Posición cerrada'}
      headline={content.headline}
      headlineValue={content.headlineValue}
      usdLine={content.usdLine}
      caption={content.caption}
      rows={content.rows}
    />
  );
}

export function FuturesShareSheet({ visible, onClose, position, kind, liveMid = null, shownPx = null }: {
  visible: boolean;
  onClose: () => void;
  position: PerpPosition;
  kind: FuturesShareKind;
  liveMid?: number | null;
  shownPx?: number | null;
}) {
  const shot = useRef<ViewShot>(null);
  const { deliver } = useShareCardDelivery('futures');
  const [showUsd, setShowUsd] = useState(false);
  // What is in progress: the card stays frozen and both buttons wait.
  const [busy, setBusy] = useState<'share' | 'save' | 'whatsapp' | 'instagram' | null>(null);
  // While busy, the card and its message stay exactly as they were when the
  // button was pressed: a live price tick must not change the image after
  // the message was written (or the dollars toggle, which is locked too).
  const [frozen, setFrozen] = useState<FuturesShareContent | null>(null);
  const live = futuresShareContent(position, kind, showUsd, liveMid, shownPx);
  const content = frozen ?? live;
  const sharing = busy !== null;
  // "Guardada" speaks only for the card on screen being the one saved: a
  // price tick, the toggle or reopening the sheet makes it a new card.
  const [savedCard, setSavedCard] = useState<string | null>(null);
  const saved = content != null && savedCard === JSON.stringify(content);
  // Each capture's ticket. Closing the sheet or leaving the screen voids it:
  // nothing pending may open the share sheet, alert or mark a save later.
  const run = useRef(0);
  useEffect(() => {
    if (visible) return undefined;
    run.current += 1;
    setBusy(null);
    setFrozen(null);
    setSavedCard(null);
    return undefined;
  }, [visible]);
  useEffect(() => () => { run.current += 1; }, []);

  /** Freeze the card, render it once, and capture it; null on failure (said) or when voided. */
  const capture = async (what: 'share' | 'save') => {
    if (!content || busy) return null;
    const ticket = ++run.current;
    const alive = () => run.current === ticket;
    const snapshot = content;
    setFrozen(snapshot);
    setBusy(what);
    // Let the frozen card render before it is captured.
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
    let uri: string | undefined;
    try {
      uri = alive() ? await shot.current?.capture?.() : undefined;
    } catch {
      uri = undefined;
    }
    if (!alive()) return null;
    if (!uri) {
      setBusy(null);
      setFrozen(null);
      Alert.alert('No pudimos preparar la imagen', 'Inténtalo de nuevo en un momento.');
      return null;
    }
    return { uri, snapshot, alive };
  };

  /** One capture, sent to `target`; "Guardada" only for a save. */
  const send = async (target: ShareTarget) => {
    const captured = await capture(target === 'save' ? 'save' : 'share');
    if (!captured) return;
    const { uri, snapshot, alive } = captured;
    if (target === 'whatsapp' || target === 'instagram') setBusy(target);
    try {
      await deliver(target, uri, {
        lead: snapshot.lead,
        product: 'perps',
        filename: `Confio_${snapshot.ticker}`,
        title: kind === 'position' ? `Mi posición en ${snapshot.ticker}` : `Mi resultado en ${snapshot.ticker}`,
        ticker: snapshot.ticker,
        reference: String(position.id ?? ''),
        showAmount: Boolean(snapshot.usdLine),
      });
      if (target === 'save' && alive()) setSavedCard(JSON.stringify(snapshot));
    } catch {
      if (alive()) {
        if (target === 'save') {
          Alert.alert('No pudimos guardar la imagen', 'Revisa el permiso de la galería e inténtalo de nuevo.');
        } else {
          Alert.alert('No pudimos compartir', 'Inténtalo de nuevo o elige otra app.');
        }
      }
    } finally {
      if (alive()) {
        setBusy(null);
        setFrozen(null);
      }
    }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={sheet.backdrop} onPress={onClose} />
      <View style={sheet.body}>
        <Text style={sheet.title}>{kind === 'position' ? 'Compartir tu posición' : 'Compartir tu resultado'}</Text>
        <Text style={sheet.sub}>Tú decides dónde publicarla. Confío no publica nada por ti.</Text>
        {content ? (
          <ViewShot ref={shot} options={{ format: 'png', quality: 1 }}>
            <FuturesShareCard content={content} />
          </ViewShot>
        ) : (
          <Text style={sheet.sub}>Todavía no hay un resultado para mostrar.</Text>
        )}
        <View style={sheet.toggle}>
          <View style={{ flex: 1 }}>
            <Text style={sheet.toggleTitle}>Mostrar el monto en dólares</Text>
            <Text style={sheet.toggleSub}>Si lo apagas, solo se ve el porcentaje.</Text>
          </View>
          <Switch value={showUsd} onValueChange={setShowUsd} disabled={sharing} testID="futures-share-usd"
            trackColor={{ true: colors.primaryDark, false: '#D1D5DB' }} />
        </View>
        <View style={sheet.actions}>
          <Pressable style={[sheet.secondary, (!content || sharing) && sheet.disabled]} disabled={!content || sharing}
            onPress={() => { void send('save'); }} testID="futures-share-save" accessibilityRole="button">
            <Icon name={saved ? 'check' : 'download'} size={18} color={colors.primaryDark} />
            <Text style={sheet.secondaryText}>{busy === 'save' ? 'Guardando…' : saved ? 'Guardada' : 'Guardar imagen'}</Text>
          </Pressable>
          <Pressable style={[sheet.primary, (!content || sharing) && sheet.disabled]} disabled={!content || sharing}
            onPress={() => { void send('system'); }} testID="futures-share-go" accessibilityRole="button">
            <Icon name="share-2" size={18} color={colors.white} />
            <Text style={sheet.primaryText}>{busy === 'share' ? 'Preparando…' : 'Compartir'}</Text>
          </Pressable>
        </View>
        {content ? (
          <ShareAppButtons onPress={(app) => { void send(app); }} busy={busy} testIDPrefix="futures-share-app" />
        ) : null}
      </View>
    </Modal>
  );
}

const sheet = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.4)' },
  body: { backgroundColor: colors.white, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20, paddingBottom: 34, gap: 14 },
  title: { fontSize: 18, fontWeight: '800', color: colors.dark },
  sub: { fontSize: 13, color: colors.text.secondary, marginTop: -8 },
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
