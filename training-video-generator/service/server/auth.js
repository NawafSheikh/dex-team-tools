'use strict';
const crypto = require('node:crypto');
const fs = require('node:fs');
const { ApiError } = require('./errors');

function loadApiKey(file) {
  let key;
  try {
    key = fs.readFileSync(file, 'utf8').trim();
  } catch (e) {
    throw new Error(`API key file unreadable (${file}): ${e.code || e.message}`);
  }
  if (key.length < 24) throw new Error(`API key in ${file} is missing or too short`);
  return key;
}

/** Constant time comparison via hashing, so length differences leak nothing. */
function keyMatches(expected, provided) {
  if (typeof provided !== 'string') return false;
  const a = crypto.createHash('sha256').update(expected).digest();
  const b = crypto.createHash('sha256').update(provided).digest();
  return crypto.timingSafeEqual(a, b);
}

function requireKey(expected, headers) {
  if (!keyMatches(expected, headers['x-api-key'])) throw new ApiError(401, 'UNAUTHORIZED', 'Missing or invalid x-api-key header');
}

module.exports = { loadApiKey, keyMatches, requireKey };
