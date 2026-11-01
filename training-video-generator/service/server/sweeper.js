'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');

/** Delete documents after docTtlHours, finished videos after videoTtlDays, stale work after a day. Hourly. */
function startSweeper({ cfg, log }) {
  async function sweep() {
    const now = Date.now();
    const rmOld = async (dir, maxAgeMs) => {
      for (const name of await fs.readdir(dir).catch(() => [])) {
        const p = path.join(dir, name);
        const st = await fs.stat(p).catch(() => null);
        if (st && now - st.mtimeMs > maxAgeMs) await fs.rm(p, { recursive: true, force: true });
      }
    };
    try {
      await rmOld(cfg.docsDir, cfg.docTtlHours * 3600e3);
      await rmOld(cfg.outDir, cfg.videoTtlDays * 86400e3);
      await rmOld(cfg.workDir, 24 * 3600e3);
    } catch (e) {
      log({ level: 'error', msg: 'sweep failed', error: e.message });
    }
  }
  sweep();
  return setInterval(sweep, 3600e3).unref();
}

module.exports = { startSweeper };
