import React, { useMemo, useRef, useState } from 'react';
import { CameraRoll } from '@react-native-camera-roll/camera-roll';
import Clipboard from '@react-native-clipboard/clipboard';
import {
  ActivityIndicator,
  Alert,
  Image,
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
import Share from 'react-native-share';
import Icon from 'react-native-vector-icons/Feather';
import QRCode from 'react-native-qrcode-svg';
import ViewShot from 'react-native-view-shot';
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
import { colors } from '../config/theme';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'RampInstructions'>;
type RouteProps = RouteProp<MainStackParamList, 'RampInstructions'>;

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
        icon: 'clock' as const,
      };
    case 'PENDING':
    case 'PAYMENT_CREATED':
    case 'PAYMENT_RECEIVED':
      return {
        label: direction === 'ON_RAMP' ? 'Procesando tu compra' : 'Procesando tu retiro',
        detailLabel: 'En proceso',
        tone: 'info' as const,
        icon: 'loader' as const,
      };
    case 'EXECUTING':
    case 'IN_PROGRESS':
    case 'CRYPTO_TX_SENT':
    case 'FIAT_SENT':
      return {
        label: direction === 'ON_RAMP' ? 'Procesando tu compra' : 'Procesando tu retiro',
        detailLabel: 'En proceso',
        tone: 'info' as const,
        icon: 'loader' as const,
      };
    case 'DELIVERED':
      return {
        label: direction === 'ON_RAMP' ? 'Compra completada' : 'Retiro completado',
        detailLabel: 'Completado',
        tone: 'success' as const,
        icon: 'check-circle' as const,
      };
    case 'REJECTED':
    case 'INVALID_WITHDRAWALS_DETAILS':
      return {
        label: direction === 'ON_RAMP' ? 'Compra rechazada' : 'Retiro rechazado',
        detailLabel: statusCode === 'INVALID_WITHDRAWALS_DETAILS' ? 'Datos inválidos' : 'Rechazado',
        tone: 'error' as const,
        icon: 'x-circle' as const,
      };
    default:
      return {
        label: loading ? 'Actualizando estado...' : 'Estado de la orden',
        detailLabel: loading ? 'Actualizando...' : 'Sin estado',
        tone: 'neutral' as const,
        icon: 'activity' as const,
      };
  }
};

const statusPillIconColor: Record<string, string> = {
  neutral: '#374151',
  info: '#3b82f6',
  success: '#047857',
  error: '#b91c1c',
};

const QR_RENDER_MAX_BYTES = 2048;

