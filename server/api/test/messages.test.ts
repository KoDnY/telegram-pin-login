import assert from 'node:assert/strict';
import { test } from 'node:test';
import request from 'supertest';
import { createApp } from '../src/app.js';
import { BotClient, BotDeliveryError, type MessageSender } from '../src/bot-client.js';
import { PinStore } from '../src/store.js';

const profile = { telegramId: 123, firstName: 'Иван', lastName: null, username: 'ivan', avatar: null };
function fixture(deliver?: Pick<BotClient, 'sendMessage'>) {
  const store = new PinStore({ generatePin: () => '123456', generateToken: () => 'test-session' });
  const pin = store.issuePin(profile).pin;
  const session = store.consumePin(pin)!;
  const calls: { sender: MessageSender; text: string }[] = [];
  const botClient = deliver ?? { async sendMessage(sender: MessageSender, text: string) {
    calls.push({ sender, text });
    return { status: 'sent' as const, telegramMessageId: 456 };
  } };
  const app = createApp({ internalApiKey: 'test-internal-secret', store, botClient });
  return { app, calls, send: (body: unknown) => request(app).post('/messages')
    .set('Authorization', `Bearer ${session.accessToken}`).send(body) };
}

test('authenticated message trims text and ignores forged sender identity', async () => {
  const f = fixture();
  const result = await f.send({ text: '  <b>Привет</b> 😀\n ', sender: { telegramId: 999 }, telegramId: 999 }).expect(200);
  assert.deepEqual(result.body, { status: 'sent' });
  assert.deepEqual(f.calls, [{ sender: { telegramId: 123, firstName: 'Иван', username: 'ivan' }, text: '<b>Привет</b> 😀' }]);
});

for (const header of ['', 'Bearer missing', 'Basic test-session', 'Bearer test-session extra']) {
  test(`reject unauthorized message (${header || 'absent header'})`, async () => {
    const f = fixture();
    const result = await request(f.app).post('/messages').set('Authorization', header).send({ text: 'hello' }).expect(401);
    assert.equal(result.body.error.code, 'UNAUTHORIZED');
    assert.equal(f.calls.length, 0);
  });
}

for (const text of [undefined, null, 5, [], {}, '', ' \n\t ', 'a'.repeat(3001), '\ud800', '\udc00']) {
  test(`reject invalid message text ${JSON.stringify(text)?.slice(0, 35)}`, async () => {
    const f = fixture();
    const result = await f.send({ text }).expect(400);
    assert.equal(result.body.error.code, 'INVALID_TEXT');
    assert.equal(f.calls.length, 0);
  });
}

test('UTF-16 length boundary accepts 3000 units and rejects 3002 units', async () => {
  const f = fixture();
  await f.send({ text: ` ${'😀'.repeat(1500)} ` }).expect(200);
  await f.send({ text: '😀'.repeat(1501) }).expect(400);
  assert.equal(f.calls.length, 1);
});

test('malformed JSON and scalar JSON do not reach delivery', async () => {
  const f = fixture();
  for (const body of ['{', '"hello"', 'null']) {
    const result = await request(f.app).post('/messages').set('Authorization', 'Bearer test-session')
      .set('Content-Type', 'application/json').send(body).expect(400);
    assert.equal(result.body.error.code, 'INVALID_JSON');
  }
  assert.equal(f.calls.length, 0);
});

for (const [error, status, code] of [
  [new BotDeliveryError(), 502, 'DELIVERY_FAILED'],
  [new BotDeliveryError(true), 504, 'DELIVERY_UNCONFIRMED'],
  [new TypeError('private network diagnostic'), 504, 'DELIVERY_UNCONFIRMED'],
] as const) {
  test(`delivery failure returns ${code} without retry or diagnostic leakage`, async () => {
    let calls = 0;
    const f = fixture({ async sendMessage() { calls++; throw error; } });
    const result = await f.send({ text: 'hello' }).expect(status);
    assert.equal(result.body.error.code, code);
    assert.equal(calls, 1);
    assert.doesNotMatch(JSON.stringify(result.body), /private|test-session|test-internal-secret/);
  });
}

test('success is returned only after bot acceptance', async () => {
  let release!: () => void;
  const accepted = new Promise<void>((resolve) => { release = resolve; });
  let entered!: () => void;
  const started = new Promise<void>((resolve) => { entered = resolve; });
  const f = fixture({ async sendMessage() {
    entered();
    await accepted;
    return { status: 'sent', telegramMessageId: 12 };
  } });
  let completed = false;
  const result = f.send({ text: 'hello' }).then((response) => { completed = true; return response; });
  await started;
  assert.equal(completed, false);
  release();
  assert.equal((await result).status, 200);
});
