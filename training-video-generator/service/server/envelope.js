'use strict';
const { ApiError } = require('./errors');
const { parsePlan, parseBrand, VOICES } = require('./plan-schema');

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const FILE_NAME = /^[^\\/\u0000-\u001f]{1,200}\.(docx|pdf|txt|md)$/i;
const IMG_NAME = /^[^\\/\u0000-\u001f]{1,200}\.(png|jpe?g)$/i;
const B64 = /^[A-Za-z0-9+/\r\n]*={0,2}$/;

function fail(issues) {
  return new ApiError(400, 'BAD_REQUEST', `Request body is invalid: ${issues.join('; ')}`, { errors: issues.map((m) => ({ path: '$', message: m })) });
}

function only(body, allowed, issues) {
  const extra = Object.keys(body).filter((k) => !allowed.includes(k));
  if (extra.length) issues.push(`unknown field(s): ${extra.join(', ')}`);
}

/** Copilot's Power Fx JSON(file, IncludeBinaryData) gives a quoted data URI; keep only the base64 part. */
const stripDataUri = (v) => (typeof v === 'string' ? v.trim().replace(/^"/, '').replace(/"$/, '').replace(/^data:[^,]*;base64,/, '') : v);

/** POST /ingest: a file as base64, or pasted text; optional extra screenshots. */
function parseIngestBody(raw, maxFileBytes) {
  if (!isObj(raw)) throw fail(['body must be a JSON object']);
  const body = { ...raw, fileBase64: stripDataUri(raw.fileBase64) };
  const issues = [];
  only(body, ['fileName', 'fileBase64', 'text', 'screenshots'], issues);
  const hasFile = body.fileBase64 !== undefined && body.fileBase64 !== '';
  // The attached file wins over text the model may also have filled in.
  const hasText = !hasFile && body.text !== undefined && body.text !== '';
  if (!hasFile && !hasText) issues.push('send either "fileBase64" with "fileName", or "text"');
  if (hasFile) {
    if (!(typeof body.fileName === 'string' && FILE_NAME.test(body.fileName))) issues.push('"fileName" must end in .docx, .pdf, .txt or .md');
    if (!(typeof body.fileBase64 === 'string' && B64.test(body.fileBase64))) issues.push('"fileBase64" must be the file bytes as base64');
  }
  if (hasText && !(typeof body.text === 'string' && body.text.trim().length >= 40)) issues.push('"text" must be the procedure text (at least 40 characters)');
  const shots = body.screenshots === undefined ? [] : body.screenshots;
  if (!Array.isArray(shots) || shots.length > 20) issues.push('"screenshots" must be a list of at most 20 images');
  else {
    shots.forEach((s, i) => {
      if (!isObj(s) || !IMG_NAME.test(s.name || '') || typeof s.base64 !== 'string' || !B64.test(s.base64)) issues.push(`screenshots[${i}] needs "name" (.png or .jpg) and "base64"`);
    });
  }
  if (issues.length) throw fail(issues);
  const extraImages = shots.map((s) => ({ ext: s.name.toLowerCase().endsWith('.png') ? '.png' : '.jpg', data: Buffer.from(s.base64, 'base64') }));
  const total = extraImages.reduce((a, s) => a + s.data.length, 0);
  if (hasText) return { text: body.text, extraImages };
  const buffer = Buffer.from(body.fileBase64, 'base64');
  if (buffer.length === 0) throw fail(['"fileBase64" decoded to an empty file']);
  if (buffer.length + total > maxFileBytes) throw new ApiError(413, 'FILE_TOO_LARGE', `Upload is ${buffer.length + total} bytes; the limit is ${maxFileBytes}`);
  return { fileName: body.fileName, buffer, extraImages };
}

/** POST /render: docId, the plan (object or JSON string), brand and voice. */
function parseRenderBody(body) {
  if (!isObj(body)) throw fail(['body must be a JSON object']);
  const issues = [];
  only(body, ['docId', 'plan', 'brand', 'brandName', 'brandColor', 'voice'], issues);
  if (typeof body.docId !== 'string') issues.push('"docId" is required (from IngestDocument)');
  if (body.plan === undefined) issues.push('"plan" is required');
  if (body.voice !== undefined && body.voice !== '' && !VOICES.includes(body.voice)) issues.push(`"voice" must be one of ${VOICES.join(', ')}`);
  if (issues.length) throw fail(issues);
  const plan = parsePlan(body.plan);
  // Flat brandName and brandColor are easier for a Copilot tool to fill than a nested object.
  const brandRaw = isObj(body.brand) ? body.brand : {};
  const name = brandRaw.name || body.brandName;
  const primary = brandRaw.primary || body.brandColor;
  const brand = parseBrand({ ...(name ? { name } : {}), ...(primary ? { primary } : {}) });
  return { docId: body.docId, plan, brand, voice: body.voice || 'Sulafat' };
}

module.exports = { parseIngestBody, parseRenderBody };
