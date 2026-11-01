'use strict';

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const r3 = (n) => Math.round(n * 1000) / 1000;
const CHECK = '<svg viewBox="0 0 52 52"><rect width="52" height="52" rx="15" fill="var(--brand)"/><path d="M15 27l7 7 15-16" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>';

const STEP_AREA = { x: 730, y: 150, w: 1070, h: 740 };
const TITLE_AREA = { x: 1000, y: 210, w: 800, h: 600 };
const CHROME = 40;
const MAX_ZOOM = 2.0;

/** Fit an image into an area under a browser-style chrome bar; returns card and scale. */
function fitCard(img, area) {
  const scale = Math.min(area.w / img.width, (area.h - CHROME) / img.height, 1.5);
  const w = Math.round(img.width * scale);
  const h = Math.round(img.height * scale);
  return { scale, w, h, left: Math.round(area.x + area.w - w), top: Math.round(area.y + (area.h - (h + CHROME)) / 2) };
}

function cardHtml(id, img, fit, rings) {
  const ringHtml = rings.map((rg, k) => `<div class="ring" id="${id}r${k}" style="left:${rg.x}px;top:${rg.y}px;width:${rg.w}px;height:${rg.h}px"></div>`).join('');
  return `<div class="card" id="${id}c" style="left:${fit.left}px;top:${fit.top}px;width:${fit.w}px;height:${fit.h + CHROME}px">
  <div class="chrome"><i></i><i></i><i></i></div>
  <div class="viewport" style="top:${CHROME}px"><div class="stage" id="${id}st" style="width:${fit.w}px;height:${fit.h}px">
    <img src="assets/${esc(img.file)}" alt="">${ringHtml}</div></div></div>`;
}

/** Zoom that makes a small highlight readable, clamped so the image always fills the viewport. */
function zoomFor(ring, fit) {
  const z = Math.min(MAX_ZOOM, (0.34 * fit.w) / ring.w, (0.45 * fit.h) / ring.h);
  if (z < 1.15) return null;
  const cx = ring.x + ring.w / 2;
  const cy = ring.y + ring.h / 2;
  const x = Math.min(0, Math.max(fit.w - fit.w * z, fit.w / 2 - cx * z));
  const y = Math.min(0, Math.max(fit.h - fit.h * z, fit.h / 2 - cy * z));
  return { scale: r3(z), x: r3(x), y: r3(y) };
}

function enter(id, t, end) {
  return [
    `tl.fromTo("#${id}w", { opacity: 0, y: 26 }, { opacity: 1, y: 0, duration: 0.55, ease: "power3.out" }, ${r3(t)});`,
    `tl.to("#${id}w", { opacity: 0, y: -10, duration: 0.38, ease: "power2.in" }, ${r3(end - 0.42)});`,
  ];
}

function titleScene(s, sc, ctx) {
  const id = `s${sc.index}`;
  const img = s.image && ctx.images.get(s.image);
  const fit = img && fitCard(img, TITLE_AREA);
  const chip = `Training video &middot; ${ctx.stepCount} step${ctx.stepCount === 1 ? '' : 's'}`;
  const html = `<div class="wrap" id="${id}w">
  <div class="title-text${img ? '' : ' solo'}">
    <div class="eyebrow" id="${id}e">${esc(ctx.brandName)}</div>
    <h1 id="${id}h">${esc(s.heading)}</h1>
    ${s.sub ? `<div class="sub" id="${id}s">${esc(s.sub)}</div>` : ''}
    <div><span class="chip" id="${id}k"><i></i>${chip}</span></div>
  </div>
  ${img ? cardHtml(id, img, fit, []) : ''}</div>`;
  const t = sc.start;
  const js = [
    `tl.to("#${id}w", { opacity: 0, y: -10, duration: 0.38, ease: "power2.in" }, ${r3(t + sc.duration - 0.42)});`,
    `tl.fromTo("#${id}h", { y: 10 }, { y: 0, duration: 1.4, ease: "power2.out" }, ${r3(t)});`,
    s.sub ? `tl.fromTo("#${id}s", { opacity: 0.0, y: 16 }, { opacity: 1, y: 0, duration: 0.7, ease: "power3.out" }, ${r3(t + 0.3)});` : '',
    `tl.fromTo("#${id}k", { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.6, ease: "power3.out" }, ${r3(t + 0.55)});`,
    img ? `tl.fromTo("#${id}c", { x: 40, rotationY: -12, transformPerspective: 1600 }, { x: 0, rotationY: -7, duration: 1.2, ease: "power3.out" }, ${r3(t)});` : '',
    img ? `tl.to("#${id}c", { rotationY: -3, y: -8, duration: ${r3(Math.max(1, sc.duration - 1.6))}, ease: "sine.inOut" }, ${r3(t + 1.45)});` : '',
  ];
  return { html, js };
}

