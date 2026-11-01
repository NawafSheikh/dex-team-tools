'use strict';
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const config = require('./config');
const { ApiError } = require('./errors');
const { requireKey } = require('./auth');
const { createLimiter } = require('./ratelimit');
const { parseIngestBody, parseRenderBody } = require('./envelope');
const { ingest, loadDoc } = require('./ingest');
const { checkImages, words } = require('./plan-schema');

const OPENAPI = path.join(__dirname, '..', 'openapi', 'train-video.swagger.json');

/** The OpenAPI 2.0 definition with host and basePath taken from the public base URL of this deployment. */
function openapiFor(publicBase) {
  const spec = JSON.parse(fs.readFileSync(OPENAPI, 'utf8'));
  const u = new URL(publicBase);
  return { ...spec, host: u.host, basePath: u.pathname.replace(/\/$/, '') || '/', schemes: [u.protocol.replace(':', '')] };
}

const send = (res, status, obj, extraHeaders) => {
  const body = JSON.stringify(obj);
  res.writeHead(status, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body), ...extraHeaders });
  res.end(body);
};

function readJson(req, limit) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > limit) {
        reject(new ApiError(413, 'BODY_TOO_LARGE', `Request body exceeds ${limit} bytes`));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => {
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || 'null')); } catch { reject(new ApiError(400, 'BAD_JSON', 'Body is not valid JSON')); }
    });
    req.on('error', (e) => reject(new ApiError(400, 'BAD_REQUEST', e.message)));
  });
}

/** Rough film length before narration exists: about 2.5 spoken words a second plus scene leads and tails. */
const estimateSeconds = (plan) => plan.scenes.reduce((a, s) => a + words(s.narration) / 2.5 + 1.4, 1);

const ARTIFACT_TYPES = { mp4: 'video/mp4', srt: 'application/x-subrip; charset=utf-8' };

/**
 * A finished video or its captions. The unguessable 96-bit token in the link is the access check (links are
 * shared with people who have no API key), so no key is required. Supports byte ranges for video seeking.
 */
