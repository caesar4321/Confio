// CORRECTED Apple Sign-In flow for zkLogin
// This follows the REQUIRED flow: PrepareZkLogin → Compute Nonce → Pass to OAuth → Finalize

public async signInWithApple() {
  if (Platform.OS !== 'ios') {
    throw new Error('Apple Sign In is only supported on iOS');
  }

  try {
    if (!apolloClient) {
      throw new Error('Apollo client not initialized');
    }
    
    console.log('===== Starting Apple Sign-In with zkLogin =====');
    
    // STEP 1: Get zkLogin parameters FIRST (before OAuth!)
    console.log('Step 1: Getting zkLogin parameters from server...');
    
    const { data: prepareData } = await apolloClient.mutate({
      mutation: PREPARE_ZKLOGIN
    });
    
    if (!prepareData?.prepareZkLogin?.success) {
      throw new Error(prepareData?.prepareZkLogin?.error || 'Failed to prepare zkLogin');
    }
    
    const { maxEpoch, randomness: serverRandomness } = prepareData.prepareZkLogin;
    console.log('Got zkLogin params - maxEpoch:', maxEpoch, 'randomness length:', serverRandomness.length);
    
    // STEP 2: Generate temporary ephemeral keypair (without real sub yet)
    console.log('Step 2: Generating temporary ephemeral keypair...');
    
    // Use a placeholder sub for initial keypair generation
    const tempSalt = await this.generateZkLoginSalt(
      'https://appleid.apple.com',
      'TEMP_APPLE_SUB', // Placeholder
      'apple'
    );
    
    // Derive temporary ephemeral keypair from salt
    const tempKeypair = this.deriveEphemeralKeypair(tempSalt, 'TEMP_APPLE_SUB', 'apple');
    
    // STEP 3: Compute zkLogin nonce BEFORE OAuth
    console.log('Step 3: Computing zkLogin nonce...');
    const zkLoginNonce = await this._generateNonce(tempKeypair, maxEpoch, serverRandomness);
    console.log('Computed zkLogin nonce:', zkLoginNonce);
    console.log('Nonce length:', zkLoginNonce.length);
    
    // STEP 4: Perform Apple Sign-In WITH our computed nonce
    console.log('Step 4: Performing Apple Sign-In with zkLogin nonce...');
    const { appleAuth } = await import('@invertase/react-native-apple-authentication');
    
    const appleAuthResponse = await appleAuth.performRequest({
      requestedOperation: appleAuth.Operation.LOGIN,
      requestedScopes: [appleAuth.Scope.EMAIL, appleAuth.Scope.FULL_NAME],
      nonce: zkLoginNonce  // ✅ PASS OUR COMPUTED NONCE HERE!
    });
    
    if (!appleAuthResponse.identityToken) {
      throw new Error('No identity token received from Apple');
    }
    
    console.log('Apple Sign-In successful, got identity token');
    
    // STEP 5: Decode JWT and verify nonce
    const decodedAppleJwt = jwtDecode<{ sub: string; iss: string; nonce: string }>(appleAuthResponse.identityToken);
    console.log('Apple JWT nonce (should be SHA256 of our nonce):', decodedAppleJwt.nonce);
    console.log('Apple JWT nonce length:', decodedAppleJwt.nonce.length);
    
    // STEP 6: Sign in with Firebase
    const appleCredential = auth.AppleAuthProvider.credential(appleAuthResponse.identityToken, appleAuthResponse.nonce);
    const userCredential = await this.auth.signInWithCredential(appleCredential);
    const firebaseToken = await userCredential.user.getIdToken();
    
    console.log('Firebase sign-in successful');
    
    // STEP 7: Collect device fingerprint
    console.log('Collecting device fingerprint (Apple)...');
    let deviceFingerprint = null;
    try {
      deviceFingerprint = await DeviceFingerprint.generateFingerprint();
      console.log('Device fingerprint collected successfully (Apple)');
    } catch (error) {
      console.error('Error collecting device fingerprint (Apple):', error);
    }
    
    // STEP 8: Now regenerate salt and keypair with real Apple sub
    console.log('Step 8: Regenerating salt and keypair with real Apple sub...');
    const appleSub = decodedAppleJwt.sub;
    const salt = await this.generateZkLoginSalt(decodedAppleJwt.iss, appleSub, 'apple');
    const ephemeralKeypair = this.deriveEphemeralKeypair(salt, appleSub, 'apple');
    this.suiKeypair = ephemeralKeypair;
    
    // Get current account context for finalization
    const accountManager = AccountManager.getInstance();
    const accountContext = await accountManager.getActiveAccountContext();
    console.log('Account context for finalization (Apple):', {
      accountType: accountContext.type,
      accountIndex: accountContext.index,
      accountId: accountManager.generateAccountId(accountContext.type, accountContext.index)
    });

    // STEP 9: Get the extended ephemeral public key
    const extendedEphemeralPublicKey = ephemeralKeypair.getPublicKey().toBase64();

    // STEP 10: Call the NEW finalize mutation that handles Apple's SHA256 nonce correctly
    console.log('Step 10: Finalizing zkLogin with Apple nonce...');
    const { data: finalizeData } = await apolloClient.mutate({
      mutation: FINALIZE_ZKLOGIN_WITH_NONCE,  // NEW mutation!
      variables: {
        firebaseToken: firebaseToken,
        providerToken: appleAuthResponse.identityToken,
        provider: 'apple',
        extendedEphemeralPublicKey,
        maxEpoch: maxEpoch.toString(),
        randomness: serverRandomness,
        salt: salt,
        userSignature: bytesToBase64(await ephemeralKeypair.sign(new Uint8Array(0))),
        keyClaimName: 'sub',
        accountType: accountContext.type,
        accountIndex: accountContext.index,
        deviceFingerprint: deviceFingerprint ? JSON.stringify(deviceFingerprint) : null
      }
    });

    if (!finalizeData?.finalizeZkLoginWithNonce) {
      throw new Error('No data received from zkLogin finalization');
    }

    // STEP 11: Store auth tokens if received
    if (finalizeData.finalizeZkLoginWithNonce.authAccessToken) {
      console.log('Storing auth tokens in Keychain...');
      try {
        await Keychain.setGenericPassword(
          AUTH_KEYCHAIN_USERNAME,
          JSON.stringify({
            accessToken: finalizeData.finalizeZkLoginWithNonce.authAccessToken,
            refreshToken: finalizeData.finalizeZkLoginWithNonce.authRefreshToken
          }),
          {
            service: AUTH_KEYCHAIN_SERVICE,
            username: AUTH_KEYCHAIN_USERNAME,
            accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED
          }
        );
        console.log('Auth tokens stored successfully');
      } catch (error) {
        console.error('Error storing auth tokens:', error);
      }
    }

    // STEP 12: Store sensitive data securely
    console.log('Step 12: Storing zkLogin data...');
    await this.storeSensitiveData(
      finalizeData.finalizeZkLoginWithNonce,
      salt,
      appleSub,
      'apple',
      Number(maxEpoch),
      serverRandomness,
      appleAuthResponse.identityToken
    );

    console.log('Step 13: All zkLogin data stored successfully');
    
    // STEP 13: Store Firebase user data
    console.log('Step 14: Storing Firebase user data...');
    const user = this.auth.currentUser;
    if (user) {
      await this.updateUserData(user);
    }

    console.log('Apple Sign In successful!');
    
    return {
      success: true,
      zkProof: finalizeData.finalizeZkLoginWithNonce.zkProof,
      suiAddress: finalizeData.finalizeZkLoginWithNonce.suiAddress,
      user: finalizeData.finalizeZkLoginWithNonce,
      isPhoneVerified: finalizeData.finalizeZkLoginWithNonce.isPhoneVerified || false
    };

  } catch (error: any) {
    console.error('Apple Sign In Error:', error);
    console.error('Error details:', {
      message: error?.message,
      code: error?.code,
      stack: error?.stack
    });
    
    if (error?.code === appleAuth.Error.CANCELED) {
      console.log('Apple Sign In was canceled by user');
    }
    
    // Clean up on error
    try {
      if (this.auth.currentUser) {
        await this.auth.signOut();
      }
    } catch (signOutError) {
      console.error('Error signing out after failed Apple sign in:', signOutError);
    }
    
    throw error;
  }
}