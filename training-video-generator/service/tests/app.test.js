'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createServer } = require('../server/app');

const KEY = 'k'.repeat(32);

async function start(overrides = {}) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'tvapp-'));
  const cfg = {
    docsDir: path.join(dir, 'docs'), maxImages: 30, maxDocChars: 40000, bodyLimitBytes: 1e6, ingestBodyLimitBytes: 5e6,
    ingestFileLimitBytes: 4e6, rendersPerHour: 2, ingestsPerMinute: 5, publicBase: 'https://train.example.com/tv', ...overrides,
  };
  const submitted = [];
  const jobs = {
    stats: () => ({ active: null, queued: 0 }),
    submit: async (input) => { submitted.push(input); return { jobId: 'job12345', status: 'queued', estimatedReadySec: 200 }; },
    get: async (id) => ({ jobId: id, status: 'done', videoUrl: 'https://x/v/a.mp4' }),
    waitFor: async (id) => ({ jobId: id, status: 'done', waited: true }),
  };
  const server = createServer({ apiKey: KEY, jobs, cfg, log: () => {} });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const call = (method, p, body, key = KEY) => fetch(base + p, { method, headers: { 'content-type': 'application/json', ...(key ? { 'x-api-key': key } : {}) }, body: body && JSON.stringify(body) })
    .then(async (r) => ({ status: r.status, json: await r.json() }));
  return { server, call, submitted };
}

const TEXT = 'How to submit an expense\nStep 1. Open the app and select New expense.\nStep 2. Add the receipt.';
const PLAN = {
  title: 'Submit an expense',
  scenes: [
    { type: 'title', heading: 'Submit an expense', narration: 'This is how you submit an expense.' },
    { type: 'step', heading: 'Open the app', narration: 'Open the app and select New expense.' },
    { type: 'recap', heading: 'Done', bullets: ['Opened the app', 'Selected New expense'], narration: 'That is all.' },
  ],
};

test('api: health is open, everything else needs the key', async () => {
  const { server, call } = await start();
  assert.equal((await call('GET', '/tv/health', null, null)).json.service, 'train-video');
  assert.equal((await call('POST', '/ingest', { text: TEXT }, 'wrong')).status, 401);
  server.close();
});

test('api: ingest text, render, poll with wait', async () => {
  const { server, call, submitted } = await start();
  const ing = await call('POST', '/tv/ingest', { text: TEXT });
  assert.equal(ing.status, 200);
  assert.match(ing.json.docId, /^[A-Za-z0-9_-]{10,}$/);
  const r = await call('POST', '/tv/render', { docId: ing.json.docId, plan: JSON.stringify(PLAN), brandName: 'Brightwater' });
  assert.equal(r.status, 202);
  assert.equal(submitted[0].brand.name, 'Brightwater');
  assert.ok(submitted[0].estimateSec > 3);
  assert.equal((await call('GET', '/tv/jobs/job12345?waitSeconds=30')).json.waited, true);
  assert.equal((await call('GET', '/tv/jobs/job12345')).json.waited, undefined);
  server.close();
});

test('api: plan errors come back as a list; unknown doc is 404; render is rate limited', async () => {
  const { server, call } = await start();
  const ing = await call('POST', '/ingest', { text: TEXT });
  const bad = await call('POST', '/render', { docId: ing.json.docId, plan: { ...PLAN, scenes: PLAN.scenes.slice(1) } });
  assert.equal(bad.status, 200);
  assert.equal(bad.json.ok, false);
  assert.equal(bad.json.code, 'PLAN_INVALID');
  assert.ok(bad.json.errors.length >= 1);
  assert.equal((await call('POST', '/render', { docId: 'nosuchdoc123', plan: PLAN })).status, 404);
  assert.equal((await call('POST', '/render', { docId: ing.json.docId, plan: PLAN })).status, 202);
  assert.equal((await call('POST', '/render', { docId: ing.json.docId, plan: PLAN })).status, 202);
  const third = await call('POST', '/render', { docId: ing.json.docId, plan: PLAN });
  assert.equal(third.status, 429);
  server.close();
});

test('openapi: every route the connector uses exists with an operationId', async () => {
  const spec = JSON.parse(await fs.readFile(path.join(__dirname, '..', 'openapi', 'train-video.swagger.json'), 'utf8'));
  const ops = Object.values(spec.paths).flatMap((p) => Object.values(p).map((o) => o.operationId));
  assert.deepEqual(ops.sort(), ['GetTrainingVideo', 'IngestDocument', 'StartTrainingVideo']);
  assert.equal(spec.basePath, '/tv');
});

test('openapi.json is served with the deployment host and base path', async () => {
  const { server, call } = await start();
  const spec = (await call('GET', '/openapi.json', null, null)).json;
  assert.equal(spec.host, 'train.example.com');
  assert.equal(spec.basePath, '/tv');
  assert.deepEqual(spec.schemes, ['https']);
  server.close();
});

test('finished videos and captions download without a key, with byte ranges', async () => {
  const outDir = await fs.mkdtemp(path.join(os.tmpdir(), 'tvout-'));
  await fs.writeFile(path.join(outDir, 'AbCdEfGhIjKlMnOp.mp4'), Buffer.from('0123456789'));
  await fs.writeFile(path.join(outDir, 'AbCdEfGhIjKlMnOp.srt'), '1\n00:00:00,000 --> 00:00:01,000\nHi\n');
  const { server } = await start({ outDir });
  const base = `http://127.0.0.1:${server.address().port}`;
  const full = await fetch(`${base}/tv/v/AbCdEfGhIjKlMnOp.mp4`);
  assert.equal(full.status, 200);
  assert.equal(full.headers.get('content-type'), 'video/mp4');
  assert.equal(await full.text(), '0123456789');
  const part = await fetch(`${base}/v/AbCdEfGhIjKlMnOp.mp4`, { headers: { range: 'bytes=2-4' } });
  assert.equal(part.status, 206);
  assert.equal(await part.text(), '234');
  assert.equal((await fetch(`${base}/v/AbCdEfGhIjKlMnOp.srt`)).status, 200);
  assert.equal((await fetch(`${base}/v/ZZZZZZZZZZZZZZZZ.mp4`)).status, 404);
  assert.equal((await fetch(`${base}/v/..%2F..%2Fsecret.mp4`)).status, 401);
  server.close();
});

test('a malformed request target gets 400 and the server keeps running', async () => {
  const net = require('node:net');
  const { server, call } = await start();
  const reply = await new Promise((resolve) => {
    const sock = net.connect(server.address().port, '127.0.0.1', () => sock.write('GET //[ HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n'));
    let data = '';
    sock.on('data', (d) => { data += d; });
    sock.on('end', () => resolve(data));
  });
  assert.match(reply, /^HTTP\/1\.1 400/);
  assert.equal((await call('GET', '/health', null, null)).status, 200);
  server.close();
});
