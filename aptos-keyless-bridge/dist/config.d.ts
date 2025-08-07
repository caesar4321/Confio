import { Network } from '@aptos-labs/ts-sdk';
export declare const config: {
    port: number;
    nodeEnv: string;
    aptos: {
        network: Network;
    };
    cors: {
        allowedOrigins: string[];
    };
    logging: {
        level: string;
    };
    security: {
        jwtSecret: string;
    };
    rateLimit: {
        windowMs: number;
        maxRequests: number;
    };
    oauth: {
        providers: {
            google: {
                authUrl: string;
                scope: string;
            };
            apple: {
                authUrl: string;
                scope: string;
            };
        };
    };
};
export declare const isDevelopment: boolean;
export declare const isProduction: boolean;
//# sourceMappingURL=config.d.ts.map