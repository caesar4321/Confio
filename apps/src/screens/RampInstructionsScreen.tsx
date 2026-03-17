import React, { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Clipboard,
  Linking,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import QRCode from 'react-native-qrcode-svg';
import { RouteProp, useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';

import { MainStackParamList } from '../types/navigation';
import { GET_RAMP_ORDER_STATUS } from '../apollo/queries';
import { RampActionBar } from '../components/ramps/RampActionBar';
import { RampCard } from '../components/ramps/RampCard';
import { RampHero } from '../components/ramps/RampHero';
import { RampReveal } from '../components/ramps/RampReveal';
import { formatRampMoney } from '../hooks/useRampQuoteFlow';
import { buildRampInstructionView } from '../utils/rampInstructions';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'RampInstructions'>;
type RouteProps = RouteProp<MainStackParamList, 'RampInstructions'>;

const colors = {
  dark: '#111827',
  textPrimary: '#1f2937',
  textMuted: '#6b7280',
  border: '#e5e7eb',
  background: '#f0fdf4',
  surface: '#ffffff',
  primary: '#059669',
  primaryDark: '#047857',
  accent: '#3b82f6',
  accentLight: '#dbeafe',
  heroFrom: '#059669',
  heroTo: '#34d399',
};

const cleanDisplay = (text?: string | null): string => {
  if (!text) return '';
  return text.replace(/->/g, ' ').replace(/\u2192/g, ' ').replace(/\s{2,}/g, ' ').trim();
};

const parsePaymentDetails = (value?: Record<string, unknown> | string | null): Record<string, unknown> | null => {
  if (!value) return null;
  if (typeof value === 'string') {
    try {
      return JSON.parse(value);
    } catch {
      return null;
    }
  }
  return value;
};

const getStatusMeta = (
  direction: 'ON_RAMP' | 'OFF_RAMP',
  statusCode: string,
  loading: boolean,
) => {
  switch (statusCode) {
    case 'WAITING':
      return {
        label: direction === 'ON_RAMP' ? 'Esperando tu pago' : 'Esperando confirmación',
        detailLabel: direction === 'ON_RAMP' ? 'En espera de pago' : 'Pendiente de confirmación',
        tone: 'neutral' as const,
      };
    case 'PENDING':
      return { label: 'Pendiente', detailLabel: 'Pendiente', tone: 'neutral' as const };
    case 'EXECUTING':
    case 'IN_PROGRESS':
      return {
        label: direction === 'ON_RAMP' ? 'Procesando tu compra' : 'Procesando tu retiro',
        detailLabel: 'En proceso',
        tone: 'info' as const,
      };
    case 'DELIVERED':
      return {
        label: direction === 'ON_RAMP' ? 'Compra completada' : 'Retiro completado',
        detailLabel: 'Completado',
        tone: 'success' as const,
      };
    case 'REJECTED':
    case 'INVALID_WITHDRAWALS_DETAILS':
      return {
        label: direction === 'ON_RAMP' ? 'Compra rechazada' : 'Retiro rechazado',
        detailLabel: statusCode === 'INVALID_WITHDRAWALS_DETAILS' ? 'Datos inválidos' : 'Rechazado',
        tone: 'error' as const,
      };
    default:
      return {
        label: loading ? 'Actualizando estado...' : 'Estado de la orden',
        detailLabel: loading ? 'Actualizando...' : 'Sin estado',
        tone: 'neutral' as const,
      };
  }
};

export const RampInstructionsScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { width } = useWindowDimensions();
  const route = useRoute<RouteProps>();
  const {
    direction,
    orderId,
    countryCode,
    paymentMethodCode,
    paymentMethodDisplay,
    amountOut,
    fiatCurrency,
    destinationSummary,
    nextActionUrl,
    paymentDetails,
  } = route.params;
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);

  const { data, loading, refetch, networkStatus } = useQuery(GET_RAMP_ORDER_STATUS, {
    variables: {
      orderId,
      countryCode,
    },
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
    pollInterval: 10000,
  });
  const isRefreshing = networkStatus === 4;

  const orderStatus = data?.rampOrderStatus;
  const initialPaymentDetails = parsePaymentDetails(paymentDetails);
  const polledPaymentDetails = parsePaymentDetails(orderStatus?.success ? orderStatus.paymentDetails : null);
  const livePaymentDetails = {
    ...(initialPaymentDetails || {}),
    ...(polledPaymentDetails || {}),
  };
  const liveActionUrl = orderStatus?.success ? (orderStatus.nextActionUrl || nextActionUrl) : nextActionUrl;
  const liveAmountOut = String((livePaymentDetails as Record<string, unknown>).amountOut || amountOut || '');

  const instructionView = useMemo(
    () =>
      buildRampInstructionView({
        direction,
        paymentMethodCode,
        paymentMethodDisplay,
        paymentDetails: livePaymentDetails,
        nextActionUrl: liveActionUrl,
      }),
    [direction, liveActionUrl, livePaymentDetails, paymentMethodCode, paymentMethodDisplay],
  );

  const statusCode = String(orderStatus?.status || '').toUpperCase();
  const statusDetails = orderStatus?.statusDetails || '';

  const statusMeta = useMemo(() => getStatusMeta(direction, statusCode, loading), [direction, loading, statusCode]);
  const isTerminalSuccess = statusCode === 'DELIVERED';
  const isTerminalError = statusCode === 'REJECTED' || statusCode === 'INVALID_WITHDRAWALS_DETAILS';
  const summaryLabel = direction === 'ON_RAMP' ? 'Recibirás aprox.' : 'Recibirás aprox.';
  const isCompact = width < 380;

  const copyInstructionValue = (label: string, value: string) => {
    Clipboard.setString(value);
    Alert.alert('Copiado', `${label} copiado.`);
  };

  const handleRefresh = async () => {
    setRefreshMessage('Actualizando estado...');
    try {
      const result = await refetch();
      const refreshedStatus = result?.data?.rampOrderStatus;
      if (refreshedStatus?.success) {
        const refreshedMeta = getStatusMeta(
          direction,
          String(refreshedStatus.status || '').toUpperCase(),
          false,
        );
        const label = refreshedStatus.statusDetails
          ? `Estado actualizado: ${refreshedStatus.statusDetails}.`
          : `Estado actualizado: ${refreshedMeta.detailLabel}.`;
        setRefreshMessage(label);
        return;
      }
      setRefreshMessage(refreshedStatus?.error || 'No pudimos actualizar el estado.');
    } catch (error: any) {
      setRefreshMessage(error?.message || 'No pudimos actualizar el estado.');
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.heroFrom} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <RampReveal delay={0}>
        <RampHero
          eyebrow={direction === 'ON_RAMP' ? 'Pago' : 'Retiro'}
          title={instructionView.title}
          subtitle={instructionView.subtitle}
          onBack={() => navigation.goBack()}
          compact={isCompact}
          fromColor={colors.heroFrom}
          toColor={colors.heroTo}
        />
        </RampReveal>

        <RampReveal delay={70}>
        <RampCard style={styles.card}>
          <Text style={styles.summaryEyebrow}>Seguimiento de la orden</Text>
          <View style={[styles.statusPill, styles[`statusPill_${statusMeta.tone}`]]}>
            <Text style={[styles.statusPillText, styles[`statusPillText_${statusMeta.tone}`]]}>{statusMeta.label}</Text>
          </View>
          <View style={styles.stackedRow}>
            <Text style={styles.label}>Orden</Text>
            <Text style={styles.orderValue}>{orderId}</Text>
          </View>
          {statusCode ? (
            <View style={styles.row}>
              <Text style={styles.label}>Estado</Text>
              <Text style={styles.value}>{statusMeta.detailLabel}</Text>
            </View>
          ) : null}
          {statusDetails ? (
            <View style={styles.row}>
              <Text style={styles.label}>Detalle</Text>
              <Text style={styles.value}>{statusDetails}</Text>
            </View>
          ) : null}
          <View style={styles.row}>
            <Text style={styles.label}>{direction === 'ON_RAMP' ? 'Medio de pago' : 'Forma de cobro'}</Text>
            <Text style={styles.value}>{paymentMethodDisplay || paymentMethodCode || '--'}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>{summaryLabel}</Text>
            <Text style={styles.valueHighlight}>
              {formatRampMoney(liveAmountOut, direction === 'ON_RAMP' ? 'cUSD' : fiatCurrency || '')}
            </Text>
          </View>
          {destinationSummary ? (
            <View style={styles.row}>
              <Text style={styles.label}>Destino</Text>
              <Text style={styles.value}>{destinationSummary}</Text>
            </View>
          ) : null}
        </RampCard>
        </RampReveal>

        <RampReveal delay={120}>
        <RampCard style={[styles.card, styles.variantCard, styles[`variantCard_${instructionView.variant}`]]}>
          {instructionView.sectionTitle ? (
            <Text style={styles.sectionTitle}>{instructionView.sectionTitle}</Text>
          ) : null}
          {instructionView.sectionBody ? (
            <Text style={styles.sectionBody}>{instructionView.sectionBody}</Text>
          ) : null}

          {instructionView.steps?.length ? (
            <View style={styles.stepsWrap}>
              {instructionView.steps.map((stepText, index) => (
                <View key={`${stepText}-${index}`} style={styles.stepRow}>
                  <View style={styles.stepDot}>
                    <Text style={styles.stepDotText}>{index + 1}</Text>
                  </View>
                  <Text style={styles.stepText}>{stepText}</Text>
                </View>
              ))}
            </View>
          ) : null}
        </RampCard>
        </RampReveal>

        <RampReveal delay={170}>
        <RampCard style={styles.card}>
          {instructionView.rows.length > 0 ? (
            <>
              {instructionView.rows.map((item, index) => (
                <View key={`${item.label}-${index}`} style={styles.instructionRow}>
                  <Text style={styles.instructionLabel}>{item.label}</Text>
                  <Text style={styles.instructionValue}>{cleanDisplay(item.value)}</Text>
                  <TouchableOpacity
                    style={styles.copyPillInline}
                    onPress={() => copyInstructionValue(item.label, cleanDisplay(item.value))}
                    activeOpacity={0.7}
                  >
                    <Icon name="copy" size={12} color={colors.accent} />
                    <Text style={styles.copyPillText}>Copiar</Text>
                  </TouchableOpacity>
                </View>
              ))}
            </>
          ) : null}

          {instructionView.qrValue ? (
            <View style={styles.qrWrap}>
              <QRCode value={instructionView.qrValue} size={190} />
              <TouchableOpacity
                style={styles.copyPill}
                onPress={() => copyInstructionValue('Código QR', instructionView.qrValue!)}
                activeOpacity={0.7}
              >
                <Icon name="copy" size={12} color={colors.accent} />
                <Text style={styles.copyPillText}>Copiar código</Text>
              </TouchableOpacity>
            </View>
          ) : null}

          {instructionView.note ? <Text style={styles.note}>{instructionView.note}</Text> : null}
        </RampCard>
        </RampReveal>

        {liveActionUrl && instructionView.allowExternalAction ? (
          <RampReveal delay={210}>
          <RampActionBar
            primaryLabel={instructionView.actionLabel || 'Abrir proveedor'}
            onPrimaryPress={() => {
              void Linking.openURL(liveActionUrl);
            }}
          />
          </RampReveal>
        ) : null}

        <RampReveal delay={240}>
        <TouchableOpacity style={[styles.refreshButton, isRefreshing && styles.refreshButtonDisabled]} onPress={handleRefresh} activeOpacity={0.7} disabled={isRefreshing}>
          {isRefreshing ? <ActivityIndicator size="small" color={colors.accent} /> : <Icon name="refresh-cw" size={14} color={colors.accent} />}
          <Text style={styles.refreshButtonText}>{isRefreshing ? 'Actualizando...' : 'Consultar estado'}</Text>
        </TouchableOpacity>
        </RampReveal>
        {refreshMessage ? <Text style={styles.refreshMessage}>{refreshMessage}</Text> : null}

        {isTerminalSuccess || isTerminalError ? (
          <RampReveal delay={270}>
          <RampCard style={styles.card}>
            <Text style={styles.sectionTitle}>{isTerminalSuccess ? 'Resultado final' : 'Qué puedes hacer ahora'}</Text>
            <Text style={styles.sectionBody}>
              {isTerminalSuccess
                ? direction === 'ON_RAMP'
                  ? 'La compra ya fue procesada. Puedes volver al inicio y revisar tu saldo.'
                  : 'El retiro ya fue procesado. Puedes volver al inicio y revisar tus movimientos.'
                : 'Revisa los datos mostrados arriba y, si hace falta, intenta de nuevo con otro método o vuelve a cargar tus datos.'}
            </Text>
          </RampCard>
          </RampReveal>
        ) : null}

        <RampReveal delay={300}>
        <TouchableOpacity
          style={styles.ghostButton}
          onPress={() => navigation.navigate('BottomTabs', { screen: 'Home' })}
          activeOpacity={0.7}
        >
          <Text style={styles.ghostButtonText}>Ir al inicio</Text>
        </TouchableOpacity>
        </RampReveal>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    paddingBottom: 60,
  },
  card: {
    gap: 12,
  },
  variantCard: {
    borderWidth: 1,
    borderColor: colors.border,
  },
  variantCard_bank_transfer: {
    backgroundColor: '#ecfdf5',
    borderColor: '#a7f3d0',
  },
  variantCard_redirect: {
    backgroundColor: '#eff6ff',
    borderColor: '#bfdbfe',
  },
  variantCard_qr: {
    backgroundColor: '#f5f3ff',
    borderColor: '#ddd6fe',
  },
  variantCard_payout_pending: {
    backgroundColor: '#fffbeb',
    borderColor: '#fde68a',
  },
  variantCard_generic: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 18,
    paddingVertical: 2,
  },
  stackedRow: {
    gap: 8,
  },
  summaryEyebrow: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    color: colors.primaryDark,
  },
  label: {
    flex: 0.92,
    fontSize: 14,
    color: colors.textMuted,
    lineHeight: 20,
  },
  value: {
    flex: 1.08,
    fontSize: 14,
    fontWeight: '700',
    color: colors.textPrimary,
    textAlign: 'right',
    lineHeight: 20,
  },
  valueHighlight: {
    flex: 1.08,
    fontSize: 16,
    fontWeight: '800',
    color: colors.primaryDark,
    textAlign: 'right',
    lineHeight: 22,
  },
  orderValue: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.textPrimary,
    flexWrap: 'wrap',
    lineHeight: 20,
  },
  statusPill: {
    alignSelf: 'flex-start',
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 6,
    marginBottom: 4,
  },
  statusPill_neutral: {
    backgroundColor: '#f3f4f6',
  },
  statusPill_info: {
    backgroundColor: '#dbeafe',
  },
  statusPill_success: {
    backgroundColor: '#d1fae5',
  },
  statusPill_error: {
    backgroundColor: '#fee2e2',
  },
  statusPillText: {
    fontSize: 12,
    fontWeight: '700',
  },
  statusPillText_neutral: {
    color: colors.textPrimary,
  },
  statusPillText_info: {
    color: colors.accent,
  },
  statusPillText_success: {
    color: colors.primaryDark,
  },
  statusPillText_error: {
    color: '#b91c1c',
  },
  instructionRow: {
    gap: 6,
    paddingBottom: 12,
    marginBottom: 2,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  sectionTitle: {
    fontSize: 17,
    fontWeight: '800',
    color: colors.textPrimary,
  },
  sectionBody: {
    fontSize: 14,
    lineHeight: 22,
    color: colors.textMuted,
  },
  stepsWrap: {
    gap: 12,
    marginTop: 6,
  },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  stepDot: {
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: 'rgba(5,150,105,0.12)',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 1,
  },
  stepDotText: {
    fontSize: 11,
    fontWeight: '800',
    color: colors.primaryDark,
  },
  stepText: {
    flex: 1,
    fontSize: 14,
    lineHeight: 20,
    color: colors.textPrimary,
  },
  instructionLabel: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.textMuted,
    letterSpacing: 0.2,
  },
  instructionValue: {
    fontSize: 15,
    lineHeight: 22,
    color: colors.textPrimary,
  },
  qrWrap: {
    alignItems: 'center',
    gap: 14,
    marginVertical: 10,
    paddingVertical: 10,
  },
  note: {
    fontSize: 13,
    lineHeight: 19,
    color: colors.accent,
  },
  copyPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: colors.accentLight,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  copyPillInline: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: colors.accentLight,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 6,
    marginTop: 6,
  },
  copyPillText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.accent,
  },
  refreshButton: {
    marginTop: 10,
    marginHorizontal: 22,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    borderRadius: 16,
    paddingVertical: 14,
    backgroundColor: colors.accentLight,
    borderWidth: 1,
    borderColor: '#bfdbfe',
  },
  refreshButtonDisabled: {
    opacity: 0.7,
  },
  refreshButtonText: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.accent,
  },
  refreshMessage: {
    marginTop: 10,
    marginHorizontal: 22,
    fontSize: 13,
    lineHeight: 18,
    color: colors.textMuted,
    textAlign: 'center',
  },
  ghostButton: {
    marginTop: 12,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 14,
    marginHorizontal: 22,
    borderRadius: 16,
    borderWidth: 1.5,
    borderColor: colors.border,
  },
  ghostButtonText: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.textPrimary,
  },
});

export default RampInstructionsScreen;
