// Detail view for one Ahorros e Inversiones movement (cUSD+ world).
//
// Reached by tapping any row in Movimientos — the hub preview and the full
// SavingsMovements list, both of which render MovementRow.
//
// This is deliberately NOT TransactionDetailScreen: that screen's conversion
// branch is hardcoded to the Algorand-era usdc_to_cusd / cusd_to_usdc shapes
// (USDC logos, "Conversión USDC → cUSD" titles) and has no cUSD+/USDT
// awareness at all, so a Recarga would render as the wrong currency. The
// cUSD+ ledger is its own small world — Recargar/Retirar plus the rails that
// settle in it — and gets its own honest detail.
//
// The row itself arrives via route params, so the screen paints instantly
// with no spinner. Only the chain fields (tx hash, source rail) come from a
// query, and it is deliberately ISOLATED from the hub's portfolio query: a
// server that predates these fields fails THIS query alone, leaving the
// savings hub intact and this screen merely hash-less.

import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  StatusBar,
  Linking,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import Clipboard from '@react-native-clipboard/clipboard';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { gql, useQuery } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { SavingsMovementType } from '../hooks/useSavingsPortfolio';
import { formatUsdDeltaAbs } from '../utils/savingsFormat';

// Isolated on purpose — see the header note. Never fold these fields into
// GET_AHORRO_PORTFOLIO.
const GET_MOVEMENT_CHAIN_DETAIL = gql`
  query SavingsMovementChainDetail($id: ID!) {
    cusdPlusMovement(id: $id) {
      id
      txHash
      sourceType
    }
  }
`;

const MOVEMENT_ICONS: Record<string, string> = {
  deposit: 'arrow-down-circle',
  withdraw: 'arrow-up-circle',
  send: 'send',
  receive: 'arrow-down-left',
  payment: 'shopping-bag',
  payroll: 'briefcase',
};

const MOVEMENT_LABELS: Record<SavingsMovementType, string> = {
  deposit: 'Recarga',
  withdraw: 'Retiro',
  send: 'Envío',
  receive: 'Recibido',
  payment: 'Pago',
  payroll: 'Nómina',
};

