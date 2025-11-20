import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet, AppState, AppStateStatus } from 'react-native';
import { useQuery } from '@apollo/client';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { GET_MY_BALANCES } from '../apollo/queries';
import { useAuth } from '../contexts/AuthContext';
import { colors } from '../config/theme';
import { navigationRef } from '../navigation/RootNavigation';

const USDC_THRESHOLD = 0.0001;

export const USDCConversionNotice: React.FC = () => {
  const { isAuthenticated } = useAuth();
  const insets = useSafeAreaInsets();

  const { data, loading, error, refetch } = useQuery(GET_MY_BALANCES, {
    skip: !isAuthenticated,
    fetchPolicy: 'network-only',
    nextFetchPolicy: 'network-only',
    pollInterval: 10000,
    notifyOnNetworkStatusChange: true,
  });

  const [lastUsdcBalance, setLastUsdcBalance] = React.useState<number | null>(null);

  React.useEffect(() => {
    const handleAppState = (state: AppStateStatus) => {
      if (state === 'active' && isAuthenticated) {
        refetch().catch(() => {});
      }
    };
    const sub = AppState.addEventListener('change', handleAppState);
    return () => sub.remove();
  }, [refetch, isAuthenticated]);

  React.useEffect(() => {
    if (error) {
      console.log('[USDCConversionNotice] Failed to fetch balances:', error);
    }
  }, [error]);

  const liveUsdcBalance = React.useMemo(() => {
    const parsed = parseFloat(data?.myBalances?.usdc ?? '0');
    return Number.isFinite(parsed) ? parsed : NaN;
  }, [data?.myBalances?.usdc]);

  React.useEffect(() => {
    if (Number.isFinite(liveUsdcBalance)) {
      setLastUsdcBalance(liveUsdcBalance);
    }
  }, [liveUsdcBalance]);

  const effectiveUsdcBalance = Number.isFinite(liveUsdcBalance)
    ? liveUsdcBalance
    : (lastUsdcBalance ?? 0);

  const shouldShowBanner = isAuthenticated && effectiveUsdcBalance > USDC_THRESHOLD;

  const handleConvert = React.useCallback(() => {
    navigationRef.navigate('Main' as never, {
      screen: 'USDCConversion',
    } as never);
  }, []);

  if (!shouldShowBanner) {
    return null;
  }

  return (
    <View style={[styles.container, { paddingTop: Math.max(insets.top + 4, 12), paddingBottom: 10 }]}> 
      <View style={styles.inner}> 
        <View style={styles.iconBubble}> 
          <Icon name="info" size={16} color={colors.primaryDark} style={styles.icon} /> 
        </View> 
        <View style={styles.textBlock}> 
          <Text style={styles.title}>Tienes USDC. Úsalo como cUSD.</Text> 
        </View> 
        <TouchableOpacity style={styles.ctaButton} activeOpacity={0.9} onPress={handleConvert}> 
          <Text style={styles.ctaText}>Convertir</Text> 
          <Icon name="chevron-right" size={14} color="#ffffff" /> 
        </TouchableOpacity> 
      </View> 
    </View> 
  ); 
}; 

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#ECFDF5',
    paddingHorizontal: 12,
    borderBottomColor: '#D1FAE5',
    borderBottomWidth: 1,
  },
  inner: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  iconBubble: {
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: '#D1FAE5',
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'center',
  },
  icon: {
    transform: [{ translateY: 0.5 }],
  },
  textBlock: {
    flex: 1,
    marginLeft: 12,
    justifyContent: 'center',
  },
  title: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.primaryDark,
    lineHeight: 18,
    textAlignVertical: 'center',
  },
  ctaButton: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    flexDirection: 'row',
    alignItems: 'center',
    marginLeft: 10,
    alignSelf: 'center',
  },
  ctaText: {
    color: '#ffffff',
    fontWeight: '700',
    fontSize: 12,
    marginRight: 4,
  },
});
