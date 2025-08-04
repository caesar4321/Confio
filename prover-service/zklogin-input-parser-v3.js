import crypto from 'crypto';

/**
 * zkLogin input parser V3 - Fixed nonce handling
 * The circuit expects the ORIGINAL 27-char nonce, not the hashed 44-char one from JWT
 */

function base64urlDecode(str) {
    const padding = '='.repeat((4 - str.length % 4) % 4);
    const base64 = (str + padding).replace(/-/g, '+').replace(/_/g, '/');
    return Buffer.from(base64, 'base64');
}

function stringToAsciiArray(str, maxLen) {
    const arr = [];
    for (let i = 0; i < maxLen; i++) {
        // Return string values, not numbers
        arr.push(i < str.length ? str.charCodeAt(i).toString() : '0');
    }
    return arr;
}

function findSubstringIndex(str, substr) {
    const index = str.indexOf(substr);
    return index === -1 ? 0 : index;
}

function findBase64Pattern(b64String, pattern) {
    // Based on zkLogin circuit ASCIISubstrExistsInB64 template
    // We need to find where the pattern appears when base64 is decoded
    
    // Add padding to make valid base64
    const padding = '='.repeat((4 - b64String.length % 4) % 4);
    const paddedB64 = b64String + padding;
    
    // Decode to find the actual position
    const decoded = Buffer.from(paddedB64, 'base64').toString();
    
    // Look for the pattern with quotes (as it appears in JSON)
    const quotedPattern = '"' + pattern + '"';
    const decodedIndex = decoded.indexOf(quotedPattern);
    
    if (decodedIndex === -1) {
        // Pattern not found
        return 0;
    }
    
    // Calculate the base64 index more accurately
    // Every 3 bytes in decoded become 4 chars in base64
    // We need to find where in the base64 string this pattern starts
    
    // Re-encode the portion up to the pattern to find exact b64 position
    const beforePattern = decoded.substring(0, decodedIndex);
    const beforePatternB64 = Buffer.from(beforePattern).toString('base64').replace(/=/g, '');
    
    // The pattern starts at this position in the base64 string
    return beforePatternB64.length;
}

function hashToField(data) {
    const hash = crypto.createHash('sha256').update(data).digest();
    const fieldPrime = BigInt('21888242871839275222246405745257275088548364400416034343698204186575808495617');
    const hashBigInt = BigInt('0x' + hash.toString('hex'));
    return (hashBigInt % fieldPrime).toString();
}

// Generate the original 27-char nonce from ephemeral key, epoch, and randomness
function generateOriginalNonce(ephemeralPublicKey, maxEpoch, jwtRandomness) {
    // This would normally use Poseidon hash, but for now we'll use the nonce
    // that was computed client-side and passed through the prover request
    // The actual nonce should be passed as a separate parameter
    console.log('⚠️ Warning: Original nonce should be passed from client, not computed from JWT nonce');
    
    // For now, return a placeholder that's the right length
    // In production, this should be the actual computed nonce from the client
    const placeholder = 'abcdefghijklmnopqrstuvwxyz0';
    return placeholder.substring(0, 27);
}

