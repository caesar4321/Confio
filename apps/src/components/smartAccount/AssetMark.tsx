import React from 'react';
import { Image, StyleSheet } from 'react-native';
import { CryptoAssetMark } from '../CryptoAssetMark';
import { TickerLogo } from '../TickerLogo';
import cUSDLogo from '../../assets/png/cUSD.png';
import cUSDPlusLogo from '../../assets/png/cUSDPlus.png';
import CONFIOLogo from '../../assets/png/CONFIO.png';

/** The picture for an asset held in a Cuenta inteligente: the same marks the
 *  wallet rows and Invertir already use. Decorative (the row carries the label). */
export function AssetMark({ asset, size = 44 }: {
  asset: { key: string; kind?: string; symbol: string }; size?: number;
}) {
  const round = { width: size, height: size, borderRadius: size / 2 };
  if (asset.key === 'cusd_plus') {
    return <Image source={cUSDPlusLogo} style={[styles.image, round]} />;
  }
  if (asset.key === 'cusd') {
    return <Image source={cUSDLogo} style={[styles.image, round]} />;
  }
  if (asset.key === 'confio' || asset.kind === 'confio') {
    return <Image source={CONFIOLogo} style={[styles.image, round]} />;
  }
  if (asset.kind === 'crypto' || asset.key.startsWith('crypto:')) {
    const ticker = asset.symbol.toUpperCase();
    const isMetal = /^(XAU|PAXG)/.test(ticker);
    return <CryptoAssetMark ticker={ticker.replace(/B$/, '') === 'BTC' ? 'BTC' : ticker} category={isMetal ? 'metal' : 'coin'} size={size} />;
  }
  return <TickerLogo ticker={asset.symbol.replace(/on$/, '')} color="#334155" size={size} />;
}

const styles = StyleSheet.create({ image: { resizeMode: 'cover' } });
