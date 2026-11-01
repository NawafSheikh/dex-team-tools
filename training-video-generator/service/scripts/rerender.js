'use strict';
/**
 * Re-render a finished job from its saved source (plan, brand, voice, docId) into the same video file, so the
 * link the user already has serves the new render. Used after a service fix (for example the dash rule).
 * Usage (on the render host, as the service user): node scripts/rerender.js <jobId>
 * The job file records the re-render (rerenderedAt, rerenderReason) so it is never silent.
 */
const fs = require('node:fs/promises');
const path = require('node:path');
const cfg = require('../server/config');
const { parsePlan } = require('../server/plan-schema');
const { loadDoc, ensureOcr } = require('../server/ingest');
const { narrate } = require('../server/tts');
const { makeBed } = require('../server/music');
const { compileProject } = require('../server/compile');
const { renderVideo, mixAudio } = require('../server/render');
const { estimateSeconds } = require('../server/app');

const log = (o) => process.stdout.write(`${JSON.stringify(o)}\n`);

async function main(jobId, reason) {
  const jobFile = path.join(cfg.jobsDir, `${jobId}.json`);
  const job = JSON.parse(await fs.readFile(jobFile, 'utf8'));
  if (job.status !== 'done' || !job.source) throw new Error('job is not done or has no saved source');
  const token = /\/v\/([A-Za-z0-9_-]+)\.mp4$/.exec(job.videoUrl)[1];
  const plan = parsePlan(job.source.plan);
  await loadDoc(job.source.docId, cfg);
  const doc = await ensureOcr(job.source.docId, cfg);
  const work = path.join(cfg.workDir, `${jobId}-re`);
  const t0 = Date.now();
  await fs.mkdir(work, { recursive: true });
  const [voices, bed] = await Promise.all([
    narrate({ scenes: plan.scenes, voice: job.source.voice, dir: path.join(work, 'vo'), cfg, log }),
    makeBed({ seconds: estimateSeconds(plan) + 8, dir: work, cfg, log }),
  ]);
  const project = await compileProject({ plan, brand: job.source.brand, voices, doc, docDir: path.join(cfg.docsDir, job.source.docId), outDir: path.join(work, 'project') });
  const silent = path.join(work, 'silent.mp4');
  await renderVideo({ projectDir: project.dir, outFile: silent, cfg });
  const tmp = path.join(cfg.outDir, `${token}.tmp.mp4`);
  await mixAudio({ videoFile: silent, voices, film: project.film, bedFile: bed.file, outFile: tmp });
  await fs.rename(tmp, path.join(cfg.outDir, `${token}.mp4`));
  await fs.copyFile(path.join(project.dir, 'captions.srt'), path.join(cfg.outDir, `${token}.srt`));
  await fs.rm(work, { recursive: true, force: true });
  const updated = { ...job, rerenderedAt: new Date().toISOString(), rerenderReason: reason, rerenderSec: Math.round((Date.now() - t0) / 1000), rerenderWarnings: project.warnings };
  await fs.writeFile(jobFile, JSON.stringify(updated));
  log({ level: 'info', msg: 'rerendered', jobId, token, seconds: updated.rerenderSec, warnings: project.warnings });
}

main(process.argv[2], process.argv.slice(3).join(' ') || 'service fix').catch((e) => {
  process.stderr.write(`rerender failed: ${e.message}\n`);
  process.exit(1);
});
