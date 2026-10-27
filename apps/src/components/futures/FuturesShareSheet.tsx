// The member shares their own Futuros position or realized result to their
// own social networks: an image card, through the phone's share sheet, or
// saved to their gallery (Android's share sheet has no "save" target).
// Confío never posts it. Percent by default; dollars only if they choose.

import React, { useEffect, useRef, useState } from 'react';
import { Alert, Image, Modal, Pressable, StyleSheet, Switch, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Share from 'react-native-share';
import ViewShot from 'react-native-view-shot';
import Svg, { Defs, LinearGradient as SvgLinearGradient, Rect, Stop } from 'react-native-svg';

import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import { PerpMarketMark } from './PerpMarketMark';
import ConfioLogo from '../../assets/png/CONFIO.png';
import HyperliquidLogo from '../../assets/png/Hyperliquid.png';
import type { PerpPosition } from '../../services/perps';
import { saveImageToGallery } from '../../utils/saveImageToGallery';
import { futuresShareContent, FuturesShareContent, FuturesShareKind } from '../../utils/futuresShare';

const UP = '#6EE7B7';
const DOWN = '#FCA5A5';

export function FuturesShareCard({ content }: { content: FuturesShareContent }) {
  const tone = content.headlineValue > 0 ? UP : content.headlineValue < 0 ? DOWN : '#E5E7EB';
  return (
    <View style={card.wrap} testID="futures-share-card">
      <Svg style={StyleSheet.absoluteFill} pointerEvents="none">
        <Defs>
          <SvgLinearGradient id="futuresShare" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor="#047857" />
            <Stop offset="1" stopColor="#064E3B" />
          </SvgLinearGradient>
        </Defs>
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#futuresShare)" />
      </Svg>
      <View style={card.brandRow}>
        <Image source={ConfioLogo} style={card.logo} />
        <Text style={card.brand}>Confío</Text>
        <Text style={card.product}>· Futuros</Text>
      </View>
      <View style={card.assetRow}>
        <PerpMarketMark ticker={content.ticker} size={44} />
        <View style={{ flex: 1 }}>
          <Text style={card.ticker}>{content.ticker}</Text>
          <Text style={card.name} numberOfLines={1}>{content.name}</Text>
        </View>
        <View style={card.sideTag}>
          <Icon name={content.side === 'long' ? 'trending-up' : 'trending-down'} size={14} color="#ECFDF5" />
          <Text style={card.sideText}>{content.sideLine}</Text>
        </View>
      </View>
      <Text style={card.kind}>{content.kind === 'position' ? 'Posición abierta' : content.liquidated ? 'Liquidada' : 'Posición cerrada'}</Text>
      <Text style={[card.headline, { color: tone }]}>{content.headline}</Text>
      {content.usdLine ? <Text style={[card.usd, { color: tone }]}>{content.usdLine}</Text> : null}
      <Text style={card.caption}>{content.caption}</Text>
      <View style={card.rows}>
        {content.rows.map((row) => (
          <View key={row.label} style={card.row}>
            <Text style={card.rowLabel}>{row.label}</Text>
            <Text style={card.rowValue}>{row.value}</Text>
          </View>
        ))}
      </View>
      <View style={card.footer}>
        <View style={card.venue}>
          <Text style={card.footText}>Se opera en</Text>
          <Image source={HyperliquidLogo} style={card.venueLogo} />
          <Text style={card.footBrand}>Hyperliquid</Text>
        </View>
        <Text style={card.footText}>confio.lat</Text>
      </View>
      <Text style={card.risk}>
        Hyperliquid es un exchange descentralizado de terceros, independiente de Confío. Con apalancamiento
        puedes perder todo tu margen. No es asesoría financiera.
      </Text>
    </View>
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
  const [showUsd, setShowUsd] = useState(false);
  // What is in progress: the card stays frozen and both buttons wait.
  const [busy, setBusy] = useState<'share' | 'save' | null>(null);
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

  const share = async () => {
    const captured = await capture('share');
    if (!captured) return;
    const { uri, snapshot, alive } = captured;
    try {
      await Share.open({
        title: kind === 'position' ? `Mi posición en ${snapshot.ticker}` : `Mi resultado en ${snapshot.ticker}`,
        message: snapshot.message,
        url: uri,
        type: 'image/png',
        filename: `Confio_${snapshot.ticker}`,
        failOnCancel: false,
      });
    } catch (e: any) {
      // Dismissing the sheet is not an error; anything else is said.
      const text = String(e?.message ?? e ?? '');
      if (alive() && !/cancel|dismiss/i.test(text)) {
        Alert.alert('No pudimos compartir', 'Inténtalo de nuevo o elige otra app.');
      }
    } finally {
      if (alive()) {
        setBusy(null);
        setFrozen(null);
      }
    }
  };

  const save = async () => {
    const captured = await capture('save');
    if (!captured) return;
    const { uri, snapshot, alive } = captured;
    try {
      await saveImageToGallery(uri);
      if (alive()) setSavedCard(JSON.stringify(snapshot));
    } catch {
      if (alive()) Alert.alert('No pudimos guardar la imagen', 'Revisa el permiso de la galería e inténtalo de nuevo.');
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
            onPress={() => { void save(); }} testID="futures-share-save" accessibilityRole="button">
            <Icon name={saved ? 'check' : 'download'} size={18} color={colors.primaryDark} />
            <Text style={sheet.secondaryText}>{busy === 'save' ? 'Guardando…' : saved ? 'Guardada' : 'Guardar imagen'}</Text>
          </Pressable>
          <Pressable style={[sheet.primary, (!content || sharing) && sheet.disabled]} disabled={!content || sharing}
            onPress={() => { void share(); }} testID="futures-share-go" accessibilityRole="button">
            <Icon name="share-2" size={18} color={colors.white} />
            <Text style={sheet.primaryText}>{busy === 'share' ? 'Preparando…' : 'Compartir'}</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const card = StyleSheet.create({
  wrap: { borderRadius: 20, overflow: 'hidden', padding: 20, backgroundColor: '#065F46' },
  brandRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  logo: { width: 22, height: 22, borderRadius: 11 },
  brand: { fontSize: 16, fontWeight: '800', color: '#FFFFFF' },
  product: { fontSize: 14, fontWeight: '600', color: '#A7F3D0' },
  assetRow: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 18 },
  ticker: { fontSize: 22, fontWeight: '800', color: '#FFFFFF' },
  name: { fontSize: 13, color: '#A7F3D0' },
  sideTag: { flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: 'rgba(255,255,255,0.14)', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 },
  sideText: { fontSize: 13, fontWeight: '700', color: '#ECFDF5' },
  kind: { fontSize: 13, color: '#A7F3D0', marginTop: 20 },
  headline: { fontSize: 46, fontWeight: '800', marginTop: 2 },
  usd: { fontSize: 20, fontWeight: '700' },
  caption: { fontSize: 13, color: '#D1FAE5', marginTop: 2 },
  rows: { marginTop: 16, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.15)', paddingTop: 10, gap: 6 },
  row: { flexDirection: 'row', justifyContent: 'space-between' },
  rowLabel: { fontSize: 13, color: '#A7F3D0' },
  rowValue: { fontSize: 13, fontWeight: '700', color: '#FFFFFF' },
  footer: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 18 },
  venue: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  venueLogo: { width: 14, height: 14, borderRadius: 7 },
  footText: { fontSize: 12, color: '#A7F3D0' },
  footBrand: { fontSize: 12, fontWeight: '700', color: '#FFFFFF' },
  risk: { fontSize: 10, color: '#6EE7B7', marginTop: 10 },
});

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
