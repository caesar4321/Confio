import { Router } from 'express';
import { 
  Aptos, 
  AptosConfig, 
  Network, 
  EphemeralKeyPair
} from '@aptos-labs/ts-sdk';
import loggerModule from '../logger';

const router = Router();
const logger = loggerModule;

// Initialize Aptos client for testnet
const config = new AptosConfig({ 
  network: Network.TESTNET
});
const aptos = new Aptos(config);

/**
 * Debug endpoint to test keyless account creation and signing
 * POST /api/keyless/debug-keyless
 */
router.post('/debug-keyless', async (req, res) => {
  try {
    const { jwt, ephemeralKeyPair, pepper, rawTransaction, senderAuthenticator } = req.body;
    
    // Support both modes - full keyless creation or just debugging existing tx
    if (rawTransaction && senderAuthenticator) {
      // Debug mode - analyze existing transaction and authenticator
      logger.info('Debug mode: Analyzing existing transaction and authenticator');
      
      const { Deserializer, AccountAuthenticator, RawTransaction } = require('@aptos-labs/ts-sdk');
      
      try {
        // Decode from base64
        const rawTxBytes = Buffer.from(rawTransaction, 'base64');
        const authBytes = Buffer.from(senderAuthenticator, 'base64');
        
        // Deserialize the raw transaction
        const rawTxDeserializer = new Deserializer(rawTxBytes);
        const rawTx = RawTransaction.deserialize(rawTxDeserializer);
        
        // Deserialize the authenticator
        const authDeserializer = new Deserializer(authBytes);
        const authenticator = AccountAuthenticator.deserialize(authDeserializer);
        
        // Extract details from authenticator
        let authDetails: any = {
          type: authenticator.constructor.name
        };
        
        // Check if it's a SingleKeyAuthenticator with Keyless
        if ((authenticator as any).public_key && (authenticator as any).signature) {
          const pubKey = (authenticator as any).public_key;
          const sig = (authenticator as any).signature;
          
          authDetails.publicKeyType = pubKey.constructor.name;
          authDetails.signatureType = sig.constructor.name;
          
          // If it's a keyless signature, extract more details
          if ((sig as any).cert) {
            const cert = (sig as any).cert;
            authDetails.hasOpenIdSig = !!(cert as any).openidSig;
            authDetails.hasEphemeralCert = !!(cert as any).ephemeralCert;
            authDetails.hasExpiryDateSecs = !!(cert as any).expiryDateSecs;
            
            // Check the ephemeral signature
            if ((sig as any).ephemeralSignature) {
              authDetails.ephemeralSigType = (sig as any).ephemeralSignature.constructor.name;
            }
          }
        }
        
        // Check account on-chain
        let accountInfo = null;
        try {
          accountInfo = await aptos.account.getAccountInfo({
            accountAddress: rawTx.sender
          });
        } catch (e) {
          logger.error('Account does not exist on-chain');
        }
        
        return res.json({
          success: true,
          debug: {
            transaction: {
              sender: rawTx.sender.toString(),
              sequenceNumber: rawTx.sequence_number.toString(),
              maxGasAmount: rawTx.max_gas_amount.toString(),
              gasUnitPrice: rawTx.gas_unit_price.toString(),
              expirationTimestampSecs: rawTx.expiration_timestamp_secs.toString(),
              chainId: rawTx.chain_id.value
            },
            authenticator: authDetails,
            account: accountInfo ? {
              exists: true,
              sequenceNumber: accountInfo.sequence_number,
              authenticationKey: accountInfo.authentication_key
            } : {
              exists: false,
              message: 'Account not found on-chain'
            }
          }
        });
      } catch (error: any) {
        return res.json({
          success: false,
          error: `Failed to analyze transaction: ${error.message}`,
          stack: error.stack
        });
      }
    }
    
    if (!jwt || !ephemeralKeyPair || !pepper) {
      return res.status(400).json({
        success: false,
        error: 'Missing jwt, ephemeralKeyPair, or pepper (or provide rawTransaction and senderAuthenticator for debug mode)'
      });
    }
    
    logger.info('Debug keyless endpoint called - full keyless flow');
    
    // Decode JWT to check details
    const jwtParts = jwt.split('.');
    const jwtPayload = JSON.parse(Buffer.from(jwtParts[1], 'base64').toString());
    
    logger.info('JWT details:', {
      aud: jwtPayload.aud,
      sub: jwtPayload.sub,
      nonce: jwtPayload.nonce,
      iat: jwtPayload.iat,
      exp: jwtPayload.exp,
      iss: jwtPayload.iss
    });
    
    // Check if JWT is expired
    const now = Math.floor(Date.now() / 1000);
    if (jwtPayload.exp < now) {
      logger.error('JWT is expired!', {
        exp: jwtPayload.exp,
        now: now,
        diff: now - jwtPayload.exp
      });
      return res.json({
        success: false,
        error: 'JWT is expired'
      });
    }
    
    // Recreate ephemeral key pair
    const privateKeyBytes = Buffer.from(ephemeralKeyPair.privateKey, 'base64');
    const ephemeralKeyPairObj = EphemeralKeyPair.fromBytes(privateKeyBytes);
    
    logger.info('Ephemeral key pair:', {
      nonce: ephemeralKeyPairObj.nonce,
      publicKeyHex: ephemeralKeyPairObj.getPublicKey().toString()
    });
    
    // Check nonce match
    if (jwtPayload.nonce !== ephemeralKeyPairObj.nonce) {
      logger.error('Nonce mismatch!', {
        jwtNonce: jwtPayload.nonce,
        ephemeralNonce: ephemeralKeyPairObj.nonce
      });
    }
    
    // Decode pepper
    const pepperBytes = Buffer.from(pepper, 'base64');
    logger.info('Pepper length:', pepperBytes.length);
    
    // Derive keyless account
    logger.info('Deriving keyless account...');
    const keylessAccount = await aptos.deriveKeylessAccount({
      jwt,
      ephemeralKeyPair: ephemeralKeyPairObj,
      pepper: pepperBytes
    });
    
    logger.info('Keyless account derived:', {
      address: keylessAccount.accountAddress.toString()
    });
    
    // Wait for proof
    logger.info('Waiting for proof...');
    await keylessAccount.waitForProofFetch();
    
    logger.info('Proof fetched successfully');
    
    // Check account on-chain
    try {
      const account = await aptos.account.getAccountInfo({
        accountAddress: keylessAccount.accountAddress
      });
      logger.info('Account exists on-chain:', {
        sequenceNumber: account.sequence_number,
        authKey: account.authentication_key
      });
    } catch (e) {
      logger.error('Account does not exist on-chain');
      return res.json({
        success: false,
        error: 'Account does not exist on-chain. Please fund it first.',
        address: keylessAccount.accountAddress.toString()
      });
    }
    
    // Try to create and sign a simple transaction
    logger.info('Building test transaction...');
    const transaction = await aptos.transaction.build.simple({
      sender: keylessAccount.accountAddress,
      data: {
        function: '0x1::aptos_account::transfer',
        functionArguments: [
          '0x2b4efedbd302b5546cd11730537a8f65c07e0444bb0c7fa73ce59bb78b266d36',
          '1000000' // 0.01 APT
        ]
      }
    });
    
    logger.info('Transaction built, signing...');
    const authenticator = aptos.transaction.sign({
      signer: keylessAccount,
      transaction
    });
    
    logger.info('Transaction signed, authenticator type:', authenticator.constructor.name);
    
    // Try to submit
    logger.info('Submitting transaction...');
    try {
      const pendingTxn = await aptos.transaction.submit.simple({
        transaction,
        senderAuthenticator: authenticator
      });
      
      logger.info('Transaction submitted:', pendingTxn.hash);
      
      return res.json({
        success: true,
        transactionHash: pendingTxn.hash,
        debug: {
          address: keylessAccount.accountAddress.toString(),
          jwtNonce: jwtPayload.nonce,
          ephemeralNonce: ephemeralKeyPairObj.nonce,
          nonceMatch: jwtPayload.nonce === ephemeralKeyPairObj.nonce
        }
      });
    } catch (submitError: any) {
      logger.error('Transaction submission failed:', submitError.message);
      return res.json({
        success: false,
        error: submitError.message,
        debug: {
          address: keylessAccount.accountAddress.toString(),
          jwtNonce: jwtPayload.nonce,
          ephemeralNonce: ephemeralKeyPairObj.nonce,
          nonceMatch: jwtPayload.nonce === ephemeralKeyPairObj.nonce
        }
      });
    }
    
  } catch (error) {
    logger.error('Error in debug-keyless:', error);
    return res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : String(error)
    });
  }
});

export default router;