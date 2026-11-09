import { randomBytes, randomInt } from 'node:crypto';

export interface UserProfile {
  telegramId: number;
  firstName: string;
  lastName: string | null;
  username: string | null;
  avatar: { mimeType: 'image/jpeg' | 'image/png'; base64: string } | null;
}

export interface PinStoreOptions {
  now?: () => number;
  generatePin?: () => string;
  generateToken?: () => string;
}

interface PinRecord {
  telegramId: number;
  expiresAt: number;
}

export class PinCapacityError extends Error {
  readonly code = 'PIN_CAPACITY_EXCEEDED';

  constructor() {
    super('No free PIN is available');
    this.name = 'PinCapacityError';
  }
}

const PIN_TTL_MS = 15 * 60 * 1000;
const PIN_SPACE = 1_000_000;

/** Single-process memory store. No method yields between checking and consuming a PIN. */
export class PinStore {
  private readonly profiles = new Map<number, UserProfile>();
  private readonly pins = new Map<string, PinRecord>();
  private readonly userPins = new Map<number, string>();
  private readonly sessions = new Map<string, number>();
  private readonly sessionUsers = new Set<number>();
  private readonly now: () => number;
  private readonly generatePin: () => string;
  private readonly generateToken: () => string;

  constructor(options: PinStoreOptions = {}) {
    this.now = options.now ?? Date.now;
    this.generatePin = options.generatePin ?? (() => String(randomInt(PIN_SPACE)).padStart(6, '0'));
    this.generateToken = options.generateToken ?? (() => randomBytes(32).toString('hex'));
  }

  issuePin(user: UserProfile): { pin: string; expiresAt: string } {
    const now = this.now();
    this.cleanup(now);
    const previous = this.userPins.get(user.telegramId);
    // Keep the old code reserved until a different code is successfully allocated.
    const pin = this.allocatePin(previous);
    const expiresAt = now + PIN_TTL_MS;
    const snapshot = structuredClone(user);
    if (previous !== undefined) this.pins.delete(previous);
    this.profiles.set(user.telegramId, snapshot);
    this.pins.set(pin, { telegramId: user.telegramId, expiresAt });
    this.userPins.set(user.telegramId, pin);
    return { pin, expiresAt: new Date(expiresAt).toISOString() };
  }

  consumePin(pin: string): { user: UserProfile; accessToken: string } | null {
    this.cleanup();
    const record = this.pins.get(pin);
    if (!record) return null;
    const user = this.profiles.get(record.telegramId);
    if (!user) return null;
    // Token allocation failures leave the PIN usable; successful consumption is atomic.
    const accessToken = this.allocateToken();
    const snapshot = structuredClone(user);
    this.pins.delete(pin);
    this.userPins.delete(record.telegramId);
    this.sessions.set(accessToken, record.telegramId);
    this.sessionUsers.add(record.telegramId);
    return { user: snapshot, accessToken };
  }

  getUserByToken(token: string): UserProfile | null {
    const telegramId = this.sessions.get(token);
    if (telegramId === undefined) return null;
    const user = this.profiles.get(telegramId);
    return user ? structuredClone(user) : null;
  }

  /** Also called by the server's periodic timer; expiry is checked lazily on auth. */
  cleanup(now = this.now()): void {
    for (const [pin, record] of this.pins) {
      if (record.expiresAt > now) continue;
      this.pins.delete(pin);
      if (this.userPins.get(record.telegramId) === pin) {
        this.userPins.delete(record.telegramId);
        if (!this.sessionUsers.has(record.telegramId)) this.profiles.delete(record.telegramId);
      }
    }
  }

  private allocatePin(previous: string | undefined): string {
    if (this.pins.size >= PIN_SPACE) throw new PinCapacityError();
    // Try randomness first, then a bounded scan so collisions never cause an infinite loop.
    for (let attempt = 0; attempt < 32; attempt++) {
      const candidate = this.generatePin();
      if (!/^[0-9]{6}$/.test(candidate)) throw new Error('PIN generator must return six digits');
      if (candidate !== previous && !this.pins.has(candidate)) return candidate;
    }
    for (let value = 0; value < PIN_SPACE; value++) {
      const candidate = String(value).padStart(6, '0');
      if (candidate !== previous && !this.pins.has(candidate)) return candidate;
    }
    throw new PinCapacityError();
  }

  private allocateToken(): string {
    for (let attempt = 0; attempt < 32; attempt++) {
      const token = this.generateToken();
      if (!token) throw new Error('Token generator must return a nonempty token');
      if (!this.sessions.has(token)) return token;
    }
    throw new Error('Unable to allocate a unique session token');
  }
}
