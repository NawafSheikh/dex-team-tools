'use strict';

const BASE = 'https://generativelanguage.googleapis.com/v1beta/models';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * One generateContent call that returns inline audio. Retries rate limits and 5xx with the server's
 * suggested delay; no client timeout on the model call itself (house rule).
 */
async function generateAudio({ key, model, body, log, attempts = 6 }) {
  for (let attempt = 1; ; attempt += 1) {
    const res = await fetch(`${BASE}/${model}:generateContent`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-goog-api-key': key },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      const json = await res.json();
      const part = (json.candidates?.[0]?.content?.parts || []).find((p) => p.inlineData?.data);
      if (!part) throw new Error(`${model} returned no audio (finishReason ${json.candidates?.[0]?.finishReason || 'none'})`);
      return { data: Buffer.from(part.inlineData.data, 'base64'), mime: part.inlineData.mimeType || '' };
    }
    const detail = (await res.text()).slice(0, 400);
    const retryable = res.status === 429 || res.status >= 500;
    if (!retryable || attempt >= attempts) throw new Error(`${model} HTTP ${res.status}: ${detail}`);
    const hinted = /"retryDelay":\s*"(\d+)s"/.exec(detail);
    const waitMs = hinted ? Number(hinted[1]) * 1000 + 500 : Math.min(30000, 1500 * 2 ** attempt);
    if (log) log({ level: 'warn', msg: 'gemini retry', model, status: res.status, waitMs });
    await sleep(waitMs);
  }
}

module.exports = { generateAudio };
