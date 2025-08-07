"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.isProduction = exports.isDevelopment = exports.config = void 0;
const dotenv_1 = __importDefault(require("dotenv"));
dotenv_1.default.config();
exports.config = {
    port: parseInt(process.env.PORT || '3333', 10),
    nodeEnv: process.env.NODE_ENV || 'development',
    aptos: {
        network: (process.env.APTOS_NETWORK || 'devnet'),
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
exports.isDevelopment = exports.config.nodeEnv === 'development';
exports.isProduction = exports.config.nodeEnv === 'production';
//# sourceMappingURL=config.js.map