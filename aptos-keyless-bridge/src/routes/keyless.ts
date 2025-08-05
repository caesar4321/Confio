import { Router, Request, Response } from 'express';
import { KeylessService } from '../services/keylessService';
import {
  GenerateEphemeralKeyRequest,
  DeriveAccountRequest,
  GetOAuthUrlRequest,
  SignAndSubmitRequest,
  ErrorResponse,
} from '../types';
import logger from '../logger';

const router = Router();
const keylessService = new KeylessService();

/**
 * Generate a new ephemeral key pair
 */
router.post('/ephemeral-key', async (req: Request<{}, {}, GenerateEphemeralKeyRequest>, res: Response) => {
  try {
    const { expiryHours = 24 } = req.body;
    const ephemeralKeyPair = await keylessService.generateEphemeralKeyPair(expiryHours);
    
    res.json({
      success: true,
      data: ephemeralKeyPair,
    });
  } catch (error) {
    logger.error('Error in /ephemeral-key:', error);
    const errorResponse: ErrorResponse = {
      error: 'EPHEMERAL_KEY_ERROR',
      message: error instanceof Error ? error.message : 'Failed to generate ephemeral key',
    };
    res.status(500).json(errorResponse);
  }
});

/**
 * Generate OAuth URL with nonce
 */
router.post('/oauth-url', async (req: Request<{}, {}, GetOAuthUrlRequest>, res: Response) => {
  try {
    const { provider, clientId, redirectUri, ephemeralPublicKey, expiryDate, blinder } = req.body;
    
    if (!provider || !clientId || !redirectUri || !ephemeralPublicKey || !expiryDate) {
      res.status(400).json({
        error: 'MISSING_PARAMETERS',
        message: 'Missing required parameters',
      });
      return;
    }

    const oauthUrl = await keylessService.generateOAuthUrl(
      provider,
      clientId,
      redirectUri,
      {
        privateKey: '', // Not needed for URL generation
        publicKey: ephemeralPublicKey,
        expiryDate,
        blinder,
      }
    );

    res.json({
      success: true,
      data: {
        url: oauthUrl,
      },
    });
  } catch (error) {
    logger.error('Error in /oauth-url:', error);
    const errorResponse: ErrorResponse = {
      error: 'OAUTH_URL_ERROR',
      message: error instanceof Error ? error.message : 'Failed to generate OAuth URL',
    };
    res.status(500).json(errorResponse);
  }
});

/**
 * Derive Keyless account from JWT
 */
router.post('/derive-account', async (req: Request<{}, {}, DeriveAccountRequest>, res: Response) => {
  try {
    const { jwt, ephemeralKeyPair, pepper } = req.body;
    
    if (!jwt || !ephemeralKeyPair) {
      res.status(400).json({
        error: 'MISSING_PARAMETERS',
        message: 'Missing required parameters: jwt and ephemeralKeyPair',
      });
      return;
    }

    const account = await keylessService.deriveKeylessAccount({
      jwt,
      ephemeralKeyPair,
      pepper,
    });

    res.json({
      success: true,
      data: account,
    });
  } catch (error) {
    logger.error('Error in /derive-account:', error);
    const errorResponse: ErrorResponse = {
      error: 'DERIVE_ACCOUNT_ERROR',
      message: error instanceof Error ? error.message : 'Failed to derive account',
    };
    res.status(500).json(errorResponse);
  }
});

/**
 * Sign and submit transaction
 */
router.post('/sign-and-submit', async (req: Request<{}, {}, SignAndSubmitRequest>, res: Response) => {
  try {
    const { jwt, ephemeralKeyPair, transaction, pepper } = req.body;
    
    if (!jwt || !ephemeralKeyPair || !transaction) {
      res.status(400).json({
        error: 'MISSING_PARAMETERS',
        message: 'Missing required parameters',
      });
      return;
    }

    const result = await keylessService.signAndSubmitTransaction(
      jwt,
      ephemeralKeyPair,
      transaction,
      pepper
    );

    res.json({
      success: true,
      data: result,
    });
  } catch (error) {
    logger.error('Error in /sign-and-submit:', error);
    const errorResponse: ErrorResponse = {
      error: 'TRANSACTION_ERROR',
      message: error instanceof Error ? error.message : 'Failed to sign and submit transaction',
    };
    res.status(500).json(errorResponse);
  }
});

/**
 * Get account balance
 */
router.get('/balance/:address', async (req: Request<{ address: string }>, res: Response) => {
  try {
    const { address } = req.params;
    
    if (!address) {
      res.status(400).json({
        error: 'MISSING_ADDRESS',
        message: 'Address parameter is required',
      });
      return;
    }

    const balance = await keylessService.getAccountBalance(address);

    res.json({
      success: true,
      data: balance,
    });
  } catch (error) {
    logger.error('Error in /balance:', error);
    const errorResponse: ErrorResponse = {
      error: 'BALANCE_ERROR',
      message: error instanceof Error ? error.message : 'Failed to get balance',
    };
    res.status(500).json(errorResponse);
  }
});

/**
 * Health check endpoint
 */
router.get('/health', (_req: Request, res: Response) => {
  res.json({
    success: true,
    message: 'Aptos Keyless Bridge is running',
    version: '1.0.0',
    network: process.env.APTOS_NETWORK || 'devnet',
  });
});

export default router;