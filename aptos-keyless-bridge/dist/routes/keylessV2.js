"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const keylessServiceV2_1 = require("../services/keylessServiceV2");
const logger_1 = __importDefault(require("../logger"));
const router = (0, express_1.Router)();
// Store pending transactions temporarily (in production, use Redis or similar)
const pendingTransactions = new Map();
/**
 * Submit a sponsored transaction using SDK pattern
 */
router.post('/submit-sponsored', async (req, res) => {
    try {
        const { senderAddress, recipientAddress, amount, tokenType, senderAuthenticator } = req.body;
        // Validate required fields
        if (!senderAddress || !recipientAddress || !amount || !tokenType || !senderAuthenticator) {
            return res.status(400).json({
                success: false,
                error: 'Missing required fields'
            });
        }
        logger_1.default.info('Processing sponsored transaction request');
        logger_1.default.info('Sender:', senderAddress);
        logger_1.default.info('Recipient:', recipientAddress);
        logger_1.default.info('Amount:', amount);
        logger_1.default.info('Token:', tokenType);
        const result = await keylessServiceV2_1.keylessServiceV2.submitSponsoredTransaction({
            senderAddress,
            recipientAddress,
            amount,
            tokenType,
            senderAuthenticator
        });
        if (result.success) {
            logger_1.default.info('Sponsored transaction successful:', result.transactionHash);
            return res.json({
                success: true,
                transactionHash: result.transactionHash
            });
        }
        else {
            logger_1.default.error('Sponsored transaction failed:', result.error);
            return res.status(400).json({
                success: false,
                error: result.error
            });
        }
    }
    catch (error) {
        logger_1.default.error('Error in submit-sponsored endpoint:', error);
        return res.status(500).json({
            success: false,
            error: error instanceof Error ? error.message : 'Internal server error'
        });
    }
});
/**
 * Build a sponsored transaction (returns transaction and sponsor signature)
 */
router.post('/build-sponsored', async (req, res) => {
    try {
        const { senderAddress, recipientAddress, amount, tokenType } = req.body;
        // Validate required fields
        if (!senderAddress || !recipientAddress || !amount || !tokenType) {
            return res.status(400).json({
                success: false,
                error: 'Missing required fields'
            });
        }
        logger_1.default.info('Building sponsored transaction');
        logger_1.default.info('Sender:', senderAddress);
        logger_1.default.info('Recipient:', recipientAddress);
        logger_1.default.info('Amount:', amount);
        logger_1.default.info('Token:', tokenType);
        const result = await keylessServiceV2_1.keylessServiceV2.buildSponsoredTransaction({
            senderAddress,
            recipientAddress,
            amount,
            tokenType,
            senderAuthenticator: '' // Not needed for building
        });
        if (result.success) {
            logger_1.default.info('Sponsored transaction built successfully');
            return res.json(result);
        }
        else {
            logger_1.default.error('Failed to build sponsored transaction:', result.error);
            return res.status(400).json({
                success: false,
                error: result.error
            });
        }
    }
    catch (error) {
        logger_1.default.error('Error in build-sponsored endpoint:', error);
        return res.status(500).json({
            success: false,
            error: error instanceof Error ? error.message : 'Internal server error'
        });
    }
});
/**
 * Prepare a sponsored CONFIO transfer
 */
router.post('/prepare-sponsored-confio-transfer', async (req, res) => {
    try {
        const { senderAddress, recipientAddress, amount } = req.body;
        if (!senderAddress || !recipientAddress || amount === undefined) {
            return res.status(400).json({
                success: false,
                error: 'Missing required fields: senderAddress, recipientAddress, amount'
            });
        }
        logger_1.default.info('Preparing sponsored CONFIO transfer');
        // Build the transaction using the V2 service
        const result = await keylessServiceV2_1.keylessServiceV2.buildSponsoredTransaction({
            senderAddress,
            recipientAddress,
            amount,
            tokenType: 'CONFIO',
            senderAuthenticator: ''
        });
        if (result.success) {
            // Store transaction for later submission
            const transactionId = result.transactionId || Date.now().toString();
            // Store the transaction ID for later retrieval
            // The actual transaction and sponsor authenticator are stored in keylessServiceV2
            pendingTransactions.set(transactionId, {
                transactionId: result.transactionId, // Store the ID for reference
                senderAddress,
                recipientAddress,
                amount,
                tokenType: 'CONFIO',
                rawTransaction: result.rawTransaction || result.signingMessage,
                timestamp: Date.now()
            });
            // Clean up old transactions (older than 5 minutes)
            const fiveMinutesAgo = Date.now() - 5 * 60 * 1000;
            for (const [id, data] of pendingTransactions.entries()) {
                if (data.timestamp < fiveMinutesAgo) {
                    pendingTransactions.delete(id);
                }
            }
            return res.json({
                success: true,
                transactionId,
                rawTransaction: result.rawTransaction || result.signingMessage,
                rawBcs: result.rawBcs, // A/B Test: Include raw BCS bytes
                feePayerAddress: result.sponsorAddress
            });
        }
        else {
            return res.status(400).json({
                success: false,
                error: result.error
            });
        }
    }
    catch (error) {
        logger_1.default.error('Error preparing sponsored CONFIO transfer:', error);
        return res.status(500).json({
            success: false,
            error: error instanceof Error ? error.message : 'Internal server error'
        });
    }
});
/**
 * Prepare a sponsored CUSD transfer
 */
