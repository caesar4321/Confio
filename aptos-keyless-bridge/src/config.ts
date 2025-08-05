import dotenv from 'dotenv';
import { Network } from '@aptos-labs/ts-sdk';

dotenv.config();

export const config = {
  port: parseInt(process.env.PORT || '3333', 10),
  nodeEnv: process.env.NODE_ENV || 'development',
  
  aptos: {
    network: (process.env.APTOS_NETWORK || 'devnet') as Network,
  },
  
  cors: {
    allowedOrigins: process.env.ALLOWED_ORIGINS?.split(',') || ['http://localhost:3000', 'http://localhost:8000'],
  },
  
  logging: {
    level: process.env.LOG_LEVEL || 'info',
  },
  
  security: {
    jwtSecret: process.env.JWT_SECRET || 'default-dev-secret',
  },
  
  rateLimit: {
    windowMs: parseInt(process.env.RATE_LIMIT_WINDOW_MS || '60000', 10),
    maxRequests: parseInt(process.env.RATE_LIMIT_MAX_REQUESTS || '100', 10),
  },
  
  oauth: {
    providers: {
      google: {
        authUrl: 'https://accounts.google.com/o/oauth2/v2/auth',
        scope: 'openid email profile',
      },
      apple: {
        authUrl: 'https://appleid.apple.com/auth/authorize',
        scope: 'openid email name',
      },
    },
  },
};

export const isDevelopment = config.nodeEnv === 'development';
export const isProduction = config.nodeEnv === 'production';