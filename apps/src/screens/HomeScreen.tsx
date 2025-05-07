import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Platform, Alert } from 'react-native';
import { Gradient } from '../components/common/Gradient';
import { AuthService } from '../services/authService';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useAuth } from '../contexts/AuthContext';

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

  React.useEffect(() => {
    const loadData = async () => {
      try {
        // First check server session
        const isSessionValid = await checkServerSession();
        if (!isSessionValid) {
          console.log('Session invalid, returning to auth screen');
          return;
        }

        // Get stored zkLogin data first
        const authService = AuthService.getInstance();
        let zkLoginData = await authService.getStoredZkLoginData();
        
        // If no data found, wait and retry once
        if (!zkLoginData) {
          console.log('No zkLogin data found, waiting and retrying...');
          await new Promise(resolve => setTimeout(resolve, 1000));
          zkLoginData = await authService.getStoredZkLoginData();
        }

        if (!zkLoginData) {
          console.log('Still no zkLogin data found after retry, returning to auth screen');
          return;
        }

        // Verify we have all required fields
        if (!zkLoginData.zkProof || !zkLoginData.salt || !zkLoginData.subject || !zkLoginData.clientId) {
          console.log('Missing required zkLogin data fields:', {
            hasProof: !!zkLoginData.zkProof,
            hasSalt: !!zkLoginData.salt,
            hasSubject: !!zkLoginData.subject,
            hasClientId: !!zkLoginData.clientId
          });
          return;
        }

        // Ensure the proof structure is valid
        if (!zkLoginData.zkProof.zkProof) {
          console.log('Invalid proof structure:', {
            hasZkProof: !!zkLoginData.zkProof.zkProof,
            hasSubject: !!zkLoginData.subject,
            hasClientId: !!zkLoginData.clientId
          });
          return;
        }

        // Then load Sui address
        console.log('Loading Sui address...');
        const address = await authService.getZkLoginAddress();
        console.log('Sui address loaded:', address);
        setSuiAddress(address);

        console.log('zkLogin data:', {
          hasZkProof: !!zkLoginData.zkProof,
          hasSubject: !!zkLoginData.subject,
          hasClientId: !!zkLoginData.clientId,
          zkProof: zkLoginData.zkProof
        });
      } catch (error) {
        console.error('Error loading data:', error);
        // If there's an error, check session again
        await checkServerSession();
      } finally {
        setIsLoading(false);
      }
    };

    loadData();
  }, []);

  const handleSignOut = async () => {
    try {
      console.log('Starting sign out process...');
      await signOut();
      setSuiAddress('');
      console.log('Sign out completed successfully');
    } catch (error) {
      console.error('Error during sign out:', error);
      Alert.alert(
        'Sign Out Error',
        'There was an error signing out. Please try again.'
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
          <Text style={styles.title}>Loading...</Text>
        </View>
      </Gradient>
    );
  }

  return (
    <Gradient
      fromColor="#5AC8A8"
      toColor="#72D9BC"
      style={styles.container}
    >
      <View style={styles.content}>
        <Text style={styles.title}>Welcome to Confío</Text>
        <Text style={styles.subtitle}>Your Sui wallet is ready</Text>
        {suiAddress && (
          <View style={styles.addressContainer}>
            <Text style={styles.addressLabel}>Your Sui Address:</Text>
            <Text style={styles.address}>
              {suiAddress.slice(0, 6)}...{suiAddress.slice(-4)}
            </Text>
          </View>
        )}
        <TouchableOpacity style={styles.signOutButton} onPress={handleSignOut}>
          <Text style={styles.signOutText}>Sign Out</Text>
        </TouchableOpacity>
      </View>
    </Gradient>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#FFFFFF',
    marginBottom: 10,
  },
  subtitle: {
    fontSize: 16,
    color: '#FFFFFF',
    opacity: 0.8,
    marginBottom: 30,
  },
  addressContainer: {
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
    padding: 15,
    borderRadius: 10,
    width: '100%',
    marginBottom: 30,
  },
  addressLabel: {
    color: '#FFFFFF',
    fontSize: 14,
    marginBottom: 5,
  },
  address: {
    color: '#FFFFFF',
    fontSize: 12,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  signOutButton: {
    backgroundColor: 'rgba(255, 255, 255, 0.2)',
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 20,
  },
  signOutText: {
    color: '#FFFFFF',
    fontSize: 16,
  },
}); 