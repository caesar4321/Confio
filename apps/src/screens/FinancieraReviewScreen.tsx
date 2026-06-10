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
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { useNumberFormat } from '../utils/numberFormatting';
import { MOCK_FINANCIERAS } from '../utils/financierasMock';

type NavProp = NativeStackNavigationProp<MainStackParamList>;
type ReviewRoute = RouteProp<MainStackParamList, 'FinancieraReview'>;

const STAR_GOLD = '#F59E0B';

// Simulated: in production this comes from the user's identity-verification status.
const USER_VERIFIED = true;

const ratingText: Record<number, string> = {
  1: 'Muy malo',
  2: 'Malo',
  3: 'Regular',
  4: 'Bueno',
  5: 'Excelente',
};

const VerificationGate = ({ onBack }: { onBack: () => void }) => (
  <View style={styles.gate}>
    <View style={styles.gateIcon}>
      <Icon name="user-check" size={32} color={colors.primaryDark} />
    </View>
    <Text style={styles.gateTitle}>Verifica tu identidad</Text>
    <Text style={styles.gateText}>
      Solo las personas con identidad verificada pueden dejar reseñas. Así mantenemos las
      reseñas reales y confiables para todos.
    </Text>
    <TouchableOpacity style={styles.gatePrimary}>
      <Text style={styles.gatePrimaryText}>Verificar mi identidad</Text>
    </TouchableOpacity>
    <TouchableOpacity onPress={onBack}>
      <Text style={styles.gateSecondary}>Volver</Text>
    </TouchableOpacity>
  </View>
);

// Decimal-pad keyboards show a comma in most LATAM locales; accept both
// separators rather than silently truncating "98,5" to 98.
const parseAmount = (value: string) => parseFloat(value.replace(',', '.'));

export const FinancieraReviewScreen = () => {
  const navigation = useNavigation<NavProp>();
  const route = useRoute<ReviewRoute>();
  const { formatNumber } = useNumberFormat();
  const { financieraId } = route.params;
  const financiera = MOCK_FINANCIERAS.find((f) => f.id === financieraId);

  const [rating, setRating] = useState(0);
  const [sentUsdc, setSentUsdc] = useState('');
  const [receivedUsd, setReceivedUsd] = useState('');
  const [comment, setComment] = useState('');

  const sent = parseAmount(sentUsdc);
  const received = parseAmount(receivedUsd);
  const previewPer100 =
    sent > 0 && received > 0 ? Math.round((received / sent) * 100 * 10) / 10 : null;

  // Soft typo guard: receiving more USD than USDC sent is implausible (the
  // financiera takes a cut), and less than half suggests a slipped digit.
  const amountWarning =
    sent > 0 && received > 0
      ? received > sent
        ? '¿Recibiste más dólares de los que enviaste? Revisa los montos.'
        : received < sent / 2
        ? 'Eso es menos de la mitad de lo que enviaste. Revisa los montos.'
        : null
      : null;

  const canSubmit = rating > 0 && sent > 0 && received > 0;

  const submitReview = () => {
    Alert.alert(
      '¡Gracias!',
      'Tu reseña anónima ayuda a tu comunidad a cambiar con confianza.',
      [{ text: 'Listo', onPress: () => navigation.goBack() }],
    );
  };

  if (!USER_VERIFIED) {
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
        <Header title="Dejar reseña" onBack={() => navigation.goBack()} />
        <VerificationGate onBack={() => navigation.goBack()} />
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

          {/* Rating */}
          <View style={styles.card}>
            <Text style={styles.label}>¿Cómo fue tu experiencia?</Text>
            <View style={styles.starRow}>
              {[1, 2, 3, 4, 5].map((s) => (
                <TouchableOpacity key={s} onPress={() => setRating(s)} style={styles.starBtn}>
                  <Icon name="star" size={36} color={rating >= s ? STAR_GOLD : '#E5E7EB'} />
                </TouchableOpacity>
              ))}
            </View>
            {rating > 0 && <Text style={styles.ratingLabel}>{ratingText[rating]}</Text>}
          </View>

          {/* Amounts */}
          <View style={styles.card}>
            <Text style={styles.label}>¿Cuánto enviaste?</Text>
            <View style={styles.amountInputWrap}>
              <TextInput
                style={styles.amountInput}
                placeholder="100"
                placeholderTextColor={colors.text.light}
                keyboardType="decimal-pad"
                value={sentUsdc}
                onChangeText={setSentUsdc}
              />
              <Text style={styles.amountUnit}>USDC</Text>
            </View>

            <Text style={[styles.label, { marginTop: 20 }]}>¿Cuánto recibiste en dólares (USD)?</Text>
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
                  Equivale a 100 USDC →{' '}
                  <Text style={styles.previewStrong}>
                    ${formatNumber(previewPer100, { maximumFractionDigits: 1 })}
                  </Text>
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
              Tu reseña es anónima. Solo se muestra que proviene de un usuario verificado.
            </Text>
          </View>
        </ScrollView>

        <SafeAreaView edges={['bottom']} style={styles.footer}>
          <TouchableOpacity
            style={[styles.submitBtn, !canSubmit && styles.submitBtnDisabled]}
            disabled={!canSubmit}
            onPress={submitReview}
          >
            <Text style={styles.submitText}>Publicar reseña</Text>
          </TouchableOpacity>
        </SafeAreaView>
      </KeyboardAvoidingView>
    </View>
  );
};

const Header = ({ title, onBack }: { title: string; onBack: () => void }) => (
  <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
    <View style={styles.header}>
      <TouchableOpacity onPress={onBack} style={styles.headerIconBtn}>
        <Icon name="arrow-left" size={24} color="#fff" />
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
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: '#fff' },

  scrollContent: { padding: 16, paddingBottom: 24 },
  forName: { fontSize: 14, color: colors.text.secondary, marginBottom: 12 },

  card: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: colors.borderLight,
  },
  label: { fontSize: 14, fontWeight: '600', color: colors.text.primary },

  starRow: { flexDirection: 'row', justifyContent: 'center', gap: 6, marginTop: 14 },
  starBtn: { padding: 2 },
  ratingLabel: { textAlign: 'center', marginTop: 10, fontSize: 15, fontWeight: '700', color: STAR_GOLD },

  amountInputWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    paddingHorizontal: 16,
    marginTop: 12,
    height: 52,
  },
  amountInput: { flex: 1, fontSize: 18, fontWeight: '700', color: colors.text.primary, paddingVertical: 0 },
  amountUnit: { fontSize: 15, fontWeight: '700', color: colors.accent, marginLeft: 8 },

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
    backgroundColor: '#fff',
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
  submitText: { fontSize: 16, fontWeight: '700', color: '#fff' },

  // Verification gate
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
  gatePrimaryText: { fontSize: 16, fontWeight: '700', color: '#fff' },
  gateSecondary: { fontSize: 15, color: colors.text.secondary, marginTop: 16, fontWeight: '600' },
});

export default FinancieraReviewScreen;
