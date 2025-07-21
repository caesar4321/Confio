import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  StatusBar,
  SafeAreaView,
} from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { MainStackParamList } from '../types/navigation';
import { useCurrency } from '../hooks/useCurrency';

type TraderProfileRouteProp = RouteProp<MainStackParamList, 'TraderProfile'>;
type TraderProfileNavigationProp = NativeStackNavigationProp<MainStackParamList, 'TraderProfile'>;

export const TraderProfileScreen: React.FC = () => {
  const navigation = useNavigation<TraderProfileNavigationProp>();
  const route = useRoute<TraderProfileRouteProp>();
  const { offer, crypto } = route.params;
  
  // Use currency system based on selected country
  const { currency, formatAmount } = useCurrency();

  const handleBack = () => {
    navigation.goBack();
  };

  const handleStartTrade = () => {
    navigation.navigate('TradeConfirm', { offer, crypto });
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="dark-content" backgroundColor="#fff" />
      
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity onPress={handleBack} style={styles.backButton}>
          <Icon name="arrow-left" size={24} color="#1F2937" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Perfil del Comerciante</Text>
        <View style={styles.placeholder} />
      </View>

      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.detailsCard}>
          <View style={styles.profileHeader}>
            <View style={styles.profileAvatarContainer}>
              <Text style={styles.profileAvatarText}>{offer.name.charAt(0)}</Text>
              {offer.isOnline && <View style={styles.onlineIndicatorLarge} />}
            </View>
            <View style={{flex: 1}}>
              <View style={{flexDirection: 'row', alignItems: 'center', marginBottom: 4}}>
                <Text style={styles.profileName}>{offer.name}</Text>
                {offer.verified && <Icon name="shield" size={20} color={colors.accent} style={{marginLeft: 8}} />}
              </View>
              <Text style={styles.lastSeenText}>{offer.lastSeen}</Text>
              <View style={{flexDirection: 'row', alignItems: 'center', marginTop: 4}}>
                <Icon name="star" size={16} color="#f59e0b" style={{marginRight: 4}} />
                <Text style={styles.profileStatsText}>{offer.successRate}% • {offer.completedTrades} operaciones</Text>
              </View>
            </View>
          </View>
          
          <View style={styles.statsGrid}>
            <View style={styles.statBox}>
              <Text style={styles.statLabel}>Tiempo de respuesta</Text>
              <Text style={styles.statValue}>{offer.responseTime}</Text>
            </View>
            <View style={styles.statBox}>
              <Text style={styles.statLabel}>Tasa de éxito</Text>
              <Text style={[styles.statValue, {color: '#16a34a'}]}>{offer.successRate}%</Text>
            </View>
          </View>
          
          <View style={{marginBottom: 16}}>
            <Text style={styles.sectionTitle}>Métodos de pago aceptados</Text>
            <View style={{gap: 8}}>
              {offer.paymentMethods.map((method, index) => (
                <View key={method.id || index} style={styles.paymentMethodRow}>
                  <View style={styles.paymentMethodIcon}>
                    <Text style={styles.paymentMethodIconText}>
                      {(method.displayName || method.name || 'M').charAt(0)}
                    </Text>
                  </View>
                  <Text style={styles.paymentMethodName}>
                    {method.displayName || method.name}
                  </Text>
                </View>
              ))}
            </View>
          </View>
          
          <View style={styles.infoBox}>
            <Icon name="info" size={20} color={colors.accent} style={{marginRight: 8, marginTop: 2}} />
            <View style={{flex: 1}}>
              <Text style={styles.infoBoxTitle}>Términos del comerciante</Text>
              <Text style={styles.infoBoxText}>
                {offer.terms || 'Pago dentro de 15 minutos. Enviar comprobante de pago antes de marcar como pagado.'}
              </Text>
            </View>
          </View>
        </View>
        
        <View style={styles.detailsCard}>
          <Text style={styles.sectionTitle}>Detalles de la oferta</Text>
          <View style={{gap: 12}}>
            <View style={styles.detailRow}>
              <Text style={styles.detailLabel}>Precio</Text>
              <Text style={styles.detailValueBold}>{formatAmount.withCode(offer.rate)} / {crypto}</Text>
            </View>
            <View style={styles.detailRow}>
              <Text style={styles.detailLabel}>Disponible</Text>
              <Text style={styles.detailValue}>{offer.available} {crypto}</Text>
            </View>
            <View style={styles.detailRow}>
              <Text style={styles.detailLabel}>Límites</Text>
              <Text style={styles.detailValue}>{offer.limit} {crypto}</Text>
            </View>
            <View style={styles.detailRow}>
              <Text style={styles.detailLabel}>Tiempo límite de pago</Text>
              <Text style={styles.detailValue}>15 minutos</Text>
            </View>
          </View>
        </View>
      </ScrollView>

      {/* Bottom Button */}
      <View style={styles.bottomButtonContainer}>
        <TouchableOpacity style={styles.bottomButton} onPress={handleStartTrade}>
          <Text style={styles.bottomButtonText}>Iniciar Intercambio</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 16,
    backgroundColor: '#fff',
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
  },
  backButton: {
    padding: 4,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1F2937',
  },
  placeholder: {
    width: 32,
  },
  content: {
    flex: 1,
    padding: 16,
  },
  detailsCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 1,
    },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  profileHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 16,
  },
  profileAvatarContainer: {
    position: 'relative',
    marginRight: 12,
  },
  profileAvatarText: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: colors.primary,
    color: '#fff',
    fontSize: 24,
    fontWeight: '600',
    textAlign: 'center',
    lineHeight: 60,
  },
  onlineIndicatorLarge: {
    position: 'absolute',
    bottom: 2,
    right: 2,
    width: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: '#16a34a',
    borderWidth: 2,
    borderColor: '#fff',
  },
  profileName: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1F2937',
  },
  lastSeenText: {
    fontSize: 14,
    color: '#6B7280',
  },
  profileStatsText: {
    fontSize: 14,
    color: '#6B7280',
  },
  statsGrid: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 16,
  },
  statBox: {
    flex: 1,
    backgroundColor: '#F9FAFB',
    borderRadius: 8,
    padding: 12,
  },
  statLabel: {
    fontSize: 12,
    color: '#6B7280',
    marginBottom: 4,
  },
  statValue: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2937',
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 12,
  },
  paymentMethodRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
  },
  paymentMethodIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  paymentMethodIconText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  paymentMethodName: {
    fontSize: 16,
    color: '#1F2937',
  },
  infoBox: {
    flexDirection: 'row',
    backgroundColor: '#FEF3C7',
    borderRadius: 8,
    padding: 12,
  },
  infoBoxTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#92400E',
    marginBottom: 4,
  },
  infoBoxText: {
    fontSize: 14,
    color: '#92400E',
    lineHeight: 20,
  },
  detailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  detailLabel: {
    fontSize: 16,
    color: '#6B7280',
  },
  detailValue: {
    fontSize: 16,
    color: '#1F2937',
    fontWeight: '500',
  },
  detailValueBold: {
    fontSize: 16,
    color: '#1F2937',
    fontWeight: '600',
  },
  bottomButtonContainer: {
    padding: 16,
    backgroundColor: '#fff',
    borderTopWidth: 1,
    borderTopColor: '#E5E7EB',
  },
  bottomButton: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: 'center',
  },
  bottomButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
}); 