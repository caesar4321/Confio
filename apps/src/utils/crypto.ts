import { Buffer } from 'buffer';
import { getRandomValues } from 'react-native-get-random-values';

export const generateRandomness = (): string => {
  const randomBytes = new Uint8Array(32); // 256 bits of randomness
  getRandomValues(randomBytes);
  return Buffer.from(randomBytes).toString('hex');
}; 