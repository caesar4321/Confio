import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Platform, Alert, ScrollView, Image } from 'react-native';
import { Gradient } from '../components/common/Gradient';
import { AuthService } from '../services/authService';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useAuth } from '../contexts/AuthContext';
import cUSDLogo from '../assets/png/cUSD.png';
import USDCLogo from '../assets/png/USDC.png';
import CONFIOLogo from '../assets/png/CONFIO.png';

type RootStackParamList = {
  Auth: undefined;
  Home: undefined;
};

type HomeScreenNavigationProp = NativeStackNavigationProp<RootStackParamList, 'Home'>;

export const HomeScreen = () => {
  const navigation = useNavigation<HomeScreenNavigationProp>();
  const { signOut, checkServerSession } = useAuth();
  const [suiAddress, setSuiAddress] = React.useState<string>('');
  const [isLoading, setIsLoading] = React.useState(true);
  const [showLocalCurrency, setShowLocalCurrency] = useState(false);
  
  // Mock balances - replace with real data later
  const mockBalances = {
    cusd: "1,234.56",
    usdc: "789.10",
    confio: "1,000.00"
  };

  // Mock exchange rates - replace with real data later
  const mockLocalCurrency = {
    name: "Bolívares",
    rate: 35.5,
    symbol: "Bs."
  };

  React.useEffect(() => {
    const loadData = async () => {
      try {
        const isSessionValid = await checkServerSession();
        if (!isSessionValid) {
          console.log('Session invalid, returning to auth screen');
          return;
        }

        const authService = AuthService.getInstance();
        let zkLoginData = await authService.getStoredZkLoginData();
        
        if (!zkLoginData) {
          await new Promise(resolve => setTimeout(resolve, 1000));
          zkLoginData = await authService.getStoredZkLoginData();
        }

        if (zkLoginData) {
          const address = await authService.getZkLoginAddress();
          setSuiAddress(address);
        }
      } catch (error) {
        console.error('Error loading data:', error);
        await checkServerSession();
      } finally {
        setIsLoading(false);
      }
    };

    loadData();
  }, []);

  const handleSignOut = async () => {
    try {
      await signOut();
      setSuiAddress('');
    } catch (error) {
      console.error('Error during sign out:', error);
      Alert.alert(
        'Error al cerrar sesión',
        'Hubo un error al cerrar la sesión. Por favor intente de nuevo.'
      );
    }
  };

  if (isLoading) {
    return (
      <Gradient
        fromColor="#5AC8A8"
        toColor="#72D9BC"
        style={styles.container}
      >
        <View style={styles.content}>
          <Text style={styles.loadingText}>Cargando...</Text>
        </View>
      </Gradient>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: '#F3F4F6' }}>
      {/* Header Section */}
      <View style={styles.headerBox}>
        <View style={styles.headerTopRow}>
          <Text style={styles.headerTitle}>Confío</Text>
          <View style={styles.headerButtons}>
            <TouchableOpacity style={styles.headerCircleButton}>
              <Text style={styles.headerButtonText}>🔍</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.headerCircleButton}>
              <Text style={styles.headerButtonText}>🔔</Text>
            </TouchableOpacity>
          </View>
        </View>
        <Text style={styles.balanceLabel}>Dólares estadounidenses</Text>
        <Text style={styles.balanceAmount}>${mockBalances.cusd}</Text>
        <TouchableOpacity 
          style={styles.currencyToggle}
          onPress={() => setShowLocalCurrency(!showLocalCurrency)}
        >
          {showLocalCurrency && (
            <Text style={styles.localCurrency}>
              {mockLocalCurrency.symbol} {(Number(mockBalances.cusd.replace(',', '')) * mockLocalCurrency.rate).toLocaleString()}
            </Text>
          )}
          <Text style={styles.toggleText}>
            {showLocalCurrency ? 'Ocultar moneda local' : 'Mostrar en moneda local'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Wallets Section */}
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingTop: 12 }}>
        <View style={styles.assetsHeaderRow}>
          <Text style={styles.assetsTitle}>Mis Activos</Text>
        </View>
        <View style={styles.walletsContainer}>
          <View style={styles.assetCard}>
            <Image source={cUSDLogo} style={styles.assetLogo} />
            <View style={styles.assetInfo}>
              <Text style={styles.assetName}>Confío Dollar</Text>
              <Text style={styles.assetSymbol}>$cUSD</Text>
            </View>
            <View style={styles.assetValueBlock}>
              <Text style={styles.assetValue}>${mockBalances.cusd}</Text>
            </View>
          </View>
          <View style={styles.assetCard}>
            <Image source={USDCLogo} style={styles.assetLogo} />
            <View style={styles.assetInfo}>
              <Text style={styles.assetName}>USD Coin</Text>
              <Text style={styles.assetSymbol}>$USDC</Text>
            </View>
            <View style={styles.assetValueBlock}>
              <Text style={styles.assetValue}>${mockBalances.usdc}</Text>
            </View>
          </View>
          <View style={styles.assetCard}>
            <Image source={CONFIOLogo} style={styles.assetLogo} />
            <View style={styles.assetInfo}>
              <Text style={styles.assetName}>Confío</Text>
              <Text style={styles.assetSymbol}>$CONFIO</Text>
            </View>
            <View style={styles.assetValueBlock}>
              <Text style={styles.assetValue}>{mockBalances.confio}</Text>
            </View>
          </View>
        </View>
      </ScrollView>

      {/* Temporary Sign Out Button for Testing */}
      <View style={{ padding: 20 }}>
        <TouchableOpacity
          style={{
            backgroundColor: '#EF4444',
            paddingVertical: 14,
            borderRadius: 10,
            alignItems: 'center',
          }}
          onPress={handleSignOut}
        >
          <Text style={{ color: '#fff', fontWeight: 'bold', fontSize: 16 }}>Sign Out (Test)</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#1F2937',
  },
  content: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    fontSize: 18,
    color: '#FFFFFF',
    textAlign: 'center',
  },
  headerBox: {
    backgroundColor: '#72D9BC',
    borderBottomLeftRadius: 32,
    borderBottomRightRadius: 32,
    paddingTop: 56,
    paddingBottom: 32,
    paddingHorizontal: 20,
  },
  headerTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 24,
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#FFFFFF',
  },
  headerButtons: {
    flexDirection: 'row',
    gap: 12,
  },
  headerCircleButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.2)',
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: 8,
  },
  headerButtonText: {
    color: '#FFFFFF',
    fontSize: 20,
  },
  balanceLabel: {
    fontSize: 15,
    color: '#FFFFFF',
    opacity: 0.8,
    marginBottom: 4,
  },
  balanceAmount: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#FFFFFF',
    marginBottom: 20,
  },
  currencyToggle: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    borderWidth: 1,
    borderColor: '#FFFFFF',
    borderRadius: 16,
  },
  localCurrency: {
    color: '#FFFFFF',
    fontSize: 14,
    marginRight: 8,
  },
  toggleText: {
    color: '#FFFFFF',
    fontSize: 14,
  },
  assetsHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    marginBottom: 8,
  },
  assetsTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  walletsContainer: {
    gap: 14,
    paddingHorizontal: 12,
  },
  assetCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F8FAFC',
    borderRadius: 16,
    padding: 16,
    marginBottom: 6,
  },
  assetLogo: {
    width: 40,
    height: 40,
    borderRadius: 20,
    marginRight: 12,
  },
  assetInfo: {
    flex: 1,
  },
  assetName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  assetSymbol: {
    fontSize: 13,
    color: '#64748B',
    marginTop: 2,
  },
  assetValueBlock: {
    alignItems: 'flex-end',
    minWidth: 90,
  },
  assetValue: {
    fontSize: 17,
    fontWeight: 'bold',
    color: '#1F2937',
  },
}); 