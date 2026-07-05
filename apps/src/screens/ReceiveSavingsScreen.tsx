// Recibir USDT (BEP-20) — the external-deposit rail for the savings chain
// (ORCHESTRATION.md §5, source 3): crypto-native users and no-Koywe
// countries onramp by sending USDT straight to their own BSC address.
// Without this rail they would be forced through USDC-Algorand and the
// thin Allbridge pool to acquire a token they already hold.
//
// Semantics: user.bsc is the savings-chain address, so what arrives HERE
// becomes savings (cUSD+) — minted by the user's own signature on next
// foreground (the auto-swap pattern; prompt ships with the vault).
//
// The BSC sibling of DepositScreen (Algorand). Simpler — EVM needs no
// asset opt-ins — but the wrong-network warning matters MORE: USDT exists
// on many chains and a TRC-20/ERC-20 send to this address is unrecoverable.

import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  StatusBar,
  Image,
  Linking,
  Share,
} from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import QRCode from 'react-native-qrcode-svg';
import { colors } from '../config/theme';
import { getEvmAddressForDisplay, evmAccountKey } from '../services/secureDeterministicWallet';
import { useAccountManager } from '../hooks/useAccountManager';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';

const STEPS = [
  {
    title: 'En tu exchange o billetera, elige enviar USDT',
    body: 'Binance, OKX, Bybit, Trust Wallet — donde tengas tus USDT.',
  },
  {
    title: 'Selecciona la red BNB Smart Chain (BEP-20)',
    body: 'Es el paso más importante. Otras redes no llegan a esta dirección.',
  },
  {
    title: 'Pega tu dirección y envía',
    body: 'Copia la dirección de arriba. Llega en 1–2 minutos.',
  },
  {
    title: 'Abre Confío y confirma',
    body: 'Lo recibido se vuelve tu ahorro (cUSD+) y empieza a generar rendimiento.',
  },
] as const;

