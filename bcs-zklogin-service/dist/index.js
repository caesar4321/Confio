"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = __importDefault(require("express"));
const cors_1 = __importDefault(require("cors"));
const bcs_1 = require("@mysten/bcs");
const crypto_1 = __importDefault(require("crypto"));
const app = (0, express_1.default)();
const PORT = process.env.PORT || 3002;
// Middleware
app.use((0, cors_1.default)());
app.use(express_1.default.json({ limit: '10mb' }));
// Health check endpoint
app.get('/health', (req, res) => {
    res.json({
        status: 'healthy',
        service: 'bcs-zklogin-service',
        timestamp: new Date().toISOString()
    });
});
// Map audience to issuer
const getIssuerFromAudience = (audience) => {
    const issuerMap = {
        'apple': 'https://appleid.apple.com',
        'google': 'https://accounts.google.com',
        'twitch': 'https://id.twitch.tv/oauth2',
        'facebook': 'https://www.facebook.com'
    };
    return issuerMap[audience] || 'https://accounts.google.com';
};
// Blake2b helper function
function blake2b(data) {
    const hash = crypto_1.default.createHash('blake2b512');
    hash.update(data);
    return hash.digest().slice(0, 32); // First 32 bytes
}
// Generate address seed according to Sui zkLogin spec
function genAddressSeed(saltBase64, name, value, audience) {
    // Convert salt from base64 to bytes
    const saltBytes = Buffer.from(saltBase64, 'base64');
    const saltBigInt = BigInt('0x' + saltBytes.toString('hex'));
    // Convert to hex string and pad to 32 bytes (64 hex chars)
    let saltHex = saltBigInt.toString(16);
    saltHex = saltHex.padStart(64, '0');
    const saltPadded = Buffer.from(saltHex, 'hex');
    // Hash name:value (e.g., "sub:000705...")
    const nameValue = Buffer.from(`${name}:${value}`);
    const nameValueHash = blake2b(nameValue);
    // Hash audience with 0x00 prefix
    const aud = Buffer.concat([Buffer.from([0]), Buffer.from(audience)]);
    const audHash = blake2b(aud);
    // Combine all parts: "ZkLoginAddressSeed" + salt + nameValueHash + audHash
    const combined = Buffer.concat([
        Buffer.from('ZkLoginAddressSeed'),
        saltPadded,
        nameValueHash,
        audHash
    ]);
    // Final hash
    const finalHash = blake2b(combined);
    // Convert to BigInt string (decimal)
    const addressSeedBigInt = BigInt('0x' + finalHash.toString('hex'));
    return addressSeedBigInt.toString();
}
// Main endpoint for BCS zkLogin signature creation
app.post('/bcs-signature', async (req, res) => {
    try {
        const { ephemeralSignature, ephemeralPublicKey, zkProof, maxEpoch, subject, audience, userSalt, issuer } = req.body;
        // Validate required fields
        if (!ephemeralSignature || !ephemeralPublicKey || !zkProof || !maxEpoch || !subject || !audience || !userSalt) {
            return res.status(400).json({
                error: 'Missing required fields',
                required: ['ephemeralSignature', 'ephemeralPublicKey', 'zkProof', 'maxEpoch', 'subject', 'audience', 'userSalt']
            });
        }
        // Validate zkProof structure
        if (!zkProof.a || !zkProof.b || !zkProof.c) {
            return res.status(400).json({
                error: 'Invalid zkProof structure',
                required: 'zkProof must contain a, b, c arrays'
            });
        }
        // Clean zkProof data - remove 0x prefixes if present
        const cleanZkProof = {
            a: zkProof.a.map(val => val.startsWith('0x') ? val.slice(2) : val),
            b: zkProof.b.map(arr => arr.map(val => val.startsWith('0x') ? val.slice(2) : val)),
            c: zkProof.c.map(val => val.startsWith('0x') ? val.slice(2) : val)
        };
        console.log('Processing zkLogin signature request:', {
            audience,
            subject: subject.substring(0, 10) + '...',
            maxEpoch,
            hasEphemeralSig: !!ephemeralSignature,
            hasEphemeralPubkey: !!ephemeralPublicKey,
            hasZkProof: !!zkProof
        });
        // Debug the proof point formats and detect if they're mock data
        const isMockData = zkProof.a[0]?.includes('1a2b3c4d') || false;
        console.log('zkProof analysis:', {
            'a[0] original': zkProof.a[0]?.substring(0, 30) + '...',
            'a[0] cleaned': cleanZkProof.a[0]?.substring(0, 30) + '...',
            'a[0] length': cleanZkProof.a[0]?.length || 0,
            'is_mock_data': isMockData,
            'a_count': zkProof.a?.length || 0,
            'b_count': zkProof.b?.length || 0,
            'c_count': zkProof.c?.length || 0
        });
        // Determine issuer
        const finalIssuer = issuer || getIssuerFromAudience(audience);
        // Convert string inputs to appropriate formats
        const maxEpochNumber = parseInt(maxEpoch, 10);
        // Prepare the zkLogin signature using Sui SDK
        try {
            // Base64 encode the issuer for issBase64Details
            const issuerBase64 = Buffer.from(finalIssuer).toString('base64');
            // CRITICAL FIX: Convert hex strings to actual bytes for proper BCS serialization
            console.log('Converting hex proof points to bytes...');
            // Helper to convert hex string to Uint8Array padded to exactly 32 bytes
            const hexToBytes32 = (hex) => {
                let cleanHex = hex.startsWith('0x') ? hex.slice(2) : hex;
                // Pad with zero if odd length
                if (cleanHex.length % 2 !== 0) {
                    cleanHex = '0' + cleanHex;
                }
                const raw = Buffer.from(cleanHex, 'hex');
                if (raw.length > 32) {
                    throw new Error(`Proof element too long: ${raw.length} bytes`);
                }
                // Left pad to 32 bytes if shorter
                if (raw.length < 32) {
                    const padded = Buffer.alloc(32);
                    raw.copy(padded, 32 - raw.length);
                    console.log(`Padded proof point from ${raw.length} to 32 bytes`);
                    return new Uint8Array(padded);
                }
                return new Uint8Array(raw);
            };
            // Try two approaches: 1) Use getZkLoginSignature with strings, 2) Manual BCS if needed
            console.log('Attempt 1: Using getZkLoginSignature with decimal BigInt strings...');
            // CRITICAL: Convert hex to decimal strings for getZkLoginSignature
            const formattedProofPoints = {
                a: cleanZkProof.a.map(hex => BigInt('0x' + hex).toString()),
                b: cleanZkProof.b.map(pair => pair.map(hex => BigInt('0x' + hex).toString())),
                c: cleanZkProof.c.map(hex => BigInt('0x' + hex).toString())
            };
            console.log('Formatted proof points sample:', {
                'a[0] type': typeof formattedProofPoints.a[0],
                'a[0] hex': cleanZkProof.a[0]?.substring(0, 20) + '...',
                'a[0] decimal': formattedProofPoints.a[0]?.substring(0, 20) + '...',
                'a[0] length': formattedProofPoints.a[0]?.length,
                'b structure': Array.isArray(formattedProofPoints.b[0]),
                'c[0] type': typeof formattedProofPoints.c[0]
            });
            // Try using the SDK's getZkLoginSignature one more time with proper inputs
            console.log('Attempting to use SDK getZkLoginSignature with proper inputs...');
            // Convert proof points to binary - this is critical!
            const binaryProofPoints = {
                a: cleanZkProof.a.map(hexToBytes32),
                b: cleanZkProof.b.map(pair => pair.map(hexToBytes32)),
                c: cleanZkProof.c.map(hexToBytes32)
            };
            console.log('Binary proof points sample:', {
                'a[0] hex': cleanZkProof.a[0]?.substring(0, 20) + '...',
                'a[0] bytes length': binaryProofPoints.a[0]?.length,
                'b[0][0] bytes length': binaryProofPoints.b[0]?.[0]?.length,
                'c[0] bytes length': binaryProofPoints.c[0]?.length,
                'total_a': binaryProofPoints.a.length,
                'total_b': binaryProofPoints.b.length,
                'total_c': binaryProofPoints.c.length
            });
            // Add detailed logging per ChatGPT's recommendation
            console.log('Proof structure validation:');
            console.log('  Proof a length:', binaryProofPoints.a.length); // should be 2
            console.log('  Proof b shape:', binaryProofPoints.b.map(x => x.length)); // each should be length 2
            console.log('  Proof c length:', binaryProofPoints.c.length); // should be 2
            console.log('  Each a[i] byte length:', binaryProofPoints.a.map(x => x.length)); // each = 32
            console.log('  Each b[i][j] byte length:', binaryProofPoints.b.flat().map(x => x.length)); // each = 32
            console.log('  Each c[i] byte length:', binaryProofPoints.c.map(x => x.length)); // each = 32
            // Build zkLogin signature manually using BCS
            console.log('Building zkLogin signature with manual BCS...');
            // Manual BCS serialization for zkLogin signature
            // Format: flag(1) + ZkLoginSignature BCS bytes
            const zkLoginFlag = 0x05; // ZkLogin signature flag (confirmed correct for Sui)
            try {
                // Convert binary proof points to arrays for BCS
                const proofPointsForBCS = {
                    a: binaryProofPoints.a.map(bytes => Array.from(bytes)),
                    b: binaryProofPoints.b.map(pair => pair.map(bytes => Array.from(bytes))),
                    c: binaryProofPoints.c.map(bytes => Array.from(bytes))
                };
                // Serialize the zkLogin inputs using BCS
                // Define the exact BCS structure according to Sui's zkLogin implementation
                // For Groth16 proofs, we know the exact sizes:
                // a: always 2 elements of 32 bytes each
                // b: always 2x2 matrix of 32 bytes each
                // c: always 2 elements of 32 bytes each
                const g1Point = bcs_1.bcs.fixedArray(32, bcs_1.bcs.u8());
                const g2Point = bcs_1.bcs.fixedArray(2, g1Point);
                const zkLoginInputs = bcs_1.bcs.struct('ZkLoginInputs', {
                    proofPoints: bcs_1.bcs.struct('ProofPoints', {
                        a: bcs_1.bcs.fixedArray(2, g1Point), // Exactly 2 G1 points
                        b: bcs_1.bcs.fixedArray(2, g2Point), // Exactly 2 G2 points (each is 2 G1 points)
                        c: bcs_1.bcs.fixedArray(2, g1Point) // Exactly 2 G1 points
                    }),
                    issBase64Details: bcs_1.bcs.struct('IssBase64Details', {
                        value: bcs_1.bcs.string(),
                        indexMod4: bcs_1.bcs.u8()
                    }),
                    headerBase64: bcs_1.bcs.string(),
                    addressSeed: bcs_1.bcs.u256() // Changed from string to u256
                });
                const zkLoginSig = bcs_1.bcs.struct('ZkLoginSignature', {
                    inputs: zkLoginInputs,
                    maxEpoch: bcs_1.bcs.u64(),
                    userSignature: bcs_1.bcs.vector(bcs_1.bcs.u8()) // Full Ed25519 signature with flag + sig + pubkey
                });
                // Calculate indexMod4 correctly - it's the issuer base64 length mod 4
                const indexMod4 = issuerBase64.length % 4;
                // Calculate addressSeed using proper genAddressSeed function
                const addressSeed = genAddressSeed(userSalt, 'sub', subject, audience);
                console.log('Calculated zkLogin parameters:', {
                    issuerBase64,
                    indexMod4,
                    addressSeed: addressSeed.substring(0, 50) + '...',
                    addressSeedLength: addressSeed.length,
                    addressSeedType: 'decimal BigInt string',
                    addressSeedFirstChars: addressSeed.substring(0, 10),
                    addressSeedIsNumeric: /^\d+$/.test(addressSeed)
                });
                // Create full Ed25519 signature: flag (0x00) + signature + public key
                const ephSigBytes = Buffer.from(ephemeralSignature, 'base64');
                const ephPubKeyBytes = Buffer.from(ephemeralPublicKey, 'base64');
                // Ed25519 signature format: 0x00 + 64-byte signature + 32-byte public key
                const fullUserSignature = new Uint8Array(1 + ephSigBytes.length + ephPubKeyBytes.length);
                fullUserSignature[0] = 0x00; // Ed25519 flag
                fullUserSignature.set(ephSigBytes, 1);
                fullUserSignature.set(ephPubKeyBytes, 1 + ephSigBytes.length);
                // Prepare the data structure with binary arrays
                const zkLoginData = {
                    inputs: {
                        proofPoints: proofPointsForBCS,
                        issBase64Details: {
                            value: issuerBase64,
                            indexMod4: indexMod4
                        },
                        headerBase64: '', // TODO: Check if this should be omitted
                        addressSeed: BigInt(addressSeed) // Convert string to BigInt for u256
                    },
                    maxEpoch: maxEpochNumber,
                    userSignature: Array.from(fullUserSignature)
                };
                console.log('Serializing zkLogin data...');
                console.log('UserSignature structure:', {
                    'signature bytes': ephSigBytes.length,
                    'pubkey bytes': ephPubKeyBytes.length,
                    'total with flag': fullUserSignature.length,
                    'ephSig first 8 bytes': ephSigBytes.slice(0, 8).toString('hex'),
                    'ephSig last 8 bytes': ephSigBytes.slice(-8).toString('hex'),
                    'fullUserSig first 8 bytes': Buffer.from(fullUserSignature.slice(0, 8)).toString('hex')
                });
                // Log the data structure before serialization for debugging
                console.log('Data structure for BCS:');
                console.log('  inputs.proofPoints.a length:', zkLoginData.inputs.proofPoints.a.length);
                console.log('  inputs.proofPoints.b length:', zkLoginData.inputs.proofPoints.b.length);
                console.log('  inputs.proofPoints.c length:', zkLoginData.inputs.proofPoints.c.length);
                console.log('  inputs.addressSeed (BigInt):', zkLoginData.inputs.addressSeed.toString());
                console.log('  inputs.addressSeed type:', typeof zkLoginData.inputs.addressSeed);
                console.log('  maxEpoch:', zkLoginData.maxEpoch);
                console.log('  userSignature length:', zkLoginData.userSignature.length);
                // Serialize using BCS
                const serializedZkLogin = zkLoginSig.serialize(zkLoginData).toBytes();
                // Log detailed byte breakdown
                console.log('\nDetailed BCS breakdown:');
                console.log('  Proof points (2 + 64 + 2 + 128 + 2 + 64 = 262 bytes expected)');
                console.log('  IssBase64Details: ~39 bytes (string length + data + u8)');
                console.log('  HeaderBase64: 1 byte (empty string = just length byte 0x00)');
                console.log('  AddressSeed: 32 bytes (u256)');
                console.log('  MaxEpoch: 8 bytes (u64)');
                console.log('  UserSignature: 98 bytes (1 byte length + 97 bytes data)');
                console.log('  Expected total: ~262 + 39 + 1 + 32 + 8 + 98 = ~440 bytes');
                console.log('  Actual serialized length:', serializedZkLogin.length);
                // Prepend the signature flag
                const fullSignature = new Uint8Array(1 + serializedZkLogin.length);
                fullSignature[0] = zkLoginFlag;
                fullSignature.set(serializedZkLogin, 1);
                const zkLoginSignature = (0, bcs_1.toB64)(fullSignature);
                console.log('✅ Manual BCS serialization succeeded');
                console.log('Serialized length (without flag):', serializedZkLogin.length);
                console.log('Total signature length:', fullSignature.length);
                console.log('First 32 bytes (hex):', Buffer.from(fullSignature.slice(0, 32)).toString('hex'));
                console.log('Last 16 bytes (hex):', Buffer.from(fullSignature.slice(-16)).toString('hex'));
                // Log the structure of the first few bytes
                console.log('\nFirst bytes breakdown:');
                console.log('  Byte 0: 0x' + fullSignature[0].toString(16).padStart(2, '0') + ' (zkLogin flag)');
                console.log('  Bytes 1-32: First proof point a[0]');
                // Return the signature
                return res.json({
                    success: true,
                    zkLoginSignature: zkLoginSignature,
                    bcsFormat: true,
                    metadata: {
                        issuer: finalIssuer,
                        maxEpoch: maxEpochNumber,
                        audience,
                        subject: subject.substring(0, 10) + '...',
                        signatureLength: fullSignature.length,
                        method: 'manual-bcs'
                    }
                });
            }
            catch (bcsError) {
                console.error('❌ Manual BCS failed:', bcsError);
                return res.status(500).json({
                    error: 'Failed to create zkLogin signature with manual BCS',
                    details: bcsError.message,
                    suggestion: 'Check proof point formats and input parameters'
                });
            }
        }
        catch (error) {
            console.error('Unexpected error in zkLogin signature creation:', error);
            return res.status(500).json({
                error: 'Failed to create zkLogin signature',
                details: error.message
            });
        }
    }
    catch (error) {
        console.error('Error processing zkLogin signature request:', error);
        return res.status(500).json({
            error: 'Internal server error',
            details: error.message
        });
    }
});
// Error handling middleware
app.use((error, req, res, next) => {
    console.error('Unhandled error:', error);
    res.status(500).json({
        error: 'Internal server error',
        details: error.message
    });
});
// Start server
app.listen(PORT, () => {
    console.log(`🚀 BCS zkLogin Service running on port ${PORT}`);
    console.log(`📋 Health check: http://localhost:${PORT}/health`);
    console.log(`🔑 BCS Signature: POST http://localhost:${PORT}/bcs-signature`);
});
exports.default = app;
//# sourceMappingURL=index.js.map