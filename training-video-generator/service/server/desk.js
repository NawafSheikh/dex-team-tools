'use strict';
const fs = require('node:fs/promises');
const { run } = require('./proc');

/**
 * Optional: when the host is shared with other heavy work guarded by a flock file (TV_DESK_LOCK), renders wait
 * while someone else holds it, so that work keeps the CPU. A holder whose owner file (TV_DESK_OWNER) names this
 * service (TV_DESK_NAME) does not block. Unset TV_DESK_LOCK: never waits.
 */
async function deskBusyByOther(cfg) {
  if (!cfg.deskLockFile) return false;
  try {
    await run('flock', ['-n', cfg.deskLockFile, 'true']);
    return false; // lock was free
  } catch {
    const owner = await fs.readFile(cfg.deskOwnerFile, 'utf8').catch(() => '');
    return !owner.includes(cfg.deskOwnName);
  }
}

module.exports = { deskBusyByOther };
