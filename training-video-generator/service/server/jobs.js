'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const { ApiError } = require('./errors');
const { narrate } = require('./tts');
const { makeBed } = require('./music');
const { compileProject } = require('./compile');
const { renderVideo, mixAudio, probeDuration } = require('./render');
const { ensureOcr } = require('./ingest');
const { deskBusyByOther } = require('./desk');

const STAGE_WEIGHT = { queued: 0, narrating: 0.05, compiling: 0.12, rendering: 0.15, mixing: 0.95, done: 1 };

/**
 * One render at a time (rendering is CPU heavy), a short FIFO queue behind it. Job state is written to disk on
 * every change so a status call never depends on memory alone. Times are measured, never estimated, except
 * the queue estimate, which uses the measured render speed of past jobs.
 */
function createJobs({ cfg, log }) {
  const queue = [];
  const jobs = new Map();
  let active = null;
  let speed = cfg.initialRenderSecPerVideoMin; // render seconds per video minute, updated from real jobs

  const file = (id) => path.join(cfg.jobsDir, `${id}.json`);
  // Write to a temporary file, then rename over the record: a crash mid-write never leaves partial JSON.
  const save = async (job) => {
    const tmp = `${file(job.id)}.${process.pid}.tmp`;
    try {
      await fs.writeFile(tmp, JSON.stringify(job));
      await fs.rename(tmp, file(job.id));
    } catch (e) {
      log({ level: 'error', msg: 'job save failed', error: e.message });
    }
  };
  const update = (job, patch) => { Object.assign(job, patch, { updatedAt: new Date().toISOString() }); return save(job); };

  function publicView(job) {
    const position = queue.findIndex((j) => j.job.id === job.id);
    return {
      jobId: job.id,
      status: job.status,
      stage: job.stage,
      progress: Math.round((job.progress || 0) * 100) / 100,
      queuePosition: position >= 0 ? position + 1 : 0,
      title: job.title,
      videoUrl: job.videoUrl,
      captionsUrl: job.captionsUrl,
      durationSec: job.durationSec,
      timings: job.timings,
      usage: job.usage,
      warnings: job.warnings || [],
      error: job.error,
      createdAt: job.createdAt,
      finishedAt: job.finishedAt,
    };
  }

  async function runJob(job, input) {
    const work = path.join(cfg.workDir, job.id);
    const t = {};
    const mark = async (stage, progress) => update(job, { status: 'running', stage, progress: progress ?? STAGE_WEIGHT[stage] });
    const t0 = Date.now();
    await mark('narrating');
    await fs.mkdir(work, { recursive: true }); // narration and music both write here, in parallel
    const tn = Date.now();
    const [voices, bed, doc] = await Promise.all([
      narrate({ scenes: input.plan.scenes, voice: input.voice, dir: path.join(work, 'vo'), cfg, log }),
      makeBed({ seconds: input.estimateSec + 8, dir: work, cfg, log }),
      ensureOcr(input.doc.docId, cfg),
    ]);
    t.narrationAndMusicSec = (Date.now() - tn) / 1000;
    await mark('compiling');
    const tc = Date.now();
    const project = await compileProject({ plan: input.plan, brand: input.brand, voices, doc, docDir: input.docDir, outDir: path.join(work, 'project') });
    t.compileSec = (Date.now() - tc) / 1000;
    await update(job, { warnings: project.warnings });
    while (await deskBusyByOther(cfg)) {
      if (job.stage !== 'waiting') { await mark('waiting', STAGE_WEIGHT.rendering); log({ level: 'info', msg: 'render waits for the shared host lock', jobId: job.id }); }
      await new Promise((r) => setTimeout(r, 30000));
    }
    await mark('rendering');
    const silent = path.join(work, 'silent.mp4');
    const r = await renderVideo({
      projectDir: project.dir, outFile: silent, cfg,
      onProgress: (p) => { job.progress = STAGE_WEIGHT.rendering + p * (STAGE_WEIGHT.mixing - STAGE_WEIGHT.rendering); },
    });
    t.renderSec = r.seconds;
    await mark('mixing');
    const tm = Date.now();
    const token = crypto.randomBytes(12).toString('base64url');
    const outFile = path.join(cfg.outDir, `${token}.mp4`);
    await mixAudio({ videoFile: silent, voices, film: project.film, bedFile: bed.file, outFile });
    await fs.copyFile(path.join(project.dir, 'captions.srt'), path.join(cfg.outDir, `${token}.srt`));
    t.mixSec = (Date.now() - tm) / 1000;
    t.totalSec = (Date.now() - t0) / 1000;
    const durationSec = await probeDuration(outFile);
    const perMin = t.renderSec / (durationSec / 60);
    speed = speed ? (speed + perMin) / 2 : perMin;
    if (!cfg.keepWork) await fs.rm(work, { recursive: true, force: true });
    for (const k of Object.keys(t)) t[k] = Math.round(t[k] * 10) / 10;
    await update(job, {
      status: 'done', stage: 'done', progress: 1, finishedAt: new Date().toISOString(),
      videoUrl: `${cfg.publicBase}/v/${token}.mp4`, captionsUrl: `${cfg.publicBase}/v/${token}.srt`,
      durationSec: Math.round(durationSec * 10) / 10,
      timings: t,
      usage: {
        narrationSeconds: Math.round(voices.reduce((a, v) => a + v.seconds, 0) * 10) / 10,
        ttsCalls: voices.length,
        music: bed.source,
        narrationModel: voices.model,
        renderSecondsPerVideoMinute: Math.round(perMin),
        renderMode: r.mode,
        workers: cfg.renderWorkers,
      },
    });
    log({ level: 'info', msg: 'job done', jobId: job.id, durationSec, timings: t });
  }

  async function pump() {
    if (active || !queue.length) return;
    const { job, input } = queue.shift();
    active = job;
    try {
      await runJob(job, input);
    } catch (e) {
      log({ level: 'error', msg: 'job failed', jobId: job.id, error: e.message.slice(0, 600) });
      await update(job, { status: 'failed', stage: 'failed', error: 'The render failed. The team has the log; try again in a few minutes.', finishedAt: new Date().toISOString() });
    } finally {
      active = null;
      setImmediate(pump);
    }
  }

  /** Queue a validated render. Returns the public view with an estimate. */
  async function submit(input) {
    if (queue.length >= cfg.maxQueue) throw new ApiError(429, 'QUEUE_FULL', `${queue.length} videos are already waiting; try again later`);
    const id = crypto.randomBytes(9).toString('base64url');
    const job = { id, status: 'queued', stage: 'queued', progress: 0, title: input.plan.title, createdAt: new Date().toISOString(),
      // kept so any video can be re-rendered exactly; never returned by the API
      source: { docId: input.doc.docId, plan: input.plan, brand: input.brand, voice: input.voice } };
    // Reserve the queue slot before any await, so concurrent submissions cannot all pass the capacity check.
    const entry = { job, input };
    queue.push(entry);
    jobs.set(id, job);
    try {
      await save(job);
    } catch (e) {
      queue.splice(queue.indexOf(entry), 1);
      jobs.delete(id);
      throw e;
    }
    setImmediate(pump);
    const ahead = queue.length - 1 + (active ? 1 : 0);
    const estimate = Math.round(60 + (input.estimateSec / 60) * speed * (ahead + 1));
    return { ...publicView(job), estimatedReadySec: estimate };
  }

  async function get(id) {
    if (!/^[A-Za-z0-9_-]{8,32}$/.test(id || '')) throw new ApiError(400, 'BAD_REQUEST', '"jobId" is invalid');
    const job = jobs.get(id) || await fs.readFile(file(id), 'utf8').then(JSON.parse).catch(() => null);
    if (!job) throw new ApiError(404, 'JOB_NOT_FOUND', 'No job with that id');
    return publicView(job);
  }

  /** Wait up to waitSec for the job to finish, so a caller does not have to poll in a tight loop. */
  async function waitFor(id, waitSec) {
    const until = Date.now() + waitSec * 1000;
    let view = await get(id);
    while (!['done', 'failed'].includes(view.status) && Date.now() < until) {
      await new Promise((r) => setTimeout(r, 2000));
      view = await get(id);
    }
    return view;
  }

  /** Jobs that were running when the service stopped are marked failed on start; nothing is retried silently. */
  async function recover() {
    const names = await fs.readdir(cfg.jobsDir).catch(() => []);
    for (const n of names.filter((x) => x.endsWith('.json'))) {
      let job;
      try {
        job = JSON.parse(await fs.readFile(path.join(cfg.jobsDir, n), 'utf8'));
      } catch (e) {
        log({ level: 'error', msg: 'skipping unreadable job record', file: n, error: e.message });
        continue;
      }
      if (!['done', 'failed'].includes(job.status)) {
        await update(job, { status: 'failed', stage: 'failed', error: 'The service restarted during this render; start it again.' });
      }
    }
  }

  return { submit, get, waitFor, recover, stats: () => ({ active: active && active.id, queued: queue.length, renderSecPerVideoMin: speed }) };
}

module.exports = { createJobs };
