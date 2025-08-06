import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  Alert,
  ScrollView,
  ActivityIndicator,
  StyleSheet,
} from 'react-native';
import { useMutation, gql } from '@apollo/client';
import { EnhancedAuthService } from '../services/enhancedAuthService';

// Test mutation for regular (non-sponsored) transactions
const TEST_REGULAR_TRANSFER = gql`
  mutation TestRegularTransfer($input: TestRegularTransferInput!) {
    testRegularTransfer(input: $input) {
      success
      transactionHash
      error
      debugInfo
    }
  }
`;

export const TestRegularTransactionScreen: React.FC = () => {
  const [recipientAddress, setRecipientAddress] = useState('');
  const [amount, setAmount] = useState('0.001');  // Small amount of APT for testing
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);

  const [testRegularTransfer] = useMutation(TEST_REGULAR_TRANSFER);

  const handleTestTransaction = async () => {
    try {
      setLoading(true);
      setResult(null);

      // Validate inputs
      if (!recipientAddress || !recipientAddress.startsWith('0x')) {
        Alert.alert('Error', 'Please enter a valid Aptos address (starting with 0x)');
        return;
      }

      const amountNum = parseFloat(amount);
      if (isNaN(amountNum) || amountNum <= 0) {
        Alert.alert('Error', 'Please enter a valid amount');
        return;
      }

      // Get the auth service instance
      const enhancedAuthService = EnhancedAuthService.getInstance();
      const authService = enhancedAuthService.authService;
      
      // Get the current account data from authService
      const keylessAccount = authService.getCurrentAccount();
      console.log('Keyless account from authService:', JSON.stringify({
        exists: !!keylessAccount,
        address: keylessAccount?.address,
        hasJwt: !!keylessAccount?.jwt,
        hasEphemeralKeyPair: !!keylessAccount?.ephemeralKeyPair,
        hasPepper: !!keylessAccount?.pepper,
        keys: keylessAccount ? Object.keys(keylessAccount) : []
      }, null, 2));
      
      if (!keylessAccount || !keylessAccount.address) {
        Alert.alert('Error', 'No keyless account found. Please sign in first.');
        return;
      }

      console.log('Starting test regular transaction...');
      console.log('Sender address:', keylessAccount.address);
      console.log('Recipient:', recipientAddress);
      console.log('Amount:', amountNum);

      // Build transaction on client side
      const { AptosKeylessService } = await import('../services/aptosKeylessService');
      const aptosKeylessService = new AptosKeylessService();
      const aptos = aptosKeylessService.getAptosClient();

      // Build the transaction - use APT transfer for testing (simpler, always available)
      const amountUnits = Math.floor(amountNum * 1e8); // Convert to smallest units (8 decimals for APT)
      
      console.log('Building transaction for APT transfer...');
      const transaction = await aptos.transaction.build.simple({
        sender: keylessAccount.address,
        data: {
          function: '0x1::aptos_account::transfer',  // Use native APT transfer for testing
          functionArguments: [recipientAddress, amountUnits.toString()]
        }
      });

      console.log('Transaction built:', {
        hasRawTransaction: !!transaction.rawTransaction,
        rawTxLength: transaction.rawTransaction ? transaction.rawTransaction.bcsToBytes().length : 0
      });

      // Get raw transaction bytes
      const rawTxBytes = transaction.rawTransaction.bcsToBytes();
      const rawTransactionBase64 = Buffer.from(rawTxBytes).toString('base64');

      // Sign the transaction using keyless account
      console.log('Keyless account pepper:', keylessAccount.pepper);
      
      // Parse pepper - it might be hex string, comma-separated, or array
      let pepperBytes: Uint8Array;
      if (keylessAccount.pepper) {
        if (typeof keylessAccount.pepper === 'string') {
          // Check if it's a hex string
          if (keylessAccount.pepper.startsWith('0x')) {
            const hexStr = keylessAccount.pepper.slice(2);
            const bytes = [];
            for (let i = 0; i < hexStr.length; i += 2) {
              bytes.push(parseInt(hexStr.substr(i, 2), 16));
            }
            pepperBytes = new Uint8Array(bytes);
            
            // Pad to 31 bytes if needed
            if (pepperBytes.length === 30) {
              console.log('Padding pepper from 30 to 31 bytes');
              const paddedPepper = new Uint8Array(31);
              paddedPepper.set([0]); // Add leading zero
              paddedPepper.set(pepperBytes, 1);
              pepperBytes = paddedPepper;
            }
          } else if (keylessAccount.pepper.includes(',')) {
            // Comma-separated values
            pepperBytes = new Uint8Array(keylessAccount.pepper.split(',').map((p: string) => parseInt(p)));
          } else {
            // Try parsing as hex without 0x prefix
            const bytes = [];
            for (let i = 0; i < keylessAccount.pepper.length; i += 2) {
              bytes.push(parseInt(keylessAccount.pepper.substr(i, 2), 16));
            }
            pepperBytes = new Uint8Array(bytes);
          }
        } else {
          pepperBytes = new Uint8Array(keylessAccount.pepper);
        }
        
        console.log('Pepper bytes length:', pepperBytes.length);
        
        // Ensure pepper is exactly 31 bytes
        if (pepperBytes.length !== 31) {
          console.error('Invalid pepper length:', pepperBytes.length);
          Alert.alert('Error', `Invalid pepper length: ${pepperBytes.length} bytes (needs 31)`);
          return;
        }
      } else {
        // If no pepper stored, we might need to get it from elsewhere
        console.error('No pepper found in keyless account');
        Alert.alert('Error', 'Account pepper not found. Please sign in again.');
        return;
      }
      
      // Get ephemeral key pair - it should be in the keyless account
      const ephemeralKeyPair = keylessAccount.ephemeralKeyPair || authService.getEphemeralKeyPair();
      console.log('Ephemeral key pair exists:', !!ephemeralKeyPair);
      
      if (!ephemeralKeyPair) {
        Alert.alert('Error', 'Ephemeral key pair not found. Please sign in again.');
        return;
      }
      
      const authenticatorResponse = await aptosKeylessService.generateAuthenticator({
        jwt: keylessAccount.jwt,
        ephemeralKeyPair: ephemeralKeyPair,
        signingMessage: rawTransactionBase64,
        pepper: pepperBytes,
      });

      console.log('Authenticator generated:', {
        authenticatorLength: authenticatorResponse.senderAuthenticatorBcsBase64.length,
        addressHex: authenticatorResponse.addressHex
      });

      // Submit to backend for testing
      const response = await testRegularTransfer({
        variables: {
          input: {
            recipientAddress,
            amount: amountNum.toString(),
            rawTransaction: rawTransactionBase64,
            senderAuthenticator: authenticatorResponse.senderAuthenticatorBcsBase64,
          }
        }
      });

      console.log('Test transaction response:', response);

      if (response.data?.testRegularTransfer?.success) {
        setResult({
          success: true,
          transactionHash: response.data.testRegularTransfer.transactionHash,
          debugInfo: response.data.testRegularTransfer.debugInfo
        });
        Alert.alert(
          'Success!',
          `Transaction submitted successfully!\nHash: ${response.data.testRegularTransfer.transactionHash}`
        );
      } else {
        const error = response.data?.testRegularTransfer?.error || 'Unknown error';
        const debugInfo = response.data?.testRegularTransfer?.debugInfo;
        setResult({
          success: false,
          error,
          debugInfo
        });
        Alert.alert('Transaction Failed', error);
      }

    } catch (error) {
      console.error('Test transaction error:', error);
      setResult({
        success: false,
        error: error instanceof Error ? error.message : String(error)
      });
      Alert.alert('Error', error instanceof Error ? error.message : 'Failed to submit transaction');
    } finally {
      setLoading(false);
    }
  };

  return (
    <ScrollView style={styles.container}>
      <View style={styles.content}>
        <Text style={styles.title}>Test Regular Transaction</Text>
        <Text style={styles.subtitle}>
          Test a non-sponsored APT transfer to verify keyless account setup
        </Text>

        <View style={styles.inputContainer}>
          <Text style={styles.label}>Recipient Address</Text>
          <TextInput
            style={styles.input}
            value={recipientAddress}
            onChangeText={setRecipientAddress}
            placeholder="0x..."
            placeholderTextColor="#999"
          />
        </View>

        <View style={styles.inputContainer}>
          <Text style={styles.label}>Amount (APT)</Text>
          <TextInput
            style={styles.input}
            value={amount}
            onChangeText={setAmount}
            placeholder="1"
            keyboardType="decimal-pad"
            placeholderTextColor="#999"
          />
        </View>

        <TouchableOpacity
          style={[styles.button, loading && styles.buttonDisabled]}
          onPress={handleTestTransaction}
          disabled={loading}
        >
          {loading ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.buttonText}>Test Transaction</Text>
          )}
        </TouchableOpacity>

        {result && (
          <View style={styles.resultContainer}>
            <Text style={styles.resultTitle}>Result:</Text>
            {result.success ? (
              <>
                <Text style={styles.successText}>✅ Transaction Successful</Text>
                <Text style={styles.resultText}>Hash: {result.transactionHash}</Text>
              </>
            ) : (
              <>
                <Text style={styles.errorText}>❌ Transaction Failed</Text>
                <Text style={styles.resultText}>Error: {result.error}</Text>
              </>
            )}
            {result.debugInfo && (
              <View style={styles.debugContainer}>
                <Text style={styles.debugTitle}>Debug Info:</Text>
                <Text style={styles.debugText}>{result.debugInfo}</Text>
              </View>
            )}
          </View>
        )}
      </View>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  content: {
    padding: 20,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#333',
    marginBottom: 10,
  },
  subtitle: {
    fontSize: 14,
    color: '#666',
    marginBottom: 30,
  },
  inputContainer: {
    marginBottom: 20,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#333',
    marginBottom: 8,
  },
  input: {
    borderWidth: 1,
    borderColor: '#e0e0e0',
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
    color: '#333',
  },
  button: {
    backgroundColor: '#4F46E5',
    borderRadius: 8,
    padding: 16,
    alignItems: 'center',
    marginTop: 20,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  resultContainer: {
    marginTop: 20,
    padding: 15,
    backgroundColor: '#f5f5f5',
    borderRadius: 8,
  },
  resultTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 10,
  },
  successText: {
    color: 'green',
    fontSize: 14,
    marginBottom: 5,
  },
  errorText: {
    color: 'red',
    fontSize: 14,
    marginBottom: 5,
  },
  resultText: {
    fontSize: 12,
    color: '#333',
    marginBottom: 5,
  },
  debugContainer: {
    marginTop: 10,
    padding: 10,
    backgroundColor: '#e8e8e8',
    borderRadius: 5,
  },
  debugTitle: {
    fontSize: 12,
    fontWeight: 'bold',
    marginBottom: 5,
  },
  debugText: {
    fontSize: 10,
    color: '#666',
    fontFamily: 'monospace',
  },
});