const formatFullDate = (iso: string) => {
  const d = new Date(iso);
  const date = d.toLocaleDateString('es', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
  const time = d.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
  return `${date} · ${time}`;
};

const truncateHash = (h: string) => `${h.slice(0, 10)}…${h.slice(-8)}`;

export const SavingsMovementDetailScreen = () => {
  const navigation = useNavigation();
  const route = useRoute<RouteProp<MainStackParamList, 'SavingsMovementDetail'>>();
  const { movement } = route.params;
  const [copied, setCopied] = useState(false);

  // errorPolicy 'all' + no error surfacing: an older server (or a row that
  // vanished) costs the hash block, never the screen.
  const { data } = useQuery(GET_MOVEMENT_CHAIN_DETAIL, {
    variables: { id: movement.id },
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
  });
  const chain = data?.cusdPlusMovement;
  const txHash: string = chain?.txHash || '';
  // Scanner-written rows have no source record: money that arrived from
  // outside Confío rather than through one of our rails.
  const isExternalDeposit = Boolean(chain) && !chain.sourceType;

  const isIn = movement.amountUsd >= 0;
  const signedAmount = `${isIn ? '+' : '−'}${formatUsdDeltaAbs(movement.amountUsd) ?? '$0.00'}`;

  const onCopyHash = () => {
    Clipboard.setString(txHash);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        <View style={styles.header}>
          <TouchableOpacity
            onPress={() => navigation.goBack()}
            style={styles.headerIconBtn}
            accessibilityRole="button"
            accessibilityLabel="Volver"
          >
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Detalle</Text>
          <View style={styles.headerIconBtn} />
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.heroCard}>
          <View style={styles.heroIcon}>
            <Icon
              name={MOVEMENT_ICONS[movement.type] || 'circle'}
              size={26}
              color={colors.primaryDark}
            />
          </View>
          <Text style={styles.heroTitle}>{movement.title}</Text>
          <Text style={[styles.heroAmount, !isIn && styles.heroAmountOut]}>
            {signedAmount}
          </Text>
          <View style={styles.statusPill}>
            <Icon name="check-circle" size={13} color={colors.primaryDark} />
            <Text style={styles.statusPillText}>Confirmado</Text>
          </View>
        </View>

        <View style={styles.card}>
          <DetailRow label="Tipo" value={MOVEMENT_LABELS[movement.type] || 'Movimiento'} />
          <DetailRow label="Fecha" value={formatFullDate(movement.createdAt)} topBorder />
          <DetailRow label="Red" value="BNB Smart Chain (BEP-20)" topBorder />
        </View>

        {isExternalDeposit && (
          <View style={styles.noteCard}>
            <Icon name="info" size={16} color={colors.text.secondary} />
            <Text style={styles.noteText}>
              Este depósito llegó desde fuera de Confío, directamente a tu dirección
              en la red.
            </Text>
          </View>
        )}

        {Boolean(txHash) && (
          <View style={styles.card}>
            <Text style={styles.hashLabel}>Comprobante en la red</Text>
            <Text style={styles.hashValue}>{truncateHash(txHash)}</Text>
            <View style={styles.hashBtnRow}>
              <TouchableOpacity
                style={styles.copyBtn}
                onPress={onCopyHash}
                activeOpacity={0.85}
                accessibilityRole="button"
                accessibilityLabel="Copiar el identificador de la transacción"
              >
                <Icon name={copied ? 'check' : 'copy'} size={15} color={colors.primaryDark} />
                <Text style={styles.copyBtnText}>{copied ? 'Copiado' : 'Copiar'}</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.scanBtn}
                onPress={() => Linking.openURL(`https://bscscan.com/tx/${txHash}`)}
                activeOpacity={0.85}
                accessibilityRole="button"
                accessibilityLabel="Ver la transacción en BscScan"
              >
                <Text style={styles.scanBtnText}>Ver en BscScan</Text>
                <Icon name="external-link" size={13} color={colors.text.secondary} />
              </TouchableOpacity>
            </View>
          </View>
        )}
      </ScrollView>
    </View>
  );
};

const DetailRow = ({
  label,
  value,
  topBorder,
}: {
  label: string;
  value: string;
  topBorder?: boolean;
}) => (
  <View style={[styles.detailRow, topBorder && styles.detailRowBorder]}>
    <Text style={styles.detailLabel}>{label}</Text>
    <Text style={styles.detailValue}>{value}</Text>
  </View>
);

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

  content: { padding: 16, paddingBottom: 40, gap: 12 },

  heroCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
    gap: 8,
  },
  heroIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 4,
  },
  heroTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.text.secondary,
    textAlign: 'center',
  },
  heroAmount: { fontSize: 32, fontWeight: '700', color: colors.primaryDark },
  heroAmountOut: { color: colors.text.primary },
  statusPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: colors.primaryLight,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 12,
    marginTop: 4,
  },
  statusPillText: { fontSize: 12, fontWeight: '600', color: colors.primaryDark },

  card: { backgroundColor: '#fff', borderRadius: 16, padding: 16 },

  detailRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    paddingVertical: 11,
  },
  detailRowBorder: { borderTopWidth: 1, borderTopColor: colors.borderLight },
  detailLabel: { fontSize: 13, color: colors.text.secondary },
  detailValue: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.primary,
    flexShrink: 1,
    textAlign: 'right',
  },

  noteCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    backgroundColor: colors.neutralDark,
    borderRadius: 16,
    padding: 14,
  },
  noteText: {
    flex: 1,
    fontSize: 12,
    color: colors.text.secondary,
    lineHeight: 17,
  },

  hashLabel: { fontSize: 13, color: colors.text.secondary, marginBottom: 6 },
  hashValue: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: 14,
  },
  hashBtnRow: { flexDirection: 'row', gap: 10 },
  copyBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: colors.primaryLight,
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 12,
  },
  copyBtnText: { fontSize: 13, fontWeight: '600', color: colors.primaryDark },
  scanBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
  scanBtnText: { fontSize: 13, fontWeight: '600', color: colors.text.secondary },
});
