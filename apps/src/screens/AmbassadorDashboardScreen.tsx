import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { useQuery } from '@apollo/client';
import { gql } from '@apollo/client';
import { NavigationProp } from '@react-navigation/native';
import Svg, { Defs, LinearGradient, Stop, Rect } from 'react-native-svg';

const GET_AMBASSADOR_PROFILE = gql`
  query GetAmbassadorProfile {
    myAmbassadorProfile {
      id
      tier
      tierDisplay
      status
      statusDisplay
      totalReferrals
      activeReferrals
      totalViralViews
      monthlyViralViews
      referralTransactionVolume
      confioEarned
      tierAchievedAt
      tierProgress
      customReferralCode
      performanceScore
      dedicatedSupport
      lastActivityAt
      benefits {
        referralBonus
        viralRate
        customCode
        dedicatedSupport
        monthlyBonus
        exclusiveEvents
        earlyFeatures
      }
    }
    myAmbassadorActivities(limit: 10) {
      id
      activityType
      activityTypeDisplay
      description
      confioRewarded
      createdAt
    }
  }
`;

interface AmbassadorDashboardScreenProps {
  navigation: NavigationProp<any>;
}

export const AmbassadorDashboardScreen: React.FC<AmbassadorDashboardScreenProps> = ({ navigation }) => {
  const [refreshing, setRefreshing] = useState(false);
  const { data, loading, error, refetch } = useQuery(GET_AMBASSADOR_PROFILE, {
    fetchPolicy: 'cache-and-network',
  });

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await refetch();
    } finally {
      setRefreshing(false);
    }
  };

  if (loading && !data) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#00BFA5" />
      </View>
    );
  }

  if (error || !data?.myAmbassadorProfile) {
    return (
      <View style={styles.errorContainer}>
        <Text style={styles.errorText}>No eres embajador aún</Text>
        <Text style={styles.errorSubtext}>
          Continúa compartiendo contenido viral para calificar
        </Text>
        <TouchableOpacity
          style={styles.backButton}
          onPress={() => navigation.goBack()}
        >
          <Text style={styles.backButtonText}>Volver</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const profile = data.myAmbassadorProfile;
  const activities = data.myAmbassadorActivities || [];

  const getTierColor = (tier: string) => {
    switch (tier) {
      case 'bronze': return ['#CD7F32', '#B87333'];
      case 'silver': return ['#C0C0C0', '#A8A8A8'];
      case 'gold': return ['#FFD700', '#FFA500'];
      case 'diamond': return ['#B9F2FF', '#00BFA5'];
      default: return ['#00BFA5', '#008F7A'];
    }
  };

  const getTierIcon = (tier: string) => {
    switch (tier) {
      case 'bronze': return '🥉';
      case 'silver': return '🥈';
      case 'gold': return '🥇';
      case 'diamond': return '💎';
      default: return '🏆';
    }
  };

  const formatNumber = (num: number) => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
  };

  return (
    <ScrollView
      style={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
      }
    >
      {/* Header with Tier Badge */}
      <View style={styles.header}>
        <Svg
          height="100%"
          width="100%"
          style={StyleSheet.absoluteFillObject}
        >
          <Defs>
            <LinearGradient id="tierGradient" x1="0%" y1="0%" x2="0%" y2="100%">
              <Stop offset="0%" stopColor={getTierColor(profile.tier)[0]} />
              <Stop offset="100%" stopColor={getTierColor(profile.tier)[1]} />
            </LinearGradient>
          </Defs>
          <Rect width="100%" height="100%" fill="url(#tierGradient)" />
        </Svg>
        <Text style={styles.tierIcon}>{getTierIcon(profile.tier)}</Text>
        <Text style={styles.tierName}>{profile.tierDisplay}</Text>
        <Text style={styles.status}>{profile.statusDisplay}</Text>
        
        {profile.customReferralCode && (
          <View style={styles.referralCodeContainer}>
            <Text style={styles.referralCodeLabel}>Código Personal:</Text>
            <Text style={styles.referralCode}>{profile.customReferralCode}</Text>
          </View>
        )}
      </View>

      {/* Performance Metrics */}
      <View style={styles.metricsContainer}>
        <Text style={styles.sectionTitle}>Métricas de Rendimiento</Text>
        
        <View style={styles.metricsGrid}>
          <View style={styles.metricCard}>
            <Text style={styles.metricValue}>{profile.totalReferrals}</Text>
            <Text style={styles.metricLabel}>Referidos Totales</Text>
          </View>
          
          <View style={styles.metricCard}>
            <Text style={styles.metricValue}>{profile.activeReferrals}</Text>
            <Text style={styles.metricLabel}>Referidos Activos</Text>
          </View>
          
          <View style={styles.metricCard}>
            <Text style={styles.metricValue}>{formatNumber(profile.totalViralViews)}</Text>
            <Text style={styles.metricLabel}>Vistas Totales</Text>
          </View>
          
          <View style={styles.metricCard}>
            <Text style={styles.metricValue}>{formatNumber(profile.monthlyViralViews)}</Text>
            <Text style={styles.metricLabel}>Vistas del Mes</Text>
          </View>
        </View>
        
        <View style={styles.earningsCard}>
          <Text style={styles.earningsLabel}>CONFIO Ganado</Text>
          <Text style={styles.earningsValue}>{profile.confioEarned.toFixed(0)} $CONFIO</Text>
        </View>
      </View>

      {/* Tier Progress */}
      {profile.tier !== 'diamond' && (
        <View style={styles.progressContainer}>
          <Text style={styles.sectionTitle}>Progreso al Siguiente Nivel</Text>
          <View style={styles.progressBar}>
            <View 
              style={[styles.progressFill, { width: `${profile.tierProgress}%` }]} 
            />
          </View>
          <Text style={styles.progressText}>{profile.tierProgress}% completado</Text>
        </View>
      )}

      {/* Benefits */}
      {profile.benefits && (
        <View style={styles.benefitsContainer}>
          <Text style={styles.sectionTitle}>Beneficios Actuales</Text>
          
          <View style={styles.benefitsList}>
            <View style={styles.benefitItem}>
              <Text style={styles.benefitIcon}>💰</Text>
              <Text style={styles.benefitText}>
                Bonus por referido: {profile.benefits.referralBonus} $CONFIO
              </Text>
            </View>
            
            <View style={styles.benefitItem}>
              <Text style={styles.benefitIcon}>📈</Text>
              <Text style={styles.benefitText}>
                Tasa viral: {profile.benefits.viralRate} $CONFIO/1K vistas
              </Text>
            </View>
            
            {profile.benefits.monthlyBonus > 0 && (
              <View style={styles.benefitItem}>
                <Text style={styles.benefitIcon}>🎁</Text>
                <Text style={styles.benefitText}>
                  Bonus mensual: {profile.benefits.monthlyBonus} $CONFIO
                </Text>
              </View>
            )}
            
            {profile.benefits.customCode && (
              <View style={styles.benefitItem}>
                <Text style={styles.benefitIcon}>🔗</Text>
                <Text style={styles.benefitText}>Código personalizado</Text>
              </View>
            )}
            
            {profile.benefits.dedicatedSupport && (
              <View style={styles.benefitItem}>
                <Text style={styles.benefitIcon}>🎯</Text>
                <Text style={styles.benefitText}>Soporte dedicado</Text>
              </View>
            )}
            
            {profile.benefits.exclusiveEvents && (
              <View style={styles.benefitItem}>
                <Text style={styles.benefitIcon}>🎉</Text>
                <Text style={styles.benefitText}>Eventos exclusivos</Text>
              </View>
            )}
            
            {profile.benefits.earlyFeatures && (
              <View style={styles.benefitItem}>
                <Text style={styles.benefitIcon}>🚀</Text>
                <Text style={styles.benefitText}>Acceso anticipado a funciones</Text>
              </View>
            )}
          </View>
        </View>
      )}

      {/* Recent Activities */}
      {activities.length > 0 && (
        <View style={styles.activitiesContainer}>
          <Text style={styles.sectionTitle}>Actividad Reciente</Text>
          
          {activities.map((activity: any) => (
            <View key={activity.id} style={styles.activityItem}>
              <View style={styles.activityHeader}>
                <Text style={styles.activityType}>{activity.activityTypeDisplay}</Text>
                {activity.confioRewarded > 0 && (
                  <Text style={styles.activityReward}>
                    +{activity.confioRewarded} $CONFIO
                  </Text>
                )}
              </View>
              <Text style={styles.activityDescription}>{activity.description}</Text>
              <Text style={styles.activityDate}>
                {new Date(activity.createdAt).toLocaleDateString()}
              </Text>
            </View>
          ))}
        </View>
      )}

      {/* Performance Score */}
      <View style={styles.performanceContainer}>
        <Text style={styles.sectionTitle}>Puntuación de Rendimiento</Text>
        <View style={styles.performanceScoreCard}>
          <Text style={[
            styles.performanceScore,
            { color: profile.performanceScore >= 80 ? '#10B981' : 
                     profile.performanceScore >= 50 ? '#F59E0B' : '#EF4444' }
          ]}>
            {profile.performanceScore}%
          </Text>
          <Text style={styles.performanceLabel}>
            {profile.performanceScore >= 80 ? 'Excelente' :
             profile.performanceScore >= 50 ? 'Bueno' : 'Necesita mejorar'}
          </Text>
        </View>
      </View>

      {/* Action Buttons */}
      <View style={styles.actionsContainer}>
        <TouchableOpacity
          style={styles.actionButton}
          onPress={() => navigation.navigate('MiProgresoViral')}
        >
          <Text style={styles.actionButtonText}>Ver Contenido Viral</Text>
        </TouchableOpacity>
        
        {profile.dedicatedSupport && (
          <TouchableOpacity
            style={[styles.actionButton, styles.supportButton]}
            onPress={() => {/* Handle support */}}
          >
            <Text style={styles.actionButtonText}>Contactar Soporte VIP</Text>
          </TouchableOpacity>
        )}
      </View>

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
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  errorText: {
    fontSize: 20,
    fontWeight: '700',
    color: '#212529',
    marginBottom: 10,
  },
  errorSubtext: {
    fontSize: 16,
    color: '#6c757d',
    textAlign: 'center',
    marginBottom: 30,
  },
  backButton: {
    backgroundColor: '#00BFA5',
    paddingHorizontal: 30,
    paddingVertical: 12,
    borderRadius: 25,
  },
  backButtonText: {
    color: 'white',
    fontSize: 16,
    fontWeight: '600',
  },
  header: {
    padding: 30,
    alignItems: 'center',
    borderBottomLeftRadius: 30,
    borderBottomRightRadius: 30,
    position: 'relative',
    overflow: 'hidden',
  },
  tierIcon: {
    fontSize: 60,
    marginBottom: 10,
    zIndex: 1,
  },
  tierName: {
    fontSize: 28,
    fontWeight: '700',
    color: 'white',
    marginBottom: 5,
    zIndex: 1,
  },
  status: {
    fontSize: 16,
    color: 'rgba(255, 255, 255, 0.9)',
    marginBottom: 20,
    zIndex: 1,
  },
  referralCodeContainer: {
    backgroundColor: 'rgba(255, 255, 255, 0.2)',
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 20,
    zIndex: 1,
  },
  referralCodeLabel: {
    fontSize: 12,
    color: 'rgba(255, 255, 255, 0.8)',
    marginBottom: 2,
  },
  referralCode: {
    fontSize: 18,
    fontWeight: '700',
    color: 'white',
  },
  metricsContainer: {
    padding: 20,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#212529',
    marginBottom: 15,
  },
  metricsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
    marginBottom: 20,
  },
  metricCard: {
    width: '48%',
    backgroundColor: 'white',
    padding: 20,
    borderRadius: 15,
    marginBottom: 15,
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.05,
    shadowRadius: 3,
    elevation: 2,
  },
  metricValue: {
    fontSize: 28,
    fontWeight: '700',
    color: '#00BFA5',
    marginBottom: 5,
  },
  metricLabel: {
    fontSize: 14,
    color: '#6c757d',
    textAlign: 'center',
  },
  earningsCard: {
    backgroundColor: '#00BFA5',
    padding: 25,
    borderRadius: 20,
    alignItems: 'center',
  },
  earningsLabel: {
    fontSize: 16,
    color: 'rgba(255, 255, 255, 0.9)',
    marginBottom: 5,
  },
  earningsValue: {
    fontSize: 32,
    fontWeight: '700',
    color: 'white',
  },
  progressContainer: {
    padding: 20,
  },
  progressBar: {
    height: 12,
    backgroundColor: '#e9ecef',
    borderRadius: 6,
    overflow: 'hidden',
    marginBottom: 10,
  },
  progressFill: {
    height: '100%',
    backgroundColor: '#8B5CF6',
    borderRadius: 6,
  },
  progressText: {
    fontSize: 14,
    color: '#6c757d',
    textAlign: 'center',
  },
  benefitsContainer: {
    padding: 20,
  },
  benefitsList: {
    backgroundColor: 'white',
    borderRadius: 15,
    padding: 20,
  },
  benefitItem: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 15,
  },
  benefitIcon: {
    fontSize: 24,
    marginRight: 15,
    width: 30,
  },
  benefitText: {
    fontSize: 16,
    color: '#495057',
    flex: 1,
  },
  activitiesContainer: {
    padding: 20,
  },
  activityItem: {
    backgroundColor: 'white',
    padding: 15,
    borderRadius: 12,
    marginBottom: 10,
  },
  activityHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  activityType: {
    fontSize: 16,
    fontWeight: '600',
    color: '#212529',
  },
  activityReward: {
    fontSize: 16,
    fontWeight: '700',
    color: '#10B981',
  },
  activityDescription: {
    fontSize: 14,
    color: '#6c757d',
    marginBottom: 5,
  },
  activityDate: {
    fontSize: 12,
    color: '#adb5bd',
  },
  performanceContainer: {
    padding: 20,
  },
  performanceScoreCard: {
    backgroundColor: 'white',
    padding: 30,
    borderRadius: 20,
    alignItems: 'center',
  },
  performanceScore: {
    fontSize: 48,
    fontWeight: '700',
    marginBottom: 5,
  },
  performanceLabel: {
    fontSize: 16,
    color: '#6c757d',
  },
  actionsContainer: {
    padding: 20,
  },
  actionButton: {
    backgroundColor: '#00BFA5',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginBottom: 12,
  },
  supportButton: {
    backgroundColor: '#8B5CF6',
  },
  actionButtonText: {
    color: 'white',
    fontSize: 16,
    fontWeight: '700',
  },
  bottomPadding: {
    height: 50,
  },
});