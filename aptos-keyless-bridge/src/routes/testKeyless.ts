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
    
    // Decode from base64
    const rawTxBytes = Buffer.from(rawTransaction, 'base64');
    const authBytes = Buffer.from(senderAuthenticator, 'base64');
    
    logger.info('Decoded raw transaction bytes:', rawTxBytes.length);
    logger.info('Decoded authenticator bytes:', authBytes.length);
    
    // We don't need to deserialize these for manual submission
    // Just use the raw bytes directly
    
    
    // Create the signed transaction bytes manually
    // SignedTransaction for UserTransaction variant (tag = 0)
    const signedTxBytes = new Uint8Array(1 + rawTxBytes.length + authBytes.length);
    signedTxBytes[0] = 0; // UserTransaction variant
    signedTxBytes.set(rawTxBytes, 1);
    signedTxBytes.set(authBytes, 1 + rawTxBytes.length);
    
    logger.info('Constructed signed transaction bytes:', signedTxBytes.length);
    
    // Submit using fetch directly to the Aptos node
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
      logger.info('Transaction submitted successfully:', result.hash);
      
      // Wait a bit for confirmation
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      // Check transaction status
      try {
        const txResponse = await aptos.getTransactionByHash({ transactionHash: result.hash });
        
        // Check if it's a successful transaction
        if ('success' in txResponse && txResponse.success) {
          return res.json({
            success: true,
            transactionHash: result.hash
          });
        } else if ('vm_status' in txResponse) {
          return res.json({
            success: false,
            error: `Transaction failed: ${(txResponse as any).vm_status}`
          });
        } else {
          // Pending or unknown status
          return res.json({
            success: true,
            transactionHash: result.hash
          });
        }
      } catch (e) {
        // Transaction might still be pending, return success
        return res.json({
          success: true,
          transactionHash: result.hash
        });
      }
    } else {
      const error = await response.text();
      logger.error('Transaction submission failed:', error);
      
      return res.json({
        success: false,
        error: `Submission failed: ${error}`
      });
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