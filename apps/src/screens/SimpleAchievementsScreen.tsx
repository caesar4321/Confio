import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { NavigationProp } from '@react-navigation/native';
import { useQuery } from '@apollo/client';
import { gql } from '@apollo/client';
import LinearGradient from 'react-native-linear-gradient';

const GET_CORE_ACHIEVEMENTS = gql`
  query GetCoreAchievements {
    achievementTypes(category: "onboarding") {
      id
      slug
      name
      description
      confioReward
    }
    userAchievements {
      id
      status
      achievementType {
        slug
      }
    }
    myConfioBalance {
      totalEarned
      totalLocked
      availableBalance
    }
  }
`;

interface SimpleAchievementsScreenProps {
  navigation: NavigationProp<any>;
}

export const SimpleAchievementsScreen: React.FC<SimpleAchievementsScreenProps> = ({ navigation }) => {
  const { data, loading } = useQuery(GET_CORE_ACHIEVEMENTS, {
    fetchPolicy: 'cache-and-network',
  });

  if (loading && !data) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#00BFA5" />
      </View>
    );
  }

  const balance = data?.myConfioBalance?.totalEarned || 0;
  const hasFirstTransaction = data?.userAchievements?.some(
    (ua: any) => ua.achievementType.slug === 'first_transaction' && ua.status === 'earned'
  );
  const hasDollarMilestone = data?.userAchievements?.some(
    (ua: any) => ua.achievementType.slug === 'dollar_milestone' && ua.status === 'earned'
  );

  return (
    <ScrollView style={styles.container}>
      {/* Simple Header */}
      <LinearGradient
        colors={['#00BFA5', '#008F7A']}
        style={styles.header}
      >
        <Text style={styles.headerTitle}>Gana $CONFIO</Text>
        <Text style={styles.balance}>{balance.toFixed(0)} $CONFIO</Text>
        <Text style={styles.balanceSubtext}>ganados hasta ahora</Text>
      </LinearGradient>

      {/* Core Message */}
      <View style={styles.mainCard}>
        <Text style={styles.mainTitle}>🎁 Gana 4 $CONFIO por cada $1</Text>
        <Text style={styles.mainDescription}>
          Envía o recibe al menos $1 y tanto tú como la otra persona ganan 4 $CONFIO cada uno
        </Text>
        
        {!hasFirstTransaction && (
          <TouchableOpacity
            style={styles.ctaButton}
            onPress={() => navigation.navigate('Send')}
          >
            <Text style={styles.ctaButtonText}>Hacer mi Primera Transacción</Text>
          </TouchableOpacity>
        )}
        
        {hasFirstTransaction && !hasDollarMilestone && (
          <TouchableOpacity
            style={styles.ctaButton}
            onPress={() => navigation.navigate('Send')}
          >
            <Text style={styles.ctaButtonText}>Enviar $1 para Ganar</Text>
          </TouchableOpacity>
        )}
        
        {hasDollarMilestone && (
          <View style={styles.completedContainer}>
            <Text style={styles.completedText}>✅ ¡Ya ganaste tus primeros CONFIO!</Text>
            <TouchableOpacity
              style={styles.secondaryButton}
              onPress={() => navigation.navigate('Send')}
            >
              <Text style={styles.secondaryButtonText}>Seguir Ganando</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>

      {/* Simple Steps */}
      <View style={styles.stepsContainer}>
        <Text style={styles.stepsTitle}>Cómo funciona:</Text>
        
        <View style={styles.step}>
          <Text style={styles.stepNumber}>1</Text>
          <View style={styles.stepContent}>
            <Text style={styles.stepTitle}>Envía o recibe $1+</Text>
            <Text style={styles.stepDescription}>
              Cualquier transacción de $1 o más califica
            </Text>
          </View>
        </View>
        
        <View style={styles.step}>
          <Text style={styles.stepNumber}>2</Text>
          <View style={styles.stepContent}>
            <Text style={styles.stepTitle}>Ambos ganan 4 $CONFIO</Text>
            <Text style={styles.stepDescription}>
              Tú y la otra persona reciben la recompensa
            </Text>
          </View>
        </View>
        
        <View style={styles.step}>
          <Text style={styles.stepNumber}>3</Text>
          <View style={styles.stepContent}>
            <Text style={styles.stepTitle}>Valor futuro</Text>
            <Text style={styles.stepDescription}>
              4 $CONFIO = $1 al precio de preventa
            </Text>
          </View>
        </View>
      </View>

      {/* Referral Section */}
      <View style={styles.referralCard}>
        <Text style={styles.referralTitle}>🚀 Multiplica tus ganancias</Text>
        <Text style={styles.referralDescription}>
          Invita amigos y gana 4 $CONFIO cuando completen su primera transacción
        </Text>
        <TouchableOpacity
          style={styles.referralButton}
          onPress={() => navigation.navigate('Referrals')}
        >
          <Text style={styles.referralButtonText}>Invitar Amigos</Text>
        </TouchableOpacity>
      </View>

      {/* Bottom Padding */}
      <View style={styles.bottomPadding} />
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f8f9fa',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  header: {
    padding: 30,
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: '700',
    color: 'white',
    marginBottom: 10,
  },
  balance: {
    fontSize: 48,
    fontWeight: '700',
    color: 'white',
  },
  balanceSubtext: {
    fontSize: 16,
    color: 'rgba(255, 255, 255, 0.8)',
  },
  mainCard: {
    backgroundColor: 'white',
    margin: 20,
    padding: 24,
    borderRadius: 20,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.05,
    shadowRadius: 3,
    elevation: 2,
  },
  mainTitle: {
    fontSize: 22,
    fontWeight: '700',
    color: '#212529',
    marginBottom: 12,
    textAlign: 'center',
  },
  mainDescription: {
    fontSize: 16,
    color: '#6c757d',
    textAlign: 'center',
    lineHeight: 24,
    marginBottom: 20,
  },
  ctaButton: {
    backgroundColor: '#00BFA5',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  ctaButtonText: {
    color: 'white',
    fontSize: 18,
    fontWeight: '700',
  },
  completedContainer: {
    alignItems: 'center',
  },
  completedText: {
    fontSize: 18,
    color: '#10B981',
    fontWeight: '600',
    marginBottom: 16,
  },
  secondaryButton: {
    backgroundColor: '#f3f4f6',
    paddingVertical: 14,
    paddingHorizontal: 24,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  secondaryButtonText: {
    color: '#00BFA5',
    fontSize: 16,
    fontWeight: '600',
  },
  stepsContainer: {
    padding: 20,
  },
  stepsTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#212529',
    marginBottom: 20,
  },
  step: {
    flexDirection: 'row',
    marginBottom: 20,
  },
  stepNumber: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#00BFA5',
    color: 'white',
    fontSize: 16,
    fontWeight: '700',
    textAlign: 'center',
    lineHeight: 32,
    marginRight: 16,
  },
  stepContent: {
    flex: 1,
  },
  stepTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#212529',
    marginBottom: 4,
  },
  stepDescription: {
    fontSize: 14,
    color: '#6c757d',
    lineHeight: 20,
  },
  referralCard: {
    backgroundColor: '#8B5CF6',
    margin: 20,
    padding: 24,
    borderRadius: 20,
  },
  referralTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: 'white',
    marginBottom: 8,
  },
  referralDescription: {
    fontSize: 16,
    color: 'rgba(255, 255, 255, 0.9)',
    lineHeight: 24,
    marginBottom: 16,
  },
  referralButton: {
    backgroundColor: 'white',
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: 'center',
  },
  referralButtonText: {
    color: '#8B5CF6',
    fontSize: 16,
    fontWeight: '700',
  },
  bottomPadding: {
    height: 40,
  },
});