import React, { useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Share, Platform, TextInput, Alert, Linking, Image } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { useAuth } from '../contexts/AuthContext';
import { useAccount } from '../contexts/AccountContext';
import { useQuery, useMutation } from '@apollo/client';
import {
  GET_ACHIEVEMENT_TYPES,
  GET_USER_ACHIEVEMENTS,
  CLAIM_ACHIEVEMENT_REWARD,
  SUBMIT_TIKTOK_SHARE,
  GET_MY_CONFIO_BALANCE,
  CHECK_REFERRAL_STATUS
} from '../apollo/queries';
import { ShareAchievementModal } from '../components/ShareAchievementModal';
import { ReferralInputModal } from '../components/ReferralInputModal';
import { PioneroBadgeModal } from '../components/PioneroBadgeModal';

const colors = {
  primary: '#34d399',
  primaryLight: '#d1fae5',
  primaryDark: '#10b981',
  secondary: '#8b5cf6',
  secondaryLight: '#e9d5ff',
  accent: '#3b82f6',
  neutral: '#f9fafb',
  neutralDark: '#f3f4f6',
  dark: '#111827',
  violet: '#8b5cf6',
  violetLight: '#ddd6fe',
  silver: '#C0C0C0',
  bronze: '#CD7F32',
  mint: '#3ADBBB',
  mintLight: '#B8F0E4',
};

type Achievement = {
  id: string;
  name: string;
  description: string;
  iconEmoji?: string;
  status: 'pending' | 'earned' | 'claimed' | 'expired';
  earnedAt?: string;
  claimedAt?: string;
  progressData?: any;
  earnedValue?: number;
  achievementType: {
    slug: string;
    name: string;
    description: string;
    category: string;
    iconEmoji?: string;
    confioReward: number;
    displayOrder: number;
  };
};

type AchievementType = {
  id: string;
  slug: string;
  name: string;
  description: string;
  category: string;
  iconEmoji?: string;
  confioReward: number;
  displayOrder: number;
};

