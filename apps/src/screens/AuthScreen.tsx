import React, { useState } from 'react';
import { View, Text, ActivityIndicator, StyleSheet } from 'react-native';
import auth from '@react-native-firebase/auth';
import { GoogleSignin } from '@react-native-google-signin/google-signin';
import { appleAuth } from '@invertase/react-native-apple-authentication';
import { useMutation } from '@apollo/client';
import { VERIFY_ZKLOGIN_PROOF } from '../apollo/queries';

const AuthScreen: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verifyProof] = useMutation(VERIFY_ZKLOGIN_PROOF);

  const handleGoogleSignIn = async () => {
    try {
      setLoading(true);
      setError(null);

      // Get the users ID token
      const { idToken } = await GoogleSignin.signIn() as { idToken: string };
      
      // Create a Google credential with the token
      const googleCredential = auth.GoogleAuthProvider.credential(idToken);
      
      // Sign-in the user with the credential
      const userCredential = await auth().signInWithCredential(googleCredential);
      
      // Get the Firebase ID token
      const firebaseToken = await userCredential.user.getIdToken();
      
      // Send the token to the prover and get the Sui address
      const { data } = await verifyProof({
        variables: {
          proofData: firebaseToken
        }
      });

      // Handle the Sui address response
      if (data?.verifyZkLoginProof?.suiAddress) {
        // TODO: Store the Sui address and navigate to the main app
        console.log('Sui Address:', data.verifyZkLoginProof.suiAddress);
      }

    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'An unknown error occurred';
      setError(errorMessage);
      console.error('Google Sign In Error:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleAppleSignIn = async () => {
    try {
      setLoading(true);
      setError(null);

      // Start the Apple sign-in process
      const appleAuthResponse = await appleAuth.performRequest({
        requestedOperation: appleAuth.Operation.LOGIN,
        requestedScopes: [appleAuth.Scope.EMAIL, appleAuth.Scope.FULL_NAME],
      });

      // Create a Firebase credential from the Apple response
      const { identityToken, nonce } = appleAuthResponse;
      const appleCredential = auth.AppleAuthProvider.credential(identityToken, nonce);

      // Sign in with the credential
      const userCredential = await auth().signInWithCredential(appleCredential);
      
      // Get the Firebase ID token
      const firebaseToken = await userCredential.user.getIdToken();
      
      // Send the token to the prover and get the Sui address
      const { data } = await verifyProof({
        variables: {
          proofData: firebaseToken
        }
      });

      // Handle the Sui address response
      if (data?.verifyZkLoginProof?.suiAddress) {
        // TODO: Store the Sui address and navigate to the main app
        console.log('Sui Address:', data.verifyZkLoginProof.suiAddress);
      }

    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'An unknown error occurred';
      setError(errorMessage);
      console.error('Apple Sign In Error:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.container}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {error && <Text style={styles.error}>{error}</Text>}
      {/* TODO: Add your sign-in buttons here */}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  error: {
    color: 'red',
    marginBottom: 20,
  },
});

export default AuthScreen; 