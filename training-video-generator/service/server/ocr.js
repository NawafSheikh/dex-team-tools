'use strict';
const path = require('node:path');
const { run } = require('./proc');

const BUTTON_PASS = path.join(__dirname, '..', 'scripts', 'button_text.py');
const ONE_THREAD = { env: { ...process.env, OMP_THREAD_LIMIT: '1' } };

function parseTsv(tsv) {
  const words = [];
  for (const line of tsv.split('\n').slice(1)) {
    const c = line.split('\t');
    if (c.length < 12) continue;
    const t = c[11].trim();
    if (!t || Number(c[10]) < 55) continue;
    words.push({ text: t, x: Number(c[6]), y: Number(c[7]), w: Number(c[8]), h: Number(c[9]), line: `p${c[2]}.${c[3]}.${c[4]}` });
  }
  return words;
}

/**
 * Words visible in a screenshot with their pixel boxes, used to pin highlights to real UI text.
 * Two passes: tesseract on the plain image, and scripts/button_text.py for light text on coloured buttons
 * (tesseract misses those). Returns [] when tesseract is not installed.
 */
async function ocrWords(file) {
  let plain;
  try {
    plain = await run('tesseract', [file, 'stdout', '--psm', '11', 'tsv'], ONE_THREAD);
  } catch {
    return [];
  }
  const words = parseTsv(plain.stdout);
  try {
    const btn = await run('python3', [BUTTON_PASS, file], ONE_THREAD);
    for (const line of btn.stdout.split('\n')) if (line.trim()) words.push(JSON.parse(line));
  } catch {
    // the button pass is a bonus; plain words still work
  }
  return words;
}

const norm = (s) => s.toLowerCase().replace(/[^a-z0-9À-ɏ]+/g, '');

/** Similarity 0..1 from the Levenshtein distance. */
function similarity(a, b) {
  if (a === b) return 1;
  const m = a.length;
  const n = b.length;
  if (!m || !n) return 0;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i += 1) {
    const cur = [i];
    for (let j = 1; j <= n; j += 1) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    prev = cur;
  }
  return 1 - prev[n] / Math.max(m, n);
}

const FUZZY_MIN = 0.75;

const unionBox = (run, pad) => {
  const x0 = Math.min(...run.map((w) => w.x));
  const y0 = Math.min(...run.map((w) => w.y));
  const x1 = Math.max(...run.map((w) => w.x + w.w));
  const y1 = Math.max(...run.map((w) => w.y + w.h));
  return { x: x0 - pad, y: y0 - pad, w: x1 - x0 + 2 * pad, h: y1 - y0 + 2 * pad, inner: x1 - x0 };
};

/**
 * OCR often drops the last word of a button label. When the leading words match exactly on one line and cover
 * at least 55 % of the phrase's letters, extend the box to the right by the missing letters' share.
 */
function prefixMatch(words, target, pad) {
  const total = target.join('').length;
  for (let k = target.length - 1; k >= 2; k -= 1) {
    const have = target.slice(0, k).join('').length;
    if (have / total < 0.55) break;
    for (let i = 0; i + k <= words.length; i += 1) {
      const run = words.slice(i, i + k);
      if (run.some((w, j) => w.line !== run[0].line || norm(w.text) !== target[j])) continue;
      const b = unionBox(run, pad);
      return { x: b.x, y: b.y, w: Math.round(b.inner * (total / have) * 1.08 + 2 * pad), h: b.h, score: 0 };
    }
  }
  return null;
}

/**
 * Find a phrase among OCR words: a run of consecutive words on one line whose joined text matches the phrase.
 * Exact matches win; otherwise the closest run scoring at least FUZZY_MIN; then a leading-words match.
 * Ties go to the topmost match. Returns the padded union box in image pixels, or null.
 */
function findPhrase(words, phrase, pad = 10) {
  const target = phrase.split(/\s+/).map(norm).filter(Boolean);
  if (!target.length) return null;
  const goal = target.join('');
  let best = null;
  for (let i = 0; i + target.length <= words.length; i += 1) {
    const run = words.slice(i, i + target.length);
    if (run.some((w) => w.line !== run[0].line)) continue;
    let score = similarity(run.map((w) => norm(w.text)).join(''), goal);
    if (target.length === 1 && norm(run[0].text).startsWith(goal)) score = Math.max(score, 0.99);
    // Same letter case as the phrase ranks above a case-insensitive hit: "Receipt" is the field label,
    // "receipt" is a word in a sentence.
    const raw = run.map((w) => w.text.replace(/[^\p{L}\p{N}]+/gu, '')).join(' ');
    if (raw === phrase.replace(/[^\p{L}\p{N}\s]+/gu, '').trim().split(/\s+/).join(' ')) score += 0.005;
    if (score < FUZZY_MIN) continue;
    const b = unionBox(run, pad);
    const box = { x: b.x, y: b.y, w: b.w, h: b.h, score };
    if (!best || score > best.score + 1e-9 || (Math.abs(score - best.score) < 1e-9 && box.y < best.y)) best = box;
  }
  if (!best && target.length >= 3) best = prefixMatch(words, target, pad);
  if (!best) return null;
  const { score, ...box } = best;
  return box;
}

module.exports = { ocrWords, findPhrase, similarity };
