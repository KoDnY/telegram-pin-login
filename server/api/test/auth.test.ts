import assert from 'node:assert/strict';
import { test } from 'node:test';
import request from 'supertest';
import { createApp } from '../src/app.js';
import { PinStore, type UserProfile } from '../src/store.js';

const secret = 'test-only-internal-key';
const user: UserProfile = {
  telegramId: 123, firstName: 'Иван', lastName: 'Иванов', username: 'ivan',
  avatar: { mimeType: 'image/png', base64: 'aW1hZ2U=' },
};
function fixture(pins = ['012345', '234567', '345678']) {
  let time = Date.UTC(2026, 0, 1);
  let pinIndex = 0;
  let tokenIndex = 0;
  const store = new PinStore({ now: () => time,
    generatePin: () => pins[pinIndex++] ?? '999999',
    generateToken: () => `session-${++tokenIndex}` });
  const app = createApp({ internalApiKey: secret, store });
  return { store, app, setTime: (value: number) => { time = value; },
    issue: (profile: unknown = user) => request(app).post('/internal/pins')
      .set('X-Internal-Key', secret).send({ user: profile }),
    auth: (key: unknown) => request(app).post('/auth').send({ key }) };
}

test('issue and exchange a leading-zero PIN, preserve complete profile, reject reuse', async () => {
  const f = fixture();
  const issued = await f.issue().expect(201);
  assert.equal(issued.body.pin, '012345');
  assert.equal(Date.parse(issued.body.expiresAt), Date.UTC(2026, 0, 1) + 900_000);
  const result = await f.auth('012345').expect(200);
  assert.deepEqual(result.body.user, user);
  assert.equal(result.body.accessToken, 'session-1');
  assert.deepEqual(f.store.getUserByToken(result.body.accessToken), user);
  const reused = await f.auth('012345').expect(401);
  assert.equal(reused.body.error.code, 'INVALID_PIN');
});

for (const offset of [-1, 0, 1]) {
  test(`expiry boundary: expiresAt ${offset < 0 ? '-' : '+'} ${Math.abs(offset)} ms`, async () => {
    const f = fixture();
    const issued = await f.issue().expect(201);
    f.setTime(Date.parse(issued.body.expiresAt) + offset);
    const result = await f.auth(issued.body.pin).expect(offset < 0 ? 200 : 401);
    if (offset >= 0) assert.equal(result.body.error.code, 'INVALID_PIN');
  });
}

test('new PIN replaces previous PIN while other users remain independent', async () => {
  const f = fixture();
  const first = await f.issue().expect(201);
  const otherUser = { ...user, telegramId: 456, firstName: 'Анна' };
  const other = await f.issue(otherUser).expect(201);
  const replacement = await f.issue().expect(201);
  assert.notEqual(replacement.body.pin, first.body.pin);
  await f.auth(first.body.pin).expect(401);
  assert.deepEqual((await f.auth(other.body.pin).expect(200)).body.user, otherUser);
  assert.deepEqual((await f.auth(replacement.body.pin).expect(200)).body.user, user);
  assert.equal((await f.auth('888888').expect(401)).body.error.code, 'INVALID_PIN');
});

test('simultaneous HTTP exchanges of one PIN produce exactly one session', async () => {
  const f = fixture();
  const issued = await f.issue().expect(201);
  const results = await Promise.all(Array.from({ length: 12 }, () => f.auth(issued.body.pin)));
  assert.equal(results.filter(result => result.status === 200).length, 1);
  assert.equal(results.filter(result => result.status === 401).length, 11);
});

test('PIN format rejects numbers, Unicode digits, wrong lengths and whitespace', async () => {
  const f = fixture();
  for (const key of [123456, null, true, {}, [], '', '12345', '1234567', '１２３４５６', '12345 ', ' 123456']) {
    const result = await f.auth(key).expect(400);
    assert.equal(result.body.error.code, 'INVALID_PIN_FORMAT');
  }
});

test('internal endpoint rejects absent/wrong secret and invalid profiles', async () => {
  const f = fixture();
  for (const key of ['', 'wrong', secret + 'x']) {
    const result = await request(f.app).post('/internal/pins').set('X-Internal-Key', key).send({ user }).expect(403);
    assert.equal(result.body.error.code, 'INTERNAL_AUTH_FAILED');
  }
  for (const profile of [null, [], {}, { ...user, telegramId: 0 }, { ...user, telegramId: 1.5 },
    { ...user, telegramId: Number.MAX_SAFE_INTEGER + 1 }, { ...user, firstName: ' ' },
    { ...user, lastName: 1 }, { ...user, username: false }, { ...user, avatar: { mimeType: 'text/plain', base64: 'eA==' } },
    { ...user, avatar: { mimeType: 'image/png', base64: '???' } }]) {
    assert.equal((await f.issue(profile).expect(400)).body.error.code, 'INVALID_PROFILE');
  }
  const minimal = { telegramId: 789, firstName: 'Пётр' };
  const pin = (await f.issue(minimal).expect(201)).body.pin;
  assert.deepEqual((await f.auth(pin).expect(200)).body.user, { ...minimal, lastName: null, username: null, avatar: null });
});

test('colliding PIN generator falls back without replacing another user code', () => {
  const store = new PinStore({ generatePin: () => '000000' });
  assert.equal(store.issuePin(user).pin, '000000');
  const second = { ...user, telegramId: 456 };
  assert.equal(store.issuePin(second).pin, '000001');
  const replacement = store.issuePin(user).pin;
  assert.equal(replacement, '000002');
  assert.equal(store.consumePin('000000'), null);
  assert.equal(store.consumePin('000001')?.user.telegramId, 456);
  assert.equal(store.consumePin(replacement)?.user.telegramId, 123);
});

test('token collision cannot consume a PIN or overwrite an existing session', () => {
  let token = 'same-token';
  const store = new PinStore({ generatePin: (() => { let n = 0; return () => String(n++).padStart(6, '0'); })(),
    generateToken: () => token });
  const firstPin = store.issuePin(user).pin;
  const first = store.consumePin(firstPin)!;
  const secondUser = { ...user, telegramId: 456 };
  const secondPin = store.issuePin(secondUser).pin;
  assert.throws(() => store.consumePin(secondPin), /unique session token/);
  assert.deepEqual(store.getUserByToken(first.accessToken), user);
  token = 'new-token';
  assert.equal(store.consumePin(secondPin)?.user.telegramId, 456);
});

test('store snapshots prevent caller mutations from changing stored profile', () => {
  const store = new PinStore();
  const input = structuredClone(user);
  const pin = store.issuePin(input).pin;
  input.firstName = 'changed';
  input.avatar!.base64 = 'changed';
  const session = store.consumePin(pin)!;
  assert.deepEqual(session.user, user);
  session.user.firstName = 'changed again';
  const snapshot = store.getUserByToken(session.accessToken)!;
  assert.deepEqual(snapshot, user);
  snapshot.avatar!.base64 = 'mutated';
  assert.deepEqual(store.getUserByToken(session.accessToken), user);
});

test('fresh process store does not accept an old PIN or token', () => {
  const old = new PinStore();
  const pin = old.issuePin(user).pin;
  const session = old.consumePin(pin)!;
  const fresh = new PinStore();
  assert.equal(fresh.consumePin(pin), null);
  assert.equal(fresh.getUserByToken(session.accessToken), null);
});
