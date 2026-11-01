'use strict';
const { spawn } = require('node:child_process');

/** Run a command, collect stdout and stderr, reject on a non-zero exit. No shell, so no injection. */
function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'], ...opts });
    const out = [];
    const err = [];
    child.stdout.on('data', (c) => { out.push(c); if (opts.onStdout) opts.onStdout(c.toString()); });
    child.stderr.on('data', (c) => { err.push(c); if (opts.onStderr) opts.onStderr(c.toString()); });
    child.on('error', reject);
    child.on('close', (code) => {
      const stdout = Buffer.concat(out).toString('utf8');
      const stderr = Buffer.concat(err).toString('utf8');
      if (code === 0) resolve({ stdout, stderr });
      else reject(Object.assign(new Error(`${cmd} exited ${code}: ${stderr.slice(-800)}`), { stdout, stderr, code }));
    });
  });
}

module.exports = { run };
