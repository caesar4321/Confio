import React, { useCallback, useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  FlatList,
} from 'react-native';
import { useZkLogin, ZkLoginProof } from '../hooks/useZkLogin';

export const ZkLoginManager: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { generateProof, verifyProof, proofs, proofsLoading } = useZkLogin();

  const handleGenerateProof = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      // Calculate max epoch (current epoch + 1000)
      const currentEpoch = Math.floor(Date.now() / 1000);
      const maxEpoch = currentEpoch + 1000;
      
      await generateProof(maxEpoch);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate proof');
    } finally {
      setLoading(false);
    }
  }, [generateProof]);

  const handleVerifyProof = useCallback(async (proofId: string) => {
    try {
      setLoading(true);
      setError(null);
      await verifyProof(proofId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to verify proof');
    } finally {
      setLoading(false);
    }
  }, [verifyProof]);

  const renderProof = ({ item }: { item: ZkLoginProof }) => (
    <View style={styles.proofContainer}>
      <Text style={styles.proofId}>ID: {item.id}</Text>
      <Text>Created: {new Date(item.createdAt).toLocaleString()}</Text>
      <Text>Status: {item.isVerified ? 'Verified' : 'Unverified'}</Text>
      {!item.isVerified && (
        <TouchableOpacity
          style={styles.verifyButton}
          onPress={() => handleVerifyProof(item.id)}
        >
          <Text style={styles.buttonText}>Verify</Text>
        </TouchableOpacity>
      )}
    </View>
  );

  return (
    <View style={styles.container}>
      <TouchableOpacity
        style={styles.generateButton}
        onPress={handleGenerateProof}
        disabled={loading}
      >
        <Text style={styles.buttonText}>Generate New Proof</Text>
      </TouchableOpacity>

      {error && <Text style={styles.error}>{error}</Text>}

      {(loading || proofsLoading) && (
        <ActivityIndicator size="large" color="#0000ff" />
      )}

      <Text style={styles.title}>Your Proofs</Text>
      <FlatList
        data={proofs}
        renderItem={renderProof}
        keyExtractor={(item) => item.id}
        style={styles.list}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 16,
    backgroundColor: '#fff',
  },
  generateButton: {
    backgroundColor: '#007AFF',
    padding: 16,
    borderRadius: 8,
    alignItems: 'center',
    marginBottom: 16,
  },
  verifyButton: {
    backgroundColor: '#34C759',
    padding: 8,
    borderRadius: 6,
    alignItems: 'center',
    marginTop: 8,
  },
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  error: {
    color: '#FF3B30',
    marginBottom: 16,
  },
  title: {
    fontSize: 20,
    fontWeight: '600',
    marginBottom: 16,
  },
  list: {
    flex: 1,
  },
  proofContainer: {
    backgroundColor: '#F2F2F7',
    padding: 16,
    borderRadius: 8,
    marginBottom: 12,
  },
  proofId: {
    fontWeight: '600',
    marginBottom: 4,
  },
}); 