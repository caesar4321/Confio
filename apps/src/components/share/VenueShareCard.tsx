// The dark-green image card a member posts to their own social networks
// (WhatsApp, Instagram, the phone's share sheet): one look for every
// investment, the product in the header and where it trades in the footer.
// Futuros trade on Hyperliquid, Oro y Bitcoin on PancakeSwap (both
// independent exchanges: "Se opera en"), Acciones come from Ondo Finance
// (our partner: "En alianza con").

import React, { useState } from 'react';
import { Image, LayoutChangeEvent, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, LinearGradient as SvgLinearGradient, Rect, Stop } from 'react-native-svg';

import { Text } from '../common/AppText';
import ConfioLogo from '../../assets/png/CONFIO.png';
import HyperliquidLogo from '../../assets/png/Hyperliquid.png';
import PancakeSwapLogo from '../../assets/png/PancakeSwap.png';
import OndoLogo from '../../assets/png/Ondo.png';

export type ShareVenue = 'hyperliquid' | 'pancakeswap' | 'ondo';

export const SHARE_VENUES: Record<ShareVenue, { lead: string; name: string; logo: number; risk: string }> = {
  hyperliquid: {
    lead: 'Se opera en',
    name: 'Hyperliquid',
    logo: HyperliquidLogo,
    risk: 'Hyperliquid es un exchange descentralizado de terceros, independiente de Confío. Con apalancamiento '
      + 'puedes perder todo tu margen. No es asesoría financiera.',
  },
  pancakeswap: {
    lead: 'Se opera en',
    name: 'PancakeSwap',
    logo: PancakeSwapLogo,
    risk: 'PancakeSwap es un exchange descentralizado de terceros, independiente de Confío. El precio puede '
      + 'subir o bajar. No es asesoría financiera.',
  },
  ondo: {
    lead: 'En alianza con',
    name: 'Ondo Finance',
    logo: OndoLogo,
    risk: 'Acciones tokenizadas a través de Ondo Finance. El valor puede subir o bajar y podrías perder dinero. '
      + 'No es asesoría financiera.',
  },
};

const UP = '#6EE7B7';
const DOWN = '#FCA5A5';
const FLAT = '#E5E7EB';
const TOP = '#047857';
const BOTTOM = '#064E3B';

export type VenueShareCardProps = {
  product: string; // "Futuros" | "Acciones" | "Oro y Bitcoin"
  venue: ShareVenue;
  mark: React.ReactNode;
  ticker: string;
  name?: string | null;
  tag?: { icon: string; text: string } | null;
  kindLabel?: string | null;
  headline: string;
  /** Sign of the headline figure; null for a non-figure headline (white). */
  headlineValue?: number | null;
  /** Smaller type for a word headline ("Compré TSLA") than for a figure. */
  headlineIsText?: boolean;
  usdLine?: string | null;
  caption?: string | null;
  rows?: { label: string; value: string }[];
  testID?: string;
};

export function VenueShareCard(props: VenueShareCardProps) {
  const { product, venue, mark, ticker, name, tag, kindLabel, headline, headlineValue = null, headlineIsText,
    usdLine, caption, rows = [], testID } = props;
  const v = SHARE_VENUES[venue];
  const tone = headlineValue == null ? FLAT : headlineValue > 0 ? UP : headlineValue < 0 ? DOWN : FLAT;
  // The gradient is drawn at the card's measured size. Sized only by
  // absoluteFill / "100%", Android captured it short of the card's right and
  // bottom edges, leaving a dark band where the plain background showed.
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const onLayout = (e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    if (!size || size.w !== width || size.h !== height) setSize({ w: width, h: height });
  };
  return (
    <View style={card.wrap} onLayout={onLayout} collapsable={false} testID={testID}>
      {size ? (
        <Svg width={size.w} height={size.h} style={card.gradient} pointerEvents="none">
          <Defs>
            <SvgLinearGradient id="venueShare" x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor={TOP} />
              <Stop offset="1" stopColor={BOTTOM} />
            </SvgLinearGradient>
          </Defs>
          <Rect x={0} y={0} width={size.w} height={size.h} fill="url(#venueShare)" />
        </Svg>
      ) : null}
      <View style={card.brandRow}>
        <Image source={ConfioLogo} style={card.logo} />
        <Text style={card.brand}>Confío</Text>
        <Text style={card.product}>· {product}</Text>
      </View>
      <View style={card.assetRow}>
        {mark}
        <View style={{ flex: 1 }}>
          <Text style={card.ticker}>{ticker}</Text>
          {name && name !== ticker ? <Text style={card.name} numberOfLines={1}>{name}</Text> : null}
        </View>
        {tag ? (
          <View style={card.sideTag}>
            <Icon name={tag.icon} size={14} color="#ECFDF5" />
            <Text style={card.sideText}>{tag.text}</Text>
          </View>
        ) : null}
      </View>
      {kindLabel ? <Text style={card.kind}>{kindLabel}</Text> : <View style={{ height: 18 }} />}
      <Text style={[headlineIsText ? card.headlineText : card.headline, { color: tone }]}>{headline}</Text>
      {usdLine ? <Text style={[card.usd, { color: tone }]}>{usdLine}</Text> : null}
      {caption ? <Text style={card.caption}>{caption}</Text> : null}
      {rows.length ? (
        <View style={card.rows}>
          {rows.map((row) => (
            <View key={row.label} style={card.row}>
              <Text style={card.rowLabel}>{row.label}</Text>
              <Text style={card.rowValue}>{row.value}</Text>
            </View>
          ))}
        </View>
      ) : null}
      <View style={[card.footer, !rows.length && card.footerRule]}>
        <View style={card.venue}>
          <Text style={card.footText}>{v.lead}</Text>
          <Image source={v.logo} style={card.venueLogo} />
          <Text style={card.footBrand}>{v.name}</Text>
        </View>
        <Text style={card.footText}>confio.lat</Text>
      </View>
      <Text style={card.risk}>{v.risk}</Text>
    </View>
  );
}

const card = StyleSheet.create({
  // The background matches the gradient's midpoint, so even the frame before
  // the first layout never shows a band of a different green.
  wrap: { borderRadius: 20, overflow: 'hidden', padding: 20, backgroundColor: '#055E48' },
  gradient: { position: 'absolute', left: 0, top: 0 },
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
  headlineText: { fontSize: 32, fontWeight: '800', marginTop: 2 },
  usd: { fontSize: 20, fontWeight: '700' },
  caption: { fontSize: 13, color: '#D1FAE5', marginTop: 2 },
  rows: { marginTop: 16, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.15)', paddingTop: 10, gap: 6 },
  row: { flexDirection: 'row', justifyContent: 'space-between' },
  rowLabel: { fontSize: 13, color: '#A7F3D0' },
  rowValue: { fontSize: 13, fontWeight: '700', color: '#FFFFFF' },
  footer: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 18 },
  footerRule: { borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.15)', paddingTop: 12 },
  venue: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  venueLogo: { width: 14, height: 14, borderRadius: 7 },
  footText: { fontSize: 12, color: '#A7F3D0' },
  footBrand: { fontSize: 12, fontWeight: '700', color: '#FFFFFF' },
  risk: { fontSize: 10, color: '#6EE7B7', marginTop: 10 },
});