async function serveArtifact(req, res, outDir, token, ext) {
  const file = path.join(outDir, `${token}.${ext}`);
  let size;
  try {
    size = (await fs.promises.stat(file)).size;
  } catch {
    throw new ApiError(404, 'NOT_FOUND', 'No such video');
  }
  const headers = { 'content-type': ARTIFACT_TYPES[ext], 'accept-ranges': 'bytes', 'cache-control': 'private, max-age=3600' };
  const range = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
  let start = 0;
  let end = size - 1;
  let status = 200;
  if (range && (range[1] || range[2])) {
    start = range[1] ? Number(range[1]) : Math.max(0, size - Number(range[2]));
    end = range[1] && range[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
    if (start > end || start >= size) {
      res.writeHead(416, { 'content-range': `bytes */${size}` });
      return res.end();
    }
    status = 206;
    headers['content-range'] = `bytes ${start}-${end}/${size}`;
  }
  res.writeHead(status, { ...headers, 'content-length': end - start + 1 });
  if (req.method === 'HEAD') return res.end();
  await new Promise((resolve, reject) => {
    fs.createReadStream(file, { start, end }).on('error', reject).on('end', resolve).pipe(res);
  });
  return undefined;
}

/**
 * Request handler. deps: {apiKey, jobs, cfg?, log?, now?}. One JSON log line per request (method, path,
 * status, ms); never bodies, documents or keys.
 */
function createApp(deps) {
  const cfg = deps.cfg || config;
  const log = deps.log || ((o) => process.stdout.write(`${JSON.stringify(o)}\n`));
  const renderLimiter = createLimiter(cfg.rendersPerHour, 3600 * 1000, deps.now);
  const ingestLimiter = createLimiter(cfg.ingestsPerMinute, 60 * 1000, deps.now);

  const limited = (limiter, res) => {
    const r = limiter.take();
    if (r.allowed) return false;
    send(res, 429, { ok: false, code: 'RATE_LIMITED', error: `Rate limit reached, retry in ${r.retryAfterSec}s` }, { 'retry-after': String(r.retryAfterSec) });
    return true;
  };

  const base = new URL(cfg.publicBase).pathname.replace(/\/$/, '');
  const stripBase = (u) => (base && (u === base || u.startsWith(`${base}/`) || u.startsWith(`${base}?`)) ? u.slice(base.length) : u);

  async function route(req, res, url) {
    const p = url.pathname;
    if (req.method === 'GET' && p === '/health') return send(res, 200, { ok: true, service: 'train-video', ...deps.jobs.stats() });
    if (req.method === 'GET' && p === '/openapi.json') return send(res, 200, openapiFor(cfg.publicBase));
    const v = /^\/v\/([A-Za-z0-9_-]{16})\.(mp4|srt)$/.exec(p);
    if ((req.method === 'GET' || req.method === 'HEAD') && v) return serveArtifact(req, res, cfg.outDir, v[1], v[2]);
    requireKey(deps.apiKey, req.headers);
    if (req.method === 'POST' && p === '/ingest') {
      if (limited(ingestLimiter, res)) return undefined;
      const parsed = parseIngestBody(await readJson(req, cfg.ingestBodyLimitBytes), cfg.ingestFileLimitBytes);
      return send(res, 200, { ok: true, ...(await ingest(parsed, cfg)) });
    }
    if (req.method === 'POST' && p === '/render') {
      let parsed;
      let doc;
      try {
        parsed = parseRenderBody(await readJson(req, cfg.bodyLimitBytes));
        doc = await loadDoc(parsed.docId, cfg);
        checkImages(parsed.plan, doc.images.map((im) => im.id));
      } catch (e) {
        // Plan problems come back as a normal answer: Copilot orchestration ends the turn on an HTTP error,
        // but reads a 200 with errors[] and fixes the plan.
        if (e instanceof ApiError && e.code === 'PLAN_INVALID') {
          return send(res, 200, { ok: false, code: e.code, status: 'plan_invalid', error: `${e.message}. Fix every item in errors and call StartTrainingVideo again.`, ...e.extra });
        }
        throw e;
      }
      if (limited(renderLimiter, res)) return undefined;
      const view = await deps.jobs.submit({ ...parsed, doc, docDir: path.join(cfg.docsDir, parsed.docId), estimateSec: estimateSeconds(parsed.plan) });
      return send(res, 202, { ok: true, ...view });
    }
    const m = /^\/jobs\/([A-Za-z0-9_-]+)$/.exec(p);
    if (req.method === 'GET' && m) {
      const wait = Math.min(20, Math.max(0, Number(url.searchParams.get('waitSeconds') || 0) || 0));
      const view = wait ? await deps.jobs.waitFor(m[1], wait) : await deps.jobs.get(m[1]);
      return send(res, 200, { ok: true, ...view });
    }
    throw new ApiError(404, 'NOT_FOUND', `No route for ${req.method} ${p}`);
  }

  return async function handler(req, res) {
    const t0 = Date.now();
    // A reverse proxy may forward the public base path (for example /tv); strip it so routes match either way.
    let url = new URL('/', 'http://local');
    try {
      try {
        url = new URL(stripBase(req.url || '/') || '/', 'http://local');
      } catch {
        throw new ApiError(400, 'BAD_REQUEST', 'Invalid request target');
      }
      await route(req, res, url);
    } catch (e) {
      if (e instanceof ApiError) {
        send(res, e.status, { ok: false, code: e.code, error: e.message, ...e.extra });
      } else {
        log({ level: 'error', path: url.pathname, error: e.message });
        send(res, 500, { ok: false, code: 'INTERNAL', error: 'Internal error' });
      }
    }
    const logged = url.pathname.startsWith('/v/') ? '/v/<token>' : url.pathname; // the token is the access check
    log({ level: 'info', method: req.method, path: logged, status: res.statusCode, ms: Date.now() - t0 });
  };
}

const createServer = (deps) => http.createServer(createApp(deps));

module.exports = { createApp, createServer, estimateSeconds };
