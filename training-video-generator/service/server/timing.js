'use strict';

const LEAD = 0.55;       // scene visuals settle before the narrator speaks
const TITLE_LEAD = 1.1;
const TAIL = 0.75;       // breath after the last word of a scene
const LAST_TAIL = 2.2;   // hold the final frame
const CAPTION_WORDS = 6;

const splitSentences = (t) => t.replace(/\s+/g, ' ').trim().split(/(?<=[.!?])\s+(?=[A-Z0-9"'(])/).filter(Boolean);
const STOP = new Set(['the', 'and', 'your', 'you', 'then', 'that', 'this', 'with', 'from', 'into', 'for', 'when', 'what', 'will', 'have', 'each', 'once', 'they', 'them', 'their', 'there', 'click', 'select', 'press']);
const keywords = (s) => new Set(s.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/).filter((w) => w.length > 3 && !STOP.has(w)));

/**
 * Place sentence boundaries on the real pauses of the clip: each expected boundary (by character share)
 * snaps to the nearest unused pause after the previous boundary. Returns [{text, start, end}] in clip seconds.
 */
function sentenceTimes(narration, seconds, pauses) {
  const sentences = splitSentences(narration);
  const total = sentences.reduce((n, s) => n + s.length, 0) || 1;
  const out = [];
  let t0 = 0;
  let acc = 0;
  let pi = 0;
  sentences.forEach((s, i) => {
    acc += s.length;
    let end = seconds;
    if (i < sentences.length - 1) {
      const expected = (acc / total) * seconds;
      let best = null;
      for (let k = pi; k < pauses.length; k += 1) {
        const mid = (pauses[k].start + pauses[k].end) / 2;
        if (mid <= t0 + 0.3) continue;
        if (!best || Math.abs(mid - expected) < Math.abs(best.mid - expected)) best = { mid, k, p: pauses[k] };
      }
      if (best && Math.abs(best.mid - expected) < Math.max(1.2, seconds * 0.15)) {
        end = best.p.start;
        pi = best.k + 1;
        out.push({ text: s, start: t0, end });
        t0 = best.p.end;
        return;
      }
      end = Math.max(expected, t0 + 0.2); // never before this sentence's own start (after a late pause)
    }
    out.push({ text: s, start: t0, end });
    t0 = end;
  });
  return out;
}

/** Balanced caption chunks (at most CAPTION_WORDS words) timed by character share inside a sentence. */
function captionChunks(sentence) {
  const ws = sentence.text.split(' ');
  const n = Math.ceil(ws.length / CAPTION_WORDS);
  const per = Math.ceil(ws.length / n);
  const groups = [];
  for (let i = 0; i < ws.length; i += per) groups.push(ws.slice(i, i + per).join(' '));
  const chars = groups.reduce((a, g) => a + g.length, 0) || 1;
  const span = sentence.end - sentence.start;
  let t = sentence.start;
  return groups.map((g) => {
    const d = (g.length / chars) * span;
    const c = { text: g, start: t, end: t + d };
    t += d;
    return c;
  });
}

/** For each item, the sentence index whose keywords overlap it most, kept in order; null when no overlap. */
function matchItems(items, sentences, from = 0) {
  let floor = from;
  return items.map((item) => {
    const kw = keywords(item);
    let best = null;
    for (let i = floor; i < sentences.length; i += 1) {
      const kws = keywords(sentences[i].text);
      const score = [...kw].filter((w) => kws.has(w) || [...kws].some((x) => x.startsWith(w.slice(0, 5)))).length;
      if (score > 0 && (!best || score > best.score)) best = { i, score };
    }
    if (!best) return null;
    floor = best.i;
    return best.i;
  });
}

/** When inside a sentence an item is named: its first keyword's character share of the sentence span. */
function wordTime(item, sentence) {
  const low = sentence.text.toLowerCase();
  const pos = [...keywords(item)].map((w) => low.indexOf(w.slice(0, 5))).filter((i) => i >= 0);
  const at = pos.length ? Math.min(...pos) / Math.max(1, low.length) : 0;
  return sentence.start + at * (sentence.end - sentence.start) + 0.1;
}

/** Reveal times (scene seconds) for n items: matched sentence starts, else spread over the narration. */
function revealTimes(items, sentences, voiceAt, voiceSeconds) {
  const matched = matchItems(items, sentences, sentences.length > items.length ? 1 : 0);
  let last = voiceAt + 0.2;
  return items.map((_, k) => {
    const even = voiceAt + voiceSeconds * (0.15 + 0.7 * (k / Math.max(1, items.length)));
    const m = matched[k];
    const t = m === null ? even : voiceAt + wordTime(items[k], sentences[m]);
    last = Math.max(last + 0.35, t);
    return last;
  });
}

/**
 * Lay out the film: scene starts and durations from the real narration lengths, sentence and caption times,
 * and reveal cues for bullets and highlights. All times in film seconds.
 */
function layout(plan, voices) {
  let t = 0;
  const scenes = plan.scenes.map((s, i) => {
    const v = voices[i];
    const lead = i === 0 ? TITLE_LEAD : LEAD;
    const tail = i === plan.scenes.length - 1 ? LAST_TAIL : TAIL;
    const duration = +(lead + v.seconds + tail).toFixed(3);
    const sentences = sentenceTimes(s.narration, v.seconds, v.pauses);
    const items = s.bullets || (s.highlights || []).map((h) => h.text || '');
    const cues = revealTimes(items, sentences, t + lead, v.seconds); // film time, like voiceAt and captions // film time, like voiceAt and captions
    const captions = sentences.flatMap(captionChunks).map((c) => ({ text: c.text, start: +(t + lead + c.start).toFixed(3), end: +(t + lead + c.end).toFixed(3) }));
    const scene = { index: i, start: +t.toFixed(3), duration, voiceAt: +(t + lead).toFixed(3), voiceSeconds: v.seconds, cues, captions };
    t += duration;
    return scene;
  });
  return { scenes, total: +t.toFixed(3) };
}

module.exports = { layout, sentenceTimes, captionChunks, splitSentences, revealTimes };
