import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import { config } from './config';
import logger from './logger';
import keylessRoutes from './routes/keyless';
import keylessV2Routes from './routes/keylessV2';

// Load environment variables
dotenv.config();

const app = express();

// Middleware
app.use(cors({
  origin: config.cors.allowedOrigins,
  credentials: true,
}));

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Request logging middleware
app.use((req, _res, next) => {
  logger.info(`${req.method} ${req.path}`, {
    query: req.query,
    body: req.body,
    ip: req.ip,
  });
  next();
});

// Routes
app.use('/api/keyless', keylessRoutes);
app.use('/api/keyless/v2', keylessV2Routes);

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
app.use((err: Error, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
  logger.error('Unhandled error:', err);
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
const port = config.port;
app.listen(port, () => {
  logger.info(`Aptos Keyless Bridge running on port ${port}`);
  logger.info(`Network: ${config.aptos.network}`);
  logger.info(`Environment: ${config.nodeEnv}`);
});