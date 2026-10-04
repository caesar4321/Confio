// Confio Assistant+: US$9.99/month, priced per country by the stores. The price
// shown is the store's own localized price (never hardcoded), and the
// server decides entitlement after verifying the purchase with the store.
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useApolloClient } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from '../components/common/AppText';
import type { AssistantPlan } from './api';
import { buy, isBillingAvailable, loadProduct, manageSubscriptions, restore, type StoreProduct } from './billingClient';
import AssistantMascot from './AssistantMascot';
import { navigationRef } from '../navigation/RootNavigation';

const EMERALD = '#047857';

const PERKS: { icon: string; title: string; body: string }[] = [
  { icon: 'phone-call', title: 'Habla con Confio Assistant', body: 'Conversación por voz en tiempo real, como una llamada.' },
  { icon: 'bar-chart-2', title: 'Más análisis', body: 'Análisis de tus movimientos y muchos más mensajes al día.' },
];

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

export default function AssistantPlusPanel({ plan, profile, onPlan, onClose, onLeave }: Props) {
  const client = useApolloClient();
  const [product, setProduct] = useState<StoreProduct | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<'buy' | 'restore' | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    if (!plan?.productId || !isBillingAvailable) {
      setLoading(false);
      return undefined;
    }
    loadProduct(plan.productId)
      .then((p) => alive && setProduct(p))
      .catch(() => alive && setProduct(null))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [plan?.productId]);

  const subscribe = async () => {
    if (!plan) {
      return;
    }
    setBusy('buy');
    setMessage(null);
    try {
      const outcome = await buy(client, plan.productId, plan.billingToken);
      if (outcome.ok) {
        onPlan(outcome.plan);
      } else if (outcome.reason !== 'cancelled') {
        setMessage(outcome.message || 'No pudimos completar la compra.');
      }
    } catch {
      setMessage('No pudimos completar la compra.');
    } finally {
      setBusy(null);
    }
  };

  const doRestore = async () => {
    setBusy('restore');
    setMessage(null);
    try {
      const outcome = await restore(client);
      if (outcome.ok) {
        onPlan(outcome.plan);
      } else {
        setMessage(outcome.message || 'No encontramos una suscripción.');
      }
    } catch {
      setMessage('No pudimos consultar tus compras.');
    } finally {
      setBusy(null);
    }
  };

  const openLegal = (docType: 'terms' | 'privacy') => {
    onLeave();
    setTimeout(() => (navigationRef as any).navigate('Main', { screen: 'LegalDocument', params: { docType } }), 250);
  };

  const store = Platform.OS === 'ios' ? 'App Store' : 'Google Play';

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
        <Text style={styles.allowance}>
          Este mes te quedan {plan.voiceMinutesLeft} de {plan.voiceMinutes} minutos de voz.
        </Text>
      ) : null}

      {message ? <Text style={styles.message}>{message}</Text> : null}

      {plan?.isPlus ? (
        <Pressable style={styles.secondaryButton} onPress={() => manageSubscriptions()}>
          <Text style={styles.secondaryText}>Administrar suscripción</Text>
        </Pressable>
      ) : !isBillingAvailable ? (
        <Text style={styles.message}>Actualiza la app para suscribirte.</Text>
      ) : loading ? (
        <ActivityIndicator color={EMERALD} style={styles.loader} />
      ) : !product ? (
        <Text style={styles.message}>Assistant+ todavía no está disponible en tu tienda.</Text>
      ) : (
        <>
          <Pressable style={[styles.primaryButton, busy && styles.disabled]} onPress={subscribe} disabled={!!busy}>
            {busy === 'buy' ? (
              <ActivityIndicator color="#FFFFFF" />
            ) : (
              <Text style={styles.primaryText}>Suscribirme · {product.displayPrice} al mes</Text>
            )}
          </Pressable>
          <Text style={styles.fine}>
            Se cobra a tu cuenta de {store} y se renueva cada mes por {product.displayPrice} hasta que la canceles.
            Puedes cancelar cuando quieras desde {store}, al menos 24 horas antes de la renovación.
          </Text>
        </>
      )}

      <View style={styles.links}>
        {!plan?.isPlus && isBillingAvailable ? (
          <Pressable onPress={doRestore} disabled={!!busy}>
            <Text style={styles.link}>{busy === 'restore' ? 'Restaurando…' : 'Restaurar compras'}</Text>
          </Pressable>
        ) : null}
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
  message: { fontSize: 14, color: '#B91C1C', marginTop: 12, textAlign: 'center' },
  loader: { marginTop: 20 },
  primaryButton: {
    marginTop: 20,
    height: 52,
    borderRadius: 16,
    backgroundColor: EMERALD,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryText: { color: '#FFFFFF', fontSize: 16, fontWeight: '700' },
  disabled: { opacity: 0.6 },
  secondaryButton: {
    marginTop: 20,
    height: 48,
    borderRadius: 14,
    backgroundColor: '#F3F4F6',
    alignItems: 'center',
    justifyContent: 'center',
  },
  secondaryText: { color: '#374151', fontSize: 15, fontWeight: '600' },
  fine: { fontSize: 12, color: '#6B7280', marginTop: 10, textAlign: 'center', lineHeight: 17 },
  links: { flexDirection: 'row', justifyContent: 'center', gap: 20, marginTop: 18 },
  link: { fontSize: 13, color: EMERALD, fontWeight: '600' },
  back: { alignSelf: 'center', marginTop: 18, padding: 8 },
  backText: { fontSize: 14, color: '#6B7280' },
});
