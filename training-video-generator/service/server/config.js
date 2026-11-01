'use strict';
const fs = require('node:fs');
const path = require('node:path');

const STATE = process.env.TV_STATE_DIR || path.join(__dirname, '..', 'state');
const DATA = process.env.TV_DATA_DIR || path.join(__dirname, '..', 'data');
const keyFile = process.env.TV_GEMINI_KEY_FILE || path.join(STATE, 'gemini-key');
let geminiKey = null;

module.exports = Object.freeze({
  port: Number(process.env.TV_PORT || 8913),
  host: process.env.TV_HOST || '127.0.0.1',
  apiKeyFile: process.env.TV_API_KEY_FILE || path.join(STATE, 'api-key'),
  publicBase: process.env.TV_PUBLIC_BASE || 'http://127.0.0.1:8913',
  docsDir: path.join(DATA, 'docs'),
  jobsDir: path.join(DATA, 'jobs'),
  workDir: path.join(DATA, 'work'),
  outDir: path.join(DATA, 'out'),
  fallbackBed: process.env.TV_FALLBACK_BED || '', // optional music file used when Lyria fails; empty = silent bed
  hyperframesBin: process.env.TV_HYPERFRAMES_BIN || path.join(__dirname, '..', 'node_modules', '.bin', 'hyperframes'),
  renderQuality: process.env.TV_RENDER_QUALITY || 'standard',
  renderWorkers: Number(process.env.TV_RENDER_WORKERS || 2),
  initialRenderSecPerVideoMin: Number(process.env.TV_INITIAL_SPEED || 300),
  deskLockFile: process.env.TV_DESK_LOCK || '',
  deskOwnerFile: process.env.TV_DESK_OWNER || '',
  deskOwnName: process.env.TV_DESK_NAME || 'train-video',
  keepWork: process.env.TV_KEEP_WORK === '1',
  ttsModel: process.env.TV_TTS_MODEL || 'gemini-3.8-flash-tts',
  ttsFallbackModel: 'gemini-3.8-flash-lite-tts',
  musicModel: process.env.TV_MUSIC_MODEL || 'lyria-3.5',
  geminiKey() {
    if (!geminiKey) {
      geminiKey = (process.env.TV_GEMINI_KEY || fs.readFileSync(keyFile, 'utf8')).trim();
      if (geminiKey.length < 20) throw new Error('Gemini key missing or too short');
    }
    return geminiKey;
  },
  bodyLimitBytes: 2 * 1024 * 1024,
  ingestBodyLimitBytes: 30 * 1024 * 1024,
  ingestFileLimitBytes: 20 * 1024 * 1024,
  maxImages: 30,
  maxDocChars: 40000,
  maxQueue: 4,
  rendersPerHour: Number(process.env.TV_RENDERS_PER_HOUR || 12),
  ingestsPerMinute: Number(process.env.TV_INGESTS_PER_MINUTE || 20),
  docTtlHours: 48,
  videoTtlDays: Number(process.env.TV_VIDEO_TTL_DAYS || 30),
});
