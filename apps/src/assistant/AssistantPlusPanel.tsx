// Confio Assistant+. The app has no in-app purchases: this panel only shows
// what Assistant+ includes and, for anyone the server already marks as Plus,
// its status. Subscriptions are managed in the store's own page.
import React from 'react';
import { Linking, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../components/common/AppText';
import type { AssistantPlan } from './api';
import AssistantMascot from './AssistantMascot';
import { navigationRef } from '../navigation/RootNavigation';

const EMERALD = '#047857';

const PERKS: { icon: string; title: string; body: string }[] = [
  { icon: 'phone-call', title: 'Habla con Confio Assistant', body: 'Conversación por voz en tiempo real, como una llamada.' },
  { icon: 'bar-chart-2', title: 'Más análisis', body: 'Análisis de tus movimientos y muchos más mensajes al día.' },
];

// The store the subscription was bought in (it may differ from this phone's).
function storeOf(plan: AssistantPlan | null) {
  const platform = (plan?.platform || Platform.OS).toLowerCase();
  return platform === 'ios' || platform === 'apple' || platform === 'app_store'
    ? { name: 'App Store', url: 'https://apps.apple.com/account/subscriptions' }
    : { name: 'Google Play', url: 'https://play.google.com/store/account/subscriptions?package=com.Confio.Confio' };
}

type Props = {
  plan: AssistantPlan | null;
  profile: { mascot?: string; mascotColor?: string; customPetUrl?: string | null } | null;
  onPlan: (plan: AssistantPlan) => void;
  onClose: () => void;
  // Close the whole Confio Assistant box (before navigating elsewhere).
  onLeave: () => void;
};

function formatDate(iso?: string | null) {
  if (!iso) {
    return '';
  }
  try {
    return new Date(iso).toLocaleDateString('es', { day: 'numeric', month: 'long', year: 'numeric' });
  } catch {
    return iso.slice(0, 10);
  }
}

export default function AssistantPlusPanel({ plan, profile, onClose, onLeave }: Props) {
  const openLegal = (docType: 'terms' | 'privacy') => {
    onLeave();
    setTimeout(() => (navigationRef as any).navigate('Main', { screen: 'LegalDocument', params: { docType } }), 250);
  };

  const { name: store, url: storeUrl } = storeOf(plan);

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <View style={styles.hero}>
        <AssistantMascot kind={profile?.mascot} imageUrl={profile?.customPetUrl} color={profile?.mascotColor} size={84} mood="happy" />
        <Text style={styles.title}>Confio Assistant+</Text>
        {plan?.isPlus ? (
          <Text style={styles.subtitle}>
            {plan.inGrace
              ? `Tu pago está pendiente en ${store}. Mantienes Assistant+ mientras se resuelve.`
              : plan.autoRenew === false
                ? `Activo hasta el ${formatDate(plan.expiresAt)}. No se renovará.`
                : `Activo. Se renueva el ${formatDate(plan.expiresAt)}.`}
          </Text>
        ) : (
          <Text style={styles.subtitle}>Tu asistente, ahora con voz.</Text>
        )}
      </View>

      {PERKS.map((perk) => (
        <View key={perk.title} style={styles.perk}>
          <View style={styles.perkIcon}>
            <Icon name={perk.icon} size={18} color={EMERALD} />
          </View>
          <View style={styles.perkText}>
            <Text style={styles.perkTitle}>{perk.title}</Text>
            <Text style={styles.perkBody}>{perk.body}</Text>
          </View>
        </View>
      ))}

      {plan?.isPlus ? (
        <>
          <Text style={styles.allowance}>
            Este mes te quedan {plan.voiceMinutesLeft} de {plan.voiceMinutes} minutos de voz.
          </Text>
          <Pressable style={styles.secondaryButton} onPress={() => Linking.openURL(storeUrl).catch(() => {})}>
            <Text style={styles.secondaryText}>Administrar suscripción</Text>
          </Pressable>
        </>
      ) : (
        <Text style={styles.message}>Assistant+ todavía no está disponible.</Text>
      )}

      <View style={styles.links}>
        <Pressable onPress={() => openLegal('terms')}>
          <Text style={styles.link}>Términos</Text>
        </Pressable>
        <Pressable onPress={() => openLegal('privacy')}>
          <Text style={styles.link}>Privacidad</Text>
        </Pressable>
      </View>
      <Pressable onPress={onClose} style={styles.back}>
        <Text style={styles.backText}>Volver al chat</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: 20, paddingBottom: 32 },
  hero: { alignItems: 'center', marginBottom: 16 },
  title: { fontSize: 24, fontWeight: '700', color: '#111827', marginTop: 8 },
  subtitle: { fontSize: 15, color: '#4B5563', marginTop: 4, textAlign: 'center' },
  perk: { flexDirection: 'row', gap: 12, paddingVertical: 10 },
  perkIcon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#ECFDF5',
    alignItems: 'center',
    justifyContent: 'center',
  },
  perkText: { flex: 1 },
  perkTitle: { fontSize: 15, fontWeight: '600', color: '#111827' },
  perkBody: { fontSize: 14, color: '#6B7280', marginTop: 2 },
  allowance: { fontSize: 14, color: '#065F46', marginTop: 12, textAlign: 'center' },
  message: { fontSize: 14, color: '#6B7280', marginTop: 16, textAlign: 'center' },
  secondaryButton: {
    marginTop: 20,
    height: 48,
    borderRadius: 14,
    backgroundColor: '#F3F4F6',
    alignItems: 'center',
    justifyContent: 'center',
  },
  secondaryText: { color: '#374151', fontSize: 15, fontWeight: '600' },
  links: { flexDirection: 'row', justifyContent: 'center', gap: 20, marginTop: 18 },
  link: { fontSize: 13, color: EMERALD, fontWeight: '600' },
  back: { alignSelf: 'center', marginTop: 18, padding: 8 },
  backText: { fontSize: 14, color: '#6B7280' },
});
