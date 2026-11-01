'use strict';
const { run } = require('./proc');

/**
 * Render the HyperFrames project to a silent MP4. Reports progress (0..1) parsed from the CLI output.
 * Returns {seconds, mode} where mode is the capture path the CLI chose (beginframe or screenshot).
 */
async function renderVideo({ projectDir, outFile, cfg, onProgress }) {
  const t0 = Date.now();
  let mode = 'unknown';
  const scan = (chunk) => {
    const m = /@hf-progress \{"code":"(?:capture|encode)","done":(\d+),"total":(\d+)/.exec(chunk);
    if (m && onProgress) onProgress(Math.min(1, Number(m[1]) / Number(m[2])));
    const cap = /(beginframe|screenshot) capture ·/.exec(chunk);
    if (cap) mode = cap[1];
  };
  await run(cfg.hyperframesBin, ['render', projectDir, '--output', outFile, '--quality', cfg.renderQuality, '--workers', String(cfg.renderWorkers), '--no-low-memory-mode'], {
    cwd: projectDir,
    env: { ...process.env, HYPERFRAMES_NO_TELEMETRY: '1', DO_NOT_TRACK: '1' },
    onStdout: scan,
    onStderr: scan,
  });
  return { seconds: (Date.now() - t0) / 1000, mode };
}

/**
 * Lay the narration clips at their film times, duck the music bed under them, master to -16 LUFS and mux
 * with the silent render. Video is stream-copied.
 */
async function mixAudio({ videoFile, voices, film, bedFile, outFile }) {
  const total = film.total;
  const args = ['-y', '-v', 'error', '-i', videoFile];
  voices.forEach((v) => args.push('-i', v.file));
  args.push('-stream_loop', '-1', '-i', bedFile);
  const bedIdx = voices.length + 1;
  const vparts = voices.map((v, i) => {
    const ms = Math.round(film.scenes[i].voiceAt * 1000);
    return `[${i + 1}:a]aresample=48000,adelay=${ms}:all=1[v${i}]`;
  });
  const fadeOut = Math.max(0, total - 2.5).toFixed(2);
  const graph = [
    ...vparts,
    `${voices.map((_, i) => `[v${i}]`).join('')}amix=inputs=${voices.length}:normalize=0:dropout_transition=0,apad,atrim=0:${total.toFixed(3)},loudnorm=I=-16:TP=-2:LRA=9,asplit=2[vo][key]`,
    `[${bedIdx}:a]aresample=48000,atrim=0:${total.toFixed(3)},asetpts=N/SR/TB,loudnorm=I=-29:TP=-6:LRA=7,afade=t=in:d=1.2,afade=t=out:st=${fadeOut}:d=2.5[bedl]`,
    '[bedl][key]sidechaincompress=threshold=0.03:ratio=5:attack=30:release=450:makeup=1[bed]',
    '[vo][bed]amix=inputs=2:normalize=0:dropout_transition=0,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[mix]',
  ].join(';');
  args.push('-filter_complex', graph, '-map', '0:v', '-map', '[mix]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ac', '2',
    '-t', total.toFixed(3), '-movflags', '+faststart', outFile);
  await run('ffmpeg', args);
}

async function probeDuration(file) {
  const r = await run('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', file]);
  return Number(r.stdout.trim());
}

module.exports = { renderVideo, mixAudio, probeDuration };