export const AchievementsScreen = () => {
  const navigation = useNavigation();
  const { userProfile } = useAuth();
  const { activeAccount } = useAccount();
  const [showReferralModal, setShowReferralModal] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);
  const [showPioneroModal, setShowPioneroModal] = useState(false);
  const [canShowReferralBox, setCanShowReferralBox] = useState(false);
  const [selectedAchievement, setSelectedAchievement] = useState<{
    id: string;
    name: string;
    description: string;
    confioReward: number;
    category: string;
    slug?: string;
    status?: string;
  } | null>(null);
  
  // GraphQL queries
  const { data: achievementTypesData, loading: achievementTypesLoading, error: achievementTypesError } = useQuery(GET_ACHIEVEMENT_TYPES);
  const { data: userAchievementsData, loading: userAchievementsLoading, error: userAchievementsError, refetch: refetchAchievements } = useQuery(GET_USER_ACHIEVEMENTS);
  const { data: confioBalanceData, refetch: refetchBalance } = useQuery(GET_MY_CONFIO_BALANCE);
  
  // GraphQL mutations
  const [claimAchievementReward] = useMutation(CLAIM_ACHIEVEMENT_REWARD);
  const [submitTikTokShare] = useMutation(SUBMIT_TIKTOK_SHARE);
  const [checkReferralStatus] = useMutation(CHECK_REFERRAL_STATUS);
  
  // Process the achievement data
  const achievementTypes: AchievementType[] = achievementTypesData?.achievementTypes || [];
  const userAchievements: Achievement[] = userAchievementsData?.userAchievements || [];
  
  // Check referral status on mount
  React.useEffect(() => {
    checkReferralStatus().then(({ data }) => {
      if (data?.checkReferralStatus) {
        setCanShowReferralBox(data.checkReferralStatus.canSetReferrer);
      }
    }).catch(err => {
      console.error('Error checking referral status:', err);
      // On error, show the box anyway for testing
      setCanShowReferralBox(true);
    });
  }, []);

  // Debug logging
  React.useEffect(() => {
    console.log('AchievementsScreen Debug:');
    console.log('- Achievement Types Loading:', achievementTypesLoading);
    console.log('- User Achievements Loading:', userAchievementsLoading);
    console.log('- Achievement Types Error:', achievementTypesError);
    console.log('- User Achievements Error:', userAchievementsError);
    console.log('- Achievement Types Count:', achievementTypes?.length || 0);
    console.log('- User Achievements Count:', userAchievements?.length || 0);
    console.log('- Achievement Types Data:', achievementTypesData);
    console.log('- User Achievements Data:', userAchievementsData);
    console.log('- Achievements Array:', achievements?.length || 0);
  }, [achievementTypes, userAchievements, achievementTypesLoading, userAchievementsLoading, achievementTypesError, userAchievementsError, achievementTypesData, userAchievementsData, achievements]);
  
  // Create a map of user achievements by achievement type slug
  const userAchievementMap = React.useMemo(() => {
    const map = new Map();
    if (userAchievements && Array.isArray(userAchievements)) {
      userAchievements.forEach(achievement => {
        if (achievement?.achievementType?.slug) {
          map.set(achievement.achievementType.slug, achievement);
        }
      });
    }
    return map;
  }, [userAchievements]);
  
  // Combine achievement types with user progress, fallback to mock data if empty
  const achievements: Achievement[] = React.useMemo(() => {
    if (achievementTypes && achievementTypes.length > 0) {
      return achievementTypes.map(type => {
        const userAchievement = userAchievementMap.get(type.slug);
        // Normalize status to lowercase
        const normalizedStatus = userAchievement?.status?.toLowerCase() || 'pending';
        return {
          id: userAchievement?.id || type.id,
          name: type.name,
          description: type.description,
          iconEmoji: type.iconEmoji,
          status: normalizedStatus,
          earnedAt: userAchievement?.earnedAt,
          claimedAt: userAchievement?.claimedAt,
          progressData: userAchievement?.progressData,
          earnedValue: userAchievement?.earnedValue,
          achievementType: type
        };
      }).sort((a, b) => a.achievementType.displayOrder - b.achievementType.displayOrder);
    } else {
      // Use mock data when GraphQL data is not available
      return mockAchievements || [];
    }
  }, [achievementTypes, userAchievementMap, mockAchievements]);

  // Ensure referral-share card is always available: inject a pending "Referido Exitoso" if missing
  const displayAchievements: Achievement[] = React.useMemo(() => {
    const list = Array.isArray(achievements) ? [...achievements] : [];
    const hasReferral = list.some(a => {
      const slug = a?.achievementType?.slug?.toLowerCase?.();
      return slug === 'referido_exitoso' || slug === 'successful_referral';
    });
    if (!hasReferral) {
      list.push({
        id: 'referral-pending',
        name: 'Referido Exitoso',
        description: 'Invita amigos y gana 4 CONFIO cuando completen su primera transacción',
        iconEmoji: '🤝',
        status: 'pending',
        achievementType: {
          slug: 'referido_exitoso',
          name: 'Referido Exitoso',
          description: 'Gana 4 CONFIO por cada referido exitoso',
          category: 'ambassador',
          confioReward: 4,
          displayOrder: 1000,
        }
      } as Achievement);
    }
    return list;
  }, [achievements]);

  const mockAchievements = React.useMemo<Achievement[]>(() => [
    // Fallback mock data when GraphQL is loading or unavailable
    {
      id: 'mock-welcome',
      name: 'Pionero Beta',
      description: 'Únete a Confío durante la fase beta - Exclusivo para los primeros usuarios',
      iconEmoji: '🚀',
      status: 'earned',
      earnedAt: new Date().toISOString(),
      progressData: null,
      earnedValue: null,
      achievementType: {
        slug: 'welcome_signup',
        name: 'Pionero Beta',
        description: 'Únete a Confío durante la fase beta - Exclusivo para los primeros usuarios',
        category: 'onboarding',
        iconEmoji: '🚀',
        confioReward: 4,
        displayOrder: 1
      }
    },
    {
      id: 'mock-verification',
      name: 'Cuenta Verificada',
      description: 'Completa la verificación de identidad',
      iconEmoji: '🛡️',
      status: 'pending',
      earnedAt: null,
      progressData: { current: 0, target: 1 },
      earnedValue: null,
      achievementType: {
        slug: 'identity_verified',
        name: 'Cuenta Verificada',
        description: 'Completa la verificación de identidad',
        category: 'verification',
        iconEmoji: '🛡️',
        confioReward: 20,
        displayOrder: 2
      }
    },
    {
      id: 'mock-first-trade',
      name: 'Trader Novato',
      description: 'Completa tu primer intercambio P2P exitoso',
      iconEmoji: '🔄',
      status: 'pending',
      earnedAt: null,
      progressData: { current: 0, target: 1 },
      earnedValue: null,
      achievementType: {
        slug: 'first_p2p_trade',
        name: 'Trader Novato',
        description: 'Completa tu primer intercambio P2P exitoso',
        category: 'trading',
        iconEmoji: '🔄',
        confioReward: 20,
        displayOrder: 20
      }
    },
    {
      id: 'mock-nano-influencer',
      name: 'Nano-Influencer',
      description: 'Trae entre 1-10 referidos que completen su registro',
      iconEmoji: '🌱',
      status: 'pending',
      earnedAt: null,
      progressData: { current: 0, target: 1 },
      earnedValue: null,
      achievementType: {
        slug: 'nano_influencer',
        name: 'Nano-Influencer',
        description: 'Trae entre 1-10 referidos que completen su registro',
        category: 'ambassador',
        iconEmoji: '🌱',
        confioReward: 4,
        displayOrder: 10
      }
    },
    {
      id: 'mock-primera-viral',
      name: 'Primera Viral',
      description: 'Tu TikTok sobre Confío alcanzó 1,000 visualizaciones',
      iconEmoji: '🎬',
      status: 'pending',
      earnedAt: null,
      progressData: { current: 0, target: 1000 },
      earnedValue: null,
      achievementType: {
        slug: 'primera_viral',
        name: 'Primera Viral',
        description: 'Tu TikTok sobre Confío alcanzó 1,000 visualizaciones',
        category: 'social',
        iconEmoji: '🎬',
        confioReward: 50,
        displayOrder: 30
      }
    }
  ], []);

  const handleClaimReward = async (achievement: Achievement) => {
    if (achievement.status?.toLowerCase() !== 'earned') return;
    
    try {
      const result = await claimAchievementReward({
        variables: { achievementId: achievement.id }
      });
      
      if (result.data?.claimAchievementReward?.success) {
        Alert.alert(
          '¡Recompensa Reclamada!',
          `Has reclamado ${achievement.achievementType.confioReward} $CONFIO`,
          [{ text: 'OK' }]
        );
        refetchAchievements();
        refetchBalance();
      } else {
        Alert.alert('Error', result.data?.claimAchievementReward?.error || 'No se pudo reclamar la recompensa');
      }
    } catch (error) {
      console.error('Error claiming reward:', error);
      Alert.alert('Error', 'Ocurrió un error al reclamar la recompensa');
    }
  };



  const handleShare = async (achievement: Achievement) => {
    console.log('handleShare called with:', achievement?.name, achievement?.status);
    
    // Allow sharing for earned, claimed, or pending referral achievements
    const slug = achievement?.achievementType?.slug;
    const isReferralSlug = slug === 'referido_exitoso' || slug === 'successful_referral';
    if (achievement.status?.toLowerCase() !== 'earned' && 
        achievement.status?.toLowerCase() !== 'claimed' &&
        !(isReferralSlug && achievement?.status?.toLowerCase() === 'pending')) {
      console.log('handleShare returning early - status check failed');
      return;
    }
    
    console.log('Setting selected achievement and showing modal');
    setSelectedAchievement({
      id: achievement.id,
      name: achievement.name,
      description: achievement.description,
      confioReward: achievement.achievementType.confioReward || 0,
      category: achievement.achievementType.category,
      slug: achievement.achievementType.slug,
    });
    setShowShareModal(true);
  };
  
  const promptForTikTokUrl = (achievement: Achievement) => {
    Alert.prompt(
      'Enlace de TikTok',
      'Pega el enlace de tu video de TikTok aquí:',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Enviar',
          onPress: (tiktokUrl) => {
            if (tiktokUrl && tiktokUrl.includes('tiktok.com')) {
              submitTikTokShare({
                variables: {
                  tiktokUrl: tiktokUrl.trim(),
                  shareType: 'achievement',
                  achievementId: achievement.id,
                  hashtagsUsed: JSON.stringify(['#Confio', '#RetoConfio', '#LogroConfio', '#AppDeDolares', '#DolarDigital'])
                }
              }).then(result => {
                if (result.data?.submitTikTokShare?.success) {
                  Alert.alert(
                    '¡TikTok Enviado!',
                    'Hemos recibido tu enlace de TikTok. Te notificaremos cuando sea verificado y recibas CONFIO extra por las visualizaciones.',
                    [{ text: 'OK' }]
                  );
                } else {
                  Alert.alert('Error', 'No se pudo procesar el enlace de TikTok');
                }
              }).catch(error => {
                console.error('Error submitting TikTok share:', error);
                Alert.alert('Error', 'Ocurrió un error al procesar el enlace');
              });
            } else {
              Alert.alert('Error', 'Por favor ingresa un enlace válido de TikTok');
            }
          }
        }
      ],
      'plain-text'
    );
  };

  const getCategoryColor = (category: string) => {
    const normalizedCategory = category.toLowerCase();
    switch (normalizedCategory) {
      case 'onboarding': return colors.primary;
      case 'trading': return colors.secondary;
      case 'payments': return '#FF6B6B';
      case 'social': return colors.accent;
      case 'verification': return '#FFB800';
      case 'ambassador': return '#FFD700';
      default: return colors.primary;
    }
  };
  
  const getCategoryIcon = (category: string) => {
    const normalizedCategory = category.toLowerCase();
    switch (normalizedCategory) {
      case 'onboarding': return 'home';
      case 'trading': return 'refresh-cw';
      case 'payments': return 'credit-card';
      case 'social': return 'users';
      case 'verification': return 'shield';
      case 'ambassador': return 'award';
      default: return 'star';
    }
  };

  const getProgressPercentage = (achievement: Achievement) => {
    if (!achievement.progressData) return 0;
    const { current, target } = achievement.progressData;
    if (!current || !target) return 0;
    return Math.min((current / target) * 100, 100);
  };

  const completedCount = (displayAchievements || []).filter(a => a.status?.toLowerCase() === 'earned' || a.status?.toLowerCase() === 'claimed').length;
  
  // Use actual CONFIO balance from database
  const confioBalance = confioBalanceData?.myConfioBalance;
  const totalConfioEarned = confioBalance?.totalLocked || 0;
  
  // Calculate pending rewards (earned but not claimed)
  const pendingConfio = (displayAchievements || [])
    .filter(a => a.status?.toLowerCase() === 'earned')
    .reduce((sum, a) => sum + (a.achievementType?.confioReward || 0), 0);

  const categories = [
    { key: 'onboarding', name: 'Bienvenida', icon: 'home' },
    { key: 'verification', name: 'Verificación', icon: 'shield' },
    { key: 'trading', name: 'Intercambios', icon: 'refresh-cw' },
    { key: 'payments', name: 'Pagos y Transacciones', icon: 'credit-card' },
    { key: 'social', name: 'Comunidad', icon: 'users' },
    { key: 'ambassador', name: 'Embajador', icon: 'award' },
  ];
  
  // Show loading state only for a brief moment, then show mock data
  const isInitialLoading = (achievementTypesLoading || userAchievementsLoading) && (!achievements || achievements.length === 0);
  
  if (isInitialLoading) {
    return (
      <SafeAreaView style={styles.container} edges={['top','bottom']}>
        <View style={[styles.header, { paddingTop: 12 }]}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Logros</Text>
          <View style={styles.headerSpacer} />
        </View>
        <View style={styles.loadingContainer}>
          <Text style={styles.loadingText}>Cargando logros...</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['top','bottom']}>
      <View style={[styles.header, { paddingTop: 12 }]}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="arrow-left" size={24} color="#fff" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Logros</Text>
        <View style={styles.headerSpacer} />
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Stats Overview */}
        <View style={styles.statsContainer}>
          <View style={styles.statCard}>
            <Text style={styles.statNumber}>{completedCount}</Text>
            <Text style={styles.statLabel}>Completados</Text>
          </View>
          <View style={styles.statCard}>
            <Text style={styles.statNumber}>{achievements?.length || 0}</Text>
            <Text style={styles.statLabel}>Total</Text>
          </View>
          <View style={styles.statCard}>
            <Icon name="lock" size={16} color={colors.violet} style={styles.lockIcon} />
            <Text style={styles.statNumber}>{totalConfioEarned}</Text>
            <Text style={styles.statLabel}>$CONFIO</Text>
            <TouchableOpacity 
              style={styles.infoButton}
              onPress={() => navigation.navigate('ConfioTokenInfo' as any)}
            >
              <Icon name="info" size={14} color={colors.violet} />
            </TouchableOpacity>
          </View>
        </View>

        {/* 1. Tu Futuro con $CONFIO - PRIMARY (Purple) */}
        <TouchableOpacity 
          style={styles.inspirationalCard}
          onPress={() => navigation.navigate('ConfioTokenInfo' as any)}
        >
          <View style={styles.inspirationalHeader}>
            <Icon name="zap" size={20} color={colors.violet} />
            <Text style={styles.inspirationalTitle}>Tu Futuro con $CONFIO</Text>
          </View>
          <Text style={styles.inspirationalText}>
            Imagina cuando toda Venezuela, Argentina y Bolivia usen la app de Confío... 🚀
          </Text>
          <Text style={styles.inspirationalSubtext}>
            Tus monedas están bloqueadas ahora, pero su valor crecerá con la adopción
          </Text>
          <View style={styles.learnMoreRow}>
            <Text style={styles.learnMoreText}>Aprende más</Text>
            <Icon name="chevron-right" size={16} color={colors.violet} />
          </View>
        </TouchableOpacity>

        {/* 2. Unified Referral - SECONDARY (Orange) - Only show if can set referrer */}
        {canShowReferralBox && (
          <TouchableOpacity 
            style={styles.orangeCard}
            onPress={() => setShowReferralModal(true)}
          >
            <View style={styles.cardHeader}>
              <Icon name="users" size={20} color="#F59E0B" />
              <Text style={styles.orangeTitle}>¿Quién te invitó a Confío?</Text>
            </View>
            <Text style={styles.orangeText}>
              Ingresa el código de tu amigo o el @username del influencer para que ambos reciban 4 CONFIO
            </Text>
            <View style={styles.learnMoreRow}>
              <Text style={styles.orangeLearnMore}>Agregar referencia</Text>
              <Icon name="chevron-right" size={16} color="#F59E0B" />
            </View>
          </TouchableOpacity>
        )}
        
        {/* 3. Mi Progreso Viral - TERTIARY (Mint) */}
        <TouchableOpacity 
          style={styles.mintCard}
          onPress={() => navigation.navigate('MiProgresoViral' as any)}
        >
          <View style={styles.cardHeader}>
            <Icon name="trending-up" size={20} color={colors.mint} />
            <Text style={styles.mintTitle}>Mi Progreso Viral</Text>
          </View>
          <Text style={styles.mintText}>
            Ve tus estadísticas de influencer, sube TikToks y gana CONFIO por visualizaciones 🚀
          </Text>
          <View style={styles.learnMoreRow}>
            <Text style={styles.mintLearnMore}>Ver dashboard</Text>
            <Icon name="chevron-right" size={16} color={colors.mint} />
          </View>
        </TouchableOpacity>


        {/* Progress Bar */}
        <View style={styles.progressContainer}>
          <View style={styles.progressHeader}>
            <Text style={styles.progressTitle}>Progreso General</Text>
            <Text style={styles.progressText}>
              {(achievements && achievements.length > 0) ? Math.round((completedCount / achievements.length) * 100) : 0}%
            </Text>
          </View>
          <View style={styles.progressBarBg}>
            <View 
              style={[
                styles.progressBarFill, 
                { width: (achievements && achievements.length > 0) ? `${(completedCount / achievements.length) * 100}%` : '0%' }
              ]} 
            />
          </View>
          {(!achievements || achievements.length === 0) && (
            <Text style={styles.noDataText}>
              Cargando logros desde el servidor...
            </Text>
          )}
        </View>

        {/* Categories */}
        {categories.map(category => {
          const categoryAchievements = (displayAchievements || []).filter(a => a.achievementType?.category?.toLowerCase() === category.key);
          const categoryCompleted = categoryAchievements.filter(a => a.status?.toLowerCase() === 'earned' || a.status?.toLowerCase() === 'claimed').length;
          
          // Skip empty categories
          if (categoryAchievements.length === 0) {
            return null;
          }
          
          return (
            <View key={category.key} style={styles.categorySection}>
              <View style={styles.categoryHeader}>
                <View style={styles.categoryTitleRow}>
                  <Icon name={category.icon} size={20} color={getCategoryColor(category.key)} />
                  <Text style={styles.categoryTitle}>{category.name}</Text>
                </View>
                <Text style={styles.categoryProgress}>
                  {categoryCompleted}/{categoryAchievements.length}
                </Text>
              </View>

              {categoryAchievements.map(achievement => {
                // Debug logging for referral achievement
                if (achievement?.achievementType?.slug === 'referido_exitoso' || achievement?.achievementType?.slug === 'successful_referral') {
                  console.log('Found referral achievement:', {
                    slug: achievement.achievementType.slug,
                    status: achievement.status,
                    name: achievement.name,
                    id: achievement.id
                  });
                }
                return (
                <TouchableOpacity
                  key={achievement.id}
                  style={[
                    styles.achievementCard,
                    (achievement.status?.toLowerCase() === 'earned' || achievement.status?.toLowerCase() === 'claimed') && styles.achievementCardCompleted,
                    ((achievement?.achievementType?.slug === 'referido_exitoso' || achievement?.achievementType?.slug === 'successful_referral') && achievement?.status?.toLowerCase() === 'pending') && styles.achievementCardReferral,
                    achievement?.achievementType?.slug === 'pionero_beta' && styles.achievementCardPionero
                  ]}
                  onPress={() => {
                    console.log('Achievement clicked:', {
                      name: achievement?.name,
                      slug: achievement?.achievementType?.slug,
                      status: achievement?.status,
                      statusLower: achievement?.status?.toLowerCase()
                    });
                    
                    // Special handling for Pionero Beta - show modal
                    if (achievement?.achievementType?.slug === 'pionero_beta') {
                      setSelectedAchievement({
                        id: achievement.id,
                        name: achievement.name,
                        description: achievement.description,
                        confioReward: achievement.achievementType.confioReward || 0,
                        category: achievement.achievementType.category,
                        slug: achievement.achievementType.slug,
                        status: achievement.status
                      });
                      setShowPioneroModal(true);
                    } else if (achievement?.status?.toLowerCase() === 'earned') {
                      handleClaimReward(achievement);
                    } else if (achievement?.status?.toLowerCase() === 'claimed' || 
                              (achievement?.achievementType?.slug === 'referido_exitoso' && achievement?.status?.toLowerCase() === 'pending')) {
                      handleShare(achievement);
                    }
                  }}
                  disabled={!achievement || (achievement.status?.toLowerCase() === 'pending' && (achievement?.achievementType?.slug !== 'referido_exitoso' && achievement?.achievementType?.slug !== 'successful_referral' && achievement?.achievementType?.slug !== 'pionero_beta'))}
                >
                  <View style={[
                    styles.achievementIcon,
                    (achievement?.status?.toLowerCase() === 'earned' || achievement?.status?.toLowerCase() === 'claimed') && styles.achievementIconCompleted,
                    achievement?.achievementType?.slug === 'pionero_beta' && styles.achievementIconPionero
                  ]}>
                    {achievement?.achievementType?.slug === 'pionero_beta' ? (
                      <Image 
                        source={require('../assets/png/PioneroBeta.png')} 
                        style={styles.pioneroBadge}
                        resizeMode="contain"
                      />
                    ) : achievement?.achievementType?.iconEmoji ? (
                      <Text style={styles.achievementEmoji}>{achievement.achievementType.iconEmoji}</Text>
                    ) : (
                      <Icon 
                        name={getCategoryIcon(achievement?.achievementType?.category || 'onboarding')} 
                        size={24} 
                        color={(achievement?.status?.toLowerCase() === 'earned' || achievement?.status?.toLowerCase() === 'claimed') ? '#fff' : '#9CA3AF'} 
                      />
                    )}
                  </View>

                  <View style={styles.achievementContent}>
                    <View style={styles.achievementTitleRow}>
                      <Text style={[
                        styles.achievementName,
                        achievement?.status?.toLowerCase() === 'pending' && styles.achievementNameLocked
                      ]}>
                        {achievement?.name || 'Unknown Achievement'}
                      </Text>
                      {achievement?.status?.toLowerCase() === 'earned' && (
                        <View style={styles.claimableBadge}>
                          <Text style={styles.claimableText}>¡Reclamar!</Text>
                        </View>
                      )}
                      {achievement?.status?.toLowerCase() === 'claimed' && (
                        <Icon name="check-circle" size={16} color={colors.primary} />
                      )}
                      {/* Show share hint for pending referral achievement */}
                      {(achievement?.achievementType?.slug === 'referido_exitoso' || achievement?.achievementType?.slug === 'successful_referral') && achievement?.status?.toLowerCase() === 'pending' && (
                        <View style={styles.shareHintBadge}>
                          <Icon name="share-2" size={12} color="#fff" />
                          <Text style={styles.shareHintText}>Compartir</Text>
                        </View>
                      )}
                    </View>
                    <Text style={styles.achievementDescription}>
                      {achievement?.description || 'No description available'}
                    </Text>
                    
                    {achievement?.progressData && achievement?.status?.toLowerCase() === 'pending' && (
                      <View style={styles.achievementProgressContainer}>
                        <View style={styles.achievementProgressBg}>
                          <View 
                            style={[
                              styles.achievementProgressFill,
                              { width: `${getProgressPercentage(achievement)}%` }
                            ]} 
                          />
                        </View>
                        <Text style={styles.achievementProgressText}>
                          {achievement.progressData?.current || 0}/{achievement.progressData?.target || 1}
                        </Text>
                      </View>
                    )}

                    {(achievement?.achievementType?.confioReward || 0) > 0 && (
                      <View style={styles.rewardContainer}>
                        <Icon name="gift" size={14} color={colors.violet} />
                        <Text style={styles.rewardText}>{achievement?.achievementType?.confioReward || 0} $CONFIO</Text>
                      </View>
                    )}

                    {achievement?.earnedAt && (
                      <Text style={styles.achievementDate}>
                        {achievement?.status?.toLowerCase() === 'claimed' ? 'Reclamado' : 'Completado'}: {new Date(achievement.earnedAt).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })}
                      </Text>
                    )}
                  </View>

                  {/* Show action button for earned/claimed achievements OR for pending referral achievement */}
                  {((achievement?.status?.toLowerCase() === 'earned' || achievement?.status?.toLowerCase() === 'claimed') || 
                    ((achievement?.achievementType?.slug === 'referido_exitoso' || achievement?.achievementType?.slug === 'successful_referral') && achievement?.status?.toLowerCase() === 'pending')) && (
                    <TouchableOpacity 
                      style={styles.actionButton}
                      onPress={() => {
                        if (achievement?.status?.toLowerCase() === 'earned') {
                          handleClaimReward(achievement);
                        } else if (achievement?.status?.toLowerCase() === 'claimed' || 
                                  ((achievement?.achievementType?.slug === 'referido_exitoso' || achievement?.achievementType?.slug === 'successful_referral') && achievement?.status?.toLowerCase() === 'pending')) {
                          handleShare(achievement);
                        }
                      }}
                    >
                      <Icon 
                        name={achievement?.status?.toLowerCase() === 'earned' ? "gift" : "share-2"} 
                        size={20} 
                        color={achievement?.status?.toLowerCase() === 'earned' ? colors.violet : colors.accent} 
                      />
                    </TouchableOpacity>
                  )}
                </TouchableOpacity>
              );})}
            </View>
          );
        })}

        <View style={styles.bottomPadding} />
      </ScrollView>
      
      {selectedAchievement && (
        <ShareAchievementModal
          visible={showShareModal}
          onClose={() => {
            setShowShareModal(false);
            setSelectedAchievement(null);
          }}
          achievement={selectedAchievement}
        />
      )}
      
      <ReferralInputModal
        visible={showReferralModal}
        onClose={() => setShowReferralModal(false)}
        onSuccess={() => {
          setShowReferralModal(false);
          // Optionally refresh achievements
          refetchAchievements();
        }}
      />
      
      {selectedAchievement && selectedAchievement.slug === 'pionero_beta' && (
        <PioneroBadgeModal
          visible={showPioneroModal}
          onClose={() => {
            setShowPioneroModal(false);
          }}
          achievement={selectedAchievement}
        />
      )}
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  header: {
    backgroundColor: colors.primary,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: 12,
    paddingBottom: 20,
    paddingHorizontal: 20,
  },
  backButton: {
    padding: 8,
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#fff',
  },
  headerSpacer: {
    width: 40,
  },
  scrollView: {
    flex: 1,
  },
  statsContainer: {
    flexDirection: 'row',
    paddingHorizontal: 16,
    paddingVertical: 20,
    gap: 12,
  },
  statCard: {
    flex: 1,
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    position: 'relative',
  },
  actionCardsWrapper: {
    paddingHorizontal: 16,
    marginBottom: 20,
  },
  actionCard: {
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1.5,
  },
  primaryActionCard: {
    backgroundColor: colors.violetLight,
    borderColor: colors.violet,
  },
  secondaryActionCard: {
    backgroundColor: colors.primaryLight,
    borderColor: colors.primary,
  },
  tertiaryActionCard: {
    backgroundColor: '#FFF7ED',
    borderColor: '#FB923C',
  },
  actionCardRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  actionCardContent: {
    flex: 1,
    marginLeft: 12,
  },
  actionCardTitle: {
    fontSize: 16,
    fontWeight: '700',
    marginBottom: 2,
  },
  actionCardDescription: {
    fontSize: 13,
    color: '#6B7280',
  },
  lockIcon: {
    position: 'absolute',
    top: 8,
    left: 8,
  },
  infoButton: {
    position: 'absolute',
    top: 8,
    right: 8,
    padding: 4,
  },
  statNumber: {
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 4,
  },
  statLabel: {
    fontSize: 12,
    color: '#6B7280',
  },
  inspirationalCard: {
    marginHorizontal: 16,
    marginBottom: 20,
    backgroundColor: colors.violetLight,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.violet,
  },
  inspirationalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  inspirationalTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.dark,
  },
  inspirationalText: {
    fontSize: 15,
    color: colors.dark,
    marginBottom: 6,
    fontWeight: '500',
  },
  inspirationalSubtext: {
    fontSize: 13,
    color: '#6B7280',
    marginBottom: 12,
  },
  learnMoreRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  learnMoreText: {
    fontSize: 14,
    color: colors.violet,
    fontWeight: '600',
  },
  progressContainer: {
    marginHorizontal: 16,
    marginBottom: 24,
    backgroundColor: colors.neutral,
    borderRadius: 12,
    padding: 16,
  },
  progressHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  progressTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.dark,
  },
  progressText: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.primary,
  },
  progressBarBg: {
    height: 8,
    backgroundColor: '#E5E7EB',
    borderRadius: 4,
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    backgroundColor: colors.primary,
    borderRadius: 4,
  },
  categorySection: {
    marginBottom: 24,
    paddingHorizontal: 16,
  },
  categoryHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  categoryTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  categoryTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.dark,
  },
  categoryProgress: {
    fontSize: 14,
    color: '#6B7280',
  },
  achievementCard: {
    flexDirection: 'row',
    backgroundColor: colors.neutral,
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  achievementCardCompleted: {
    borderColor: colors.primaryLight,
    backgroundColor: '#F0FDF4',
  },
  achievementCardReferral: {
    backgroundColor: '#e8f4ff',
    borderColor: colors.accent,
    borderWidth: 1.5,
  },
  achievementCardPionero: {
    backgroundColor: '#FFF8DC',
    borderColor: '#FFD700',
    borderWidth: 2,
    shadowColor: '#FFD700',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.25,
    shadowRadius: 3.84,
    elevation: 5,
  },
  achievementIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#E5E7EB',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  achievementIconCompleted: {
    backgroundColor: colors.primary,
  },
  achievementIconPionero: {
    backgroundColor: '#FFD700',
    borderWidth: 2,
    borderColor: '#FFA500',
  },
  pioneroBadge: {
    width: 36,
    height: 36,
  },
  achievementContent: {
    flex: 1,
  },
  achievementName: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.dark,
    marginBottom: 4,
  },
  achievementNameLocked: {
    color: '#9CA3AF',
  },
  achievementDescription: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 8,
  },
  achievementProgressContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 8,
  },
  achievementProgressBg: {
    flex: 1,
    height: 4,
    backgroundColor: '#E5E7EB',
    borderRadius: 2,
    overflow: 'hidden',
  },
  achievementProgressFill: {
    height: '100%',
    backgroundColor: colors.primary,
    borderRadius: 2,
  },
  achievementProgressText: {
    fontSize: 12,
    color: '#6B7280',
  },
  rewardContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginTop: 4,
  },
  rewardText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.violet,
  },
  achievementDate: {
    fontSize: 12,
    color: '#9CA3AF',
    marginTop: 4,
  },
  shareButton: {
    padding: 8,
  },
  bottomPadding: {
    height: 40,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    fontSize: 16,
    color: '#6B7280',
  },
  actionCardsContainer: {
    paddingHorizontal: 16,
    marginBottom: 20,
    gap: 12,
  },
  actionCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 16,
    borderRadius: 16,
    borderWidth: 1,
    marginBottom: 12,
  },
  primaryActionCard: {
    backgroundColor: colors.violetLight,
    borderColor: colors.violet,
    borderWidth: 2,
  },
  secondaryActionCard: {
    backgroundColor: colors.primaryLight,
    borderColor: colors.primary,
  },
  tertiaryActionCard: {
    backgroundColor: '#FFF7ED',
    borderColor: '#FB923C',
  },
  actionCardContent: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  actionCardTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.dark,
    flex: 1,
  },
  actionCardDescription: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 2,
  },
  influencerCard: {
    marginHorizontal: 16,
    marginBottom: 20,
    backgroundColor: colors.primaryLight,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.primary,
  },
  orangeCard: {
    marginHorizontal: 16,
    marginBottom: 20,
    backgroundColor: '#FFF7ED',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: '#FB923C',
  },
  greenCard: {
    marginHorizontal: 16,
    marginBottom: 20,
    backgroundColor: colors.primaryLight,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.primary,
  },
  mintCard: {
    marginHorizontal: 16,
    marginBottom: 20,
    backgroundColor: colors.mintLight,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.mint,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  orangeTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#F59E0B',
  },
  orangeText: {
    fontSize: 15,
    color: '#92400E',
    marginBottom: 12,
    fontWeight: '500',
  },
  orangeLearnMore: {
    fontSize: 14,
    color: '#F59E0B',
    fontWeight: '600',
  },
  orangeInputCard: {
    marginHorizontal: 16,
    marginBottom: 20,
    backgroundColor: '#FFF7ED',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: '#FB923C',
  },
  orangeInputHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  orangeInputTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#F59E0B',
  },
  greenTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.primary,
  },
  greenText: {
    fontSize: 15,
    color: '#047857',
    marginBottom: 12,
    fontWeight: '500',
  },
  greenLearnMore: {
    fontSize: 14,
    color: colors.primary,
    fontWeight: '600',
  },
  mintTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.mint,
  },
  mintText: {
    fontSize: 15,
    color: '#0F766E',
    marginBottom: 12,
    fontWeight: '500',
  },
  mintLearnMore: {
    fontSize: 14,
    color: colors.mint,
    fontWeight: '600',
  },
  shareButtonsRow: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 12,
  },
  socialShareButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: 'rgba(255, 255, 255, 0.8)',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.mint,
  },
  socialShareText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.mint,
  },
  influencerInputCard: {
    marginHorizontal: 16,
    marginBottom: 20,
    backgroundColor: colors.neutralDark,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.violet,
  },
  influencerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  influencerTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.dark,
  },
  influencerText: {
    fontSize: 15,
    color: colors.dark,
    marginBottom: 12,
    fontWeight: '500',
  },
  influencerInputLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.dark,
    marginBottom: 8,
  },
  influencerInput: {
    backgroundColor: '#fff',
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    marginBottom: 16,
  },
  inputWithAt: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    marginBottom: 12,
  },
  atSymbol: {
    paddingLeft: 12,
    paddingRight: 4,
    fontSize: 16,
    fontWeight: '600',
    color: colors.violet,
  },
  influencerInputWithAt: {
    flex: 1,
    padding: 12,
    fontSize: 16,
    paddingLeft: 0,
  },
  inputHint: {
    fontSize: 12,
    color: '#6B7280',
    fontStyle: 'italic',
    marginBottom: 16,
  },
  influencerButtonRow: {
    flexDirection: 'row',
    gap: 12,
  },
  cancelButton: {
    flex: 1,
    backgroundColor: '#E5E7EB',
    borderRadius: 8,
    padding: 12,
    alignItems: 'center',
  },
  cancelButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#6B7280',
  },
  submitButton: {
    flex: 1,
    backgroundColor: colors.violet,
    borderRadius: 8,
    padding: 12,
    alignItems: 'center',
  },
  submitButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#fff',
  },
  achievementEmoji: {
    fontSize: 24,
  },
  achievementTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
  },
  claimableBadge: {
    backgroundColor: colors.violet,
    borderRadius: 12,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  claimableText: {
    fontSize: 10,
    fontWeight: '600',
    color: '#fff',
  },
  shareHintBadge: {
    backgroundColor: colors.accent,
    borderRadius: 12,
    paddingHorizontal: 8,
    paddingVertical: 2,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  shareHintText: {
    fontSize: 10,
    fontWeight: '600',
    color: '#fff',
  },
  actionButton: {
    padding: 8,
  },
  categoryTitlePriority: {
    fontWeight: '700',
    color: colors.violet,
  },
  noDataText: {
    fontSize: 12,
    color: '#9CA3AF',
    textAlign: 'center',
    marginTop: 8,
  },
});
