import React, { useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Share, Platform, SafeAreaView } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { useAuth } from '../contexts/AuthContext';
import { useAccount } from '../contexts/AccountContext';

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
};

type Achievement = {
  id: number;
  name: string;
  description: string;
  icon: string;
  completed: boolean;
  shared: boolean;
  date?: string;
  progress?: number;
  maxProgress?: number;
  reward?: string;
  shareText?: string;
  category: 'onboarding' | 'transactions' | 'social' | 'trading';
};

export const AchievementsScreen = () => {
  const navigation = useNavigation();
  const { userProfile } = useAuth();
  const { activeAccount } = useAccount();
  
  const [achievements] = useState<Achievement[]>([
    // Onboarding Achievements
    {
      id: 1,
      name: 'Primeros Pasos',
      description: 'Crea tu cuenta y verifica tu número',
      icon: 'user-check',
      completed: true,
      shared: true,
      date: '15 Nov',
      category: 'onboarding',
      shareText: '¡Acabo de unirme a Confío! La nueva forma de manejar dinero en Latinoamérica 🚀 #RetoConfio',
    },
    {
      id: 2,
      name: 'Cuenta Verificada',
      description: 'Completa la verificación de identidad',
      icon: 'shield',
      completed: false,
      shared: false,
      category: 'onboarding',
      progress: 0,
      maxProgress: 1,
      reward: '10 $CONFIO',
      shareText: '¡Mi cuenta está verificada en Confío! Ahora puedo hacer transacciones más seguras 🛡️ #RetoConfio',
    },
    
    // Transaction Achievements
    {
      id: 3,
      name: 'Primera Compra',
      description: 'Realiza tu primera compra de cUSD',
      icon: 'shopping-cart',
      completed: true,
      shared: false,
      date: '18 Nov',
      category: 'transactions',
      reward: '5 $CONFIO',
      shareText: '¡Hice mi primera compra de stablecoins en Confío! 💰 #RetoConfio',
    },
    {
      id: 4,
      name: 'Primer Envío',
      description: 'Envía dinero a un amigo',
      icon: 'send',
      completed: true,
      shared: true,
      date: '20 Nov',
      category: 'transactions',
      shareText: '¡Envié dinero instantáneamente con Confío! Sin comisiones bancarias 📲 #RetoConfio',
    },
    {
      id: 5,
      name: 'Primera Recepción',
      description: 'Recibe dinero de otro usuario',
      icon: 'download',
      completed: true,
      shared: false,
      date: '22 Nov',
      category: 'transactions',
      shareText: '¡Recibí mi primer pago en Confío! Directo a mi wallet 🎯 #RetoConfio',
    },
    {
      id: 6,
      name: 'Primer Pago',
      description: 'Paga en un comercio con QR',
      icon: 'credit-card',
      completed: true,
      shared: false,
      date: '25 Nov',
      category: 'transactions',
      shareText: '¡Pagué con QR en Confío! El futuro de los pagos en Latinoamérica 🛒 #RetoConfio',
    },
    
    // Trading Achievements
    {
      id: 7,
      name: 'Trader Novato',
      description: 'Completa tu primer intercambio P2P',
      icon: 'refresh-cw',
      completed: false,
      shared: false,
      category: 'trading',
      progress: 0,
      maxProgress: 1,
      shareText: '¡Completé mi primer intercambio P2P en Confío! 🔄 #RetoConfio',
    },
    {
      id: 8,
      name: 'Trader Frecuente',
      description: 'Completa 10 intercambios exitosos',
      icon: 'trending-up',
      completed: false,
      shared: false,
      category: 'trading',
      progress: 3,
      maxProgress: 10,
      shareText: '¡Ya hice 10 intercambios en Confío! Soy un trader frecuente 📈 #RetoConfio',
    },
    {
      id: 9,
      name: 'Trader Experto',
      description: 'Completa 50 intercambios exitosos',
      icon: 'award',
      completed: false,
      shared: false,
      category: 'trading',
      progress: 3,
      maxProgress: 50,
      reward: '100 $CONFIO',
      shareText: '¡Soy un Trader Experto en Confío! 50 intercambios completados 🏆 #RetoConfio',
    },
    
    // Social Achievements
    {
      id: 10,
      name: 'Embajador Confío',
      description: 'Invita a 5 amigos que se registren',
      icon: 'users',
      completed: false,
      shared: false,
      category: 'social',
      progress: 2,
      maxProgress: 5,
      reward: '50 $CONFIO',
      shareText: '¡Soy Embajador Confío! Únete con mi código y recibe beneficios 🎁 #RetoConfio',
    },
    {
      id: 11,
      name: 'Influencer Cripto',
      description: 'Comparte 10 logros en redes sociales',
      icon: 'share-2',
      completed: false,
      shared: false,
      category: 'social',
      progress: 2,
      maxProgress: 10,
      shareText: '¡Soy un Influencer Cripto en Confío! Sígueme para más tips 🌟 #RetoConfio',
    },
  ]);

  const handleShare = async (achievement: Achievement) => {
    try {
      const shareText = achievement.shareText || `¡Desbloqueé "${achievement.name}" en Confío! 🎉 #RetoConfio`;
      
      await Share.share({
        message: shareText,
        title: 'Logro en Confío',
      });
      
      // Here you would update the achievement as shared
      console.log('Achievement shared:', achievement.id);
    } catch (error) {
      console.error('Error sharing achievement:', error);
    }
  };

  const getCategoryColor = (category: Achievement['category']) => {
    switch (category) {
      case 'onboarding': return colors.primary;
      case 'transactions': return colors.accent;
      case 'trading': return colors.secondary;
      case 'social': return '#FF6B6B';
      default: return colors.primary;
    }
  };

  const getProgressPercentage = (progress?: number, maxProgress?: number) => {
    if (!progress || !maxProgress) return 0;
    return (progress / maxProgress) * 100;
  };

  const completedCount = achievements.filter(a => a.completed).length;
  const totalConfioMonedas = achievements.filter(a => a.completed).reduce((sum, a) => {
    if (a.reward) {
      const monedas = parseFloat(a.reward.split(' ')[0]);
      return sum + monedas;
    }
    return sum;
  }, 0);

  const categories = [
    { key: 'onboarding', name: 'Inicio', icon: 'home' },
    { key: 'transactions', name: 'Transacciones', icon: 'credit-card' },
    { key: 'trading', name: 'Intercambios', icon: 'refresh-cw' },
    { key: 'social', name: 'Social', icon: 'users' },
  ];

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
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
            <Text style={styles.statNumber}>{achievements.length}</Text>
            <Text style={styles.statLabel}>Total</Text>
          </View>
          <View style={styles.statCard}>
            <Icon name="lock" size={16} color={colors.violet} style={styles.lockIcon} />
            <Text style={styles.statNumber}>{totalConfioMonedas}</Text>
            <Text style={styles.statLabel}>$CONFIO</Text>
            <TouchableOpacity 
              style={styles.infoButton}
              onPress={() => navigation.navigate('ConfioTokenInfo' as any)}
            >
              <Icon name="info" size={14} color={colors.violet} />
            </TouchableOpacity>
          </View>
        </View>

        {/* Inspirational Message */}
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

        {/* Progress Bar */}
        <View style={styles.progressContainer}>
          <View style={styles.progressHeader}>
            <Text style={styles.progressTitle}>Progreso General</Text>
            <Text style={styles.progressText}>
              {Math.round((completedCount / achievements.length) * 100)}%
            </Text>
          </View>
          <View style={styles.progressBarBg}>
            <View 
              style={[
                styles.progressBarFill, 
                { width: `${(completedCount / achievements.length) * 100}%` }
              ]} 
            />
          </View>
        </View>

        {/* Categories */}
        {categories.map(category => {
          const categoryAchievements = achievements.filter(a => a.category === category.key);
          const categoryCompleted = categoryAchievements.filter(a => a.completed).length;
          
          return (
            <View key={category.key} style={styles.categorySection}>
              <View style={styles.categoryHeader}>
                <View style={styles.categoryTitleRow}>
                  <Icon name={category.icon} size={20} color={getCategoryColor(category.key as Achievement['category'])} />
                  <Text style={styles.categoryTitle}>{category.name}</Text>
                </View>
                <Text style={styles.categoryProgress}>
                  {categoryCompleted}/{categoryAchievements.length}
                </Text>
              </View>

              {categoryAchievements.map(achievement => (
                <TouchableOpacity
                  key={achievement.id}
                  style={[
                    styles.achievementCard,
                    achievement.completed && styles.achievementCardCompleted
                  ]}
                  onPress={() => achievement.completed && handleShare(achievement)}
                  disabled={!achievement.completed}
                >
                  <View style={[
                    styles.achievementIcon,
                    achievement.completed && styles.achievementIconCompleted
                  ]}>
                    <Icon 
                      name={achievement.icon} 
                      size={24} 
                      color={achievement.completed ? '#fff' : '#9CA3AF'} 
                    />
                  </View>

                  <View style={styles.achievementContent}>
                    <Text style={[
                      styles.achievementName,
                      !achievement.completed && styles.achievementNameLocked
                    ]}>
                      {achievement.name}
                    </Text>
                    <Text style={styles.achievementDescription}>
                      {achievement.description}
                    </Text>
                    
                    {achievement.progress !== undefined && achievement.maxProgress && !achievement.completed && (
                      <View style={styles.achievementProgressContainer}>
                        <View style={styles.achievementProgressBg}>
                          <View 
                            style={[
                              styles.achievementProgressFill,
                              { width: `${getProgressPercentage(achievement.progress, achievement.maxProgress)}%` }
                            ]} 
                          />
                        </View>
                        <Text style={styles.achievementProgressText}>
                          {achievement.progress}/{achievement.maxProgress}
                        </Text>
                      </View>
                    )}

                    {achievement.reward && (
                      <View style={styles.rewardContainer}>
                        <Icon name="gift" size={14} color={colors.violet} />
                        <Text style={styles.rewardText}>{achievement.reward}</Text>
                      </View>
                    )}

                    {achievement.completed && achievement.date && (
                      <Text style={styles.achievementDate}>
                        Completado: {achievement.date}
                      </Text>
                    )}
                  </View>

                  {achievement.completed && (
                    <TouchableOpacity 
                      style={styles.shareButton}
                      onPress={() => handleShare(achievement)}
                    >
                      <Icon 
                        name={achievement.shared ? "check-circle" : "share-2"} 
                        size={20} 
                        color={achievement.shared ? colors.primary : colors.accent} 
                      />
                    </TouchableOpacity>
                  )}
                </TouchableOpacity>
              ))}
            </View>
          );
        })}

        <View style={styles.bottomPadding} />
      </ScrollView>
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
});