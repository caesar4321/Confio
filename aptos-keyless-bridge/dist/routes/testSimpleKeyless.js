"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const ts_sdk_1 = require("@aptos-labs/ts-sdk");
const logger_1 = __importDefault(require("../logger"));
const router = (0, express_1.Router)();
const logger = logger_1.default;
// Initialize Aptos client
const network = process.env.APTOS_NETWORK === 'mainnet' ? ts_sdk_1.Network.MAINNET : ts_sdk_1.Network.TESTNET;
const noditApiKey = process.env.NODIT_API_KEY;
// Configure to use Nodit endpoints if available
const isMainnet = network === ts_sdk_1.Network.MAINNET;
const noditEndpoint = isMainnet
    ? 'https://aptos-mainnet.nodit.io/v1'
    : 'https://aptos-testnet.nodit.io/v1';
const config = new ts_sdk_1.AptosConfig({
    network,
    fullnode: noditApiKey ? noditEndpoint : undefined,
    clientConfig: noditApiKey ? {
        HEADERS: {
            'X-API-KEY': noditApiKey
        }
    } : undefined
});
const aptos = new ts_sdk_1.Aptos(config);
/**
 * Simple test endpoint - creates a test account and tries to transfer
 * This tests if the basic SDK setup is working
 * POST /api/keyless/test-simple-transfer
 */
router.post('/test-simple-transfer', async (req, res) => {
    try {
        const { recipientAddress, amount } = req.body;
        if (!recipientAddress || !amount) {
            return res.status(400).json({
                success: false,
                error: 'Missing recipientAddress or amount'
            });
        }
        logger.info('Test simple transfer endpoint called');
        logger.info('Recipient:', recipientAddress);
        logger.info('Amount:', amount);
        // Create a test account using sponsor's private key
        const sponsorPrivateKey = process.env.APTOS_SPONSOR_PRIVATE_KEY;
        if (!sponsorPrivateKey) {
            return res.json({
                success: false,
                error: 'Sponsor private key not configured'
            });
        }
        // Create account from private key
        const privateKeyHex = sponsorPrivateKey.startsWith('0x')
            ? sponsorPrivateKey.slice(2)
            : sponsorPrivateKey;
        const privateKey = new ts_sdk_1.Ed25519PrivateKey(privateKeyHex);
        const sponsorAccount = ts_sdk_1.Account.fromPrivateKey({ privateKey });
        logger.info('Using sponsor account:', sponsorAccount.accountAddress.toString());
        // Build transaction
        const amountUnits = Math.floor(parseFloat(amount) * 1e8); // 8 decimals for APT
        const transaction = await aptos.transaction.build.simple({
            sender: sponsorAccount.accountAddress,
            data: {
                function: '0x1::aptos_account::transfer',
                functionArguments: [recipientAddress, amountUnits.toString()]
            }
        });
        logger.info('Transaction built successfully');
        // Sign transaction
        const signature = aptos.transaction.sign({
            signer: sponsorAccount,
            transaction
        });
        logger.info('Transaction signed');
        // Submit transaction
        const pendingTxn = await aptos.transaction.submit.simple({
            transaction,
            senderAuthenticator: signature
        });
        logger.info('Transaction submitted:', pendingTxn.hash);
        // Wait for confirmation
        try {
            const txResponse = await aptos.waitForTransaction({
                transactionHash: pendingTxn.hash
            });
            if (txResponse.success) {
                return res.json({
                    success: true,
                    transactionHash: pendingTxn.hash,
                    message: 'Simple transfer successful - SDK is working correctly'
                });
            }
            else {
                return res.json({
                    success: false,
                    error: `Transaction failed: ${txResponse.vm_status}`
                });
            }
        }
        catch (e) {
            // Transaction might still be pending
            return res.json({
                success: true,
                transactionHash: pendingTxn.hash,
                message: 'Transaction submitted, might still be pending'
            });
        }
    }
    catch (error) {
        logger.error('Error in test-simple-transfer:', error);
        return res.status(500).json({
            success: false,
            error: error instanceof Error ? error.message : String(error)
        });
    }
});
exports.default = router;
//# sourceMappingURL=testSimpleKeyless.js.map