router.post('/prepare-sponsored-cusd-transfer', async (req, res) => {
    try {
        const { senderAddress, recipientAddress, amount } = req.body;
        if (!senderAddress || !recipientAddress || amount === undefined) {
            return res.status(400).json({
                success: false,
                error: 'Missing required fields: senderAddress, recipientAddress, amount'
            });
        }
        logger_1.default.info('Preparing sponsored CUSD transfer');
        // Build the transaction using the V2 service
        const result = await keylessServiceV2_1.keylessServiceV2.buildSponsoredTransaction({
            senderAddress,
            recipientAddress,
            amount,
            tokenType: 'CUSD',
            senderAuthenticator: ''
        });
        if (result.success) {
            // Store transaction for later submission
            const transactionId = result.transactionId || Date.now().toString();
            pendingTransactions.set(transactionId, {
                ...result,
                senderAddress,
                recipientAddress,
                amount,
                tokenType: 'CUSD',
                timestamp: Date.now()
            });
            // Clean up old transactions
            const fiveMinutesAgo = Date.now() - 5 * 60 * 1000;
            for (const [id, data] of pendingTransactions.entries()) {
                if (data.timestamp < fiveMinutesAgo) {
                    pendingTransactions.delete(id);
                }
            }
            return res.json({
                success: true,
                transactionId,
                rawTransaction: result.rawTransaction || result.signingMessage,
                rawBcs: result.rawBcs, // A/B Test: Include raw BCS bytes
                feePayerAddress: result.sponsorAddress
            });
        }
        else {
            return res.status(400).json({
                success: false,
                error: result.error
            });
        }
    }
    catch (error) {
        logger_1.default.error('Error preparing sponsored CUSD transfer:', error);
        return res.status(500).json({
            success: false,
            error: error instanceof Error ? error.message : 'Internal server error'
        });
    }
});
/**
 * Submit a sponsored transfer (V2)
 */
router.post('/submit-sponsored-confio-transfer', async (req, res) => {
    try {
        const { transactionId, senderAuthenticator, senderAuthenticatorBcs, jwt, ephemeralKeyPair } = req.body;
        // Check if we have either an authenticator OR ephemeral key pair data for direct signing
        if (!transactionId) {
            return res.status(400).json({
                success: false,
                error: 'Missing required field: transactionId'
            });
        }
        // If we don't have an authenticator, check if we have ephemeral key pair data for direct signing
        if (!senderAuthenticator && (!jwt || !ephemeralKeyPair)) {
            return res.status(400).json({
                success: false,
                error: 'Missing required fields: either senderAuthenticator OR (jwt and ephemeralKeyPair)'
            });
        }
        // Retrieve the pending transaction
        const pendingTx = pendingTransactions.get(transactionId);
        if (!pendingTx) {
            return res.status(404).json({
                success: false,
                error: 'Transaction not found or expired'
            });
        }
        logger_1.default.info('Submitting sponsored transaction:', transactionId);
        logger_1.default.info('Using cached transaction from prepare phase');
        // Check if we need to use direct keyless signing on the bridge
        if (jwt && ephemeralKeyPair && !senderAuthenticator) {
            logger_1.default.info('EXPERIMENTAL: Using direct keyless signing on bridge');
            logger_1.default.info('Ephemeral key pair provided:', {
                hasPrivateKey: !!ephemeralKeyPair.privateKey,
                hasPublicKey: !!ephemeralKeyPair.publicKey,
                hasNonce: !!ephemeralKeyPair.nonce,
                hasBlinder: !!ephemeralKeyPair.blinder,
                expiryDateSecs: ephemeralKeyPair.expiryDateSecs
            });
            // Use the new method that handles direct keyless signing
            const result = await keylessServiceV2_1.keylessServiceV2.submitSponsoredTransaction({
                senderAddress: pendingTx.senderAddress,
                recipientAddress: pendingTx.recipientAddress,
                amount: pendingTx.amount,
                tokenType: pendingTx.tokenType || 'CONFIO',
                senderAuthenticator: '', // Empty since we'll sign on the bridge
                jwt,
                ephemeralKeyPair
            });
            if (result.success) {
                pendingTransactions.delete(transactionId);
                return res.json({
                    success: true,
                    transactionHash: result.transactionHash
                });
            }
            else {
                return res.status(400).json({
                    success: false,
                    error: result.error
                });
            }
        }
        // Otherwise use the cached transaction with pre-generated authenticator
        logger_1.default.info('Using submitCachedTransaction with specific transactionId');
        logger_1.default.info('A/B Test: Has BCS authenticator:', !!senderAuthenticatorBcs);
        const result = await keylessServiceV2_1.keylessServiceV2.submitCachedTransaction(transactionId, senderAuthenticator, senderAuthenticatorBcs // A/B Test: Pass BCS authenticator if available
        );
        if (result.success) {
            // Clean up the pending transaction
            pendingTransactions.delete(transactionId);
            return res.json({
                success: true,
                transactionHash: result.transactionHash
            });
        }
        else {
            return res.status(400).json({
                success: false,
                error: 'Failed to submit transaction'
            });
        }
    }
    catch (error) {
        logger_1.default.error('Error submitting sponsored transfer:', error);
        return res.status(500).json({
            success: false,
            error: error instanceof Error ? error.message : 'Internal server error'
        });
    }
});
exports.default = router;
//# sourceMappingURL=keylessV2.js.map