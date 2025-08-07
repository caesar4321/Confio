"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = __importDefault(require("express"));
const cors_1 = __importDefault(require("cors"));
const dotenv_1 = __importDefault(require("dotenv"));
const config_1 = require("./config");
const logger_1 = __importDefault(require("./logger"));
const keyless_1 = __importDefault(require("./routes/keyless"));
const keylessV2_1 = __importDefault(require("./routes/keylessV2"));
const testKeyless_1 = __importDefault(require("./routes/testKeyless"));
const testSimpleKeyless_1 = __importDefault(require("./routes/testSimpleKeyless"));
const debugKeyless_1 = __importDefault(require("./routes/debugKeyless"));
// Load environment variables
dotenv_1.default.config();
const app = (0, express_1.default)();
// Middleware
app.use((0, cors_1.default)({
    origin: config_1.config.cors.allowedOrigins,
    credentials: true,
}));
app.use(express_1.default.json());
app.use(express_1.default.urlencoded({ extended: true }));
// Request logging middleware
app.use((req, _res, next) => {
    logger_1.default.info(`${req.method} ${req.path}`, {
        query: req.query,
        body: req.body,
        ip: req.ip,
    });
    next();
});
// Routes
app.use('/api/keyless', keyless_1.default);
app.use('/api/keyless/v2', keylessV2_1.default);
app.use('/api/keyless', testKeyless_1.default); // Add test routes
app.use('/api/keyless', testSimpleKeyless_1.default); // Add simple test routes
app.use('/api/keyless', debugKeyless_1.default); // Add debug routes
// Base route
app.get('/', (_req, res) => {
    res.json({
        message: 'Aptos Keyless Bridge Service',
        version: '1.0.0',
        endpoints: {
            health: '/api/keyless/health',
            generateEphemeralKey: 'POST /api/keyless/ephemeral-key',
            generateOAuthUrl: 'POST /api/keyless/oauth-url',
            deriveAccount: 'POST /api/keyless/derive-account',
            signAndSubmit: 'POST /api/keyless/sign-and-submit',
            feePayerSubmit: 'POST /api/keyless/fee-payer-submit',
            getBalance: 'GET /api/keyless/balance/:address',
            v2: {
                submitSponsored: 'POST /api/keyless/v2/submit-sponsored',
                buildSponsored: 'POST /api/keyless/v2/build-sponsored',
            },
        },
    });
});
// Error handling middleware
app.use((err, _req, res, _next) => {
    logger_1.default.error('Unhandled error:', err);
    res.status(500).json({
        error: 'INTERNAL_SERVER_ERROR',
        message: 'An unexpected error occurred',
    });
});
// 404 handler
app.use((_req, res) => {
    res.status(404).json({
        error: 'NOT_FOUND',
        message: 'Endpoint not found',
    });
});
// Start server
const port = config_1.config.port;
app.listen(port, () => {
    logger_1.default.info(`Aptos Keyless Bridge running on port ${port}`);
    logger_1.default.info(`Network: ${config_1.config.aptos.network}`);
    logger_1.default.info(`Environment: ${config_1.config.nodeEnv}`);
});
//# sourceMappingURL=index.js.map