import type { UserProfile } from './store.js';

export type MessageSender = Pick<UserProfile, 'telegramId' | 'firstName' | 'username'>;
export interface BotDeliveryResult {
  status: 'sent';
  telegramMessageId: number;
}
export interface BotClientOptions {
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

/** A failure with a known rejection, or an unknown outcome that must not be retried. */
export class BotDeliveryError extends Error {
  readonly code: 'DELIVERY_FAILED' | 'DELIVERY_UNCONFIRMED';
  readonly status: 502 | 504;

  constructor(unconfirmed = false) {
    super(unconfirmed ? 'Delivery could not be confirmed' : 'Message delivery failed');
    this.name = 'BotDeliveryError';
    this.code = unconfirmed ? 'DELIVERY_UNCONFIRMED' : 'DELIVERY_FAILED';
    this.status = unconfirmed ? 504 : 502;
  }
}

/** One request only: a transport error may happen after Telegram accepted the message. */
export class BotClient {
  private readonly url: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

  constructor(baseUrl: string, private readonly internalKey: string, options: BotClientOptions = {}) {
    this.url = new URL('/internal/messages', baseUrl).toString();
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.timeoutMs = options.timeoutMs ?? 15_000;
    if (!Number.isFinite(this.timeoutMs) || this.timeoutMs <= 0) {
      throw new Error('Bot timeout must be positive');
    }
  }

  async sendMessage(sender: MessageSender, text: string): Promise<BotDeliveryResult> {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => {
        controller.abort();
        reject(new BotDeliveryError(true));
      }, this.timeoutMs);
    });
    const request = async (): Promise<BotDeliveryResult> => {
      const response = await this.fetchImpl(this.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Internal-Key': this.internalKey },
        body: JSON.stringify({
          sender: { telegramId: sender.telegramId, firstName: sender.firstName, username: sender.username },
          text,
        }),
        signal: controller.signal,
        redirect: 'error',
      });
      if (response.status !== 200) {
        // The bot explicitly rejected delivery; 504 is its ambiguous timeout outcome.
        void response.body?.cancel().catch(() => undefined);
        throw new BotDeliveryError(response.status === 504);
      }
      const body: unknown = await response.json();
      if (typeof body !== 'object' || body === null ||
          !('status' in body) || body.status !== 'sent' ||
          !('telegramMessageId' in body) || typeof body.telegramMessageId !== 'number' ||
          !Number.isSafeInteger(body.telegramMessageId) || body.telegramMessageId <= 0) {
        throw new BotDeliveryError(true);
      }
      return { status: 'sent', telegramMessageId: body.telegramMessageId };
    };
    try {
      return await Promise.race([request(), timeout]);
    } catch (error) {
      if (error instanceof BotDeliveryError) throw error;
      // Broken connections, invalid JSON and incomplete bodies cannot prove non-delivery.
      throw new BotDeliveryError(true);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }
}
