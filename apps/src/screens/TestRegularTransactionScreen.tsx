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
  const [amount, setAmount] = useState('1');
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
      if (!authService.currentAccount) {
        Alert.alert('Error', 'No account found. Please sign in first.');
        return;
      }

      console.log('Starting test regular transaction...');
      console.log('Sender:', authService.currentAccount.aptos_address);
      console.log('Recipient:', recipientAddress);
      console.log('Amount:', amountNum);

      // Build transaction on client side
      const { AptosKeylessService } = await import('../services/aptosKeylessService');
      const aptosKeylessService = new AptosKeylessService();
      const aptos = aptosKeylessService.getAptosClient();

      // Build the transaction
      const amountUnits = Math.floor(amountNum * 1e8); // Convert to smallest units (8 decimals for CONFIO)
      
      const transaction = await aptos.transaction.build.simple({
        sender: authService.currentAccount.aptos_address,
        data: {
          function: '0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c::confio::transfer_confio',
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
      const pepperBytes = new Uint8Array(authService.currentAccount.pepper.split(',').map((p: string) => parseInt(p)));
      
      const authenticatorResponse = await aptosKeylessService.generateAuthenticator({
        jwt: authService.currentAccount.jwt,
        ephemeralKeyPair: authService.ephemeralKeyPair,
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
          Test a non-sponsored keyless transaction to verify account setup
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
          <Text style={styles.label}>Amount (CONFIO)</Text>
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