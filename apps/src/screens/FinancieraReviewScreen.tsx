import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  ScrollView,
  StatusBar,
  KeyboardAvoidingView,
  Platform,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery, useMutation } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { useNumberFormat } from '../utils/numberFormatting';
import { useAuth } from '../contexts/AuthContext';
import { tokenLabel } from '../types/financiera';
import {
  GET_FINANCIERA,
  GET_MY_REVIEWABLE_USDC_SENDS,
  SUBMIT_FINANCIERA_REVIEW,
} from '../apollo/queries';

type NavProp = NativeStackNavigationProp<MainStackParamList>;
type ReviewRoute = RouteProp<MainStackParamList, 'FinancieraReview'>;

const STAR_GOLD = colors.offRampIcon;

interface ReviewableSend {
  id: string;
  kind: 'send' | 'withdrawal';
  direction: 'sent' | 'received';
  token: 'USDC' | 'CUSD';
  amountUsdc: string;
  destination: string;
  createdAt: string;
}

const ratingText: Record<number, string> = {
  1: 'Muy malo',
  2: 'Malo',
  3: 'Regular',
  4: 'Bueno',
  5: 'Excelente',
};

// Decimal-pad keyboards show a comma in most LATAM locales; accept both
// separators rather than silently truncating "98,5" to 98.
const parseAmount = (value: string) => parseFloat(value.replace(',', '.'));

const shortAddress = (addr: string) =>
  addr.length > 14 ? `${addr.slice(0, 6)}…${addr.slice(-4)}` : addr;

const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString('es', { day: 'numeric', month: 'short' });

const VerificationGate = ({ onBack, onVerify }: { onBack: () => void; onVerify: () => void }) => (
  <View style={styles.gate}>
    <View style={styles.gateIcon}>
      <Icon name="user-check" size={32} color={colors.primaryDark} />
    </View>
    <Text style={styles.gateTitle}>Verifica tu identidad</Text>
    <Text style={styles.gateText}>
      Solo las personas con identidad verificada pueden dejar reseñas. Así mantenemos las
      reseñas reales y confiables para todos.
    </Text>
    <TouchableOpacity style={styles.gatePrimary} onPress={onVerify}>
      <Text style={styles.gatePrimaryText}>Verificar mi identidad</Text>
    </TouchableOpacity>
    <TouchableOpacity onPress={onBack}>
      <Text style={styles.gateSecondary}>Volver</Text>
    </TouchableOpacity>
  </View>
);

// Reviews are anchored to real transactions: without a recent USDC/cUSD
// transfer there is nothing to review.
const NoSendsGate = ({ onBack }: { onBack: () => void }) => (
  <View style={styles.gate}>
    <View style={styles.gateIcon}>
      <Icon name="send" size={32} color={colors.primaryDark} />
    </View>
    <Text style={styles.gateTitle}>Aún no tienes transacciones para reseñar</Text>
    <Text style={styles.gateText}>
      Las reseñas se conectan a una transacción real de USDC o cUSD para que la información
      del directorio sea confiable. Cuando hayas comprado o vendido con una financiera,
      vuelve aquí para contar tu experiencia.
    </Text>
    <TouchableOpacity style={styles.gatePrimary} onPress={onBack}>
      <Text style={styles.gatePrimaryText}>Entendido</Text>
    </TouchableOpacity>
  </View>
);

