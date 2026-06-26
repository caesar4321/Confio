import React, { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Linking,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useMutation, useQuery } from '@apollo/client';
import {
  GET_ACTIVE_VENEZUELA_HUMANITARIAN_CAMPAIGN,
  GET_MY_HUMANITARIAN_VOLUNTEER_APPLICATION,
} from '../apollo/queries';
import { APPLY_HUMANITARIAN_VOLUNTEER } from '../apollo/mutations';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';

const CAMPAIGN_SLUG = 'venezuela-2026-earthquake';
type Navigation = NativeStackNavigationProp<MainStackParamList>;

function formatAmount(value?: string | number | null) {
  const n = typeof value === 'number' ? value : parseFloat(String(value || '0'));
  return `${Number.isFinite(n) ? n.toLocaleString('es-VE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '0.00'} cUSD`;
}

function shortHash(hash?: string | null) {
  if (!hash) return '';
  return hash.length > 14 ? `${hash.slice(0, 7)}...${hash.slice(-5)}` : hash;
}

function normalizeStatus(status?: string | null) {
  return String(status || '').toLowerCase();
}

export const HumanitarianAidScreen = () => {
  const navigation = useNavigation<Navigation>();
  const [serviceArea, setServiceArea] = useState('');
  const [localPhone, setLocalPhone] = useState('');
  const [notes, setNotes] = useState('');
  const { data, loading, error, refetch } = useQuery(GET_ACTIVE_VENEZUELA_HUMANITARIAN_CAMPAIGN, {
    fetchPolicy: 'cache-and-network',
  });
  const campaign = data?.activeVenezuelaHumanitarianCampaign;
  const {
    data: myApplicationData,
    refetch: refetchApplication,
  } = useQuery(GET_MY_HUMANITARIAN_VOLUNTEER_APPLICATION, {
    variables: { slug: CAMPAIGN_SLUG },
    skip: !campaign?.slug,
    fetchPolicy: 'cache-and-network',
  });
  const [applyVolunteer, { loading: applying }] = useMutation(APPLY_HUMANITARIAN_VOLUNTEER);

  const proofCount = useMemo(() => {
    return (campaign?.releases || []).reduce((count: number, release: any) => {
      return count + (release?.proofLinks?.length || 0);
    }, 0);
  }, [campaign?.releases]);

  const onApply = async () => {
    try {
      const res = await applyVolunteer({
        variables: {
          campaignSlug: CAMPAIGN_SLUG,
          serviceArea: serviceArea.trim(),
          localPhone: localPhone.trim(),
          notes: notes.trim(),
        },
      });
      const payload = res.data?.applyHumanitarianVolunteer;
      if (!payload?.success) {
        if (payload?.error === 'venezuelan_didit_kyc_required') {
          Alert.alert('Verificación requerida', 'Para ser voluntario necesitas KYC Didit verificado como Venezuela.');
        } else {
          Alert.alert('No se pudo enviar', payload?.error || 'Intenta de nuevo.');
        }
        return;
      }
      await refetchApplication();
      Alert.alert('Solicitud enviada', 'El equipo revisará tu solicitud antes de liberar fondos.');
    } catch (e: any) {
      Alert.alert('No se pudo enviar', e?.message || 'Intenta de nuevo.');
    }
  };

  const onDonate = () => {
    const vaultAddress = String(campaign?.vaultAddress || '').trim();
    if (!vaultAddress) {
      Alert.alert(
        'Donaciones pronto',
        'Estamos activando el vault transparente en Algorand. Cuando esté listo podrás donar cUSD desde aquí y ver cada entrega publicada.',
      );
      return;
    }
    navigation.navigate('SendWithAddress', {
      tokenType: 'cusd',
      prefilledAddress: vaultAddress,
    });
  };

  if (loading && !campaign) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  if (error || !campaign) {
    return (
      <ScrollView
        style={styles.container}
        contentContainerStyle={styles.centerContent}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={refetch} />}
      >
        <Text style={styles.emptyFlag}>🇻🇪</Text>
        <Text style={styles.emptyTitle}>Ayuda humanitaria</Text>
        <Text style={styles.emptyText}>Todavía no hay una campaña activa.</Text>
      </ScrollView>
    );
  }

  const application = myApplicationData?.myHumanitarianVolunteerApplication;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={refetch} />}
    >
      <View style={styles.hero}>
        <View style={styles.heroIcon}>
          <Text style={styles.heroFlag}>🇻🇪</Text>
        </View>
        <Text style={styles.kicker}>Confío Ayuda Humanitaria</Text>
        <Text style={styles.title}>Venezuela: ayuda directa y transparente</Text>
        <Text style={styles.description}>
          Dona cUSD para que voluntarios venezolanos verificados compren y entreguen ayuda local. Cada entrega queda publicada con monto, estado y prueba.
        </Text>
        <TouchableOpacity style={styles.donateButton} onPress={onDonate} activeOpacity={0.9}>
          <Icon name="send" size={17} color="#FFFFFF" />
          <Text style={styles.donateButtonText}>
            {campaign.vaultAddress ? 'Donar cUSD' : 'Donaciones pronto'}
          </Text>
        </TouchableOpacity>
        {!campaign.vaultAddress && (
          <Text style={styles.donateHint}>El vault transparente se mostrará aquí apenas esté activo.</Text>
        )}
      </View>

      <View style={styles.statsGrid}>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Recaudado</Text>
          <Text style={styles.statValue}>{formatAmount(campaign.totalDonated)}</Text>
        </View>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Entregado</Text>
          <Text style={styles.statValue}>{formatAmount(campaign.totalReleased)}</Text>
        </View>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Donantes</Text>
          <Text style={styles.statValue}>{campaign.donationCount}</Text>
        </View>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Pruebas</Text>
          <Text style={styles.statValue}>{proofCount}</Text>
        </View>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Entregas publicadas</Text>
        {(campaign.releases || []).map((release: any) => (
          <View key={release.publicId} style={styles.row}>
            <View style={styles.rowTop}>
              <Text style={styles.rowTitle}>{release.volunteerName}</Text>
              <Text style={styles.amount}>{formatAmount(release.amount)}</Text>
            </View>
            <Text style={styles.rowText}>{release.purpose}</Text>
            {!!release.publicNote && <Text style={styles.note}>{release.publicNote}</Text>}
            <View style={styles.metaRow}>
              <Text style={styles.status}>{normalizeStatus(release.status) === 'proof_published' ? 'prueba publicada' : 'prueba en camino'}</Text>
              {!!release.transactionHash && <Text style={styles.hash}>{shortHash(release.transactionHash)}</Text>}
            </View>
            {(release.proofLinks || []).map((proof: any) => (
              <TouchableOpacity
                key={`${release.publicId}-${proof.url}`}
                style={styles.proofButton}
                onPress={() => Linking.openURL(proof.url)}
              >
                <Icon name="external-link" size={14} color="#0F766E" />
                <Text style={styles.proofText}>{proof.title || proof.platform || 'Ver prueba'}</Text>
              </TouchableOpacity>
            ))}
          </View>
        ))}
        {(!campaign.releases || campaign.releases.length === 0) && (
          <Text style={styles.emptyText}>Las primeras entregas aparecerán aquí con monto, voluntario y prueba pública.</Text>
        )}
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Donaciones recientes</Text>
        {(campaign.donations || []).map((donation: any) => (
          <View key={donation.publicId} style={styles.compactRow}>
            <Text style={styles.rowTitle}>{donation.donorDisplayName || 'Donante Confío'}</Text>
            <Text style={styles.amount}>{formatAmount(donation.amount)}</Text>
          </View>
        ))}
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Voluntarios en Venezuela</Text>
        {application ? (
          <Text style={styles.rowText}>Tu solicitud está en estado: {application.status}</Text>
        ) : (
          <>
            <TextInput
              value={serviceArea}
              onChangeText={setServiceArea}
              placeholder="Zona donde puedes ayudar"
              style={styles.input}
              placeholderTextColor="#94A3B8"
            />
            <TextInput
              value={localPhone}
              onChangeText={setLocalPhone}
              placeholder="Teléfono local"
              style={styles.input}
              placeholderTextColor="#94A3B8"
            />
            <TextInput
              value={notes}
              onChangeText={setNotes}
              placeholder="Qué puedes comprar o distribuir"
              style={[styles.input, styles.textArea]}
              multiline
              placeholderTextColor="#94A3B8"
            />
            <TouchableOpacity style={styles.primaryButton} onPress={onApply} disabled={applying}>
              {applying ? <ActivityIndicator color="#FFFFFF" /> : <Text style={styles.primaryButtonText}>Postular como voluntario</Text>}
            </TouchableOpacity>
          </>
        )}
      </View>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  content: { padding: 16, paddingBottom: 32 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.neutral },
  centerContent: { flexGrow: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  hero: { paddingTop: 18, paddingBottom: 20 },
  heroIcon: { width: 48, height: 48, borderRadius: 24, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center', marginBottom: 14 },
  heroFlag: { fontSize: 26 },
  kicker: { fontSize: 13, fontWeight: '700', color: colors.primaryDark, marginBottom: 6 },
  title: { fontSize: 27, lineHeight: 33, fontWeight: '800', color: colors.textFlat, marginBottom: 8 },
  description: { fontSize: 15, lineHeight: 22, color: colors.textSecondary },
  donateButton: { marginTop: 16, height: 48, borderRadius: 8, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 8 },
  donateButtonText: { color: colors.white, fontSize: 15, fontWeight: '800' },
  donateHint: { marginTop: 8, fontSize: 13, lineHeight: 18, color: colors.textSecondary },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 18 },
  stat: { width: '48%', backgroundColor: colors.background, borderRadius: 8, padding: 14, borderWidth: 1, borderColor: colors.border },
  statLabel: { fontSize: 12, color: colors.textSecondary, marginBottom: 6 },
  statValue: { fontSize: 17, fontWeight: '800', color: colors.textFlat },
  section: { marginTop: 14 },
  sectionTitle: { fontSize: 18, fontWeight: '800', color: colors.textFlat, marginBottom: 10 },
  row: { backgroundColor: colors.background, borderRadius: 8, borderWidth: 1, borderColor: colors.border, padding: 14, marginBottom: 10 },
  compactRow: { backgroundColor: colors.background, borderRadius: 8, borderWidth: 1, borderColor: colors.border, padding: 14, marginBottom: 8, flexDirection: 'row', justifyContent: 'space-between', gap: 10 },
  rowTop: { flexDirection: 'row', justifyContent: 'space-between', gap: 12, marginBottom: 6 },
  rowTitle: { flex: 1, fontSize: 15, fontWeight: '700', color: colors.textFlat },
  rowText: { fontSize: 14, lineHeight: 20, color: colors.textSecondary },
  note: { fontSize: 13, lineHeight: 19, color: colors.textSecondary, marginTop: 6 },
  amount: { fontSize: 14, fontWeight: '800', color: colors.primaryDark },
  metaRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 10, gap: 10 },
  status: { fontSize: 12, color: colors.textSecondary, textTransform: 'capitalize' },
  hash: { fontSize: 12, color: colors.textSecondary },
  proofButton: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 10 },
  proofText: { fontSize: 13, fontWeight: '700', color: colors.primaryDark },
  emptyFlag: { fontSize: 30 },
  emptyTitle: { fontSize: 18, fontWeight: '800', color: colors.textFlat, marginTop: 12 },
  emptyText: { fontSize: 14, lineHeight: 20, color: colors.textSecondary },
  input: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.borderMedium, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 12, marginBottom: 10, fontSize: 15, color: colors.textFlat },
  textArea: { minHeight: 88, textAlignVertical: 'top' },
  primaryButton: { height: 48, borderRadius: 8, backgroundColor: colors.secondary, alignItems: 'center', justifyContent: 'center' },
  primaryButtonText: { color: colors.white, fontSize: 15, fontWeight: '800' },
});
