import React, { useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, SafeAreaView, TextInput, Alert } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { useQuery, useMutation } from '@apollo/client';
import { InfluencerTierBadge } from '../components/InfluencerTierBadge';
import {
  GET_MY_INFLUENCER_STATS,
  GET_USER_INFLUENCER_REFERRALS,
  GET_USER_TIKTOK_SHARES,
  SUBMIT_TIKTOK_SHARE
} from '../apollo/queries';

const colors = {
  primary: '#34d399',
  primaryLight: '#d1fae5',
  secondary: '#8b5cf6',
  secondaryLight: '#e9d5ff',
  accent: '#3b82f6',
  neutral: '#f9fafb',
  neutralDark: '#f3f4f6',
  dark: '#111827',
  violet: '#8b5cf6',
  violetLight: '#ddd6fe',
};

type InfluencerTier = 'nano' | 'micro' | 'macro' | 'ambassador';

const getInfluencerTier = (referralCount: number): InfluencerTier => {
  if (referralCount >= 1000) return 'ambassador';
  if (referralCount >= 101) return 'macro';
  if (referralCount >= 11) return 'micro';
  return 'nano';
};

export const MiProgresoViralScreen = () => {
  const navigation = useNavigation();
  const [tiktokUrl, setTiktokUrl] = useState('');
  const [selectedHashtags, setSelectedHashtags] = useState<string[]>([]);
  
  // GraphQL queries
  const { data: influencerStats, loading: statsLoading, refetch: refetchStats } = useQuery(GET_MY_INFLUENCER_STATS);
  const { data: referralsData, loading: referralsLoading } = useQuery(GET_USER_INFLUENCER_REFERRALS);
  const { data: tikTokSharesData, loading: sharesLoading } = useQuery(GET_USER_TIKTOK_SHARES);
  
  // GraphQL mutations
  const [submitTikTokShare] = useMutation(SUBMIT_TIKTOK_SHARE);
  
  const stats = influencerStats?.myInfluencerStats || {
    totalReferrals: 0,
    activeReferrals: 0,
    convertedReferrals: 0,
    totalVolume: 0,
    totalConfioEarned: 0,
    isAmbassadorEligible: false
  };
  
  const referrals = referralsData?.userInfluencerReferrals || [];
  const tikTokShares = tikTokSharesData?.userTikTokShares || [];
  
  const currentTier = getInfluencerTier(stats.totalReferrals);
  const nextTierTargets = { nano: 11, micro: 101, macro: 1001, ambassador: null };
  const nextTarget = nextTierTargets[currentTier];
  
  const suggestedHashtags = [
    '#Confio', '#RetoConfio', '#LogroConfio', '#AppDeDolares', '#DolarDigital'
  ];
  
  const handleSubmitTikTok = async () => {
    if (!tiktokUrl.includes('tiktok.com')) {
      Alert.alert('Error', 'Por favor ingresa un enlace válido de TikTok');
      return;
    }
    
    try {
      const result = await submitTikTokShare({
        variables: {
          tiktokUrl: tiktokUrl.trim(),
          shareType: 'user_video',
          hashtagsUsed: JSON.stringify(selectedHashtags)
        }
      });
      
      if (result.data?.submitTikTokShare?.success) {
        Alert.alert(
          '¡Video Enviado!',
          'Hemos recibido tu TikTok. Te notificaremos cuando sea verificado y recibas CONFIO por las visualizaciones.',
          [{ text: 'OK' }]
        );
        setTiktokUrl('');
        setSelectedHashtags([]);
      } else {
        Alert.alert('Error', 'No se pudo procesar el TikTok');
      }
    } catch (error) {
      console.error('Error submitting TikTok:', error);
      Alert.alert('Error', 'Ocurrió un error al procesar el TikTok');
    }
  };
  
  const toggleHashtag = (hashtag: string) => {
    setSelectedHashtags(prev => 
      prev.includes(hashtag) 
        ? prev.filter(h => h !== hashtag)
        : [...prev, hashtag]
    );
  };
  
  if (statsLoading || referralsLoading || sharesLoading) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Mi Progreso Viral</Text>
          <View style={styles.headerSpacer} />
        </View>
        <View style={styles.loadingContainer}>
          <Text style={styles.loadingText}>Cargando progreso viral...</Text>
        </View>
      </SafeAreaView>
    );
  }
  
  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="arrow-left" size={24} color="#fff" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Mi Progreso Viral</Text>
        <View style={styles.headerSpacer} />
      </View>
      
      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Current Tier */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Tu Nivel Actual</Text>
          <InfluencerTierBadge 
            tier={currentTier} 
            referralCount={stats.totalReferrals}
            size="large"
          />
          
          {nextTarget && (
            <View style={styles.progressSection}>
              <Text style={styles.progressTitle}>
                Progreso al próximo nivel: {stats.totalReferrals}/{nextTarget}
              </Text>
              <View style={styles.progressBarBg}>
                <View 
                  style={[
                    styles.progressBarFill,
                    { width: `${Math.min((stats.totalReferrals / nextTarget) * 100, 100)}%` }
                  ]}
                />
              </View>
              <Text style={styles.progressSubtext}>
                Te faltan {Math.max(0, nextTarget - stats.totalReferrals)} referidos
              </Text>
            </View>
          )}
        </View>
        
        {/* Stats Overview */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Estadísticas</Text>
          <View style={styles.statsGrid}>
            <View style={styles.statCard}>
              <Text style={styles.statNumber}>{stats.totalReferrals}</Text>
              <Text style={styles.statLabel}>Total Referidos</Text>
            </View>
            <View style={styles.statCard}>
              <Text style={styles.statNumber}>{stats.activeReferrals}</Text>
              <Text style={styles.statLabel}>Activos</Text>
            </View>
            <View style={styles.statCard}>
              <Text style={styles.statNumber}>{stats.totalConfioEarned}</Text>
              <Text style={styles.statLabel}>CONFIO Ganado</Text>
            </View>
          </View>
        </View>
        
        {/* Submit TikTok Video */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Comparte tu TikTok</Text>
          <Text style={styles.sectionSubtitle}>
            Sube tu video sobre Confío y gana CONFIO extra por visualizaciones
          </Text>
          
          <TextInput
            style={styles.urlInput}
            value={tiktokUrl}
            onChangeText={setTiktokUrl}
            placeholder="Pega el enlace de tu TikTok aquí..."
            placeholderTextColor="#9CA3AF"
          />
          
          <Text style={styles.hashtagTitle}>Hashtags sugeridos:</Text>
          <View style={styles.hashtagContainer}>
            {suggestedHashtags.map(hashtag => (
              <TouchableOpacity
                key={hashtag}
                style={[
                  styles.hashtagButton,
                  selectedHashtags.includes(hashtag) && styles.hashtagSelected
                ]}
                onPress={() => toggleHashtag(hashtag)}
              >
                <Text style={[
                  styles.hashtagText,
                  selectedHashtags.includes(hashtag) && styles.hashtagTextSelected
                ]}>
                  {hashtag}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
          
          <TouchableOpacity
            style={styles.submitButton}
            onPress={handleSubmitTikTok}
            disabled={!tiktokUrl.trim()}
          >
            <Text style={styles.submitButtonText}>Enviar TikTok</Text>
          </TouchableOpacity>
          
          <TouchableOpacity
            style={styles.templatesButton}
            onPress={() => navigation.navigate('ViralTemplates')}
          >
            <Text style={styles.templatesButtonText}>🎬 Ver Ideas para Videos</Text>
          </TouchableOpacity>
        </View>
        
        {/* Recent TikTok Shares */}
        {tikTokShares.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Mis TikToks Recientes</Text>
            {tikTokShares.slice(0, 5).map((share: any) => (
              <View key={share.id} style={styles.shareCard}>
                <View style={styles.shareHeader}>
                  <Text style={styles.shareType}>
                    {share.shareType === 'achievement' ? '🏆 Logro' : '🎬 Video Original'}
                  </Text>
                  <View style={[
                    styles.statusBadge,
                    { backgroundColor: getStatusColor(share.status) }
                  ]}>
                    <Text style={styles.statusText}>{getStatusText(share.status)}</Text>
                  </View>
                </View>
                
                {share.viewCount && (
                  <Text style={styles.shareStats}>
                    👀 {share.viewCount.toLocaleString()} visualizaciones
                  </Text>
                )}
                
                {share.totalConfioAwarded > 0 && (
                  <Text style={styles.shareReward}>
                    🎁 {share.totalConfioAwarded} CONFIO ganado
                  </Text>
                )}
              </View>
            ))}
          </View>
        )}
        
        <View style={styles.bottomPadding} />
      </ScrollView>
    </SafeAreaView>
  );
};

const getStatusColor = (status: string) => {
  switch (status) {
    case 'verified': return '#22C55E';
    case 'rewarded': return '#3B82F6';
    case 'pending': return '#F59E0B';
    case 'rejected': return '#EF4444';
    default: return '#6B7280';
  }
};

const getStatusText = (status: string) => {
  switch (status) {
    case 'verified': return 'Verificado';
    case 'rewarded': return 'Recompensado';
    case 'pending': return 'Pendiente';
    case 'rejected': return 'Rechazado';
    default: return 'Enviado';
  }
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
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    fontSize: 16,
    color: '#6B7280',
  },
  section: {
    padding: 16,
    marginBottom: 8,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.dark,
    marginBottom: 12,
  },
  sectionSubtitle: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 16,
  },
  progressSection: {
    marginTop: 16,
  },
  progressTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.dark,
    marginBottom: 8,
  },
  progressBarBg: {
    height: 8,
    backgroundColor: '#E5E7EB',
    borderRadius: 4,
    overflow: 'hidden',
    marginBottom: 4,
  },
  progressBarFill: {
    height: '100%',
    backgroundColor: colors.primary,
    borderRadius: 4,
  },
  progressSubtext: {
    fontSize: 12,
    color: '#6B7280',
  },
  statsGrid: {
    flexDirection: 'row',
    gap: 12,
  },
  statCard: {
    flex: 1,
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
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
    textAlign: 'center',
  },
  urlInput: {
    backgroundColor: colors.neutralDark,
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  hashtagTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.dark,
    marginBottom: 8,
  },
  hashtagContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 16,
  },
  hashtagButton: {
    backgroundColor: colors.neutralDark,
    borderRadius: 16,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  hashtagSelected: {
    backgroundColor: colors.violetLight,
    borderColor: colors.violet,
  },
  hashtagText: {
    fontSize: 12,
    color: '#6B7280',
  },
  hashtagTextSelected: {
    color: colors.violet,
    fontWeight: '600',
  },
  submitButton: {
    backgroundColor: colors.violet,
    borderRadius: 8,
    padding: 16,
    alignItems: 'center',
  },
  submitButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#fff',
  },
  templatesButton: {
    backgroundColor: '#f3f4f6',
    borderRadius: 8,
    padding: 16,
    alignItems: 'center',
    marginTop: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  templatesButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.violet,
  },
  shareCard: {
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    padding: 12,
    marginBottom: 8,
  },
  shareHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  shareType: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.dark,
  },
  statusBadge: {
    borderRadius: 12,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  statusText: {
    fontSize: 10,
    fontWeight: '600',
    color: '#fff',
  },
  shareStats: {
    fontSize: 12,
    color: '#6B7280',
    marginBottom: 4,
  },
  shareReward: {
    fontSize: 12,
    color: colors.violet,
    fontWeight: '600',
  },
  bottomPadding: {
    height: 40,
  },
});