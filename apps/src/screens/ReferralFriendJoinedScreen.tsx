import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { useNavigation, RouteProp, useRoute } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';
import { Button } from '../components/common/Button';
import { Header } from '../navigation/Header';

type ReferralFriendJoinedRouteProp = RouteProp<MainStackParamList, 'ReferralFriendJoined'>;

export const ReferralFriendJoinedScreen: React.FC = () => {
  const navigation = useNavigation();
  const route = useRoute<ReferralFriendJoinedRouteProp>();
  const friendName = route.params?.friendName || 'tu amigo';
  const suggestedEvent = route.params?.event || 'top_up';

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Referidos"
        backgroundColor={colors.neutralDark}
        showBackButton
      />
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
              <Icon name="lock" size={18} color={colors.primaryDark} />
              <Text style={styles.stepText}>
                El bono ya está en su cuenta, pero necesita una recarga para activarse.
              </Text>
            </View>
            <View style={styles.stepRow}>
              <Icon name="credit-card" size={18} color={colors.primaryDark} />
              <Text style={styles.stepText}>
                Guíalo para que recargue 20 cUSD o más.
              </Text>
            </View>
            <View style={styles.stepRow}>
              <Icon name="check-circle" size={18} color={colors.primaryDark} />
              <Text style={styles.stepText}>¡Listo! El bono se desbloquea automáticamente para ambos.</Text>
            </View>
          </View>

          <View style={styles.actions}>
            <Button
              title="Guiar a mi referido paso a paso"
              onPress={() =>
                navigation.navigate('ReferralActionPrompt', {
                  event: suggestedEvent,
                })
              }
              icon={<Icon name="zap" size={18} color={colors.white} />}
            />
            <Button
              title="Ver requisitos del bono"
              variant="secondary"
              onPress={() => navigation.navigate('Achievements')}
              icon={<Icon name="chevron-right" size={18} color={colors.primaryDark} />}
              style={{ backgroundColor: colors.primarySoft, borderWidth: 0 }}
              textStyle={{ color: colors.primaryDark }}
            />
          </View>
        </View>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutralDark },
  content: { padding: 20, paddingTop: 12 },
  card: {
    backgroundColor: colors.white,
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
    color: colors.primaryDark,
    textTransform: 'uppercase',
    marginBottom: 8,
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
    color: colors.text.primary,
    marginBottom: 12,
  },
  subtitle: {
    fontSize: 15,
    color: colors.text.secondary,
    lineHeight: 22,
  },
  stepCard: {
    marginTop: 24,
    padding: 16,
    borderRadius: 16,
    backgroundColor: colors.primarySoft,
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
    color: colors.primaryDark,
    lineHeight: 20,
  },
  actions: {
    marginTop: 24,
    gap: 12,
  },
});
