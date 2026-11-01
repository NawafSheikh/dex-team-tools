'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { generateAudio } = require('./gemini');
const { run } = require('./proc');

const prompt = (seconds) => `Instrumental only, no vocals. ${Math.ceil(seconds)} seconds. Calm, modern, optimistic corporate `
  + 'learning music for an internal training video: soft felt piano, light plucked guitar, warm pads, a gentle '
  + 'brushed beat, 96 BPM, major key, understated and steady so a narrator sits clearly on top, no big drops or '
  + 'swells, a clean resolved ending.';

/**
 * An original Lyria bed for this video. If the call fails it uses TV_FALLBACK_BED, or a silent bed, so a music
 * hiccup never fails a training video. Returns {file, source}.
 */
async function makeBed({ seconds, dir, cfg, log }) {
  try {
    const audio = await generateAudio({
      key: cfg.geminiKey(), model: cfg.musicModel, log, attempts: 3,
      body: { contents: [{ parts: [{ text: prompt(seconds) }] }], generationConfig: { responseModalities: ['AUDIO'] } },
    });
    const ext = /wav/.test(audio.mime) ? '.wav' : '.mp3';
    const file = path.join(dir, `bed${ext}`);
    await fs.writeFile(file, audio.data);
    return { file, source: cfg.musicModel };
  } catch (e) {
    if (cfg.fallbackBed) {
      if (log) log({ level: 'warn', msg: 'lyria failed, using the fallback bed', error: e.message.slice(0, 200) });
      return { file: cfg.fallbackBed, source: 'fallback-bed' };
    }
    if (log) log({ level: 'warn', msg: 'lyria failed, no fallback bed: silent bed', error: e.message.slice(0, 200) });
    const file = path.join(dir, 'bed_silent.wav');
    await run('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', String(Math.ceil(seconds) + 1), file]);
    return { file, source: 'silent' };
  }
}

module.exports = { makeBed };