const getQrPayloadByteLength = (value: string) => {
  try {
    if (typeof TextEncoder !== 'undefined') {
      return new TextEncoder().encode(value).length;
    }
  } catch {
    // Fall back to the raw string length when TextEncoder is unavailable.
  }
  return value.length;
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
  const qrCaptureRef = useRef<ViewShot | null>(null);

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
  const qrPayload = instructionView.qrValue?.trim() || undefined;
  const qrPayloadByteLength = useMemo(() => (qrPayload ? getQrPayloadByteLength(qrPayload) : 0), [qrPayload]);
  const canRenderQr = Boolean(qrPayload) && qrPayloadByteLength <= QR_RENDER_MAX_BYTES;
  const hasQrAsset = Boolean(instructionView.qrImageUri) || canRenderQr;
  const hasInstructionDetails =
    instructionView.rows.length > 0
    || Boolean(instructionView.qrImageUri)
    || Boolean(qrPayload)
    || Boolean(instructionView.note);

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

  const captureQrImage = async () => {
    const captureUri = await qrCaptureRef.current?.capture?.();
    if (!captureUri) {
      throw new Error('No pudimos preparar la imagen del QR.');
    }
    return captureUri;
  };

  const handleSaveQr = async () => {
    try {
      const captureUri = await captureQrImage();
      await CameraRoll.save(captureUri, { type: 'photo', album: 'Confio' });
      Alert.alert('Guardado', 'QR guardado en tu galería.');
    } catch (error: any) {
      Alert.alert('Error', error?.message || 'No se pudo guardar la imagen del QR.');
    }
  };

  const handleShareQr = async () => {
    try {
      const captureUri = await captureQrImage();
      await Share.open({
        title: 'QR de pago',
        message: direction === 'ON_RAMP'
          ? 'Abre este QR desde tu app bancaria o billetera compatible.'
          : 'Comparte este QR solo si el proveedor te lo pidió para completar el retiro.',
        url: captureUri,
        type: 'image/png',
        filename: `confio-qr-${orderId}`,
      });
    } catch (error: any) {
      if (error?.message?.includes('User did not share')) {
        return;
      }
      Alert.alert('Error', error?.message || 'No se pudo compartir el QR.');
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primaryDark} />
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        <RampReveal delay={0}>
        <RampHero
          eyebrow={direction === 'ON_RAMP' ? 'Pago' : 'Retiro'}
          title={instructionView.title}
          subtitle={instructionView.subtitle}
          onBack={() => navigation.goBack()}
          compact={isCompact}
          fromColor={colors.primaryDark}
          toColor={colors.primary}
        />
        </RampReveal>

        <RampReveal delay={70}>
        <RampCard style={styles.card}>
          <Text style={styles.summaryEyebrow}>Seguimiento de la orden</Text>
          <View style={[styles.statusPill, styles[`statusPill_${statusMeta.tone}`]]}>
            <Icon name={statusMeta.icon} size={13} color={statusPillIconColor[statusMeta.tone]} />
            <Text style={[styles.statusPillText, styles[`statusPillText_${statusMeta.tone}`]]}>{statusMeta.label}</Text>
          </View>
          <View style={styles.stackedRow}>
            <Text style={styles.label}>Orden</Text>
            <View style={styles.orderRow}>
              <Text style={styles.orderValue}>{orderId}</Text>
              <TouchableOpacity
                style={styles.copyPillInline}
                onPress={() => copyInstructionValue('ID de orden', orderId)}
                activeOpacity={0.7}
              >
                <Icon name="copy" size={11} color={colors.primaryDark} />
                <Text style={styles.copyPillText}>Copiar</Text>
              </TouchableOpacity>
            </View>
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
          {!isTerminalSuccess && !isTerminalError ? (
            <View style={styles.settlementNotice}>
              <Icon name="clock" size={13} color={colors.textSecondary} />
              <Text style={styles.settlementNoticeText}>El acreditado puede tardar hasta 1 hora según el medio de pago.</Text>
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

        {hasInstructionDetails ? (
          <RampReveal delay={170}>
          <RampCard style={styles.card}>
            {instructionView.rows.length > 0 ? (
              <>
                {instructionView.rows.map((item, index) => (
                  <View key={`${item.label}-${index}`} style={styles.instructionRow}>
                    <Text style={styles.instructionLabel}>{item.label}</Text>
                    <View style={styles.instructionValueRow}>
                      <Text style={styles.instructionValue}>{cleanDisplay(item.value)}</Text>
                      <TouchableOpacity
                        style={styles.copyPillInline}
                        onPress={() => copyInstructionValue(item.label, cleanDisplay(item.value))}
                        activeOpacity={0.7}
                      >
                        <Icon name="copy" size={11} color={colors.primaryDark} />
                        <Text style={styles.copyPillText}>Copiar</Text>
                      </TouchableOpacity>
                    </View>
                  </View>
                ))}
              </>
            ) : null}

            {hasQrAsset ? (
              <View style={styles.qrWrap}>
                {direction === 'ON_RAMP' ? (
                  <View style={styles.sameDeviceCallout}>
                    <View style={styles.sameDeviceHeader}>
                      <Icon name="smartphone" size={16} color={colors.primaryDark} />
                      <Text style={styles.sameDeviceTitle}>¿Estás en este mismo celular?</Text>
                    </View>
                    <Text style={styles.sameDeviceBody}>
                      Guarda este QR y luego ábrelo desde tu app bancaria o billetera con la opción "Desde galería" o "Cargar imagen".
                    </Text>
                    <View style={styles.sameDeviceSteps}>
                      <Text style={styles.sameDeviceStep}>1. Guarda la imagen del QR.</Text>
                      <Text style={styles.sameDeviceStep}>2. Abre tu app bancaria o billetera.</Text>
                      <Text style={styles.sameDeviceStep}>3. Busca "Pagar con QR" y luego "Desde galería".</Text>
                    </View>
                  </View>
                ) : null}
                <ViewShot
                  ref={qrCaptureRef}
                  options={{ format: 'png', quality: 1, fileName: `confio-qr-${orderId}` }}
                  style={styles.qrShot}
                >
                  <View style={styles.qrCaptureSurface}>
                    {instructionView.qrImageUri ? (
                      <View style={[styles.qrFrame, styles.qrImageFrame]}>
                        <Image
                          source={{ uri: instructionView.qrImageUri }}
                          style={styles.qrImage}
                          resizeMode="contain"
                        />
                      </View>
                    ) : canRenderQr ? (
                      <View style={styles.qrFrame}>
                        <QRCode value={qrPayload!} size={190} />
                      </View>
                    ) : null}
                  </View>
                </ViewShot>
                <View style={styles.qrActionRow}>
                  <TouchableOpacity
                    style={styles.primaryQrButton}
                    onPress={handleSaveQr}
                    activeOpacity={0.7}
                  >
                    <Icon name="download" size={14} color="#ffffff" />
                    <Text style={styles.primaryQrButtonText}>Guardar imagen QR</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.secondaryQrButton}
                    onPress={handleShareQr}
                    activeOpacity={0.7}
                  >
                    <Icon name="share-2" size={14} color={colors.primaryDark} />
                    <Text style={styles.secondaryQrButtonText}>Compartir</Text>
                  </TouchableOpacity>
                </View>
              </View>
            ) : null}

            {qrPayload ? (
              <View style={styles.qrWrap}>
                {!canRenderQr ? (
                  <View style={[styles.qrFrame, styles.qrFrameFallback]}>
                    <Icon name="alert-circle" size={28} color={colors.warning.icon} />
                    <Text style={styles.qrFallbackTitle}>Código demasiado grande</Text>
                    <Text style={styles.qrFallbackBody}>
                      El proveedor devolvió un contenido muy largo y no se puede mostrar como QR dentro de la app.
                    </Text>
                  </View>
                ) : null}
                <TouchableOpacity
                  style={styles.copyPill}
                  onPress={() => copyInstructionValue('Código QR', qrPayload)}
                  activeOpacity={0.7}
                >
                  <Icon name="copy" size={12} color={colors.primaryDark} />
                  <Text style={styles.copyPillText}>{hasQrAsset ? 'Copiar contenido del QR' : canRenderQr ? 'Copiar código' : 'Copiar contenido'}</Text>
                </TouchableOpacity>
                {!canRenderQr ? (
                  <Text style={styles.qrFallbackNote}>
                    Copia el contenido y ábrelo desde una app bancaria o billetera compatible.
                  </Text>
                ) : null}
              </View>
            ) : null}

            {instructionView.note ? <Text style={styles.note}>{instructionView.note}</Text> : null}
          </RampCard>
          </RampReveal>
        ) : null}

        {instructionView.actionUrl && instructionView.allowExternalAction ? (
          <RampReveal delay={210}>
          <RampActionBar
            primaryLabel={instructionView.actionLabel || 'Abrir proveedor'}
            onPrimaryPress={() => {
              void Linking.openURL(instructionView.actionUrl!);
            }}
          />
          </RampReveal>
        ) : null}

        <RampReveal delay={240}>
        <TouchableOpacity style={[styles.refreshButton, isRefreshing && styles.refreshButtonDisabled]} onPress={handleRefresh} activeOpacity={0.7} disabled={isRefreshing}>
          {isRefreshing ? <ActivityIndicator size="small" color={colors.primary} /> : <Icon name="refresh-cw" size={14} color={colors.primary} />}
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
          style={styles.historyButton}
          onPress={() =>
            navigation.navigate('RampHistory', {
              initialFilter: direction === 'ON_RAMP' ? 'on_ramp' : 'off_ramp',
            })
          }
          activeOpacity={0.7}
        >
          <Icon name="clock" size={15} color={colors.primary} />
          <Text style={styles.historyButtonText}>Ver historial</Text>
        </TouchableOpacity>
        </RampReveal>

        <RampReveal delay={330}>
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
    backgroundColor: colors.primaryDark,
  },
  scroll: {
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
  settlementNotice: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 6,
    paddingVertical: 6,
  },
  settlementNoticeText: {
    flex: 1,
    fontSize: 12,
    color: colors.textSecondary,
    lineHeight: 17,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 18,
    paddingVertical: 2,
  },
  stackedRow: {
    gap: 6,
  },
  orderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    flexWrap: 'wrap',
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
    color: colors.textSecondary,
    lineHeight: 20,
  },
  value: {
    flex: 1.08,
    fontSize: 14,
    fontWeight: '700',
    color: colors.textFlat,
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
    fontSize: 13,
    fontWeight: '700',
    color: colors.textFlat,
    fontVariant: ['tabular-nums'],
    letterSpacing: 0.3,
    flexShrink: 1,
  },
  statusPill: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
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
    color: colors.textFlat,
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
    gap: 4,
    paddingBottom: 12,
    marginBottom: 2,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  instructionValueRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    flexWrap: 'wrap',
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '800',
    color: colors.textFlat,
    lineHeight: 24,
  },
  sectionBody: {
    fontSize: 14,
    lineHeight: 23,
    color: colors.textSecondary,
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
    color: colors.textFlat,
  },
  instructionLabel: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.textSecondary,
    letterSpacing: 0.2,
  },
  instructionValue: {
    fontSize: 15,
    lineHeight: 22,
    color: colors.textFlat,
    flexShrink: 1,
  },
  qrWrap: {
    alignItems: 'center',
    gap: 14,
    marginVertical: 10,
    paddingVertical: 10,
    width: '100%',
  },
  qrShot: {
    width: '100%',
    alignItems: 'center',
  },
  qrCaptureSurface: {
    backgroundColor: '#ffffff',
    borderRadius: 20,
    paddingVertical: 14,
    paddingHorizontal: 14,
  },
  qrFrame: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 16,
    shadowColor: '#111827',
    shadowOpacity: 0.08,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 3,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  qrImageFrame: {
    padding: 10,
  },
  qrImage: {
    width: 240,
    height: 240,
  },
  qrFrameFallback: {
    minHeight: 190,
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    paddingHorizontal: 18,
  },
  qrFallbackTitle: {
    fontSize: 16,
    fontWeight: '800',
    color: colors.textFlat,
    textAlign: 'center',
  },
  qrFallbackBody: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.textSecondary,
    textAlign: 'center',
  },
  qrFallbackNote: {
    fontSize: 13,
    lineHeight: 19,
    color: colors.textSecondary,
    textAlign: 'center',
  },
  sameDeviceCallout: {
    width: '100%',
    backgroundColor: '#eff6ff',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#bfdbfe',
    padding: 14,
    gap: 10,
  },
  sameDeviceHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  sameDeviceTitle: {
    fontSize: 15,
    fontWeight: '800',
    color: colors.primaryDark,
  },
  sameDeviceBody: {
    fontSize: 13,
    lineHeight: 19,
    color: colors.textFlat,
  },
  sameDeviceSteps: {
    gap: 4,
  },
  sameDeviceStep: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.textSecondary,
  },
  qrActionRow: {
    width: '100%',
    flexDirection: 'row',
    gap: 10,
  },
  primaryQrButton: {
    flex: 1,
    minHeight: 44,
    borderRadius: 14,
    backgroundColor: colors.primary,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingHorizontal: 14,
  },
  primaryQrButtonText: {
    fontSize: 13,
    fontWeight: '800',
    color: '#ffffff',
  },
  secondaryQrButton: {
    flex: 1,
    minHeight: 44,
    borderRadius: 14,
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#bfdbfe',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingHorizontal: 14,
  },
  secondaryQrButtonText: {
    fontSize: 13,
    fontWeight: '800',
    color: colors.primaryDark,
  },
  note: {
    fontSize: 13,
    lineHeight: 19,
    color: colors.textSecondary,
    fontStyle: 'italic',
  },
  copyPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#ecfdf5',
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: '#a7f3d0',
  },
  copyPillInline: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#ecfdf5',
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 6,
    marginTop: 6,
    borderWidth: 1,
    borderColor: '#a7f3d0',
  },
  copyPillText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.primaryDark,
  },
  refreshButton: {
    marginTop: 10,
    marginHorizontal: 22,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    borderRadius: 16,
    paddingVertical: 13,
    backgroundColor: 'transparent',
    borderWidth: 1.5,
    borderColor: colors.primary,
    borderStyle: 'dashed',
  },
  refreshButtonDisabled: {
    opacity: 0.6,
  },
  refreshButtonText: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.primary,
  },
  refreshMessage: {
    marginTop: 10,
    marginHorizontal: 22,
    fontSize: 13,
    lineHeight: 18,
    color: colors.textSecondary,
    textAlign: 'center',
  },
  historyButton: {
    marginTop: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 14,
    marginHorizontal: 22,
    borderRadius: 16,
    borderWidth: 1.5,
    borderColor: colors.primary,
    backgroundColor: '#f0fdf4',
  },
  historyButtonText: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.primary,
  },
  ghostButton: {
    marginTop: 10,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 14,
    marginHorizontal: 22,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
  },
  ghostButtonText: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.textSecondary,
  },
});

export default RampInstructionsScreen;
