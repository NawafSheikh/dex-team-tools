'use strict';
const fs = require('node:fs');
const config = require('./config');
const { loadApiKey } = require('./auth');
const { createJobs } = require('./jobs');
const { createServer } = require('./app');
const { startSweeper } = require('./sweeper');

const log = (o) => process.stdout.write(`${JSON.stringify({ t: new Date().toISOString(), ...o })}\n`);

async function main() {
  const apiKey = loadApiKey(config.apiKeyFile);
  config.geminiKey(); // fail at start-up, not on the first job
  for (const d of [config.docsDir, config.jobsDir, config.workDir, config.outDir]) fs.mkdirSync(d, { recursive: true });
  const jobs = createJobs({ cfg: config, log });
  await jobs.recover();
  startSweeper({ cfg: config, log });
  const server = createServer({ apiKey, jobs, log });
  server.requestTimeout = 5 * 60 * 1000;
  server.listen(config.port, config.host, () => log({ level: 'info', msg: 'train-video listening', host: config.host, port: config.port }));
}

main().catch((e) => {
  process.stderr.write(`startup failed: ${e.message}\n`);
  process.exit(1);
});
