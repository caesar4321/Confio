import React, { useMemo } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, RouteProp, useRoute } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';

type ReferralActionRouteProp = RouteProp<MainStackParamList, 'ReferralActionPrompt'>;

export const ReferralActionPromptScreen: React.FC = () => {
  const navigation = useNavigation();
  const route = useRoute<ReferralActionRouteProp>();
  const event = route.params?.event || 'top_up';

  const stepOptions = useMemo(() => ({
    top_up: {
      title: 'Desbloquea tu bono de 5 $CONFIO',
      steps: [
        'Tienes 5 $CONFIO bloqueados en tu cuenta',
        'Haz una recarga de 20 USDC o más para activarlos',
        '¡Listo! El bono se desbloquea al instante',
      ],
      requirement:
        'El bono está reservado para ti. Solo necesitas completar tu primera recarga de 20 USDC (con tarjeta o cripto) para desbloquearlo y usarlo.',
      actions: [
        {
          label: 'Recargar en Confío',
          icon: 'credit-card',
          onPress: () =>
            navigation.navigate('TopUp' as never),
        },
        {
          label: 'Depositar USDC/cUSD',
          icon: 'download',
          onPress: () =>
            navigation.navigate('USDCDeposit', {
              tokenType: 'usdc',
            }),
        },
      ],
      ctaLabel: 'Ver opciones de depósito',
      action: () =>
        navigation.navigate('USDCDeposit', {
          tokenType: 'cusd',
        }),
    },
    conversion_usdc_to_cusd: {
      title: 'Conversión USDC → cUSD',
      steps: ['Deposita USDC en su cuenta', 'Abre la pantalla de Conversión', 'Convierte al menos 20 USDC a cUSD'],
      requirement: 'Solo registramos la primera conversión exitosa de 20 USDC o más para liberar el bono.',
      ctaLabel: 'Ir a Convertir',
      action: () => navigation.navigate('USDCConversion'),
    },
  }), [navigation]);

  const nextSteps = stepOptions[event as keyof typeof stepOptions] || stepOptions.top_up;

  const renderActions = () => {
    if (Array.isArray(nextSteps.actions) && nextSteps.actions.length > 0) {
      return (
        <View style={styles.actionButtons}>
          {nextSteps.actions.map((btn) => (
            <TouchableOpacity
              key={btn.label}
              style={[
                styles.optionButton,
                btn.icon === 'download' && styles.secondaryOptionButton,
              ]}
              onPress={btn.onPress}>
              <Icon name={btn.icon} size={18} color="#fff" />
              <Text style={styles.optionButtonText}>{btn.label}</Text>
            </TouchableOpacity>
          ))}
        </View>
      );
    }
    return (
      <TouchableOpacity style={styles.primaryButton} onPress={nextSteps.action}>
        <Text style={styles.primaryButtonText}>{nextSteps.ctaLabel}</Text>
        <Icon name="chevron-right" size={18} color="#fff" />
      </TouchableOpacity>
    );
  };

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity style={styles.backButton} onPress={() => navigation.goBack()}>
          <Icon name="arrow-left" size={20} color="#111827" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Acción requerida</Text>
      </View>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.card}>
          <Text style={styles.eyebrow}>Activa tu bono</Text>
          <Text style={styles.title}>{nextSteps.title}</Text>
          <Text style={styles.subtitle}>
            Solo hay que completar la primera acción válida para liberar el bono en $CONFIO.
          </Text>

          <View style={styles.noteCard}>
            <Icon name="info" size={18} color="#0F766E" />
            <View style={styles.noteTextWrapper}>
              <Text style={styles.noteTitle}>Requisito único</Text>
              <Text style={styles.noteText}>{nextSteps.requirement}</Text>
            </View>
          </View>

          <View style={styles.stepList}>
            {nextSteps.steps.map((step, index) => (
              <View key={step} style={styles.stepRow}>
                <View style={styles.stepNumberWrap}>
                  <Text style={styles.stepNumber}>{index + 1}</Text>
                </View>
                <Text style={styles.stepText}>{step}</Text>
              </View>
            ))}
          </View>

          {renderActions()}
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
  card: { backgroundColor: '#fff', borderRadius: 24, padding: 24, shadowColor: '#0F172A', shadowOffset: { width: 0, height: 12 }, shadowOpacity: 0.08, shadowRadius: 20 },
  eyebrow: { fontSize: 12, fontWeight: '600', color: '#10B981', textTransform: 'uppercase', marginBottom: 8 },
  title: { fontSize: 24, fontWeight: '700', color: '#111827', marginBottom: 12 },
  subtitle: { fontSize: 15, color: '#6B7280', lineHeight: 22 },
  noteCard: {
    marginTop: 18,
    flexDirection: 'row',
    gap: 12,
    padding: 14,
    borderRadius: 16,
    backgroundColor: '#E0F2FE',
  },
  noteTextWrapper: { flex: 1 },
  noteTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: '#0F172A',
    marginBottom: 4,
  },
  noteText: {
    fontSize: 13,
    color: '#0F172A',
    lineHeight: 18,
  },
  stepList: { marginTop: 20 },
  stepRow: { flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 10 },
  stepNumberWrap: { width: 32, height: 32, borderRadius: 16, backgroundColor: '#ECFDF5', justifyContent: 'center', alignItems: 'center' },
  stepNumber: { fontWeight: '600', color: '#047857' },
  stepText: { flex: 1, fontSize: 14, color: '#374151' },
  primaryButton: {
    marginTop: 24,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 14,
    borderRadius: 14,
    backgroundColor: '#10B981',
  },
  primaryButtonText: { color: '#fff', fontWeight: '600', fontSize: 15 },
  actionButtons: {
    marginTop: 24,
    flexDirection: 'column',
    gap: 12,
  },
  optionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 14,
    borderRadius: 14,
    backgroundColor: '#10B981',
  },
  secondaryOptionButton: {
    backgroundColor: '#0F766E',
  },
  optionButtonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 15,
  },
});
