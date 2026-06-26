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
import { useMutation, useQuery } from '@apollo/client';
import {
  GET_ACTIVE_VENEZUELA_HUMANITARIAN_CAMPAIGN,
  GET_MY_HUMANITARIAN_VOLUNTEER_APPLICATION,
} from '../apollo/queries';
import { APPLY_HUMANITARIAN_VOLUNTEER } from '../apollo/mutations';

const CAMPAIGN_SLUG = 'venezuela-2026-earthquake';

function formatAmount(value?: string | number | null) {
  const n = typeof value === 'number' ? value : parseFloat(String(value || '0'));
  return `${Number.isFinite(n) ? n.toLocaleString('es-VE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '0.00'} cUSD`;
}

function shortHash(hash?: string | null) {
  if (!hash) return '';
  return hash.length > 14 ? `${hash.slice(0, 7)}...${hash.slice(-5)}` : hash;
}

export const HumanitarianAidScreen = () => {
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

  const pctReleased = useMemo(() => {
    const donated = parseFloat(campaign?.totalDonated || '0');
    const released = parseFloat(campaign?.totalReleased || '0');
    if (!donated) return 0;
    return Math.min(100, Math.round((released / donated) * 100));
  }, [campaign?.totalDonated, campaign?.totalReleased]);

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

  if (loading && !campaign) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color="#14B8A6" />
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
        <Icon name="heart" size={28} color="#14B8A6" />
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
          <Icon name="heart" size={24} color="#FFFFFF" />
        </View>
        <Text style={styles.kicker}>Confío Ayuda Humanitaria</Text>
        <Text style={styles.title}>{campaign.title}</Text>
        <Text style={styles.description}>{campaign.description}</Text>
      </View>

      <View style={styles.statsGrid}>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Donado</Text>
          <Text style={styles.statValue}>{formatAmount(campaign.totalDonated)}</Text>
        </View>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Liberado</Text>
          <Text style={styles.statValue}>{formatAmount(campaign.totalReleased)}</Text>
        </View>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Avances</Text>
          <Text style={styles.statValue}>{campaign.releaseCount}</Text>
        </View>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Ejecutado</Text>
          <Text style={styles.statValue}>{pctReleased}%</Text>
        </View>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Liberaciones y pruebas</Text>
        {(campaign.releases || []).map((release: any) => (
          <View key={release.publicId} style={styles.row}>
            <View style={styles.rowTop}>
              <Text style={styles.rowTitle}>{release.volunteerName}</Text>
              <Text style={styles.amount}>{formatAmount(release.amount)}</Text>
            </View>
            <Text style={styles.rowText}>{release.purpose}</Text>
            {!!release.publicNote && <Text style={styles.note}>{release.publicNote}</Text>}
            <View style={styles.metaRow}>
              <Text style={styles.status}>{release.status === 'proof_published' ? 'prueba publicada' : 'prueba pendiente'}</Text>
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
          <Text style={styles.emptyText}>Todavía no hay liberaciones confirmadas.</Text>
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
  container: { flex: 1, backgroundColor: '#F8FAFC' },
  content: { padding: 16, paddingBottom: 32 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#F8FAFC' },
  centerContent: { flexGrow: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  hero: { paddingTop: 18, paddingBottom: 18 },
  heroIcon: { width: 44, height: 44, borderRadius: 22, backgroundColor: '#14B8A6', alignItems: 'center', justifyContent: 'center', marginBottom: 14 },
  kicker: { fontSize: 13, fontWeight: '700', color: '#0F766E', marginBottom: 6 },
  title: { fontSize: 28, lineHeight: 34, fontWeight: '800', color: '#0F172A', marginBottom: 8 },
  description: { fontSize: 15, lineHeight: 22, color: '#475569' },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 18 },
  stat: { width: '48%', backgroundColor: '#FFFFFF', borderRadius: 8, padding: 14, borderWidth: 1, borderColor: '#E2E8F0' },
  statLabel: { fontSize: 12, color: '#64748B', marginBottom: 6 },
  statValue: { fontSize: 17, fontWeight: '800', color: '#0F172A' },
  section: { marginTop: 14 },
  sectionTitle: { fontSize: 18, fontWeight: '800', color: '#0F172A', marginBottom: 10 },
  row: { backgroundColor: '#FFFFFF', borderRadius: 8, borderWidth: 1, borderColor: '#E2E8F0', padding: 14, marginBottom: 10 },
  compactRow: { backgroundColor: '#FFFFFF', borderRadius: 8, borderWidth: 1, borderColor: '#E2E8F0', padding: 14, marginBottom: 8, flexDirection: 'row', justifyContent: 'space-between', gap: 10 },
  rowTop: { flexDirection: 'row', justifyContent: 'space-between', gap: 12, marginBottom: 6 },
  rowTitle: { flex: 1, fontSize: 15, fontWeight: '700', color: '#0F172A' },
  rowText: { fontSize: 14, lineHeight: 20, color: '#475569' },
  note: { fontSize: 13, lineHeight: 19, color: '#64748B', marginTop: 6 },
  amount: { fontSize: 14, fontWeight: '800', color: '#0F766E' },
  metaRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 10, gap: 10 },
  status: { fontSize: 12, color: '#64748B', textTransform: 'capitalize' },
  hash: { fontSize: 12, color: '#64748B' },
  proofButton: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 10 },
  proofText: { fontSize: 13, fontWeight: '700', color: '#0F766E' },
  emptyTitle: { fontSize: 18, fontWeight: '800', color: '#0F172A', marginTop: 12 },
  emptyText: { fontSize: 14, lineHeight: 20, color: '#64748B' },
  input: { backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: '#CBD5E1', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 12, marginBottom: 10, fontSize: 15, color: '#0F172A' },
  textArea: { minHeight: 88, textAlignVertical: 'top' },
  primaryButton: { height: 48, borderRadius: 8, backgroundColor: '#14B8A6', alignItems: 'center', justifyContent: 'center' },
  primaryButtonText: { color: '#FFFFFF', fontSize: 15, fontWeight: '800' },
});
