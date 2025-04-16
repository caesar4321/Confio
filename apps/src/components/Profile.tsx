import React from 'react';
import { useQuery, useMutation } from '@apollo/client';
import { GET_USER_PROFILE, VERIFY_ZKLOGIN_PROOF } from '../apollo/queries';
import { View, Text, Button, ActivityIndicator } from 'react-native';

const Profile: React.FC = () => {
  const { loading, error, data } = useQuery(GET_USER_PROFILE);
  const [verifyProof, { loading: verifying }] = useMutation(VERIFY_ZKLOGIN_PROOF);

  if (loading) return <ActivityIndicator size="large" />;
  if (error) return <Text>Error: {error.message}</Text>;

  const handleVerifyProof = async () => {
    try {
      // TODO: Replace with actual proof data
      const proofData = "test_proof_data";
      await verifyProof({ variables: { proofData } });
    } catch (err) {
      console.error('Error verifying proof:', err);
    }
  };

  return (
    <View style={{ padding: 20 }}>
      <Text style={{ fontSize: 24, marginBottom: 20 }}>Profile</Text>
      <Text>Email: {data?.me?.email}</Text>
      <Text>Username: {data?.me?.username}</Text>
      
      <Text style={{ marginTop: 20, fontSize: 18 }}>ZK Login Proofs:</Text>
      {data?.me?.zkLoginProofs?.map((proof: any) => (
        <View key={proof.id} style={{ marginTop: 10 }}>
          <Text>ID: {proof.id}</Text>
          <Text>Verified: {proof.isVerified ? 'Yes' : 'No'}</Text>
          <Text>Created: {new Date(proof.createdAt).toLocaleDateString()}</Text>
        </View>
      ))}

      <Button
        title="Verify New Proof"
        onPress={handleVerifyProof}
        disabled={verifying}
      />
    </View>
  );
};

export default Profile; 