export const ReceiveSavingsScreen = () => {
  const navigation = useNavigation();
  const [copied, setCopied] = useState(false);

  // Derived at sign-in alongside the Algorand key (registered server-side);
  // on cold starts the persisted address serves display. Resolved BY ACTIVE
  // ACCOUNT — each account's address is immutable, and the screen always
  // shows the active one. Real and user-controlled — never a placeholder.
  const { activeAccount } = useAccountManager();
  const [address, setAddress] = useState<string | null>(null);
  const [resolving, setResolving] = useState(true);
  useEffect(() => {
    if (!activeAccount) return;
    const key = evmAccountKey({
      accountType: (activeAccount.type === 'business' ? 'business' : 'personal'),
      accountIndex: activeAccount.index ?? 0,
      businessId: activeAccount.business?.id,
    });
    getEvmAddressForDisplay(key)
      .then((a) => {
        setAddress(a);
        // Self-heal server registration (idempotent, marker-gated): covers
        // devices whose sign-in predated the backend deploy.
        if (a) {
          import('../services/authService').then(({ ensureBscAddressRegistered }) =>
            ensureBscAddressRegistered(a),
          ).catch(() => {});
        }
      })
      .finally(() => setResolving(false));
  }, [activeAccount]);

  const onCopy = async () => {
    if (!address) return;
    await Clipboard.setString(address);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Sharing the address by WhatsApp IS the LATAM flow (DepositScreen parity).
  // The message carries the network warning — it will be read outside the app.
  const onShare = async () => {
    if (!address) return;
    try {
      await Share.share({
        title: 'Dirección de ahorro Confío',
        message:
          `Esta es mi dirección para recibir USDT en Confío:\n${address}\n\n` +
          'Importante: solo USDT por la red BNB Smart Chain (BEP-20).',
      });
    } catch {}
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerIconBtn}>
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Recibir USDT</Text>
          <View style={styles.headerIconBtn} />
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        {resolving ? null : address ? (
          <>
            {/* Address card: QR + copy — the DepositScreen grammar */}
            <View style={styles.qrCard}>
              <Text style={styles.qrCardTitle}>Tu dirección de ahorro</Text>
              <View style={styles.networkPill}>
                <Text style={styles.networkPillText}>Red: BNB Smart Chain (BEP-20)</Text>
              </View>
              <View style={styles.qrWrap}>
                <QRCode value={address} size={180} />
              </View>
              <Text style={styles.address}>{address}</Text>
              <View style={styles.btnRow}>
                <TouchableOpacity style={styles.copyBtn} onPress={onCopy} activeOpacity={0.85}>
                  <Icon name={copied ? 'check' : 'copy'} size={16} color="#fff" />
                  <Text style={styles.copyBtnText}>
                    {copied ? 'Copiada' : 'Copiar'}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.shareBtn} onPress={onShare} activeOpacity={0.85}>
                  <Icon name="share-2" size={16} color={colors.primaryDark} />
                  <Text style={styles.shareBtnText}>Compartir</Text>
                </TouchableOpacity>
              </View>
              <TouchableOpacity
                style={styles.scanLink}
                onPress={() => Linking.openURL(`https://bscscan.com/address/${address}`)}
              >
                <Text style={styles.scanLinkText}>Ver en BscScan</Text>
                <Icon name="external-link" size={12} color={colors.text.secondary} />
              </TouchableOpacity>
            </View>

            {/* THE warning. USDT lives on many networks; a wrong-network
                send to this address is permanent loss. */}
            <View style={styles.warnCard}>
              <Icon name="alert-triangle" size={18} color="#B45309" />
              <Text style={styles.warnText}>
                Envía únicamente <Text style={styles.warnStrong}>USDT</Text> por la red{' '}
                <Text style={styles.warnStrong}>BNB Smart Chain (BEP-20)</Text>. Enviar por
                otra red (TRC-20, ERC-20, Polygon…) o enviar otros tokens resultará en
                pérdida permanente de los fondos.
              </Text>
            </View>

            {/* What it becomes: the savings semantic, with the brand mark */}
            <View style={styles.becomesCard}>
              <Image source={cUSDPlusLogo} style={styles.becomesLogo} />
              <Text style={styles.becomesText}>
                Lo que recibas aquí se convierte en tu ahorro{' '}
                <Text style={styles.warnStrong}>(Confío Dollar+)</Text> y genera rendimiento
                diario. Confirmas la conversión al abrir la app.
              </Text>
            </View>

            <Text style={styles.sectionTitle}>Cómo enviar</Text>
            {STEPS.map((s, i) => (
              <View key={s.title} style={styles.stepRow}>
                <View style={styles.stepNum}>
                  <Text style={styles.stepNumText}>{i + 1}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.stepTitle}>{s.title}</Text>
                  <Text style={styles.stepBody}>{s.body}</Text>
                </View>
              </View>
            ))}
          </>
        ) : (
          // Cached wallet missing (session predates the EVM sibling):
          // honest state, never a wrong address.
          <View style={styles.warnCard}>
            <Icon name="refresh-ccw" size={18} color="#B45309" />
            <Text style={styles.warnText}>
              Tu dirección de ahorro se genera al iniciar sesión. Cierra sesión y vuelve a
              entrar para activarla.
            </Text>
          </View>
        )}
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },

  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.primary,
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 16,
  },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: '#fff' },

  scrollContent: { padding: 16, paddingBottom: 40 },

  qrCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 20,
    alignItems: 'center',
    marginBottom: 12,
  },
  networkPill: {
    backgroundColor: '#FEF3C7',
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 5,
    marginBottom: 14,
  },
  networkPillText: { fontSize: 12, fontWeight: '700', color: '#92400E' },
  qrWrap: { padding: 12, backgroundColor: '#fff', borderRadius: 12 },
  address: {
    fontSize: 12,
    color: colors.text.secondary,
    textAlign: 'center',
    marginTop: 12,
    paddingHorizontal: 8,
    fontFamily: 'monospace' as any,
  },
  qrCardTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text.primary,
    marginBottom: 12,
  },
  btnRow: { flexDirection: 'row', gap: 10, marginTop: 14 },
  shareBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderWidth: 1.5,
    borderColor: colors.primaryDark,
    borderRadius: 12,
    paddingHorizontal: 18,
    paddingVertical: 11,
  },
  shareBtnText: { color: colors.primaryDark, fontSize: 14, fontWeight: '700' },
  copyBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingHorizontal: 18,
    paddingVertical: 11,
  },
  copyBtnText: { color: '#fff', fontSize: 14, fontWeight: '700' },
  scanLink: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 12 },
  scanLinkText: { fontSize: 12, color: colors.text.secondary },

  warnCard: {
    flexDirection: 'row',
    gap: 10,
    backgroundColor: '#FEF3C7',
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  warnText: { flex: 1, fontSize: 13, color: '#92400E', lineHeight: 18 },
  warnStrong: { fontWeight: '800' },

  becomesCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 14,
    marginBottom: 16,
  },
  becomesLogo: { width: 30, height: 30, borderRadius: 15 },
  becomesText: { flex: 1, fontSize: 13, color: colors.text.secondary, lineHeight: 18 },

  sectionTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text.primary,
    marginBottom: 10,
  },
  stepRow: {
    flexDirection: 'row',
    gap: 12,
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 14,
    marginBottom: 8,
  },
  stepNum: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepNumText: { fontSize: 13, fontWeight: '800', color: colors.primaryDark },
  stepTitle: { fontSize: 14, fontWeight: '600', color: colors.text.primary },
  stepBody: { fontSize: 12, color: colors.text.secondary, marginTop: 2, lineHeight: 17 },
});