export function prepareZkLoginInputs(
    jwt,
    ephemeralPublicKey, 
    maxEpoch,
    jwtRandomness,
    salt,
    keyClaimName = 'sub',
    originalNonce = null  // Add parameter for the original 27-char nonce
) {
    // Parse JWT
    const [headerB64, payloadB64, signatureB64] = jwt.split('.');
    
    // Decode JWT parts
    const headerBytes = base64urlDecode(headerB64);
    const payloadBytes = base64urlDecode(payloadB64);
    const signatureBytes = base64urlDecode(signatureB64);
    
    const headerStr = headerBytes.toString('utf-8');
    const payloadStr = payloadBytes.toString('utf-8');
    
    const headerJson = JSON.parse(headerStr);
    const payloadJson = JSON.parse(payloadStr);
    
    // Extract key fields
    const iss = payloadJson.iss || '';
    const aud = payloadJson.aud || '';
    const sub = payloadJson.sub || '';
    const jwtNonce = payloadJson.nonce || '';  // This is the hashed 44-char nonce from provider
    
    // The circuit now accepts variable-length nonces (27-64 chars)
    // No need for the original nonce workaround anymore
    
    // Compute unsigned JWT
    const unsignedJwt = `${headerB64}.${payloadB64}`;
    const paddedUnsignedJwt = stringToAsciiArray(unsignedJwt, 1600);  // Circuit expects 1600
    
    // Find field positions in base64 payload
    const audIndex = findBase64Pattern(payloadB64, 'aud');
    const nonceIndex = findBase64Pattern(payloadB64, 'nonce');
    const kcIndex = findBase64Pattern(payloadB64, keyClaimName);
    const issIndex = findBase64Pattern(payloadB64, 'iss');
    
    // Find field positions in JSON string
    const audColonIndex = findSubstringIndex(payloadStr, '"aud":');
    const nonceColonIndex = findSubstringIndex(payloadStr, '"nonce":');
    const kcColonIndex = findSubstringIndex(payloadStr, `"${keyClaimName}":`);
    
    // Find value positions (relative to colon position for circuit)
    const audValueIndex = findSubstringIndex(payloadStr, aud) - audColonIndex;
    const nonceValueIndex = findSubstringIndex(payloadStr, jwtNonce) - nonceColonIndex;  // Use JWT nonce for position
    const kcValueIndex = findSubstringIndex(payloadStr, payloadJson[keyClaimName] || sub) - kcColonIndex;
    
    // Parse ephemeral public key - split into high and low 128-bit parts
    // Based on zkLogin circuit requirement: [publicKey / 2^128, publicKey % 2^128]
    const ephKeyBytes = Buffer.from(ephemeralPublicKey, 'base64');
    const ephKeyBigInt = BigInt('0x' + ephKeyBytes.toString('hex'));
    const ephHigh = (ephKeyBigInt >> BigInt(128)).toString();
    const ephLow = (ephKeyBigInt & ((BigInt(1) << BigInt(128)) - BigInt(1))).toString();
    const ephPublicKey = [ephHigh, ephLow];
    
    // Compute all inputs hash - hash the entire unsigned JWT to field
    // This is used as a public input to the circuit
    const allInputsHash = hashToField(unsignedJwt);
    
    // RSA modulus will be added by the main prover after fetching from JWKS
    
    // Signature as array of 32 64-bit chunks (as strings for circuit)
    const signatureArray = [];
    for (let i = 0; i < 32; i++) {
        const start = i * 8;
        const end = start + 8;
        const chunk = signatureBytes.slice(start, end);
        
        if (chunk.length > 0) {
            // Convert chunk to BigInt (big-endian for RSA signature)
            let value = BigInt(0);
            for (let j = 0; j < chunk.length; j++) {
                // Big-endian: most significant byte first
                value = (value << BigInt(8)) | BigInt(chunk[j]);
            }
            signatureArray.push(value.toString());
        } else {
            signatureArray.push('0');
        }
    }
    
    // Extended fields (as ASCII arrays)
    // Use exact sizes from the circuit's requirements
    const extAud = stringToAsciiArray(aud, 160);  
    // IMPORTANT: Circuit expects maxExtNonceLength = 7 + 66 + 2 + 6 = 81
    // This includes: "nonce"(7) + value(66) + colon+comma(2) + whitespace(6)
    // We need to create the full JSON field: "nonce":"value"
    const nonceField = `"nonce":"${jwtNonce}"`;
    const extNonce = stringToAsciiArray(nonceField, 85);  // Full field padded to 85 (matches circuit)
    const extKc = stringToAsciiArray(payloadJson[keyClaimName] || sub, 126);  
    
    // Email verified field (if exists)
    const evValue = payloadJson.email_verified !== undefined ? 
        (payloadJson.email_verified ? 'true' : 'false') : '';
    const evIndex = evValue ? findBase64Pattern(payloadB64, 'email_verified') : 0;
    const evColonIndex = evValue ? findSubstringIndex(payloadStr, '"email_verified":') : 0;
    const evValueIndex = evValue ? (findSubstringIndex(payloadStr, evValue) - evColonIndex) : 0;
    const extEv = stringToAsciiArray(evValue, 53);  
    
    // Calculate SHA2 blocks needed
    const numSha2Blocks = Math.ceil((headerB64.length + payloadB64.length + 1) / 64);
    
    // Prepare circuit inputs
    const inputs = {
        all_inputs_hash: allInputsHash,
        
        // Audience field
        aud_colon_index: audColonIndex.toString(),
        aud_index_b64: audIndex.toString(),
        aud_length_b64: Math.ceil((5 + aud.length) * 4 / 3).toString(), // Base64 length of "aud":"value"
        aud_value_index: Math.max(0, audValueIndex).toString(),
        aud_value_length: aud.length.toString(),
        
        // Ephemeral public key
        eph_public_key: ephPublicKey,
        
        // Email verified field
        ev_colon_index: evColonIndex.toString(),
        ev_index_b64: evIndex.toString(),
        ev_length_b64: evValue ? '20' : '0',
        ev_name_length: evValue ? '14' : '0', // "email_verified"
        ev_value_index: Math.max(0, evValueIndex).toString(),
        ev_value_length: evValue.length.toString(),
        
        // Extended fields
        ext_aud: extAud,
        ext_aud_length: aud.length.toString(),
        ext_ev: extEv,
        ext_ev_length: evValue.length.toString(),
        ext_kc: extKc,
        ext_kc_length: (payloadJson[keyClaimName] || sub).length.toString(),
        ext_nonce: extNonce,
        ext_nonce_length: nonceField.length.toString(),  // Length of full "nonce":"value" field
        
        // Issuer field  
        iss_index_b64: issIndex.toString(),
        iss_length_b64: Math.ceil((5 + iss.length) * 4 / 3).toString(), // Base64 length of "iss":"value"
        
        // JWT randomness (convert from base64 to BigInt string)
        jwt_randomness: BigInt('0x' + Buffer.from(jwtRandomness, 'base64').toString('hex')).toString(),
        
        // Key claim field
        kc_colon_index: kcColonIndex.toString(),
        kc_index_b64: kcIndex.toString(),
        kc_length_b64: Math.ceil((keyClaimName.length + 3) * 4 / 3).toString(), // Base64 length of "key":"
        kc_name_length: keyClaimName.length.toString(),
        kc_value_index: Math.max(0, kcValueIndex).toString(),
        kc_value_length: (payloadJson[keyClaimName] || sub).length.toString(),
        
        // Max epoch
        max_epoch: maxEpoch.toString(),
        
        // RSA modulus (will be added by main prover after fetching from JWKS)
        // modulus: modulus,
        
        // Nonce field (positions still refer to JWT's nonce location)
        nonce_colon_index: nonceColonIndex.toString(),
        nonce_index_b64: nonceIndex.toString(),
        nonce_length_b64: Math.ceil((7 + jwtNonce.length) * 4 / 3).toString(), // Base64 length of JWT's nonce
        nonce_value_index: Math.max(0, nonceValueIndex).toString(),
        
        // SHA2 blocks
        num_sha2_blocks: numSha2Blocks.toString(),
        
        // Padded unsigned JWT
        padded_unsigned_jwt: paddedUnsignedJwt,
        
        // Payload info
        payload_len: payloadB64.length.toString(),
        payload_start_index: (headerB64.length + 1).toString(),
        
        // Salt (convert from base64 to BigInt string)
        salt: BigInt('0x' + Buffer.from(salt, 'base64').toString('hex')).toString(),
        
        // Signature
        signature: signatureArray
    };
    
    return inputs;
}