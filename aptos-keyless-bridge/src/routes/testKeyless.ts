import { Router } from 'express';
import { Aptos, AptosConfig, Network } from '@aptos-labs/ts-sdk';
import loggerModule from '../logger';

const router = Router();
const logger = loggerModule;

// Initialize Aptos client
const network = process.env.APTOS_NETWORK === 'mainnet' ? Network.MAINNET : Network.TESTNET;
const noditApiKey = process.env.NODIT_API_KEY;

// Configure to use Nodit endpoints if available
const isMainnet = network === Network.MAINNET;
const noditEndpoint = isMainnet 
  ? 'https://aptos-mainnet.nodit.io/v1'
  : 'https://aptos-testnet.nodit.io/v1';

const config = new AptosConfig({ 
  network,
  fullnode: noditApiKey ? noditEndpoint : undefined,
  clientConfig: noditApiKey ? {
    HEADERS: {
      'X-API-KEY': noditApiKey
    }
  } : undefined
});

const aptos = new Aptos(config);

/**
 * Test endpoint for submitting regular keyless transactions
 * POST /api/keyless/test-regular-submit
 */
router.post('/test-regular-submit', async (req, res) => {
  try {
    const { rawTransaction, senderAuthenticator } = req.body;
    
    if (!rawTransaction || !senderAuthenticator) {
      return res.status(400).json({
        success: false,
        error: 'Missing rawTransaction or senderAuthenticator'
      });
    }
    
    logger.info('Test regular submit endpoint called');
    logger.info('Raw transaction length:', rawTransaction.length);
    logger.info('Sender authenticator length:', senderAuthenticator.length);
    
    // Import necessary classes
    const { Deserializer, AccountAuthenticator, RawTransaction, SimpleTransaction } = require('@aptos-labs/ts-sdk');
    
    try {
      // Decode from base64
      const rawTxBytes = Buffer.from(rawTransaction, 'base64');
      const authBytes = Buffer.from(senderAuthenticator, 'base64');
      
      logger.info('Decoded raw transaction bytes:', rawTxBytes.length);
      logger.info('Decoded authenticator bytes:', authBytes.length);
      
      // Deserialize the raw transaction
      const rawTxDeserializer = new Deserializer(rawTxBytes);
      const rawTx = RawTransaction.deserialize(rawTxDeserializer);
      
      // Deserialize the authenticator  
      const authDeserializer = new Deserializer(authBytes);
      const authenticator = AccountAuthenticator.deserialize(authDeserializer);
      
      logger.info('Deserialized transaction and authenticator successfully');
      
      // Create SimpleTransaction object
      const simpleTransaction = new SimpleTransaction(rawTx);
      
      // Submit using SDK
      const pendingTxn = await aptos.transaction.submit.simple({
        transaction: simpleTransaction,
        senderAuthenticator: authenticator
      });
      
      logger.info('Transaction submitted:', pendingTxn.hash);
      
      // Wait for confirmation
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      try {
        const txResponse = await aptos.waitForTransaction({ 
          transactionHash: pendingTxn.hash 
        });
        
        if (txResponse.success) {
          return res.json({
            success: true,
            transactionHash: pendingTxn.hash
          });
        } else {
          return res.json({
            success: false,
            error: `Transaction failed: ${txResponse.vm_status}`
          });
        }
      } catch (e) {
        // Transaction might still be pending
        return res.json({
          success: true,
          transactionHash: pendingTxn.hash  
        });
      }
      
    } catch (deserializeError: any) {
      logger.error('Deserialization error:', deserializeError);
      
      // If SDK approach fails, try manual submission as fallback
      const rawTxBytes = Buffer.from(rawTransaction, 'base64');
      const authBytes = Buffer.from(senderAuthenticator, 'base64');
      
      // For keyless accounts, the authenticator already includes the variant tag
      // Try submitting without adding another variant tag
      const signedTxBytes = new Uint8Array(rawTxBytes.length + authBytes.length);
      signedTxBytes.set(rawTxBytes, 0);
      signedTxBytes.set(authBytes, rawTxBytes.length);
      
      logger.info('Fallback: Trying manual submission without variant tag');
      
      const submitUrl = `${noditEndpoint}/transactions`;
      const headers: any = {
        'Content-Type': 'application/x.aptos.signed_transaction+bcs'
      };
      
      if (noditApiKey) {
        headers['X-API-KEY'] = noditApiKey;
      }
      
      const response = await fetch(submitUrl, {
        method: 'POST',
        headers,
        body: signedTxBytes
      });
    
      if (response.ok || response.status === 202) {
        const result: any = await response.json();
        logger.info('Fallback submission successful:', result.hash);
        
        return res.json({
          success: true,
          transactionHash: result.hash
        });
      } else {
        const error = await response.text();
        logger.error('All submission attempts failed:', error);
        
        return res.json({
          success: false,
          error: `Submission failed: ${error}`
        });
      }
    }
    
  } catch (error) {
    logger.error('Error in test-regular-submit:', error);
    return res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : String(error)
    });
  }
});

export default router;