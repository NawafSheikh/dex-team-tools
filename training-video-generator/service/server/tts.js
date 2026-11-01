'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { generateAudio } = require('./gemini');

// Gemini 3.8 TTS reads the text verbatim; delivery direction goes in speechMetadata.style, never in the text.
const STYLE = 'Narrator of a short internal training video: clear, warm, confident and friendly, like a helpful '
  + 'colleague; normal conversational volume, steady medium pace, short natural pauses between sentences.';

/** PCM s16le mono 24 kHz to a WAV file. */
function wav(pcm, rate = 24000) {
  const h = Buffer.alloc(44);
  h.write('RIFF', 0); h.writeUInt32LE(36 + pcm.length, 4); h.write('WAVE', 8); h.write('fmt ', 12);
  h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22); h.writeUInt32LE(rate, 24);
  h.writeUInt32LE(rate * 2, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34); h.write('data', 36);
  h.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([h, pcm]);
}

/**
 * The PCM samples from a TTS response. Gemini 3.8 returns a whole WAV (RIFF) whose data chunk is followed by a
 * C2PA content-credentials chunk; older models return raw L16. Only the data chunk is audio: anything else played
 * as samples is noise. Returns {pcm, rate}.
 */
function pcmFrom(buf, mime = '') {
  if (buf.length >= 12 && buf.toString('ascii', 0, 4) === 'RIFF' && buf.toString('ascii', 8, 12) === 'WAVE') {
    let rate = 24000;
    let i = 12;
    while (i + 8 <= buf.length) {
      const id = buf.toString('ascii', i, i + 4);
      const n = buf.readUInt32LE(i + 4);
      if (id === 'fmt ') {
        const channels = buf.readUInt16LE(i + 10);
        const bits = buf.readUInt16LE(i + 22);
        rate = buf.readUInt32LE(i + 12);
        if (channels !== 1 || bits !== 16) throw new Error(`unsupported TTS wav: ${channels} ch, ${bits} bit`);
      }
      if (id === 'data') return { pcm: buf.subarray(i + 8, Math.min(buf.length, i + 8 + n)), rate };
      i += 8 + n + (n & 1);
    }
    throw new Error('TTS wav has no data chunk');
  }
  const m = /rate=(\d+)/.exec(mime);
  return { pcm: buf, rate: m ? Number(m[1]) : 24000 };
}

/** Short linear fades on both ends so no clip starts or stops with a click. */
function fadeEdges(pcm, rate, ms = 30) {
  const out = Buffer.from(pcm);
  const n = out.length >> 1;
  const f = Math.min(Math.round((rate * ms) / 1000), n >> 1);
  for (let k = 0; k < f; k += 1) {
    const g = k / f;
    out.writeInt16LE(Math.round(out.readInt16LE(k * 2) * g), k * 2);
    out.writeInt16LE(Math.round(out.readInt16LE((n - 1 - k) * 2) * g), (n - 1 - k) * 2);
  }
  return out;
}

/** Trim leading and trailing near-silence (keeps 60 ms), returns the trimmed PCM. */
function trimPcm(pcm, rate = 24000, thresh = 500) {
  const n = pcm.length >> 1;
  let a = 0;
  let b = n - 1;
  while (a < n && Math.abs(pcm.readInt16LE(a * 2)) < thresh) a += 1;
  while (b > a && Math.abs(pcm.readInt16LE(b * 2)) < thresh) b -= 1;
  const keep = Math.round(rate * 0.06);
  a = Math.max(0, a - keep);
  b = Math.min(n - 1, b + keep);
  return pcm.subarray(a * 2, (b + 1) * 2);
}

/**
 * Speech pauses in a clip (runs of quiet >= minGap s), used to time sentence captions to the real audio.
 * Returns [{start, end}] in seconds.
 */
function pauses(pcm, rate = 24000, minGap = 0.18) {
  const win = Math.round(rate * 0.02);
  const n = pcm.length >> 1;
  const quiet = [];
  for (let i = 0; i + win <= n; i += win) {
    let s = 0;
    for (let k = i; k < i + win; k += 1) s += Math.abs(pcm.readInt16LE(k * 2));
    quiet.push(s / win < 350);
  }
  const out = [];
  let runStart = -1;
  quiet.forEach((q, i) => {
    if (q && runStart < 0) runStart = i;
    if ((!q || i === quiet.length - 1) && runStart >= 0) {
      const len = (i - runStart) * 0.02;
      if (len >= minGap && runStart > 0) out.push({ start: runStart * 0.02, end: i * 0.02 });
      runStart = -1;
    }
  });
  return out;
}

async function speakScene({ text, voice, outFile, cfg, log, model }) {
  const body = {
    contents: [{ parts: [{ text, speechMetadata: { style: STYLE } }] }],
    generationConfig: { responseModalities: ['AUDIO'], speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: voice } } } },
  };
  const audio = await generateAudio({ key: cfg.geminiKey(), model, body, log });
  const { pcm: raw, rate } = pcmFrom(audio.data, audio.mime);
  const pcm = fadeEdges(trimPcm(raw, rate), rate);
  await fs.mkdir(path.dirname(outFile), { recursive: true });
  await fs.writeFile(outFile, wav(pcm, rate));
  return { file: outFile, seconds: (pcm.length >> 1) / rate, pauses: pauses(pcm, rate) };
}

async function narrateWith({ scenes, voice, dir, cfg, log, concurrency, model }) {
  const results = new Array(scenes.length);
  const modelDir = path.join(dir, model.replace(/[^A-Za-z0-9._-]/g, '_')); // each model's files apart
  let next = 0;
  let failed = null;
  async function worker() {
    while (next < scenes.length && !failed) {
      const i = next;
      next += 1;
      try {
        results[i] = await speakScene({ text: scenes[i].narration, voice, outFile: path.join(modelDir, `vo_${i}.wav`), cfg, log, model });
      } catch (e) {
        failed = failed || e;
      }
    }
  }
  // Workers never reject: every in-flight request settles before this returns, so nothing writes late.
  await Promise.all(Array.from({ length: Math.min(concurrency, scenes.length) }, worker));
  if (failed) throw failed;
  return results;
}

/**
 * Narrate every scene, a few at a time, with ONE model for the whole video: if any scene fails on the main model,
 * every scene is narrated again on the fallback model, so the narrator never changes voice mid-video.
 * Returns per-scene {file, seconds, pauses} plus .model on the array.
 */
async function narrate({ scenes, voice, dir, cfg, log, concurrency = 3 }) {
  let results;
  let model = cfg.ttsModel;
  try {
    results = await narrateWith({ scenes, voice, dir, cfg, log, concurrency, model });
  } catch (e) {
    if (log) log({ level: 'warn', msg: 'tts main model failed, narrating the whole video on the fallback', error: e.message.slice(0, 200) });
    model = cfg.ttsFallbackModel;
    results = await narrateWith({ scenes, voice, dir, cfg, log, concurrency, model });
  }
  results.model = model;
  return results;
}

module.exports = { narrate, wav, trimPcm, pauses, pcmFrom, fadeEdges };
