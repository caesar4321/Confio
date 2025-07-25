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
import { getPaymentMethodIcon } from '../utils/paymentMethodIcons';
import { getCurrencyForCountry } from '../utils/currencyMapping';
import { useQuery, useMutation, gql } from '@apollo/client';
import { GET_P2P_OFFERS, GET_USER_BANK_ACCOUNTS, TOGGLE_FAVORITE_TRADER } from '../apollo/queries';
import { useAccount } from '../contexts/AccountContext';
import { useAuth } from '../contexts/AuthContext';
import { Alert } from 'react-native';

type TraderProfileRouteProp = RouteProp<MainStackParamList, 'TraderProfile'>;
type TraderProfileNavigationProp = NativeStackNavigationProp<MainStackParamList, 'TraderProfile'>;

export const TraderProfileScreen: React.FC = () => {
  const navigation = useNavigation<TraderProfileNavigationProp>();
  const route = useRoute<TraderProfileRouteProp>();
  const { offer, trader, crypto } = route.params;
  const { activeAccount } = useAccount();
  const { profileData: authProfileData } = useAuth();
  const user = authProfileData?.userProfile;
  const [expandedOffers, setExpandedOffers] = React.useState<Record<string, boolean>>({});
  const [isFavoriting, setIsFavoriting] = React.useState(false);
  const [isFavorite, setIsFavorite] = React.useState(false);
  
  // Use currency system based on selected country
  const { currency, formatAmount } = useCurrency();

  // Determine if we're in trader view mode or offer view mode
  const isTraderView = !!trader && !offer;
  const profileData = isTraderView ? trader : offer;
  
  // Define mutation inline to avoid import issues
  const TOGGLE_FAVORITE_MUTATION = gql`
    mutation ToggleFavoriteTrader($traderUserId: ID, $traderBusinessId: ID, $note: String) {
      toggleFavoriteTrader(traderUserId: $traderUserId, traderBusinessId: $traderBusinessId, note: $note) {
        success
        isFavorite
        message
      }
    }
  `;
  
  const [toggleFavorite] = useMutation(TOGGLE_FAVORITE_MUTATION);
  
  // Handle toggle favorite
  const handleToggleFavorite = async () => {
    if (!user || isFavoriting) return;
    
    try {
      setIsFavoriting(true);
      
      // Determine trader ID from the profile data
      let mutationVariables = {};
      if (trader?.businessId) {
        mutationVariables = { traderBusinessId: trader.businessId };
      } else if (trader?.userId) {
        mutationVariables = { traderUserId: trader.userId };
      } else if (offer?.offerBusiness?.id) {
        mutationVariables = { traderBusinessId: offer.offerBusiness.id };
      } else if (offer?.offerUser?.id) {
        mutationVariables = { traderUserId: offer.offerUser.id };
      } else if (offer?.user?.id) {
        mutationVariables = { traderUserId: offer.user.id };
      } else {
        Alert.alert('Error', 'No se pudo identificar al trader');
        return;
      }
      
      const { data } = await toggleFavorite({
        variables: mutationVariables
      });
      
      if (data?.toggleFavoriteTrader?.success) {
        setIsFavorite(data.toggleFavoriteTrader.isFavorite);
      } else {
        const message = data?.toggleFavoriteTrader?.message || 'No se pudo actualizar el favorito';
        Alert.alert('Error', message);
      }
    } catch (error) {
      console.error('Error toggling favorite:', error);
      Alert.alert('Error', 'Ocurrió un error al actualizar el favorito');
    } finally {
      setIsFavoriting(false);
    }
  };
  
  // Debug logging
  if (isTraderView && trader) {
    console.log('[TraderProfileScreen] Received trader data:', {
      name: trader.name,
      successRate: trader.successRate,
      avgRating: trader.avgRating,
      completedTrades: trader.completedTrades,
      typeOfSuccessRate: typeof trader.successRate,
      typeOfAvgRating: typeof trader.avgRating
    });
  }

  const handleBack = () => {
    navigation.goBack();
  };

  const handleStartTrade = () => {
    if (offer) {
      navigation.navigate('TradeConfirm', { offer, crypto: crypto || 'cUSD' });
    }
  };

  // Fetch all offers and filter by trader
  const { data: offersData, loading: offersLoading } = useQuery(GET_P2P_OFFERS, {
    skip: !isTraderView || !trader,
    fetchPolicy: 'cache-and-network',
  });

  // Fetch user's bank accounts for payment method availability check
  const { data: bankAccountsData } = useQuery(GET_USER_BANK_ACCOUNTS, {
    variables: { accountId: activeAccount?.id },
    skip: !activeAccount?.id,
    fetchPolicy: 'cache-and-network',
  });

  // Filter offers by this trader
  const traderOffers = React.useMemo(() => {
    if (!offersData?.p2pOffers || !trader) return [];
    
    console.log('[TraderProfile] Filtering offers for trader:', {
      traderId: trader.id,
      traderUserId: trader.userId,
      traderBusinessId: trader.businessId,
      traderName: trader.name,
      totalOffers: offersData.p2pOffers.length,
      sampleOffers: offersData.p2pOffers.slice(0, 3).map((o: any) => ({
        id: o.id,
        offerUserId: o.offerUser?.id,
        offerUserName: o.offerUser?.username || `${o.offerUser?.firstName} ${o.offerUser?.lastName}`,
        offerBusinessId: o.offerBusiness?.id,
        offerBusinessName: o.offerBusiness?.name,
        userStatsId: o.userStats?.id,
        oldUserId: o.user?.id,
        oldUserName: o.user?.username || `${o.user?.firstName} ${o.user?.lastName}`,
      })),
    });
    
    return offersData.p2pOffers.filter((offer: any) => {
      const offerUserId = offer.offerUser?.id || offer.user?.id;
      const offerBusinessId = offer.offerBusiness?.id;
      const offerBusinessName = offer.offerBusiness?.name;
      
      // For "Salud de Julian" it might be a business name match
      const businessNameMatch = offerBusinessName && 
                               offerBusinessName.toLowerCase() === trader.name.toLowerCase();
      
      // Check multiple ways to match using all available IDs
      const matches = offerUserId === trader.id || 
                     offerUserId === trader.userId ||
                     offerBusinessId === trader.id ||
                     offerBusinessId === trader.businessId ||
                     businessNameMatch ||
                     (offer.userStats?.id && (offer.userStats.id === trader.id || 
                                              offer.userStats.id === trader.userId ||
                                              offer.userStats.id === trader.businessId));
      
      if (matches || (offerBusinessName && trader.name.includes('Julian'))) {
        console.log('[TraderProfile] Potential match found:', {
          offerId: offer.id,
          offerUserId,
          offerUserName: offer.offerUser?.username || offer.offerUser?.firstName,
          offerBusinessId,
          offerBusinessName,
          userStatsId: offer.userStats?.id,
          traderId: trader.id,
          traderName: trader.name,
          matches,
        });
      }
      
      return matches;
    });
  }, [offersData, trader]);

  // Helper function to format amount with offer's currency
  const formatOfferAmount = (amount: string | number, countryCode?: string) => {
    if (!countryCode) return formatAmount.withCode(amount);
    
    // Create a dummy Country array with the country code at index 2
    const dummyCountry: any = ['', '', countryCode, ''];
    const currency = getCurrencyForCountry(dummyCountry);
    const amountStr = typeof amount === 'number' ? amount.toString() : amount;
    
    return `${currency} ${parseFloat(amountStr).toLocaleString('es-VE', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })}`;
  };

  // Check if an offer belongs to the current user/account
  const checkIfOwnOffer = (offer: any): boolean => {
    if (!activeAccount) return false;
    
    const isBusinessAccount = activeAccount.type === 'business';
    const currentBusinessId = isBusinessAccount ? activeAccount.business?.id : null;
    const currentUserId = userProfile?.id;
    
    if (isBusinessAccount) {
      // Business account viewing - only own if offer is from same business
      return offer.offerBusiness?.id === currentBusinessId;
    } else {
      // Personal account viewing - only own if offer is from same user (not business)
      // If the offer is from a business, it's not "own" even if same underlying user
      if (offer.offerBusiness) {
        return false; // Business offers are never "own" for personal accounts
      }
      
      // Check for old user field fallback
      const hasOldUserField = !!offer.user;
      if (hasOldUserField && !offer.offerUser && !offer.offerBusiness) {
        // Only use old field if new fields are missing (legacy data)
        return offer.user?.id === currentUserId;
      }
      
      return offer.offerUser?.id === currentUserId;
    }
  };

  // Helper function to check if user has payment methods for offer requirements
  const checkPaymentMethodAvailability = (offer: any): boolean => {
    const userBankAccounts = bankAccountsData?.userBankAccounts || [];
    if (userBankAccounts.length === 0) return false;
    
    // Check if user has any payment method that matches the offer's payment methods
    const offerPaymentMethods = offer.paymentMethods || [];
    
    return offerPaymentMethods.some((offerMethod: any) => {
      return userBankAccounts.some((userAccount: any) => {
        // First check if user has the new paymentMethod field
        if (userAccount.paymentMethod) {
          // Match by payment method ID
          if (userAccount.paymentMethod.id === offerMethod.id) {
            // Additional validation for required fields
            if (offerMethod.requiresPhone && !userAccount.phoneNumber) return false;
            if (offerMethod.requiresEmail && !userAccount.email) return false;
            if (offerMethod.requiresAccountNumber && !userAccount.accountNumber) return false;
            return true;
          }
        } 
        // Legacy check for old bank-only structure
        else if (offerMethod.providerType === 'BANK' && userAccount.bank) {
          return userAccount.bank.id === offerMethod.bank?.id;
        }
        return false;
      });
    });
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
              <Text style={styles.profileAvatarText}>{profileData!.name.charAt(0)}</Text>
              {profileData!.isOnline && <View style={styles.onlineIndicatorLarge} />}
            </View>
            <View style={{flex: 1}}>
              <View style={{flexDirection: 'row', alignItems: 'center', marginBottom: 4}}>
                <Text style={styles.profileName}>{profileData!.name}</Text>
                {profileData!.verified && <Icon name="shield" size={20} color={colors.accent} style={{marginLeft: 8}} />}
                {user && (
                  <TouchableOpacity 
                    style={styles.favoriteButton}
                    onPress={handleToggleFavorite}
                    disabled={isFavoriting}
                  >
                    <Icon 
                      name="star" 
                      size={20} 
                      color={isFavorite ? '#FBBF24' : '#9CA3AF'} 
                    />
                  </TouchableOpacity>
                )}
              </View>
              <Text style={styles.lastSeenText}>{profileData!.lastSeen}</Text>
              <View style={{flexDirection: 'row', alignItems: 'center', marginTop: 4}}>
                <Icon name="check-circle" size={16} color="#16a34a" style={{marginRight: 4}} />
                <Text style={styles.profileStatsText}>{Number(profileData!.successRate).toFixed(1)}% completado • {profileData!.completedTrades} operaciones</Text>
              </View>
            </View>
          </View>
          
          <View style={styles.statsGrid}>
            <View style={styles.statBox}>
              <Text style={styles.statLabel}>Tiempo de respuesta</Text>
              <Text style={styles.statValue}>{profileData!.responseTime}</Text>
            </View>
            <View style={styles.statBox}>
              <Text style={styles.statLabel}>{isTraderView ? 'Calificación' : 'Tasa de éxito'}</Text>
              <Text style={[styles.statValue, {color: '#16a34a'}]}>
                {isTraderView && trader?.avgRating ? 
                  `${trader.avgRating.toFixed(1)} ★` : 
                  `${Number(profileData!.successRate).toFixed(1)}%`
                }
              </Text>
            </View>
          </View>
          
          {/* Show payment methods only for offer view */}
          {!isTraderView && offer && (
            <>
              <View style={{marginBottom: 16}}>
                <Text style={styles.sectionTitle}>Métodos de pago aceptados</Text>
                <View style={{gap: 8}}>
                  {offer.paymentMethods.map((method, index) => (
                    <View key={method.id || index} style={styles.paymentMethodRow}>
                      <View style={styles.paymentMethodIcon}>
                        <Icon 
                          name={getPaymentMethodIcon(method.icon, method.providerType, method.displayName || method.name)} 
                          size={14} 
                          color="#fff" 
                        />
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
            </>
          )}

          {/* Show trader info for trader view */}
          {isTraderView && (
            <View style={styles.infoBox}>
              <Icon name="info" size={20} color={colors.accent} style={{marginRight: 8, marginTop: 2}} />
              <View style={{flex: 1}}>
                <Text style={styles.infoBoxTitle}>Información del trader</Text>
                <Text style={styles.infoBoxText}>
                  Este trader ha completado {trader.completedTrades} intercambios con una tasa de éxito del {Number(trader.successRate).toFixed(1)}%.
                  {trader.avgRating && trader.avgRating > 0 ? ` Su calificación promedio es ${trader.avgRating.toFixed(1)}/5.` : ''}
                </Text>
              </View>
            </View>
          )}
        </View>
        
        {/* Show offer details only for offer view */}
        {!isTraderView && offer && (
          <View style={styles.detailsCard}>
            <Text style={styles.sectionTitle}>Detalles de la oferta</Text>
            <View style={{gap: 12}}>
              <View style={styles.detailRow}>
                <Text style={styles.detailLabel}>Precio</Text>
                <Text style={styles.detailValueBold}>{formatOfferAmount(offer.rate, offer.countryCode)} / {crypto}</Text>
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
        )}

        {/* Show trader's offers for trader view */}
        {isTraderView && (
          <View style={styles.detailsCard}>
            <Text style={styles.sectionTitle}>
              Ofertas activas de {trader.name} ({traderOffers.length})
            </Text>
            {offersLoading ? (
              <View style={styles.loadingContainer}>
                <Text style={styles.loadingText}>Cargando ofertas...</Text>
              </View>
            ) : traderOffers.length === 0 ? (
              <View style={styles.emptyContainer}>
                <Icon name="inbox" size={32} color="#9CA3AF" />
                <Text style={styles.emptyText}>
                  Este trader no tiene ofertas activas en este momento
                </Text>
              </View>
            ) : (
              <View style={styles.offersContainer}>
                {traderOffers.map((offer: any) => {
                  const mappedOffer = {
                    id: offer.id,
                    name: trader.name,
                    rate: offer.rate.toString(),
                    limit: `${offer.minAmount} - ${offer.maxAmount}`,
                    available: offer.availableAmount.toString(),
                    paymentMethods: offer.paymentMethods || [],
                    responseTime: trader.responseTime,
                    completedTrades: trader.completedTrades,
                    successRate: trader.successRate,
                    verified: trader.verified,
                    isOnline: trader.isOnline,
                    lastSeen: trader.lastSeen,
                    countryCode: offer.countryCode,
                  };
                  
                  return (
                    <View key={offer.id} style={styles.offerCard}>
                      {/* Offer header with rate */}
                      <View style={styles.offerHeader}>
                        <View style={styles.offerInfo}>
                          <Text style={[
                            styles.offerType,
                            offer.exchangeType === 'SELL' ? styles.sellType : styles.buyType
                          ]}>
                            {offer.exchangeType === 'SELL' ? 'Vende' : 'Compra'} {offer.tokenType === 'CUSD' ? 'cUSD' : 'CONFIO'}
                          </Text>
                          <Text style={styles.offerLimits}>
                            Límite: {offer.minAmount} - {offer.maxAmount}
                          </Text>
                          <Text style={styles.offerAvailable}>
                            Disponible: {offer.availableAmount} {offer.tokenType === 'CUSD' ? 'cUSD' : 'CONFIO'}
                          </Text>
                        </View>
                        <View style={styles.offerRateContainer}>
                          <Text style={styles.rateValue}>{formatOfferAmount(offer.rate, offer.countryCode)}</Text>
                          <Text style={styles.ratePerCrypto}>/ {offer.tokenType === 'CUSD' ? 'cUSD' : 'CONFIO'}</Text>
                        </View>
                      </View>
                      
                      {/* Payment methods */}
                      <TouchableOpacity 
                        style={styles.paymentMethodsContainer}
                        onPress={() => setExpandedOffers(prev => ({ ...prev, [offer.id]: !prev[offer.id] }))}
                        activeOpacity={0.7}
                      >
                        {expandedOffers[offer.id] ? (
                          <View style={styles.paymentMethodsExpanded}>
                            <View style={styles.paymentMethodsList}>
                              {offer.paymentMethods.map((method: any, index: number) => (
                                <View key={method.id || index} style={styles.paymentMethodTag}>
                                  <Icon 
                                    name={getPaymentMethodIcon(method.icon, method.providerType, method.displayName || method.name)} 
                                    size={12} 
                                    color="#6B7280" 
                                  />
                                  <Text style={styles.paymentMethodText} numberOfLines={1}>
                                    {method.displayName || method.name}
                                  </Text>
                                </View>
                              ))}
                            </View>
                            <View style={styles.collapseIndicator}>
                              <Text style={styles.collapseText}>Ver menos</Text>
                              <Icon name="chevron-up" size={16} color="#6B7280" />
                            </View>
                          </View>
                        ) : (
                          <View style={styles.paymentMethodsCollapsed}>
                            <View style={styles.paymentMethodsList}>
                              {offer.paymentMethods.slice(0, 3).map((method: any, index: number) => (
                                <View key={method.id || index} style={styles.paymentMethodTag}>
                                  <Icon 
                                    name={getPaymentMethodIcon(method.icon, method.providerType, method.displayName || method.name)} 
                                    size={12} 
                                    color="#6B7280" 
                                  />
                                  <Text style={styles.paymentMethodText} numberOfLines={1}>
                                    {method.displayName || method.name}
                                  </Text>
                                </View>
                              ))}
                              {offer.paymentMethods.length > 3 && (
                                <View style={styles.expandIndicator}>
                                  <Text style={styles.morePaymentMethods}>
                                    +{offer.paymentMethods.length - 3} más
                                  </Text>
                                  <Icon name="chevron-down" size={16} color="#6B7280" />
                                </View>
                              )}
                            </View>
                          </View>
                        )}
                      </TouchableOpacity>
                      
                      {/* Action button */}
                      <TouchableOpacity 
                        style={styles.tradeButton}
                        onPress={() => {
                          // Check if user is trying to trade with themselves
                          const isOwnOffer = checkIfOwnOffer(offer);
                          
                          if (isOwnOffer) {
                            Alert.alert(
                              'No puedes comerciar con tu propia oferta',
                              'Esta oferta fue creada por tu cuenta. No puedes crear un intercambio con tus propias ofertas.',
                              [{ text: 'Entendido', style: 'default' }]
                            );
                            return;
                          }
                          
                          // Check if user has configured payment methods for this offer
                          if (!checkPaymentMethodAvailability(offer)) {
                            Alert.alert(
                              'Configura tu método de pago',
                              'Para intercambiar con esta oferta, primero debes configurar un método de pago compatible.',
                              [
                                { text: 'Cancelar', style: 'cancel' },
                                { 
                                  text: 'Configurar', 
                                  onPress: () => navigation.navigate('BankInfo'),
                                  style: 'default' 
                                }
                              ]
                            );
                            return;
                          }
                          
                          navigation.navigate('TradeConfirm', { 
                            offer: mappedOffer, 
                            crypto: offer.tokenType === 'CUSD' ? 'cUSD' : 'CONFIO',
                            tradeType: offer.exchangeType === 'SELL' ? 'buy' : 'sell'
                          });
                        }}
                      >
                        <Text style={styles.tradeButtonText}>
                          {offer.exchangeType === 'SELL' ? 'Comprar' : 'Vender'}
                        </Text>
                      </TouchableOpacity>
                    </View>
                  );
                })}
              </View>
            )}
          </View>
        )}
      </ScrollView>

      {/* Bottom Button - only for offer view */}
      {!isTraderView && offer && (
        <View style={styles.bottomButtonContainer}>
          <TouchableOpacity style={styles.bottomButton} onPress={handleStartTrade}>
            <Text style={styles.bottomButtonText}>Iniciar Intercambio</Text>
          </TouchableOpacity>
        </View>
      )}
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
  favoriteButton: {
    marginLeft: 8,
    padding: 4,
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
  loadingContainer: {
    padding: 20,
    alignItems: 'center',
  },
  loadingText: {
    color: '#6B7280',
    fontSize: 14,
  },
  emptyContainer: {
    padding: 32,
    alignItems: 'center',
    gap: 12,
  },
  emptyText: {
    color: '#6B7280',
    fontSize: 14,
    textAlign: 'center',
  },
  offersContainer: {
    gap: 12,
  },
  offerCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 2,
  },
  offerHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 12,
  },
  offerInfo: {
    flex: 1,
  },
  offerType: {
    fontSize: 14,
    fontWeight: '600',
    marginBottom: 4,
  },
  buyType: {
    color: colors.primary,
  },
  sellType: {
    color: '#EF4444',
  },
  offerLimits: {
    fontSize: 13,
    color: '#6B7280',
    marginBottom: 2,
  },
  offerAvailable: {
    fontSize: 13,
    color: '#6B7280',
  },
  offerRateContainer: {
    alignItems: 'flex-end',
  },
  rateValue: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.dark,
  },
  ratePerCrypto: {
    fontSize: 12,
    color: '#6B7280',
  },
  paymentMethodsContainer: {
    marginBottom: 12,
  },
  paymentMethodsCollapsed: {
    // Keep existing layout
  },
  paymentMethodsExpanded: {
    // Keep existing layout
  },
  paymentMethodsList: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
  },
  paymentMethodTag: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F3F4F6',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
    gap: 4,
  },
  paymentMethodText: {
    fontSize: 12,
    color: '#4B5563',
    maxWidth: 100,
  },
  morePaymentMethods: {
    fontSize: 12,
    color: '#6B7280',
    marginRight: 4,
  },
  expandIndicator: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 6,
  },
  collapseIndicator: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 8,
    paddingVertical: 4,
  },
  collapseText: {
    fontSize: 12,
    color: '#6B7280',
    marginRight: 4,
  },
  tradeButton: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: 'center',
  },
  tradeButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
}); 