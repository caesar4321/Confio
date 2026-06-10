import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Linking,
  StatusBar,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { getCountryByIso } from '../utils/countries';
import { useNumberFormat } from '../utils/numberFormatting';
import {
  FinancieraReview,
  USDC_ALGORAND_TAG,
  avgReceivedPer100,
  serviceBadge,
  MANDATORY_SERVICE_ID,
} from '../types/financiera';
import { MOCK_FINANCIERAS } from '../utils/financierasMock';

type NavProp = NativeStackNavigationProp<MainStackParamList>;
type DetailRoute = RouteProp<MainStackParamList, 'FinancieraDetail'>;

const WHATSAPP_GREEN = '#25D366';
const STAR_GOLD = '#F59E0B';

const Stars = ({ rating, size = 16 }: { rating: number; size?: number }) => (
  <View style={{ flexDirection: 'row' }}>
    {[1, 2, 3, 4, 5].map((s) => (
      <Icon
        key={s}
        name="star"
        size={size}
        color={rating >= s - 0.25 ? STAR_GOLD : '#E5E7EB'}
        style={{ marginRight: 1 }}
      />
    ))}
  </View>
);

const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric' });

const ReviewRow = ({ review }: { review: FinancieraReview }) => {
  const { formatNumber } = useNumberFormat();
  return (
    <View style={styles.reviewRow}>
      <View style={styles.reviewTop}>
        <Stars rating={review.rating} size={13} />
        <Text style={styles.reviewDate}>{formatDate(review.createdAt)}</Text>
      </View>
      <View style={styles.reviewRateRow}>
        <Text style={styles.reviewRateText}>
          Envié <Text style={styles.reviewRateStrong}>{formatNumber(review.sentUsdc, { maximumFractionDigits: 2 })} USDC</Text>
        </Text>
        <Icon name="arrow-right" size={13} color={colors.text.light} />
        <Text style={styles.reviewRateText}>
          Recibí <Text style={[styles.reviewRateStrong, { color: colors.primaryDark }]}>${formatNumber(review.receivedUsd, { maximumFractionDigits: 2 })}</Text>
        </Text>
      </View>
      {!!review.comment && <Text style={styles.reviewComment}>“{review.comment}”</Text>}
      <Text style={styles.reviewAnon}>Reseña anónima · Usuario verificado</Text>
    </View>
  );
};

