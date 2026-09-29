// Generate the Worker's Ed25519 signing key.
//
//   node scripts/generate-key.mjs
//
// Prints the private key (PKCS8, base64) for `wrangler secret put
// STATUS_SIGNING_KEY`, and the raw public key (hex) for the app's
// OUTAGE_STATUS_PUBLIC_KEY_HEX. Never commit the private key.
import { generateKeyPairSync } from 'node:crypto';

const { privateKey, publicKey } = generateKeyPairSync('ed25519');
const pkcs8 = privateKey.export({ format: 'der', type: 'pkcs8' }).toString('base64');
// SPKI for Ed25519 is a fixed 12-byte header followed by the 32-byte key.
const rawPublic = publicKey.export({ format: 'der', type: 'spki' }).subarray(12).toString('hex');

console.log('STATUS_SIGNING_KEY (wrangler secret, keep private):');
console.log(pkcs8);
console.log('\nOUTAGE_STATUS_PUBLIC_KEY_HEX (app bundle, public):');
console.log(rawPublic);
