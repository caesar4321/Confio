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
      title: 'Deposita desde Confío o exchanges',
      steps: [
        'Elige Recargar dentro de Confío o Depositar desde otro exchange',
        'Si recarga en Confío, sigue las instrucciones para pagar con tarjeta o vendedores P2P',
        'Si deposita desde Binance/Coinbase, envía cUSD a su dirección Confío',
      ],
      requirement:
        'La primera recarga o depósito por al menos 20 USD desbloquea el bono. Si su país no admite tarjetas, puede transferir cUSD/USDC desde Binance, Coinbase u otro exchange hacia su dirección Confío.',
      actions: [
        {
          label: 'Recargar en Confío',
          icon: 'credit-card',
          onPress: () =>
            navigation.navigate('USDCDeposit', {
              tokenType: 'cusd',
            }),
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
    send: {
      title: 'Primer envío completado',
      steps: ['Elige un contacto o dirección Confío', 'Ingresa el monto a enviar', 'Confirma la operación'],
      requirement: 'Un solo envío completado desbloquea el bono. Después del primero no necesita repetirlo para este referido.',
      ctaLabel: 'Ir a Enviar',
      action: () => navigation.navigate('SendToFriend', { tokenType: 'cusd', friend: { name: '', avatar: '', phone: '', isOnConfio: true } }),
    },
    conversion_usdc_to_cusd: {
      title: 'Conversión USDC → cUSD',
      steps: ['Deposita USDC en su cuenta', 'Abre la pantalla de Conversión', 'Convierte un equivalente mínimo de 20 en cUSD'],
      requirement: 'Solo registramos la primera conversión exitosa del referido para liberar el bono.',
      ctaLabel: 'Ir a Convertir',
      action: () => navigation.navigate('USDCConversion'),
    },
    payment: {
      title: 'Pagar a un comercio',
      steps: ['El comercio genera un QR Confío', 'Escanéalo desde la app', 'Confirma el pago'],
      requirement: 'Un pago exitoso es suficiente; no necesita hacer más para este bono.',
      ctaLabel: 'Escanear un pago',
      action: () => navigation.navigate('Scan', { mode: 'pagar' }),
    },
    p2p_trade: {
      title: 'Primer trade P2P',
      steps: ['Explora ofertas disponibles', 'Confirma el pago fiat al vendedor', 'Recibe los cUSD en Confío'],
      requirement: 'El bono solo requiere el primer trade exitoso de tu referido, sin importar el monto mientras cumpla el mínimo.',
      ctaLabel: 'Explorar P2P',
      action: () => navigation.navigate('Exchange', { showMyOffers: false }),
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
