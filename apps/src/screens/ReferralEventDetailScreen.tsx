import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { RouteProp, useNavigation, useRoute } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';

type ReferralEventDetailRouteProp = RouteProp<MainStackParamList, 'ReferralEventDetail'>;

const EVENT_COPY = {
  top_up: {
    eyebrow: 'Recarga completa',
    referee: {
      title: 'Tu saldo ya está en Confío',
      description: 'Aprovecha la recarga para invitar a otro amigo y repetir el bono. Conversión o envío son los próximos pasos.',
      tip: 'Convierte al menos 20 cUSD para activar el regalo automáticamente.',
    },
    referrer: {
      title: 'Tu referido recargó la billetera',
      description: 'Guíalo al siguiente paso (conversión a cUSD) para liberar los CONFIO del bono y vuelve a compartir tu enlace.',
      tip: 'Envíale tu guía paso a paso desde la app.',
    },
  },
  conversion_usdc_to_cusd: {
    eyebrow: 'Conversión confirmada',
    referee: {
      title: 'Tus CONFIO están reservados',
      description: 'Ya eres oficialmente elegible. Comparte tu enlace para que un nuevo amigo reciba el mismo beneficio.',
      tip: 'Abre “Invita y gana” para obtener tu enlace personal.',
    },
    referrer: {
      title: 'Tu amigo ya convirtió a cUSD',
      description: 'Tus CONFIO quedaron asegurados. Aprovecha el momentum y comparte tu enlace con otra persona.',
      tip: 'Revisa Mi Progreso Viral para enviar plantillas y obtener más referidos.',
    },
  },
  send: {
    eyebrow: 'Primer envío',
    referee: {
      title: 'Completaste tu primer envío',
      description: 'Cuenta cómo fue tu experiencia y comparte tu enlace para que otro amigo desbloquee los CONFIO.',
      tip: 'Enviar invitaciones desde Mi Progreso Viral sólo toma un minuto.',
    },
    referrer: {
      title: 'Tu referido envió su primer pago',
      description: 'Los bonos quedaron listos. Sigue impulsando tu comunidad compartiendo otro enlace.',
      tip: 'Comparte los resultados en redes sociales y copia tu código.',
    },
  },
  payment: {
    eyebrow: 'Pago con QR',
    referee: {
      title: 'Pagaste con Confío',
      description: 'Demuestra que pagar con stablecoins es fácil. Comparte tu experiencia y obtén más recompensas.',
      tip: 'Usa las plantillas de “Viral” para explicar el proceso.',
    },
    referrer: {
      title: 'Tu invitado pagó a un comercio',
      description: 'Excelente indicador de confianza. Invita a comercios o usuarios para replicar el flujo.',
      tip: 'Comparte tus casos de uso en tu comunidad.',
    },
  },
  p2p_trade: {
    eyebrow: 'Trade P2P',
    referee: {
      title: 'Primer intercambio exitoso',
      description: 'Ya sabes cómo entrar y salir de stablecoins. Invita a tu círculo y multiplica los bonos.',
      tip: 'Muestra en redes cómo cerraste el trade.',
    },
    referrer: {
      title: 'Tu referido dominó el P2P',
      description: 'Es el mejor momento para compartir otro enlace y seguir acumulando CONFIO.',
      tip: 'Refuerza la narrativa con historias en Instagram/TikTok.',
    },
  },
} as const;

export const ReferralEventDetailScreen: React.FC = () => {
  const navigation = useNavigation();
  const route = useRoute<ReferralEventDetailRouteProp>();
  const event = route.params?.event as keyof typeof EVENT_COPY;
  const role = (route.params?.role === 'referrer' ? 'referrer' : 'referee') as 'referee' | 'referrer';
  const friendName = route.params?.friendName || 'tu referido';

  const copy = EVENT_COPY[event] || EVENT_COPY.top_up;
  const roleCopy = copy[role];

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity style={styles.backButton} onPress={() => navigation.goBack()}>
          <Icon name="arrow-left" size={20} color="#111827" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Progreso de referidos</Text>
      </View>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.card}>
          <Text style={styles.eyebrow}>{copy.eyebrow}</Text>
          <Text style={styles.title}>{roleCopy.title}</Text>
          <Text style={styles.subtitle}>{roleCopy.description}</Text>
          <View style={styles.friendPill}>
            <Icon name="user" size={16} color="#047857" />
            <Text style={styles.friendText}>{friendName}</Text>
          </View>
          <View style={styles.tipCard}>
            <Icon name="zap" size={18} color="#0F766E" />
            <View style={styles.tipTextWrapper}>
              <Text style={styles.tipTitle}>Siguiente movimiento</Text>
              <Text style={styles.tipText}>{roleCopy.tip}</Text>
            </View>
          </View>
          <View style={styles.actions}>
            <TouchableOpacity style={styles.primaryButton} onPress={() => navigation.navigate('MiProgresoViral')}>
              <Icon name="share-2" size={18} color="#fff" />
              <Text style={styles.primaryButtonText}>Compartir mi invitación</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.secondaryButton}
              onPress={() =>
                navigation.navigate('ReferralActionPrompt', {
                  event: route.params?.event,
                })
              }
            >
              <Text style={styles.secondaryButtonText}>Ver pasos sugeridos</Text>
              <Icon name="chevron-right" size={18} color="#10B981" />
            </TouchableOpacity>
          </View>
        </View>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F3F4F6' },
  header: {
    paddingTop: 56,
    paddingHorizontal: 20,
    paddingBottom: 8,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  backButton: {},
  headerTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#111827',
  },
  content: { padding: 20, paddingTop: 12 },
  card: {
    backgroundColor: '#fff',
    borderRadius: 24,
    padding: 24,
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.08,
    shadowRadius: 20,
    elevation: 4,
    gap: 16,
  },
  eyebrow: {
    fontSize: 12,
    fontWeight: '600',
    color: '#10B981',
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
    color: '#111827',
  },
  subtitle: {
    fontSize: 15,
    color: '#4B5563',
    lineHeight: 22,
  },
  friendPill: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
    backgroundColor: '#ECFDF5',
    gap: 8,
  },
  friendText: { color: '#047857', fontWeight: '600' },
  tipCard: {
    flexDirection: 'row',
    gap: 12,
    padding: 16,
    borderRadius: 16,
    backgroundColor: '#E0F2FE',
  },
  tipTextWrapper: { flex: 1 },
  tipTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: '#0F172A',
    marginBottom: 4,
  },
  tipText: {
    fontSize: 13,
    color: '#0F172A',
    lineHeight: 18,
  },
  actions: {
    marginTop: 12,
    gap: 12,
  },
  primaryButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 14,
    borderRadius: 14,
    backgroundColor: '#10B981',
  },
  primaryButtonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 15,
  },
  secondaryButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: '#ECFDF5',
  },
  secondaryButtonText: {
    color: '#047857',
    fontWeight: '600',
    fontSize: 14,
  },
});