export const FinancieraDetailScreen = () => {
  const navigation = useNavigation<NavProp>();
  const route = useRoute<DetailRoute>();
  const { formatNumber } = useNumberFormat();
  const { financieraId } = route.params;
  const financiera = MOCK_FINANCIERAS.find((f) => f.id === financieraId);

  // Mock report flow — wire to the backend moderation queue when it lands.
  const reportFinanciera = () => {
    Alert.alert(
      'Reportar financiera',
      '¿Tuviste un problema con esta financiera? Tu reporte es anónimo y nuestro equipo lo revisará.',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Reportar',
          style: 'destructive',
          onPress: () =>
            Alert.alert('Gracias', 'Recibimos tu reporte. Nuestro equipo lo revisará pronto.'),
        },
      ],
    );
  };

  if (!financiera) {
    return (
      <View style={[styles.container, { justifyContent: 'center', alignItems: 'center' }]}>
        <Text style={{ color: colors.text.secondary }}>Financiera no encontrada</Text>
      </View>
    );
  }

  const per100 = avgReceivedPer100(financiera);
  const country = getCountryByIso(financiera.countryIso);
  const extraServices = financiera.services.filter((s) => s !== MANDATORY_SERVICE_ID);

  const openWhatsApp = () => {
    const text = encodeURIComponent(
      `Hola ${financiera.name}, te encontré en Confío. Quiero cambiar USDC por dólares.`,
    );
    Linking.openURL(`https://wa.me/${financiera.whatsapp}?text=${text}`).catch(() => {});
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        <View style={styles.header}>
          <View style={styles.headerTopRow}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerIconBtn}>
              <Icon name="arrow-left" size={24} color="#fff" />
            </TouchableOpacity>
            <Text style={styles.headerTitle} numberOfLines={1}>
              {financiera.name}
            </Text>
            <TouchableOpacity onPress={reportFinanciera} style={styles.headerIconBtn}>
              <Icon name="flag" size={20} color="#fff" />
            </TouchableOpacity>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        {/* Identity */}
        <View style={styles.card}>
          <View style={styles.nameRow}>
            <Text style={styles.name}>{financiera.name}</Text>
            {financiera.verified && (
              <View style={styles.verifiedBadge}>
                <Icon name="check-circle" size={12} color={colors.primaryDark} />
                <Text style={styles.verifiedText}>Identidad verificada</Text>
              </View>
            )}
          </View>
          <View style={styles.locationRow}>
            <Icon name="map-pin" size={14} color={colors.text.secondary} />
            <Text style={styles.locationText}>
              {country?.[3]} {financiera.barrio}, {financiera.city}, {financiera.state},{' '}
              {country?.[0]}
            </Text>
          </View>
          <View style={styles.ratingRow}>
            <Stars rating={financiera.avgRating} />
            <Text style={styles.ratingValue}>
              {formatNumber(financiera.avgRating, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
            </Text>
            <Text style={styles.reviewCount}>· {financiera.reviewCount} reseñas</Text>
          </View>
        </View>

        {/* Headline rate */}
        <View style={styles.card}>
          <Text style={styles.sectionLabel}>Tasa promedio según reseñas</Text>
          <View style={styles.rateBox}>
            <View style={styles.rateSide}>
              <Text style={styles.rateLabel}>Envías</Text>
              <Text style={styles.rateValue}>100 USDC</Text>
            </View>
            <Icon name="arrow-right" size={20} color={colors.text.light} />
            <View style={styles.rateSide}>
              <Text style={styles.rateLabel}>Recibes aprox.</Text>
              <Text style={[styles.rateValue, { color: colors.primaryDark }]}>
                {per100 != null ? `$${formatNumber(per100, { maximumFractionDigits: 1 })}` : '—'}
              </Text>
              <Text style={styles.rateCashTag}>en efectivo</Text>
            </View>
          </View>
          <Text style={styles.rateCaption}>
            Calculado con {financiera.reviewCount} reseñas reales
          </Text>
        </View>

        {/* What it offers */}
        <View style={styles.card}>
          <Text style={styles.sectionLabel}>Qué ofrece</Text>
          <View style={styles.serviceLine}>
            <View style={styles.railChip}>
              <Icon name="check" size={12} color="#fff" />
              <Text style={styles.railChipText}>{USDC_ALGORAND_TAG}</Text>
            </View>
          </View>
          {extraServices.map((s) => (
            <View key={s} style={styles.serviceRow}>
              <Icon name="check" size={16} color={colors.primaryDark} />
              <Text style={styles.serviceRowText}>{serviceBadge(s)}</Text>
            </View>
          ))}
        </View>

        {/* Reviews */}
        <View style={styles.card}>
          <View style={styles.reviewsHeader}>
            <Text style={styles.sectionLabel}>Reseñas ({financiera.reviewCount})</Text>
            <TouchableOpacity
              onPress={() =>
                navigation.navigate('FinancieraReview' as any, { financieraId: financiera.id })
              }
            >
              <Text style={styles.addReviewLink}>Dejar reseña</Text>
            </TouchableOpacity>
          </View>
          {financiera.reviews.map((r) => (
            <ReviewRow key={r.id} review={r} />
          ))}
        </View>

        {/* Safety tips — the last thing read before tapping the WhatsApp CTA */}
        <View style={styles.safetyCard}>
          <View style={styles.safetyHeader}>
            <Icon name="shield" size={16} color={colors.primaryDark} />
            <Text style={styles.safetyTitle}>Consejos de seguridad</Text>
          </View>
          {[
            'Visita el local de la financiera o acuerda un punto público.',
            'Nunca envíes USDC antes de tener el efectivo en mano o un acuerdo claro.',
            'La primera vez, empieza con un monto pequeño.',
            'Si algo no se siente bien, no continúes — y cuéntalo en una reseña.',
          ].map((tip, i) => (
            <View key={i} style={styles.safetyRow}>
              <Text style={styles.safetyBullet}>•</Text>
              <Text style={styles.safetyText}>{tip}</Text>
            </View>
          ))}
        </View>

        <View style={styles.disclaimer}>
          <Icon name="info" size={14} color={colors.accent} />
          <Text style={styles.disclaimerText}>
            Confío no participa en este cambio. Verifica siempre con quién operas; puedes pedir
            visitar la financiera en persona.
          </Text>
        </View>

        <TouchableOpacity style={styles.reportLink} onPress={reportFinanciera}>
          <Icon name="flag" size={13} color={colors.text.light} />
          <Text style={styles.reportLinkText}>Reportar un problema con esta financiera</Text>
        </TouchableOpacity>
      </ScrollView>

      {/* Sticky WhatsApp CTA */}
      <SafeAreaView edges={['bottom']} style={styles.footer}>
        <TouchableOpacity style={styles.whatsappBtn} onPress={openWhatsApp}>
          <Icon name="message-circle" size={18} color="#fff" />
          <Text style={styles.whatsappText}>Contactar por WhatsApp</Text>
        </TouchableOpacity>
      </SafeAreaView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },

  header: { backgroundColor: colors.primary, paddingHorizontal: 16, paddingTop: 8, paddingBottom: 16 },
  headerTopRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: '#fff', flex: 1, textAlign: 'center' },

  scrollContent: { padding: 16, paddingBottom: 24 },

  card: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: colors.borderLight,
  },

  nameRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  name: { fontSize: 20, fontWeight: '800', color: colors.text.primary },
  verifiedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: colors.primaryLight,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
  },
  verifiedText: { fontSize: 11, fontWeight: '700', color: colors.primaryDark },
  locationRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 10 },
  locationText: { flex: 1, fontSize: 13, color: colors.text.secondary, lineHeight: 18 },
  ratingRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 12 },
  ratingValue: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  reviewCount: { fontSize: 13, color: colors.text.secondary },

  sectionLabel: { fontSize: 13, fontWeight: '700', color: colors.text.secondary, marginBottom: 12 },

  rateBox: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.primarySoft,
    borderRadius: 12,
    paddingVertical: 16,
    paddingHorizontal: 20,
  },
  rateSide: { alignItems: 'center' },
  rateLabel: { fontSize: 12, color: colors.text.secondary, marginBottom: 4 },
  rateValue: { fontSize: 22, fontWeight: '800', color: colors.text.primary },
  rateCashTag: { fontSize: 11, fontWeight: '700', color: colors.primaryDark, marginTop: 2 },
  rateCaption: { fontSize: 12, color: colors.text.secondary, marginTop: 10, textAlign: 'center' },

  serviceLine: { flexDirection: 'row', marginBottom: 4 },
  railChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: colors.primary,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 8,
  },
  railChipText: { fontSize: 12, fontWeight: '700', color: '#fff' },
  serviceRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 12 },
  serviceRowText: { fontSize: 14, color: colors.text.primary },

  reviewsHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  addReviewLink: { fontSize: 13, fontWeight: '700', color: colors.primaryDark, marginBottom: 12 },
  reviewRow: { paddingVertical: 12, borderTopWidth: 1, borderTopColor: colors.borderLight },
  reviewTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  reviewDate: { fontSize: 12, color: colors.text.light },
  reviewRateRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 8 },
  reviewRateText: { fontSize: 13, color: colors.text.secondary },
  reviewRateStrong: { fontWeight: '700', color: colors.text.primary },
  reviewComment: { fontSize: 14, color: colors.text.primary, marginTop: 8, lineHeight: 20, fontStyle: 'italic' },
  reviewAnon: { fontSize: 11, color: colors.text.light, marginTop: 8 },

  safetyCard: {
    backgroundColor: colors.primarySoft,
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
  },
  safetyHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 10 },
  safetyTitle: { fontSize: 14, fontWeight: '700', color: colors.text.primary },
  safetyRow: { flexDirection: 'row', gap: 8, marginTop: 6 },
  safetyBullet: { fontSize: 13, color: colors.primaryDark, lineHeight: 19 },
  safetyText: { flex: 1, fontSize: 13, color: colors.text.secondary, lineHeight: 19 },

  disclaimer: {
    flexDirection: 'row',
    backgroundColor: colors.infoLight,
    borderRadius: 12,
    padding: 12,
    gap: 8,
  },
  disclaimerText: { flex: 1, fontSize: 12, color: colors.text.secondary, lineHeight: 17 },

  reportLink: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 14,
  },
  reportLinkText: { fontSize: 12, color: colors.text.light, textDecorationLine: 'underline' },

  footer: {
    backgroundColor: '#fff',
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingHorizontal: 16,
    paddingTop: 12,
  },
  whatsappBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: WHATSAPP_GREEN,
    borderRadius: 14,
    height: 52,
  },
  whatsappText: { color: '#fff', fontSize: 16, fontWeight: '700' },
});

export default FinancieraDetailScreen;
