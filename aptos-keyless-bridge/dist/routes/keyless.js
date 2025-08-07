"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const keylessService_1 = require("../services/keylessService");
const logger_1 = __importDefault(require("../logger"));
const router = (0, express_1.Router)();
const keylessService = new keylessService_1.KeylessService();
/**
 * Generate a new ephemeral key pair
 */
router.post('/ephemeral-key', async (req, res) => {
    try {
        const { expiryHours = 24 } = req.body;
        const ephemeralKeyPair = await keylessService.generateEphemeralKeyPair(expiryHours);
        res.json({
            success: true,
            data: ephemeralKeyPair,
        });
    }
    catch (error) {
        logger_1.default.error('Error in /ephemeral-key:', error);
        const errorResponse = {
            error: 'EPHEMERAL_KEY_ERROR',
            message: error instanceof Error ? error.message : 'Failed to generate ephemeral key',
        };
        res.status(500).json(errorResponse);
    }
});
/**
 * Generate OAuth URL with nonce
 */
router.post('/oauth-url', async (req, res) => {
    try {
        const { provider, clientId, redirectUri, ephemeralPublicKey, expiryDate, blinder } = req.body;
        if (!provider || !clientId || !redirectUri || !ephemeralPublicKey || !expiryDate) {
            res.status(400).json({
                error: 'MISSING_PARAMETERS',
                message: 'Missing required parameters',
            });
            return;
        }
        const oauthUrl = await keylessService.generateOAuthUrl(provider, clientId, redirectUri, {
            privateKey: '', // Not needed for URL generation
            publicKey: ephemeralPublicKey,
            expiryDate,
            blinder,
        });
        res.json({
            success: true,
            data: {
                url: oauthUrl,
            },
        });
    }
    catch (error) {
        logger_1.default.error('Error in /oauth-url:', error);
        const errorResponse = {
            error: 'OAUTH_URL_ERROR',
            message: error instanceof Error ? error.message : 'Failed to generate OAuth URL',
        };
        res.status(500).json(errorResponse);
    }
});
/**
 * Derive Keyless account from JWT
 */
router.post('/derive-account', async (req, res) => {
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
    }
    catch (error) {
        logger_1.default.error('Error in /derive-account:', error);
        const errorResponse = {
            error: 'DERIVE_ACCOUNT_ERROR',
            message: error instanceof Error ? error.message : 'Failed to derive account',
        };
        res.status(500).json(errorResponse);
    }
});
/**
 * Generate authenticator for a transaction (for sponsored transactions)
 */
router.post('/generate-authenticator', async (req, res) => {
    try {
        const { jwt, ephemeralKeyPair, signingMessage, pepper } = req.body;
        if (!jwt || !ephemeralKeyPair || !signingMessage) {
            res.status(400).json({
                error: 'MISSING_PARAMETERS',
                message: 'Missing required parameters',
            });
            return;
        }
        const result = await keylessService.generateAuthenticator(jwt, ephemeralKeyPair, signingMessage, pepper);
        res.json({
            success: true,
            data: result,
        });
    }
    catch (error) {
        logger_1.default.error('Error in /generate-authenticator:', error);
        const errorResponse = {
            error: 'AUTHENTICATOR_ERROR',
            message: error instanceof Error ? error.message : 'Failed to generate authenticator',
        };
        res.status(500).json(errorResponse);
    }
});
/**
 * Sign and submit transaction
 */
router.post('/sign-and-submit', async (req, res) => {
    try {
        const { jwt, ephemeralKeyPair, transaction, pepper } = req.body;
        if (!jwt || !ephemeralKeyPair || !transaction) {
            res.status(400).json({
                error: 'MISSING_PARAMETERS',
                message: 'Missing required parameters',
            });
            return;
        }
        const result = await keylessService.signAndSubmitTransaction(jwt, ephemeralKeyPair, transaction, pepper);
        res.json({
            success: true,
            data: result,
        });
    }
    catch (error) {
        logger_1.default.error('Error in /sign-and-submit:', error);
        const errorResponse = {
            error: 'TRANSACTION_ERROR',
            message: error instanceof Error ? error.message : 'Failed to sign and submit transaction',
        };
        res.status(500).json(errorResponse);
    }
});
/**
 * Get account balance
 */
router.get('/balance/:address', async (req, res) => {
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
    }
    catch (error) {
        logger_1.default.error('Error in /balance:', error);
        const errorResponse = {
            error: 'BALANCE_ERROR',
            message: error instanceof Error ? error.message : 'Failed to get balance',
        };
        res.status(500).json(errorResponse);
    }
});
/**
 * Health check endpoint
 */
router.get('/health', (_req, res) => {
    res.json({
        success: true,
        message: 'Aptos Keyless Bridge is running',
        version: '1.0.0',
        network: process.env.APTOS_NETWORK || 'devnet',
    });
});
/**
 * Submit fee-payer transaction with keyless authenticator
 */
router.post('/fee-payer-submit', async (req, res) => {
    try {
        const { rawTxnBcsBase64, senderAuthenticatorBcsBase64, sponsorAddressHex, policyMetadata } = req.body;
        if (!rawTxnBcsBase64 || !senderAuthenticatorBcsBase64 || !sponsorAddressHex) {
            res.status(400).json({
                error: 'MISSING_PARAMETERS',
                message: 'Missing required parameters: rawTxnBcsBase64, senderAuthenticatorBcsBase64, sponsorAddressHex',
            });
            return;
        }
        const result = await keylessService.submitFeePayerTransaction(rawTxnBcsBase64, senderAuthenticatorBcsBase64, sponsorAddressHex, policyMetadata);
        res.json({
            success: true,
            data: result,
        });
    }
    catch (error) {
        logger_1.default.error('Error in /fee-payer-submit:', error);
        const errorResponse = {
            error: 'FEE_PAYER_SUBMIT_ERROR',
            message: error instanceof Error ? error.message : 'Failed to submit fee-payer transaction',
        };
        res.status(500).json(errorResponse);
    }
});
exports.default = router;
//# sourceMappingURL=keyless.js.map