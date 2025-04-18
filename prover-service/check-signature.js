import { getZkLoginSignature } from '@mysten/zklogin';
import * as signature from '@mysten/sui/zklogin/signature';

// Log the functions to see their implementations
console.log('getZkLoginSignature:', getZkLoginSignature.toString());
console.log('getZkLoginSignatureBytes:', signature.getZkLoginSignatureBytes.toString()); 