function listScene(s, sc, ctx, checked) {
  const id = `s${sc.index}`;
  const rows = s.bullets.map((b, k) => `<div class="row" id="${id}b${k}">${checked ? CHECK : `<span class="n">${k + 1}</span>`}<span>${esc(b)}</span></div>`).join('');
  const html = `<div class="wrap" id="${id}w"><div class="listscene">
    <div class="eyebrow">${checked ? 'Recap' : 'In this video'}</div>
    <h2 id="${id}h">${esc(s.heading)}</h2>
    <div class="list">${rows}</div>
    ${s.closing ? `<div class="closing" id="${id}x">${esc(s.closing)}</div>` : ''}
  </div></div>`;
  const t = sc.start;
  const js = [
    ...enter(id, t, t + sc.duration),
    ...s.bullets.map((_, k) => `tl.from("#${id}b${k}", { opacity: 0, x: -28, duration: 0.5, ease: "power3.out" }, ${r3(sc.cues[k])});`),
    ...(checked ? s.bullets.map((_, k) => `tl.from("#${id}b${k} svg", { scale: 0.4, transformOrigin: "50% 50%", duration: 0.45, ease: "back.out(2.4)" }, ${r3(sc.cues[k] + 0.12)});`) : []),
    s.closing ? `tl.from("#${id}x", { opacity: 0, y: 14, duration: 0.5, ease: "power3.out" }, ${r3(Math.max(sc.cues[sc.cues.length - 1] + 0.6, sc.voiceAt + sc.voiceSeconds - 2.4))});` : '',
  ];
  return { html, js };
}

function stepScene(s, sc, ctx) {
  const id = `s${sc.index}`;
  const n = ctx.stepNumber.get(sc.index);
  const img = s.image && ctx.images.get(s.image);
  const fit = img && fitCard(img, STEP_AREA);
  const rings = [];
  if (img) {
    (s.highlights || []).forEach((h) => {
      const box = h.box ? { x: h.box[0] * img.width, y: h.box[1] * img.height, w: h.box[2] * img.width, h: h.box[3] * img.height } : ctx.findText(img, h.text);
      if (!box) { ctx.warn(`scene ${sc.index + 1}: "${h.text}" was not found on ${img.id}; no highlight drawn`); return; }
      rings.push({ x: r3(box.x * fit.scale), y: r3(box.y * fit.scale), w: r3(box.w * fit.scale), h: r3(box.h * fit.scale) });
    });
  }
  const html = `<div class="wrap" id="${id}w">
  <div class="steptext${img ? '' : ' solo'}">
    <div class="eyebrow" id="${id}e">Step ${n} of ${ctx.stepCount}</div>
    <div class="num" id="${id}n">${n}</div>
    <h2 id="${id}h">${esc(s.heading)}</h2>
    ${s.body ? `<div class="body" id="${id}b">${esc(s.body)}</div>` : ''}
  </div>
  ${img ? cardHtml(id, img, fit, rings) : ''}</div>`;
  const t = sc.start;
  const end = t + sc.duration;
  const js = [
    ...enter(id, t, end),
    `tl.from("#${id}n", { opacity: 0, scale: 0.6, transformOrigin: "50% 50%", duration: 0.55, ease: "back.out(2)" }, ${r3(t + 0.12)});`,
    `tl.from("#${id}h", { opacity: 0, y: 22, duration: 0.55, ease: "power3.out" }, ${r3(t + 0.22)});`,
    s.body ? `tl.from("#${id}b", { opacity: 0, y: 16, duration: 0.55, ease: "power3.out" }, ${r3(t + 0.4)});` : '',
    img ? `tl.from("#${id}c", { opacity: 0, x: 70, duration: 0.8, ease: "power3.out" }, ${r3(t + 0.1)});` : '',
  ];
  rings.forEach((rg, k) => {
    const at = Math.min(sc.cues[k] ?? sc.voiceAt + 1, end - 2.2);
    js.push(`tl.fromTo("#${id}r${k}", { opacity: 0, scale: 1.18, transformOrigin: "50% 50%" }, { opacity: 1, scale: 1, duration: 0.5, ease: "power3.out" }, ${r3(at)});`);
    if (k > 0) js.push(`tl.to("#${id}r${k - 1}", { opacity: 0, duration: 0.3 }, ${r3(at)});`);
    const z = zoomFor(rg, fit);
    const zoomAt = at + 0.55;
    if (z && end - zoomAt >= 2.6) js.push(`tl.to("#${id}st", { scale: ${z.scale}, x: ${z.x}, y: ${z.y}, duration: 1.1, ease: "power2.inOut" }, ${r3(zoomAt)});`);
    else if (k > 0) js.push(`tl.to("#${id}st", { scale: 1, x: 0, y: 0, duration: 0.9, ease: "power2.inOut" }, ${r3(zoomAt)});`);
  });
  return { html, js, rings: rings.length };
}

function noteScene(s, sc) {
  const id = `s${sc.index}`;
  const label = s.kind === 'important' ? 'Important' : 'Tip';
  const html = `<div class="wrap" id="${id}w"><div class="note ${s.kind}" id="${id}c">
    <div class="tag">${label}</div><h2 id="${id}h">${esc(s.heading)}</h2><div class="body" id="${id}b">${esc(s.body)}</div></div></div>`;
  const t = sc.start;
  const js = [
    ...enter(id, t, t + sc.duration),
    `tl.from("#${id}c", { scale: 0.96, transformOrigin: "50% 50%", duration: 0.7, ease: "power3.out" }, ${r3(t)});`,
    `tl.from("#${id}b", { opacity: 0, y: 16, duration: 0.55, ease: "power3.out" }, ${r3(t + 0.45)});`,
  ];
  return { html, js };
}

function sceneMarkup(s, sc, ctx) {
  if (s.type === 'title') return titleScene(s, sc, ctx);
  if (s.type === 'overview') return listScene(s, sc, ctx, false);
  if (s.type === 'recap') return listScene(s, sc, ctx, true);
  if (s.type === 'step') return stepScene(s, sc, ctx);
  return noteScene(s, sc, ctx);
}

module.exports = { sceneMarkup, esc, r3, fitCard, zoomFor };
