import { timingSafeEqual } from 'node:crypto';
import { PinStore, PinCapacityError, type UserProfile } from './store.js';
import { BotClient, BotDeliveryError } from './bot-client.js';
import express, { type Express, type RequestHandler, type ErrorRequestHandler } from 'express';

export interface AppOptions {
  internalApiKey: string;
  store?: PinStore;
  botClient?: Pick<BotClient, 'sendMessage'>;
  /** Register application routes after shared middleware and before final errors. */
  configureRoutes?: (app: Express) => void;
}

export class HttpError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string) {
    super(message);
  }
}

export function createApp(options: AppOptions): Express {
  if (!options.internalApiKey.trim() || options.internalApiKey === 'replace-with-a-random-shared-secret') {
    throw new Error('A non-placeholder INTERNAL_API_KEY is required.');
  }
  const store = options.store ?? new PinStore();
  const app = express();
  app.disable('x-powered-by');
  app.get('/health', (_req, res) => {
    res.status(200).json({ status: 'ok' });
  });

  const authorizeInternal: RequestHandler = (req, res, next) => {
    const provided = Buffer.from(req.get('X-Internal-Key') ?? '', 'utf8');
    const expected = Buffer.from(options.internalApiKey, 'utf8');
    if (provided.length !== expected.length || !timingSafeEqual(provided, expected)) {
      res.status(403).json({ error: { code: 'INTERNAL_AUTH_FAILED', message: 'Internal authorization failed.' } });
      return;
    }
    next();
  };
  // Authorize internal requests before parsing potentially large request bodies.
  app.use('/internal', authorizeInternal);
  app.use(express.json({ limit: '2mb' }));
  app.post('/internal/pins', (req, res) => {
    const user = parseProfile(req.body?.user);
    if (!user) throw new HttpError(400, 'INVALID_PROFILE', 'A valid user profile is required.');
    try {
      res.status(201).json(store.issuePin(user));
    } catch (error) {
      if (error instanceof PinCapacityError) throw new HttpError(503, 'PIN_CAPACITY_EXCEEDED', 'No free PIN is available.');
      throw error;
    }
  });
  app.post('/auth', (req, res) => {
    const pin: unknown = req.body?.key;
    if (typeof pin !== 'string' || pin.length !== 6 || !/^[0-9]{6}$/.test(pin)) {
      throw new HttpError(400, 'INVALID_PIN_FORMAT', 'PIN must contain exactly six digits.');
    }
    const session = store.consumePin(pin);
    if (!session) throw new HttpError(401, 'INVALID_PIN', 'PIN is invalid or expired.');
    res.status(200).json(session);
  });
  app.post('/messages', async (req, res) => {
    const authorization = req.get('Authorization') ?? '';
    const match = /^Bearer ([^\s]+)$/i.exec(authorization);
    const user = match?.[1] ? store.getUserByToken(match[1]) : null;
    if (!user) throw new HttpError(401, 'UNAUTHORIZED', 'Sign in before sending a message.');
    const rawText: unknown = req.body?.text;
    if (typeof rawText !== 'string') throw new HttpError(400, 'INVALID_TEXT', 'Message must be plain text.');
    const text = rawText.trim();
    // Reject unpaired UTF-16 surrogates: they cannot be transmitted as Unicode text.
    if (!text || text.length > 3000 || /[\uD800-\uDFFF]/u.test(text)) {
      throw new HttpError(400, 'INVALID_TEXT', 'Message must contain 1 to 3000 characters.');
    }
    if (!options.botClient) throw new HttpError(502, 'DELIVERY_FAILED', 'Message delivery is unavailable.');
    try {
      // Sender identity comes exclusively from the server session, never the body.
      await options.botClient.sendMessage({
        telegramId: user.telegramId, firstName: user.firstName, username: user.username,
      }, text);
    } catch (error) {
      if (error instanceof BotDeliveryError) {
        throw new HttpError(error.status, error.code, error.message);
      }
      // Unexpected transport failures cannot establish whether delivery happened.
      throw new HttpError(504, 'DELIVERY_UNCONFIRMED', 'Delivery could not be confirmed');
    }
    res.status(200).json({ status: 'sent' });
  });
  options.configureRoutes?.(app);
  app.use((_req, res) => {
    res.status(404).json({ error: { code: 'NOT_FOUND', message: 'Route not found.' } });
  });
  const handleError: ErrorRequestHandler = (error: unknown, _req, res, _next) => {
    if (res.headersSent) return;
    if (error instanceof HttpError) {
      res.status(error.status).json({ error: { code: error.code, message: error.message } });
      return;
    }
    const type = typeof error === 'object' && error !== null && 'type' in error ? error.type : undefined;
    if (type === 'entity.too.large') {
      res.status(413).json({ error: { code: 'BODY_TOO_LARGE', message: 'Request body is too large.' } });
      return;
    }
    if (type === 'entity.parse.failed') {
      res.status(400).json({ error: { code: 'INVALID_JSON', message: 'Request body must be valid JSON.' } });
      return;
    }
    // Do not return exception text, request bodies, PINs, or credentials.
    res.status(500).json({ error: { code: 'INTERNAL_ERROR', message: 'An internal error occurred.' } });
  };
  app.use(handleError);
  return app;
}

/** Normalize absent optional Telegram fields; reject malformed bot payloads. */
function parseProfile(value: unknown): UserProfile | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const user = value as Record<string, unknown>;
  if (typeof user.telegramId !== 'number' || !Number.isSafeInteger(user.telegramId) || user.telegramId <= 0) return null;
  if (typeof user.firstName !== 'string' || !user.firstName.trim()) return null;
  if (user.lastName != null && typeof user.lastName !== 'string') return null;
  if (user.username != null && typeof user.username !== 'string') return null;
  let avatar: UserProfile['avatar'] = null;
  if (user.avatar != null) {
    if (typeof user.avatar !== 'object' || Array.isArray(user.avatar)) return null;
    const image = user.avatar as Record<string, unknown>;
    if (image.mimeType !== 'image/jpeg' && image.mimeType !== 'image/png') return null;
    if (typeof image.base64 !== 'string' || image.base64.length === 0) return null;
    // Buffer.from silently tolerates invalid Base64, so validate and round-trip.
    if (image.base64.length > 4 * Math.ceil(1_048_576 / 3) ||
        !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(image.base64)) return null;
    const decoded = Buffer.from(image.base64, 'base64');
    if (decoded.length > 1_048_576 || decoded.toString('base64') !== image.base64) return null;
    avatar = { mimeType: image.mimeType, base64: image.base64 };
  }
  return {
    telegramId: user.telegramId, firstName: user.firstName,
    lastName: (user.lastName ?? null) as string | null,
    username: (user.username ?? null) as string | null, avatar,
  };
}
