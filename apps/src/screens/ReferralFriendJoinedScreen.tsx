import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, RouteProp, useRoute } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';

type ReferralFriendJoinedRouteProp = RouteProp<MainStackParamList, 'ReferralFriendJoined'>;

export const ReferralFriendJoinedScreen: React.FC = () => {
  const navigation = useNavigation();
  const route = useRoute<ReferralFriendJoinedRouteProp>();
  const friendName = route.params?.friendName || 'tu amigo';
  const suggestedEvent = route.params?.event || 'top_up';

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity style={styles.backButton} onPress={() => navigation.goBack()}>
          <Icon name="arrow-left" size={20} color="#111827" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Referidos</Text>
      </View>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.card}>
          <Text style={styles.eyebrow}>Referidos Confío</Text>
          <Text style={styles.title}>¡{friendName} ya se unió!</Text>
          <Text style={styles.subtitle}>
            Tu amigo ya recibió sus 5 $CONFIO (bloqueados). Ahora solo falta desbloquearlos.
          </Text>

          <View style={styles.stepCard}>
            <Text style={styles.stepTitle}>¿Cómo desbloquear el bono?</Text>
            <View style={styles.stepRow}>
              <Icon name="lock" size={18} color="#10B981" />
              <Text style={styles.stepText}>
                El bono ya está en su cuenta, pero necesita una recarga para activarse.
              </Text>
            </View>
            <View style={styles.stepRow}>
              <Icon name="credit-card" size={18} color="#10B981" />
              <Text style={styles.stepText}>
                Guíalo para que recargue 20 USDC o más.
              </Text>
            </View>
            <View style={styles.stepRow}>
              <Icon name="check-circle" size={18} color="#10B981" />
              <Text style={styles.stepText}>¡Listo! El bono se desbloquea automáticamente para ambos.</Text>
            </View>
          </View>

          <View style={styles.actions}>
            <TouchableOpacity
              style={styles.primaryButton}
              onPress={() =>
                navigation.navigate('ReferralActionPrompt', {
                  event: suggestedEvent,
                })
              }
            >
              <Icon name="zap" size={18} color="#fff" />
              <Text style={styles.primaryButtonText}>Guiar a mi referido paso a paso</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.secondaryButton} onPress={() => navigation.navigate('Achievements')}>
              <Text style={styles.secondaryButtonText}>Ver requisitos del bono</Text>
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
  headerTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#111827',
  },
  content: { padding: 20, paddingTop: 12 },
  backButton: {},
  card: {
    backgroundColor: '#fff',
    borderRadius: 24,
    padding: 24,
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.08,
    shadowRadius: 20,
    elevation: 4,
  },
  eyebrow: {
    fontSize: 12,
    fontWeight: '600',
    color: '#10B981',
    textTransform: 'uppercase',
    marginBottom: 8,
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
    color: '#111827',
    marginBottom: 12,
  },
  subtitle: {
    fontSize: 15,
    color: '#6B7280',
    lineHeight: 22,
  },
  stepCard: {
    marginTop: 24,
    padding: 16,
    borderRadius: 16,
    backgroundColor: '#ECFDF5',
  },
  stepTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#064E3B',
    marginBottom: 12,
  },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginBottom: 12,
  },
  stepText: {
    flex: 1,
    fontSize: 14,
    color: '#047857',
    lineHeight: 20,
  },
  actions: {
    marginTop: 24,
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