export const FinancieraReviewScreen = () => {
  const navigation = useNavigation<NavProp>();
  const route = useRoute<ReviewRoute>();
  const { formatNumber } = useNumberFormat();
  const { userProfile } = useAuth();
  const { financieraId } = route.params;

  // Usually a cache hit from the detail screen the user just came from.
  const { data } = useQuery(GET_FINANCIERA, {
    variables: { id: financieraId },
    fetchPolicy: 'cache-first',
  });
  const financiera = data?.financiera || null;

  const { data: sendsData, loading: sendsLoading } = useQuery(GET_MY_REVIEWABLE_USDC_SENDS, {
    fetchPolicy: 'cache-and-network',
  });
  const reviewableSends: ReviewableSend[] = sendsData?.myReviewableUsdcSends || [];

  const [submitMutation, { loading: submitting }] = useMutation(SUBMIT_FINANCIERA_REVIEW, {
    refetchQueries: [
      { query: GET_FINANCIERA, variables: { id: financieraId } },
      { query: GET_MY_REVIEWABLE_USDC_SENDS },
    ],
  });

  const [selectedSend, setSelectedSend] = useState<ReviewableSend | null>(null);
  const [rating, setRating] = useState(0);
  const [receivedUsd, setReceivedUsd] = useState('');
  const [comment, setComment] = useState('');

  const sent = selectedSend ? parseFloat(selectedSend.amountUsdc) : 0;
  const received = parseAmount(receivedUsd);
  const previewPer100 =
    sent > 0 && received > 0 ? Math.round((received / sent) * 100 * 10) / 10 : null;

  // Soft typo guard. The API hard-rejects fiat > USDC/cUSD only for sell-side reviews.
  const isBuyingUsdc = selectedSend?.direction === 'received';
  const amountWarning =
    sent > 0 && received > 0
      ? !isBuyingUsdc && received > sent
        ? `La transacción fue de ${formatNumber(sent, { maximumFractionDigits: 2 })} ${selectedSend ? tokenLabel(selectedSend.token) : 'USDC'} — el monto en dólares no puede ser mayor.`
        : received < sent / 2
        ? isBuyingUsdc
          ? 'Eso es menos de la mitad de lo que recibiste. Revisa el monto.'
          : 'Eso es menos de la mitad de lo que enviaste. Revisa el monto.'
        : null
      : null;

  const canSubmit =
    !!selectedSend && rating > 0 && received > 0 && (isBuyingUsdc || received <= sent) && !submitting;

  const submitReview = async () => {
    if (!selectedSend) return;
    try {
      const res = await submitMutation({
        variables: {
          financieraId,
          rating,
          receivedUsd: String(received),
          comment: comment.trim() || null,
          sendTransactionId: selectedSend.kind === 'send' ? selectedSend.id : null,
          usdcWithdrawalId: selectedSend.kind === 'withdrawal' ? selectedSend.id : null,
        },
      });
      const payload = res.data?.submitFinancieraReview;
      if (payload?.success) {
        Alert.alert(
          '¡Gracias!',
          'Tu reseña anónima ayuda a tu comunidad a elegir con confianza.',
          [{ text: 'Listo', onPress: () => navigation.goBack() }],
        );
      } else {
        Alert.alert('No se pudo publicar', payload?.error || 'Intenta de nuevo.');
      }
    } catch {
      Alert.alert('No se pudo publicar', 'Revisa tu conexión e intenta de nuevo.');
    }
  };

  if (!userProfile?.isIdentityVerified) {
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
        <Header title="Dejar reseña" onBack={() => navigation.goBack()} />
        <VerificationGate
          onBack={() => navigation.goBack()}
          onVerify={() => navigation.navigate('Verification')}
        />
      </View>
    );
  }

  if (sendsLoading && reviewableSends.length === 0) {
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
        <Header title="Dejar reseña" onBack={() => navigation.goBack()} />
        <View style={styles.gate}>
          <ActivityIndicator color={colors.primary} size="large" />
        </View>
      </View>
    );
  }

  if (reviewableSends.length === 0) {
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
        <Header title="Dejar reseña" onBack={() => navigation.goBack()} />
        <NoSendsGate onBack={() => navigation.goBack()} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <Header title="Dejar reseña" onBack={() => navigation.goBack()} />

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
          {!!financiera && (
            <Text style={styles.forName}>
              Tu experiencia con <Text style={{ fontWeight: '700' }}>{financiera.name}</Text>
            </Text>
          )}

          {/* Backing transaction */}
          <View style={styles.card}>
            <Text style={styles.label}>¿Cuál transacción respalda tu reseña?</Text>
            <Text style={styles.sublabel}>
              Tu reseña se conecta a una compra o venta real para que las tasas sean confiables.
            </Text>
            {reviewableSends.map((tx) => {
              const active = selectedSend?.id === tx.id && selectedSend?.kind === tx.kind;
              return (
                <TouchableOpacity
                  key={`${tx.kind}-${tx.id}`}
                  style={[styles.txItem, active && styles.txItemActive]}
                  onPress={() => setSelectedSend(tx)}
                  activeOpacity={0.8}
                >
                  <View style={[styles.txRadio, active && styles.txRadioActive]}>
                    {active && <Icon name="check" size={12} color={colors.white} />}
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.txAmount}>
                      {formatNumber(parseFloat(tx.amountUsdc), { maximumFractionDigits: 2 })} {tokenLabel(tx.token)}
                    </Text>
                    <Text style={styles.txMeta}>
                      {formatDate(tx.createdAt)} · {tx.kind === 'withdrawal'
                        ? 'retiro a wallet externa'
                        : tx.direction === 'received'
                          ? 'recibido en Confío'
                          : 'enviado en Confío'}
                      {tx.destination ? ` · ${shortAddress(tx.destination)}` : ''}
                    </Text>
                  </View>
                </TouchableOpacity>
              );
            })}
          </View>

          {/* Rating */}
          <View style={styles.card}>
            <Text style={styles.label}>¿Cómo fue tu experiencia?</Text>
            <View style={styles.starRow}>
              {[1, 2, 3, 4, 5].map((s) => (
                <TouchableOpacity
                  key={s}
                  onPress={() => setRating(s)}
                  style={styles.starBtn}
                  accessibilityRole="button"
                  accessibilityLabel={`Calificar con ${s} ${s === 1 ? 'estrella' : 'estrellas'}`}
                  accessibilityState={{ selected: rating >= s }}
                >
                  <Icon name="star" size={36} color={rating >= s ? STAR_GOLD : colors.border} />
                </TouchableOpacity>
              ))}
            </View>
            {rating > 0 && <Text style={styles.ratingLabel}>{ratingText[rating]}</Text>}
          </View>

          {/* Received amount */}
          <View style={styles.card}>
            <Text style={styles.label}>
              {isBuyingUsdc ? '¿Cuánto pagaste en dólares (USD)?' : '¿Cuánto recibiste en dólares (USD)?'}
            </Text>
            {selectedSend && (
              <Text style={styles.sublabel}>
                {isBuyingUsdc ? 'Recibiste' : 'Enviaste'} {formatNumber(sent, { maximumFractionDigits: 2 })} {tokenLabel(selectedSend.token)}
              </Text>
            )}
            <View style={styles.usdInputWrap}>
              <Text style={styles.usdPrefix}>$</Text>
              <TextInput
                style={styles.usdInput}
                placeholder="98"
                placeholderTextColor={colors.text.light}
                keyboardType="decimal-pad"
                value={receivedUsd}
                onChangeText={setReceivedUsd}
              />
            </View>

            {amountWarning != null && (
              <View style={styles.amountWarning}>
                <Icon name="alert-circle" size={14} color={colors.warning.icon} />
                <Text style={styles.amountWarningText}>{amountWarning}</Text>
              </View>
            )}

            {previewPer100 != null && amountWarning == null && (
              <View style={styles.preview}>
                <Text style={styles.previewText}>
                  Equivale a 100 {selectedSend ? tokenLabel(selectedSend.token) : 'USDC'} →{' '}
                  <Text style={styles.previewStrong}>
                    ${formatNumber(previewPer100, { maximumFractionDigits: 1 })}
                  </Text>
                  {isBuyingUsdc ? ' pagados' : ' recibidos'}
                </Text>
              </View>
            )}
          </View>

          {/* Comment */}
          <View style={styles.card}>
            <Text style={styles.label}>Comentario (opcional)</Text>
            <TextInput
              style={styles.commentInput}
              placeholder="Cuenta cómo fue tu experiencia..."
              placeholderTextColor={colors.text.light}
              multiline
              value={comment}
              onChangeText={setComment}
              maxLength={280}
            />
            <Text style={styles.charCount}>{comment.length}/280</Text>
          </View>

          <View style={styles.anonNote}>
            <Icon name="eye-off" size={14} color={colors.text.secondary} />
            <Text style={styles.anonText}>
              Tu reseña es anónima. Solo se muestra que proviene de un usuario verificado con una
              transacción real.
            </Text>
          </View>
        </ScrollView>

        <SafeAreaView edges={['bottom']} style={styles.footer}>
          <TouchableOpacity
            style={[styles.submitBtn, !canSubmit && styles.submitBtnDisabled]}
            disabled={!canSubmit}
            onPress={submitReview}
          >
            <Text style={styles.submitText}>
              {submitting ? 'Publicando…' : 'Publicar reseña'}
            </Text>
          </TouchableOpacity>
        </SafeAreaView>
      </KeyboardAvoidingView>
    </View>
  );
};

