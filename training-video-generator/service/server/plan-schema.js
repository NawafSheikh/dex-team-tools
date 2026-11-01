'use strict';
const { z } = require('zod');
const { ApiError } = require('./errors');

/**
 * The scene plan the LLM side writes. Small on purpose: the model chooses words and structure,
 * the compiler owns every pixel and every timing.
 */
const words = (s) => s.trim().split(/\s+/).filter(Boolean).length;
const maxWords = (n) => (s) => words(s) <= n;
const text = (maxLen, maxW, what) => z.string().trim().min(1, `${what} is empty`).max(maxLen)
  .refine(maxWords(maxW), { message: `${what} must be at most ${maxW} words` });
const narration = text(600, 70, 'narration');
const IMAGE_ID = /^img\d{1,3}$/;

const highlight = z.union([
  z.object({ text: text(80, 8, 'highlight.text') }).strict(),
  z.object({ box: z.tuple([z.number().min(0).max(1), z.number().min(0).max(1), z.number().min(0.005).max(1), z.number().min(0.005).max(1)]) }).strict(),
]);

const title = z.object({
  type: z.literal('title'),
  heading: text(80, 10, 'heading'),
  sub: text(140, 20, 'sub').optional(),
  image: z.string().regex(IMAGE_ID).optional(),
  narration,
}).strict();

const overview = z.object({
  type: z.literal('overview'),
  heading: text(60, 8, 'heading'),
  bullets: z.array(text(70, 9, 'bullet')).min(2).max(6),
  narration,
}).strict();

const step = z.object({
  type: z.literal('step'),
  heading: text(70, 9, 'heading'),
  body: text(160, 24, 'body').optional(),
  image: z.string().regex(IMAGE_ID).optional(),
  highlights: z.array(highlight).max(2).optional(),
  narration,
}).strict();

const note = z.object({
  type: z.literal('note'),
  kind: z.enum(['tip', 'important']),
  heading: text(60, 8, 'heading'),
  body: text(200, 30, 'body'),
  narration,
}).strict();

const recap = z.object({
  type: z.literal('recap'),
  heading: text(60, 8, 'heading'),
  bullets: z.array(text(70, 9, 'bullet')).min(2).max(6),
  closing: text(90, 14, 'closing').optional(),
  narration,
}).strict();

const scene = z.discriminatedUnion('type', [title, overview, step, note, recap]);

const planSchema = z.object({
  title: text(80, 10, 'title'),
  language: z.string().regex(/^[a-z]{2}(-[A-Z]{2})?$/).default('en'),
  scenes: z.array(scene).min(3).max(14),
}).strict().superRefine((plan, ctx) => {
  if (plan.scenes.length && plan.scenes[0].type !== 'title') ctx.addIssue({ code: 'custom', path: ['scenes', 0, 'type'], message: 'the first scene must be type "title"' });
  const steps = plan.scenes.filter((s) => s.type === 'step').length;
  if (steps < 1) ctx.addIssue({ code: 'custom', path: ['scenes'], message: 'add at least one "step" scene' });
  if (steps > 10) ctx.addIssue({ code: 'custom', path: ['scenes'], message: 'at most 10 step scenes; merge small steps' });
  const total = plan.scenes.reduce((n, s) => n + words(s.narration), 0);
  if (total > 420) ctx.addIssue({ code: 'custom', path: ['scenes'], message: `narration totals ${total} words; keep it at most 420 (about 3 minutes)` });
  plan.scenes.forEach((s, i) => {
    if (s.highlights && s.highlights.length && !s.image) {
      ctx.addIssue({ code: 'custom', path: ['scenes', i, 'highlights'], message: 'highlights need an "image" on the same scene' });
    }
  });
});

const brandSchema = z.object({
  name: z.string().trim().min(1).max(40).optional(),
  primary: z.string().regex(/^#[0-9A-Fa-f]{6}$/, 'primary must be a hex colour like #0F766E').optional(),
}).strict().default({});

const VOICES = ['Sulafat', 'Kore', 'Aoede', 'Achird', 'Charon', 'Puck', 'Leda', 'Orus'];

const issuesOf = (err) => err.issues.map((i) => ({ path: `$.${i.path.join('.')}`, message: i.message }));

/** House style: no em or en dashes on screen or in narration; a dash between words becomes a comma. */
const undash = (v) => {
  if (typeof v === 'string') return v.replace(/\s*[\u2014\u2013]\s*/g, ', ');
  if (Array.isArray(v)) return v.map(undash);
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, undash(x)]));
  return v;
};

/** Parse a plan given as an object or as a JSON string (Copilot tools pass strings more reliably). */
function parsePlan(raw) {
  let value = raw;
  if (typeof raw === 'string') {
    try { value = JSON.parse(raw); } catch (e) {
      throw new ApiError(400, 'PLAN_INVALID', `plan is not valid JSON: ${e.message}`, { errors: [{ path: '$.plan', message: 'not valid JSON' }] });
    }
  }
  const r = planSchema.safeParse(undash(value));
  if (!r.success) {
    const errors = issuesOf(r.error);
    throw new ApiError(400, 'PLAN_INVALID', `The scene plan has ${errors.length} problem(s); fix all and resend`, { errors });
  }
  return r.data;
}

function parseBrand(raw) {
  const r = brandSchema.safeParse(raw === undefined ? {} : raw);
  if (!r.success) throw new ApiError(400, 'BAD_REQUEST', 'brand is invalid', { errors: issuesOf(r.error) });
  return r.data;
}

/** Every image id the plan uses must exist in the ingested document. */
function checkImages(plan, imageIds) {
  const have = new Set(imageIds);
  const errors = [];
  plan.scenes.forEach((s, i) => {
    if (s.image && !have.has(s.image)) {
      errors.push({ path: `$.scenes.${i}.image`, message: `${s.image} is not in this document; available: ${[...have].join(', ') || 'none'}` });
    }
  });
  if (errors.length) throw new ApiError(400, 'PLAN_INVALID', 'The plan uses images that are not in the document', { errors });
}

module.exports = { parsePlan, parseBrand, checkImages, VOICES, words };
