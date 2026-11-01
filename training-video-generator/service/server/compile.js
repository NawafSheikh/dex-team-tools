'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { css } = require('./styles');
const { sceneMarkup, esc, r3 } = require('./scenes');
const { layout } = require('./timing');
const { findPhrase } = require('./ocr');

const FPS = 24;
const GSAP = require.resolve('gsap/dist/gsap.min.js');

const srtTime = (t) => {
  const ms = Math.max(0, Math.round(t * 1000));
  const p = (n, w = 2) => String(n).padStart(w, '0');
  return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)},${p(ms % 1000, 3)}`;
};
const toSrt = (caps) => caps.map((c, i) => `${i + 1}\n${srtTime(c.start)} --> ${srtTime(c.end)}\n${c.text}\n`).join('\n');

function captionsMarkup(caps) {
  const html = caps.map((c, i) => `<div class="clip cap" id="cap${i}" data-start="${r3(c.start)}" data-duration="${r3(Math.max(0.3, c.end - c.start))}" data-track-index="9"><span>${esc(c.text)}</span></div>`).join('\n');
  const js = caps.map((c, i) => `tl.fromTo("#cap${i} span", { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.16, ease: "power2.out" }, ${r3(c.start)});`);
  return { html, js };
}

function chromeMarkup(plan, film, ctx) {
  const stepScenes = film.scenes.filter((sc) => plan.scenes[sc.index].type === 'step');
  const segs = stepScenes.map((_, k) => `<b><span id="pg${k}"></span></b>`).join('');
  const first = film.scenes[1] ? film.scenes[1].start : film.total;
  const html = `<div class="topbar" id="tb"><div class="mark"><i></i>${esc(ctx.brandName)}</div><div class="crumb">${esc(plan.title)}</div></div>
<div class="progress" id="pg">${segs}</div>`;
  const js = [
    `tl.to("#tb, #pg", { opacity: 1, duration: 0.5, ease: "power2.out" }, ${r3(first + 0.1)});`,
    ...stepScenes.map((sc, k) => `tl.fromTo("#pg${k}", { scaleX: 0 }, { scaleX: 1, duration: 0.6, ease: "power2.out" }, ${r3(sc.start + 0.3)});`),
  ];
  return { html, js };
}

/**
 * Compile a validated plan, its narration timings and the document's images into a HyperFrames project.
 * Deterministic: the same inputs give the same files. Returns {dir, duration, captions, warnings}.
 */
async function compileProject({ plan, brand, voices, doc, docDir, outDir }) {
  const warnings = [];
  const images = new Map(doc.images.map((im) => [im.id, im]));
  const stepNumber = new Map();
  plan.scenes.forEach((s, i) => { if (s.type === 'step') stepNumber.set(i, stepNumber.size + 1); });
  const ctx = {
    images,
    stepNumber,
    stepCount: stepNumber.size,
    brandName: brand.name || 'Training',
    warn: (m) => warnings.push(m),
    findText: (img, phrase) => findPhrase(img.words || [], phrase),
  };
  const film = layout(plan, voices);
  const parts = film.scenes.map((sc) => ({ sc, ...sceneMarkup(plan.scenes[sc.index], sc, ctx) }));
  const captions = film.scenes.flatMap((sc) => sc.captions);
  const cap = captionsMarkup(captions);
  const chrome = chromeMarkup(plan, film, ctx);
  const sections = parts.map(({ sc, html }) => `<section id="s${sc.index}" class="clip scene" data-start="${sc.start}" data-duration="${sc.duration}" data-track-index="1">${html}</section>`).join('\n');
  const js = [...chrome.js, ...parts.flatMap((p) => p.js), ...cap.js].filter(Boolean).join('\n');
  const html = `<!doctype html>
<html lang="${esc(plan.language)}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=1920, height=1080" />
<title>${esc(plan.title)}</title>
<script src="assets/gsap.min.js"></script>
<style>${css(brand.primary || '#0F766E')}</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080" data-fps="${FPS}" data-duration="${film.total}">
<div class="bg"></div>
${chrome.html}
${sections}
<div class="captions" data-track-kind="captions">
${cap.html}
</div>
</div>
<script>
const tl = gsap.timeline({ paused: true });
${js}
window.__timelines["main"] = tl;
</script>
</body>
</html>
`;
  await fs.mkdir(path.join(outDir, 'assets'), { recursive: true });
  await fs.copyFile(GSAP, path.join(outDir, 'assets', 'gsap.min.js'));
  const used = new Set(plan.scenes.map((s) => s.image).filter(Boolean));
  for (const id of used) {
    const im = images.get(id);
    await fs.copyFile(path.join(docDir, im.file), path.join(outDir, 'assets', im.file));
  }
  await fs.writeFile(path.join(outDir, 'index.html'), html);
  await fs.writeFile(path.join(outDir, 'captions.srt'), toSrt(captions));
  return { dir: outDir, duration: film.total, film, captions, warnings };
}

module.exports = { compileProject, toSrt, FPS };