const Header = ({ title, onBack }: { title: string; onBack: () => void }) => (
  <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
    <View style={styles.header}>
      <TouchableOpacity onPress={onBack} style={styles.headerIconBtn} accessibilityRole="button" accessibilityLabel="Volver">
        <Icon name="arrow-left" size={24} color={colors.white} />
      </TouchableOpacity>
      <Text style={styles.headerTitle}>{title}</Text>
      <View style={styles.headerIconBtn} />
    </View>
  </SafeAreaView>
);

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },

  header: {
    backgroundColor: colors.primary,
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: colors.white },

  scrollContent: { padding: 16, paddingBottom: 24 },
  forName: { fontSize: 14, color: colors.text.secondary, marginBottom: 12 },

  card: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: colors.borderLight,
  },
  label: { fontSize: 14, fontWeight: '600', color: colors.text.primary },
  sublabel: { fontSize: 12, color: colors.text.secondary, marginTop: 4, lineHeight: 17 },

  txItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 12,
    marginTop: 10,
  },
  txItemActive: { borderColor: colors.primary, backgroundColor: colors.primarySoft },
  txRadio: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 2,
    borderColor: colors.borderMedium,
    alignItems: 'center',
    justifyContent: 'center',
  },
  txRadioActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  txAmount: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  txMeta: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },

  starRow: { flexDirection: 'row', justifyContent: 'center', gap: 6, marginTop: 14 },
  starBtn: { padding: 2 },
  ratingLabel: { textAlign: 'center', marginTop: 10, fontSize: 15, fontWeight: '700', color: STAR_GOLD },

  usdInputWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    paddingHorizontal: 16,
    marginTop: 12,
    height: 52,
  },
  usdPrefix: { fontSize: 18, fontWeight: '700', color: colors.text.secondary, marginRight: 4 },
  usdInput: { flex: 1, fontSize: 18, fontWeight: '700', color: colors.text.primary, paddingVertical: 0 },

  amountWarning: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: colors.warning.background,
    borderRadius: 10,
    padding: 12,
    marginTop: 14,
  },
  amountWarningText: { flex: 1, fontSize: 12, color: colors.warning.text, lineHeight: 17 },

  preview: {
    backgroundColor: colors.primarySoft,
    borderRadius: 10,
    padding: 12,
    marginTop: 14,
    alignItems: 'center',
  },
  previewText: { fontSize: 14, color: colors.text.secondary },
  previewStrong: { fontSize: 16, fontWeight: '800', color: colors.primaryDark },

  commentInput: {
    minHeight: 90,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 12,
    marginTop: 12,
    fontSize: 15,
    color: colors.text.primary,
    textAlignVertical: 'top',
  },
  charCount: { fontSize: 11, color: colors.text.light, textAlign: 'right', marginTop: 6 },

  anonNote: { flexDirection: 'row', gap: 8, paddingHorizontal: 4, alignItems: 'center' },
  anonText: { flex: 1, fontSize: 12, color: colors.text.secondary, lineHeight: 17 },

  footer: {
    backgroundColor: colors.white,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingHorizontal: 16,
    paddingTop: 12,
  },
  submitBtn: {
    height: 52,
    borderRadius: 14,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  submitBtnDisabled: { backgroundColor: colors.borderMedium },
  submitText: { fontSize: 16, fontWeight: '700', color: colors.white },

  // Gates
  gate: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  gateIcon: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 20,
  },
  gateTitle: { fontSize: 20, fontWeight: '800', color: colors.text.primary, marginBottom: 10 },
  gateText: { fontSize: 14, color: colors.text.secondary, textAlign: 'center', lineHeight: 20, marginBottom: 24 },
  gatePrimary: {
    backgroundColor: colors.primary,
    borderRadius: 14,
    height: 52,
    paddingHorizontal: 32,
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'stretch',
  },
  gatePrimaryText: { fontSize: 16, fontWeight: '700', color: colors.white },
  gateSecondary: { fontSize: 15, color: colors.text.secondary, marginTop: 16, fontWeight: '600' },
});

export default FinancieraReviewScreen;
