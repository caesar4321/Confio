"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.KeylessService = void 0;
const ts_sdk_1 = require("@aptos-labs/ts-sdk");
const jose = __importStar(require("jose"));
const crypto_1 = __importDefault(require("crypto"));
const config_1 = require("../config");
const logger_1 = __importDefault(require("../logger"));
const ephemeralKeyStore_1 = require("./ephemeralKeyStore");
class KeylessService {
    aptos;
    sponsorAccount;
    constructor() {
        const aptosConfig = new ts_sdk_1.AptosConfig({ network: config_1.config.aptos.network });
        this.aptos = new ts_sdk_1.Aptos(aptosConfig);
        // Initialize sponsor account from environment
        const sponsorPrivateKey = process.env.APTOS_SPONSOR_PRIVATE_KEY;
        if (!sponsorPrivateKey) {
            throw new Error('APTOS_SPONSOR_PRIVATE_KEY environment variable not set');
        }
        // Handle hex-encoded private key (remove 0x prefix if present)
        const hexKey = sponsorPrivateKey.replace(/^0x/, '');
        const privateKeyBytes = Buffer.from(hexKey, 'hex');
        // Create Ed25519 private key from bytes
        const sponsorPrivateKeyEd25519 = new ts_sdk_1.Ed25519PrivateKey(privateKeyBytes);
        this.sponsorAccount = ts_sdk_1.Account.fromPrivateKey({ privateKey: sponsorPrivateKeyEd25519 });
        logger_1.default.info('Sponsor account initialized:', this.sponsorAccount.accountAddress.toString());
    }
    /**
     * Generate a new ephemeral key pair
     */
    async generateEphemeralKeyPair(expiryHours = 24) {
        try {
            const ephemeralKeyPair = ts_sdk_1.EphemeralKeyPair.generate();
            const expiryDate = new Date();
            expiryDate.setHours(expiryDate.getHours() + expiryHours);
            // Generate a unique ID for this key pair
            const keyId = crypto_1.default.randomBytes(16).toString('hex');
            // Store the actual key pair object
            ephemeralKeyStore_1.ephemeralKeyStore.store(keyId, ephemeralKeyPair);
            const nonce = ephemeralKeyPair.nonce;
            const blinder = ephemeralKeyPair.blinder.toString();
            return {
                keyId, // Include the ID so we can retrieve the key pair later
                privateKey: ephemeralKeyPair.privateKey.toString(),
                publicKey: ephemeralKeyPair.publicKey.toString(),
                expiryDate: expiryDate.toISOString(),
                nonce,
                blinder,
            };
        }
        catch (error) {
            logger_1.default.error('Error generating ephemeral key pair:', error);
            throw new Error('Failed to generate ephemeral key pair');
        }
    }
    /**
     * Generate a deterministic ephemeral key pair from a seed
     * This ensures the same seed always produces the same address
     */
    async generateDeterministicEphemeralKeyPair(seed, expiryHours = 24) {
        try {
            // Create a deterministic seed by hashing the input seed
            const hash = crypto_1.default.createHash('sha256').update(seed).digest();
            // Create a private key from the hash (first 32 bytes)
            const privateKey = new ts_sdk_1.Ed25519PrivateKey(hash.slice(0, 32));
            // Generate deterministic nonce from seed
            const nonceHash = crypto_1.default.createHash('sha256').update(`nonce-${seed}`).digest();
            const nonce = nonceHash.toString('hex').substring(0, 32);
            // Create ephemeral key pair with deterministic values
            // Note: This is a workaround since EphemeralKeyPair doesn't have a fromSeed method
            const ephemeralKeyPair = {
                privateKey: privateKey,
                publicKey: privateKey.publicKey(),
                nonce: nonce,
                blinder: BigInt('0x' + crypto_1.default.createHash('sha256').update(`blinder-${seed}`).digest('hex')),
                expiryDate: new Date(Date.now() + expiryHours * 60 * 60 * 1000),
            };
            const expiryDate = new Date();
            expiryDate.setHours(expiryDate.getHours() + expiryHours);
            // Generate a deterministic key ID from the seed
            const keyId = crypto_1.default.createHash('sha256').update(`keyid-${seed}`).digest('hex').substring(0, 32);
            // Store a compatible ephemeral key pair object
            // We'll need to create a proper EphemeralKeyPair instance for storage
            const fullKeyPair = Object.assign(Object.create(ts_sdk_1.EphemeralKeyPair.prototype), ephemeralKeyPair);
            ephemeralKeyStore_1.ephemeralKeyStore.store(keyId, fullKeyPair);
            return {
                keyId,
                privateKey: privateKey.toString(),
                publicKey: ephemeralKeyPair.publicKey.toString(),
                expiryDate: expiryDate.toISOString(),
                nonce,
                blinder: ephemeralKeyPair.blinder.toString(),
            };
        }
        catch (error) {
            logger_1.default.error('Error generating deterministic ephemeral key pair:', error);
            throw error;
        }
    }
    /**
     * Generate OAuth URL with proper nonce
     */
    async generateOAuthUrl(provider, clientId, redirectUri, ephemeralKeyPairData) {
        try {
            const providerConfig = config_1.config.oauth.providers[provider];
            if (!providerConfig) {
                throw new Error(`Unsupported provider: ${provider}`);
            }
            // Reconstruct ephemeral key pair from data
            const ephemeralKeyPair = this.reconstructEphemeralKeyPair(ephemeralKeyPairData);
            // Generate state for CSRF protection
            const state = crypto_1.default.randomBytes(32).toString('hex');
            const params = new URLSearchParams({
                client_id: clientId,
                redirect_uri: redirectUri,
                response_type: 'code',
                scope: providerConfig.scope,
                nonce: ephemeralKeyPair.nonce,
                state,
            });
            // Apple requires additional parameters
            if (provider === 'apple') {
                params.append('response_mode', 'form_post');
            }
            return `${providerConfig.authUrl}?${params.toString()}`;
        }
        catch (error) {
            logger_1.default.error('Error generating OAuth URL:', error);
            throw new Error('Failed to generate OAuth URL');
        }
    }
    /**
     * Derive a Keyless account from JWT and ephemeral key pair
     */
    async deriveKeylessAccount(request) {
        try {
            // Decode JWT to validate
            const decodedJwt = jose.decodeJwt(request.jwt);
            if (!decodedJwt.sub || !decodedJwt.aud || !decodedJwt.iss) {
                throw new Error('Invalid JWT: missing required claims');
            }
            // Try to retrieve the stored key pair first
            let ephemeralKeyPair;
            if ('keyId' in request.ephemeralKeyPair && request.ephemeralKeyPair.keyId) {
                const storedKeyPair = ephemeralKeyStore_1.ephemeralKeyStore.retrieve(request.ephemeralKeyPair.keyId);
                if (storedKeyPair) {
                    ephemeralKeyPair = storedKeyPair;
                    logger_1.default.info('Using stored ephemeral key pair');
                }
                else {
                    logger_1.default.warn('Stored key pair not found, reconstructing from data');
                    ephemeralKeyPair = this.reconstructEphemeralKeyPair(request.ephemeralKeyPair);
                }
            }
            else {
                ephemeralKeyPair = this.reconstructEphemeralKeyPair(request.ephemeralKeyPair);
            }
            const jwtNonce = typeof decodedJwt.nonce === 'string' ? decodedJwt.nonce : String(decodedJwt.nonce);
            logger_1.default.info('JWT nonce:', jwtNonce);
            logger_1.default.info('Ephemeral key nonce:', String(ephemeralKeyPair.nonce));
            logger_1.default.info('Nonces match:', jwtNonce === String(ephemeralKeyPair.nonce));
            // Derive the Keyless account
            const keylessAccount = await this.aptos.deriveKeylessAccount({
                jwt: request.jwt,
                ephemeralKeyPair,
                pepper: request.pepper,
            });
            // Wait for the proof to be fetched
            await keylessAccount.waitForProofFetch();
            // Log the pepper for debugging
            logger_1.default.info('Keyless account derived successfully');
            logger_1.default.info('Address:', keylessAccount.accountAddress.toString());
            // Try to access the pepper from the KeylessAccount instance
            // The pepper might be stored as a property on the keylessAccount object
            const derivedPepper = keylessAccount.pepper || request.pepper;
            if (derivedPepper && !request.pepper) {
                logger_1.default.info('Pepper fetched from pepper service:', derivedPepper);
            }
            return {
                address: keylessAccount.accountAddress.toString(),
                publicKey: keylessAccount.publicKey.toString(),
                jwt: request.jwt,
                ephemeralKeyPair: request.ephemeralKeyPair,
                pepper: derivedPepper,
            };
        }
        catch (error) {
            logger_1.default.error('Error deriving keyless account:', error);
            throw new Error(`Failed to derive keyless account: ${error}`);
        }
    }
    /**
     * Generate authenticator for a transaction without submitting
     * This is used for sponsored transactions where the backend needs the authenticator
     */
    async generateAuthenticator(jwt, ephemeralKeyPairData, signingMessageBase64, pepper) {
        try {
            // Decode JWT to get claims
            const decodedJwt = jose.decodeJwt(jwt);
            // Reconstruct the ephemeral key pair
            const ephemeralKeyPair = this.reconstructEphemeralKeyPair(ephemeralKeyPairData);
            // Derive the keyless account
            const keylessAccount = await this.aptos.deriveKeylessAccount({
                jwt,
                ephemeralKeyPair,
                pepper,
            });
            // Wait for the proof to be fetched
            await keylessAccount.waitForProofFetch();
            // Decode the signing message
            const signingMessageBytes = Buffer.from(signingMessageBase64, 'base64');
            // Sign the message to get the authenticator
            const authenticator = keylessAccount.signWithAuthenticator(signingMessageBytes);
            // Serialize the authenticator to BCS
            const serializer = new ts_sdk_1.Serializer();
            authenticator.serialize(serializer);
            const authenticatorBytes = serializer.toUint8Array();
            const senderAuthenticatorBcsBase64 = Buffer.from(authenticatorBytes).toString('base64');
            // Get the auth key/address
            const authKeyHex = keylessAccount.accountAddress.toString();
            // Get ephemeral public key as hex (64 chars, no 0x)
            // Access the public key from the data structure
            const publicKeyStr = ephemeralKeyPairData.publicKey;
            const ephemeralPublicKeyHex = publicKeyStr.replace(/^0x/, '');
            // Extract JWT header to get kid
            const jwtParts = jwt.split('.');
            const header = JSON.parse(Buffer.from(jwtParts[0], 'base64').toString());
            return {
                senderAuthenticatorBcsBase64,
                authKeyHex,
                ephemeralPublicKeyHex,
                claims: {
                    iss: String(decodedJwt.iss),
                    aud: String(decodedJwt.aud),
                    sub: String(decodedJwt.sub),
                    exp: Number(decodedJwt.exp),
                    iat: Number(decodedJwt.iat),
                },
                kid: header.kid,
            };
        }
        catch (error) {
            logger_1.default.error('Error generating authenticator:', error);
            throw new Error(`Failed to generate authenticator: ${error}`);
        }
    }
    /**
     * Sign and submit a transaction using Keyless account
     */
    async signAndSubmitTransaction(jwt, ephemeralKeyPairData, transaction, pepper) {
        try {
            // Derive the keyless account again (stateless service)
            await this.deriveKeylessAccount({
                jwt,
                ephemeralKeyPair: ephemeralKeyPairData,
                pepper,
            });
            // Reconstruct the account object
            const ephemeralKeyPair = this.reconstructEphemeralKeyPair(ephemeralKeyPairData);
            const account = await this.aptos.deriveKeylessAccount({
                jwt,
                ephemeralKeyPair,
                pepper,
            });
            // Sign and submit the transaction
            const response = await this.aptos.signAndSubmitTransaction({
                signer: account,
                transaction,
            });
            return {
                ...response,
                hash: response.hash,
            };
        }
        catch (error) {
            logger_1.default.error('Error signing and submitting transaction:', error);
            throw new Error(`Failed to sign and submit transaction: ${error}`);
        }
    }
    /**
     * Get account balance for multiple tokens
     */
    async getAccountBalance(address) {
        try {
            const balances = {};
            // Get all resources to see what coin stores exist
            try {
                const resources = await this.aptos.getAccountResources({
                    accountAddress: address,
                });
                logger_1.default.info(`Found ${resources.length} resources for ${address}`);
                // Look for any CoinStore resources
                for (const resource of resources) {
                    if (resource.type.includes('coin::CoinStore')) {
                        logger_1.default.info(`Found CoinStore: ${resource.type}`);
                        const coinData = resource.data;
                        if (coinData.coin && coinData.coin.value) {
                            logger_1.default.info(`Coin value: ${coinData.coin.value}`);
                            // Check if this looks like USDC
                            if (resource.type.includes('69091fbab5f7d635ee7ac5098cf0c1efbe31d68fec0f2cd565e8d168daf52832')) {
                                balances.usdc = coinData.coin.value;
                                logger_1.default.info(`USDC balance found: ${balances.usdc}`);
                            }
                        }
                    }
                }
                // Set defaults if not found
                if (!balances.usdc)
                    balances.usdc = '0';
            }
            catch (e) {
                logger_1.default.error(`Error getting resources for ${address}: ${e}`);
                balances.usdc = '0';
            }
            // cUSD and CONFIO not yet deployed
            balances.cusd = '0';
            balances.confio = '0';
            return balances;
        }
        catch (error) {
            logger_1.default.error('Error getting account balances:', error);
            // Return zeros if account doesn't exist or other errors
            return {
                usdc: '0',
                cusd: '0',
                confio: '0'
            };
        }
    }
    /**
     * Reconstruct EphemeralKeyPair from data
     */
    /**
     * Submit fee-payer transaction with keyless authenticator
     * Updated to use official SDK pattern from aptos-ts-sdk examples
     */
    async submitFeePayerTransaction(rawTxnBcsBase64, senderAuthenticatorBcsBase64, sponsorAddressHex, _policyMetadata) {
        try {
            logger_1.default.info('Processing fee-payer transaction submission using SDK pattern');
            logger_1.default.info('Raw transaction bytes:', rawTxnBcsBase64.length);
            logger_1.default.info('Sender authenticator bytes:', senderAuthenticatorBcsBase64.length);
            logger_1.default.info('Sponsor address:', sponsorAddressHex);
            // Use the expected sponsor address from environment
            const expectedSponsorAddress = process.env.APTOS_SPONSOR_ADDRESS;
            if (expectedSponsorAddress && sponsorAddressHex !== expectedSponsorAddress) {
                throw new Error(`Sponsor address mismatch: expected ${expectedSponsorAddress}, got ${sponsorAddressHex}`);
            }
            // Log the addresses for debugging
            logger_1.default.info('Expected sponsor address:', expectedSponsorAddress);
            logger_1.default.info('Provided sponsor address:', sponsorAddressHex);
            logger_1.default.info('BRIDGE account address:', this.sponsorAccount.accountAddress.toString());
            // Decode BCS data
            const rawTxnBytes = Buffer.from(rawTxnBcsBase64, 'base64');
            const senderAuthBytes = Buffer.from(senderAuthenticatorBcsBase64, 'base64');
            logger_1.default.info('Raw transaction BCS length:', rawTxnBytes.length);
            logger_1.default.info('Sender authenticator BCS length:', senderAuthBytes.length);
            // Check raw transaction format
            logger_1.default.info('Raw txn first byte:', `0x${rawTxnBytes[0].toString(16)}`);
            // Based on ChatGPT's feedback, we need to:
            // 1. Convert MultiAgent (0x01) to FeePayer (0x02) format
            // 2. Convert the AccountAuthenticator to TransactionAuthenticator
            // 3. Use proper SDK types instead of manual byte concatenation
            // For now, let's use the manual approach that was working before
            // but fix the authenticator issue
            // Convert MultiAgent to FeePayer if needed
            let feePayerRawTxnBytes;
            if (rawTxnBytes[0] === 0x01) {
                logger_1.default.info('Converting MultiAgent (0x01) to FeePayer (0x02) format');
                // Extract sponsor address for the raw transaction
                const sponsorAddrForRaw = Buffer.from(sponsorAddressHex.replace(/^0x/, ''), 'hex');
                // Build FeePayer RawTransactionWithData:
                // - tag: 0x02 (FeePayer)
                // - inner raw transaction (everything after the 0x01 tag)
                // - fee payer address (32 bytes)
                feePayerRawTxnBytes = Buffer.concat([
                    Buffer.from([0x02]), // FeePayer tag
                    rawTxnBytes.slice(1), // Skip MultiAgent tag, keep the rest
                    sponsorAddrForRaw // Append fee-payer address
                ]);
                logger_1.default.info('Created FeePayer RawTransactionWithData, length:', feePayerRawTxnBytes.length);
                logger_1.default.info('Expected: 1 (tag) + 198 (inner) + 32 (address) = 231 bytes');
            }
            else if (rawTxnBytes[0] === 0x02) {
                // Already FeePayer format
                feePayerRawTxnBytes = rawTxnBytes;
                logger_1.default.info('Raw transaction already in FeePayer format');
            }
            else {
                throw new Error(`Unexpected raw transaction tag: 0x${rawTxnBytes[0].toString(16)}`);
            }
            // Create domain separator for sponsor signing
            const domainSeparator = 'APTOS::RawTransactionWithData';
            const hasher = crypto_1.default.createHash('sha3-256');
            hasher.update(domainSeparator);
            const domainHash = hasher.digest();
            // Create signing message for sponsor using FeePayer format
            const sponsorSigningMessage = Buffer.concat([domainHash, feePayerRawTxnBytes]);
            logger_1.default.info('Sponsor signing message length:', sponsorSigningMessage.length);
            logger_1.default.info('Expected: 32 (hash) + 231 (feepayer raw) = 263 bytes');
            // Sign with sponsor account
            const sponsorSignature = this.sponsorAccount.sign(sponsorSigningMessage);
            // Create sponsor authenticator (97 bytes: 0x00 + 32-byte pubkey + 64-byte signature)
            const sponsorPubKeyBytes = this.sponsorAccount.publicKey.toUint8Array();
            const sponsorSigBytes = sponsorSignature.toUint8Array();
            const sponsorAuthenticator = new Uint8Array(97);
            sponsorAuthenticator[0] = 0x00; // Ed25519 discriminant
            sponsorAuthenticator.set(sponsorPubKeyBytes, 1);
            sponsorAuthenticator.set(sponsorSigBytes, 33);
            // Tags for TransactionAuthenticator variants
            const TA = {
                ED25519: 0x00,
                MULTI_ED25519: 0x01,
                MULTI_AGENT: 0x02,
                FEE_PAYER: 0x03,
                SINGLE_SENDER: 0x04,
            };
            // Tags for AccountAuthenticator variants
            const AA = {
                ED25519: 0x00,
                MULTI_ED25519: 0x01,
                KEYLESS: 0x02,
            };
            // Ensure the provided sender authenticator is account-level KEYLESS
            if (senderAuthBytes[0] !== AA.KEYLESS) {
                throw new Error(`Expected AccountAuthenticator::Keyless (0x02) for sender, got 0x${senderAuthBytes[0].toString(16)}`);
            }
            // Convert AccountAuthenticator to TransactionAuthenticator
            // The sender sent us an AccountAuthenticator (starts with 0x02 for keyless)
            // We need to wrap it as TransactionAuthenticator::SingleSender (tag 0x04)
            logger_1.default.info('Wrapping sender AccountAuthenticator as TransactionAuthenticator::SingleSender');
            const wrappedSenderAuth = Buffer.concat([
                Buffer.from([TA.SINGLE_SENDER]), // SingleSender tag = 0x04
                senderAuthBytes // The account authenticator
            ]);
            // Build the complete SignedTransaction with FeePayer authenticator
            // Structure per ChatGPT:
            // - Raw transaction (231 bytes for FeePayer format)
            // - TransactionAuthenticator::FeePayer (tag 0x03)
            //   - sender: TransactionAuthenticator (wrapped sender auth)
            //   - secondary_signer_addresses: empty vec
            //   - fee_payer_address: 32 bytes
            //   - fee_payer_signer: AccountAuthenticator (97 bytes)
            //   - secondary_signers: empty vec
            const TAG_FEEPAYER = Buffer.from([TA.FEE_PAYER]); // 0x03
            const VEC_EMPTY = Buffer.from([0x00]); // ULEB128 length 0
            const sponsorAddr = Buffer.from(sponsorAddressHex.replace(/^0x/, ''), 'hex');
            // Build the authenticator
            const signedTxnBytes = Buffer.concat([
                feePayerRawTxnBytes, // 231 bytes (FeePayer RawTransactionWithData)
                TAG_FEEPAYER, // 1 byte (TransactionAuthenticator::FeePayer = 0x03)
                wrappedSenderAuth, // 457 bytes (0x04 + 456-byte keyless account auth)
                VEC_EMPTY, // 1 byte (secondary_signer_addresses)
                sponsorAddr, // 32 bytes (fee_payer_address)
                Buffer.from(sponsorAuthenticator), // 97 bytes (fee_payer_signer)
                VEC_EMPTY // 1 byte (secondary_signers)
            ]);
            // Optional assertions to help catch mis-tags early
            if (signedTxnBytes[feePayerRawTxnBytes.length] !== TA.FEE_PAYER) {
                throw new Error('Missing TA::FeePayer tag');
            }
            if (signedTxnBytes[feePayerRawTxnBytes.length + 1] !== TA.SINGLE_SENDER) {
                throw new Error('Sender must be TA::SingleSender (0x04)');
            }
            if (signedTxnBytes[feePayerRawTxnBytes.length + 2] !== AA.KEYLESS) {
                throw new Error('Inner account auth must be KEYLESS (0x02)');
            }
            // Expected total: 231 + 1 + 457 + 1 + 32 + 97 + 1 = 820 bytes
            logger_1.default.info(`Submitting ${signedTxnBytes.length}-byte signed transaction`);
            logger_1.default.info(`Structure: feepayer_raw(231) + tag(1) + wrapped_sender(457) + empty(1) + addr(32) + sponsor(97) + empty(1)`);
            // Submit to Aptos network
            const fullnodeUrl = config_1.config.aptos.network === 'mainnet'
                ? 'https://fullnode.mainnet.aptoslabs.com/v1'
                : 'https://fullnode.testnet.aptoslabs.com/v1';
            const url = `${fullnodeUrl}/transactions`;
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x.aptos.signed_transaction+bcs',
                },
                body: signedTxnBytes,
            });
            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`Transaction submission failed: ${response.status} ${errorText}`);
            }
            const result = await response.json();
            logger_1.default.info('Transaction submitted successfully:', result.hash);
            return {
                transactionHash: result.hash,
                success: true,
            };
        }
        catch (error) {
            logger_1.default.error('Error submitting fee-payer transaction:', error);
            throw error;
        }
    }
    reconstructEphemeralKeyPair(data) {
        try {
            // The data contains the private key in hex format
            // We need to reconstruct the EphemeralKeyPair from the private key
            const privateKeyHex = data.privateKey.replace('0x', '');
            const privateKeyBytes = new Uint8Array(privateKeyHex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
            // Reconstruct using the Aptos SDK method
            const ephemeralKeyPair = new ts_sdk_1.EphemeralKeyPair({
                privateKey: new ts_sdk_1.Ed25519PrivateKey(privateKeyBytes),
                expiryDateSecs: Math.floor(new Date(data.expiryDate).getTime() / 1000), // Convert to Unix timestamp
                blinder: data.blinder ? new Uint8Array(data.blinder.split(',').map(b => parseInt(b))) : undefined, // Convert blinder array
            });
            // The nonce should match the one that was used when generating the key
            // Check if the reconstructed nonce matches the original
            if (String(ephemeralKeyPair.nonce) !== String(data.nonce)) {
                logger_1.default.error('Nonce mismatch after reconstruction!');
                logger_1.default.error('Original nonce:', data.nonce);
                logger_1.default.error('Reconstructed nonce:', String(ephemeralKeyPair.nonce));
                // Try to manually set the nonce if possible
                // This is a workaround - the SDK should handle this properly
                // Make sure it's a string, not an object
                const nonceString = typeof data.nonce === 'string'
                    ? data.nonce
                    : typeof data.nonce === 'object' && data.nonce !== null
                        ? Object.values(data.nonce).join('')
                        : String(data.nonce);
                ephemeralKeyPair.nonce = nonceString;
            }
            logger_1.default.debug('Final ephemeral key pair nonce:', String(ephemeralKeyPair.nonce));
            return ephemeralKeyPair;
        }
        catch (error) {
            logger_1.default.error('Error reconstructing ephemeral key pair:', error);
            throw new Error('Failed to reconstruct ephemeral key pair');
        }
    }
}
exports.KeylessService = KeylessService;
//# sourceMappingURL=keylessService.js.map