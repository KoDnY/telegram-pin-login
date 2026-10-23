import { fileURLToPath } from 'node:url';
import { config } from 'dotenv';
import { createApp } from './app.js';
import { PinStore } from './store.js';
import { BotClient } from './bot-client.js';

// Both src/server.ts and dist/server.js resolve to the same api/.env.
config({ path: fileURLToPath(new URL('../.env', import.meta.url)), quiet: true });

const portText = process.env.PORT ?? '3000';
const port = Number(portText);
if (!/^\d+$/.test(portText) || !Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error('PORT must be an integer between 1 and 65535.');
}
const internalApiKey = process.env.INTERNAL_API_KEY;
if (!internalApiKey) throw new Error('INTERNAL_API_KEY is required in api/.env.');
const store = new PinStore();
const cleanupTimer = setInterval(() => store.cleanup(), 60_000);
cleanupTimer.unref();
const botClient = new BotClient(process.env.BOT_INTERNAL_URL ?? 'http://127.0.0.1:8080', internalApiKey);
const app = createApp({ internalApiKey, store, botClient });
const server = app.listen(port, '127.0.0.1', () => {
  console.info(`API listening at http://127.0.0.1:${port}`);
});
server.on('error', () => {
  console.error('API could not start. Check that the configured port is available.');
  process.exitCode = 1;
});
server.on('close', () => clearInterval(cleanupTimer));
