'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const JSZip = require('jszip');
const { ApiError } = require('./errors');
const { run } = require('./proc');
const { imageSize } = require('./image-size');
const { ocrWords } = require('./ocr');

const IMG_EXT = new Set(['.png', '.jpg', '.jpeg']);

const decodeXml = (s) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&');

/** Walk word/document.xml in order: paragraphs to text lines, drawings to [image:imgN] markers. */
async function readDocx(buffer) {
  let zip;
  try { zip = await JSZip.loadAsync(buffer); } catch { throw new ApiError(422, 'UNREADABLE_DOCUMENT', 'The .docx file could not be opened (it may be corrupt or encrypted)'); }
  const docXml = zip.file('word/document.xml');
  if (!docXml) throw new ApiError(422, 'UNREADABLE_DOCUMENT', 'The .docx file has no document body');
  const xml = await docXml.async('string');
  const relsFile = zip.file('word/_rels/document.xml.rels');
  const rels = new Map();
  if (relsFile) {
    const relsXml = await relsFile.async('string');
    for (const m of relsXml.matchAll(/<Relationship\b[^>]*>/g)) {
      const id = /Id="([^"]+)"/.exec(m[0]);
      const target = /Target="([^"]+)"/.exec(m[0]);
      if (id && target) rels.set(id[1], target[1]);
    }
  }
  const lines = [];
  const images = [];
  for (const p of xml.matchAll(/<w:p[ >][\s\S]*?<\/w:p>/g)) {
    const para = p[0];
    const style = /<w:pStyle w:val="([^"]+)"/.exec(para);
    const isList = /<w:numPr[\s>/]/.test(para);
    let line = '';
    for (const tok of para.matchAll(/<w:t(?: [^>]*)?>([^<]*)<\/w:t>|<w:tab\/>|<a:blip [^>]*r:embed="([^"]+)"/g)) {
      if (tok[2]) {
        const target = rels.get(tok[2]);
        if (!target) continue;
        const file = zip.file(path.posix.join('word', target).replace(/^word\/\.\.\//, ''));
        if (!file) continue;
        const ext = path.extname(target).toLowerCase();
        if (!IMG_EXT.has(ext)) continue;
        const id = `img${images.length + 1}`;
        images.push({ id, ext, data: await file.async('nodebuffer') });
        line += ` [image:${id}] `;
      } else if (tok[0] === '<w:tab/>') {
        line += '\t';
      } else {
        line += decodeXml(tok[1]);
      }
    }
    line = line.replace(/[ \t]+/g, ' ').trim();
    if (!line) continue;
    const heading = style && /^(Heading|Title)(\d?)/i.exec(style[1]);
    if (heading) line = `${'#'.repeat(Math.min(Number(heading[2] || 1), 3))} ${line}`;
    else if (isList) line = `- ${line}`;
    lines.push(line);
  }
  return { text: lines.join('\n'), images };
}

async function readPdf(buffer, workDir) {
  const src = path.join(workDir, 'source.pdf');
  await fs.writeFile(src, buffer);
  const out = await run('pdftotext', ['-layout', '-enc', 'UTF-8', src, '-']).catch(() => {
    throw new ApiError(422, 'UNREADABLE_DOCUMENT', 'The PDF could not be read (it may be corrupt or encrypted)');
  });
  const imgDir = path.join(workDir, 'pdfimg');
  await fs.mkdir(imgDir, { recursive: true });
  await run('pdfimages', ['-png', '-p', src, path.join(imgDir, 'x')]).catch(() => null);
  const files = (await fs.readdir(imgDir)).filter((f) => f.endsWith('.png')).sort();
  const images = [];
  for (const f of files) {
    const data = await fs.readFile(path.join(imgDir, f));
    const size = imageSize(data);
    if (!size || size.width < 320 || size.height < 200) continue; // icons and rules, not screenshots
    images.push({ id: `img${images.length + 1}`, ext: '.png', data, page: Number(/x-(\d+)-/.exec(f)?.[1] || 0) });
  }
  const pages = out.stdout.split('\f');
  const text = pages.map((pg, i) => {
    const marks = images.filter((im) => im.page === i + 1).map((im) => `[image:${im.id}]`).join(' ');
    return `${pg.replace(/[ \t]+\n/g, '\n').trim()}${marks ? `\n${marks}` : ''}`;
  }).filter(Boolean).join('\n\n');
  if (!text.replace(/\[image:img\d+\]/g, '').trim()) throw new ApiError(422, 'NO_TEXT', 'The PDF has no text layer (a scan); send the Word file or the text instead');
  return { text, images };
}

const contextBefore = (text, id) => {
  const at = text.indexOf(`[image:${id}]`);
  const before = text.slice(Math.max(0, at - 220), at).replace(/\[image:img\d+\]/g, '').replace(/\s+/g, ' ').trim();
  return before.length > 160 ? `...${before.slice(-160)}` : before;
};

/**
 * Store a document for planning: text with image markers, each image with its size and OCR words
 * (so the plan can pin a highlight to visible text such as a button label).
 */
async function ingest({ fileName, buffer, text: rawText, extraImages }, cfg) {
  const docId = crypto.randomBytes(9).toString('base64url');
  const dir = path.join(cfg.docsDir, docId);
  await fs.mkdir(dir, { recursive: true });
  const ext = fileName ? path.extname(fileName).toLowerCase() : '.txt';
  let parsed;
  if (rawText !== undefined) parsed = { text: rawText.trim(), images: [] };
  else if (ext === '.docx') parsed = await readDocx(buffer);
  else if (ext === '.pdf') parsed = await readPdf(buffer, dir);
  else if (ext === '.txt' || ext === '.md') parsed = { text: buffer.toString('utf8').trim(), images: [] };
  else throw new ApiError(415, 'UNSUPPORTED_TYPE', 'Send a .docx, .pdf, .txt or .md file');
  const images = [...parsed.images];
  for (const extra of extraImages || []) images.push({ id: `img${images.length + 1}`, ext: extra.ext, data: extra.data });
  if (images.length > cfg.maxImages) throw new ApiError(413, 'TOO_MANY_IMAGES', `The document has ${images.length} images; the limit is ${cfg.maxImages}`);
  if (parsed.text.length > cfg.maxDocChars) throw new ApiError(413, 'DOCUMENT_TOO_LONG', `The document has ${parsed.text.length} characters; the limit is ${cfg.maxDocChars}. Send one procedure at a time.`);
  const meta = [];
  for (const im of images) {
    const size = imageSize(im.data);
    if (!size) continue;
    const file = `${im.id}${im.ext === '.jpeg' ? '.jpg' : im.ext}`;
    await fs.writeFile(path.join(dir, file), im.data);
    meta.push({ id: im.id, file, width: size.width, height: size.height });
  }
  const doc = { docId, fileName: fileName || 'pasted text', createdAt: new Date().toISOString(), text: parsed.text, images: meta, ocrDone: !meta.length };
  await fs.writeFile(path.join(dir, 'doc.json'), JSON.stringify(doc));
  // OCR runs in the background so a slow, shared server never makes the tool call time out. The response waits
  // up to ocrWaitMs for it; a render job waits for it fully (ensureOcr) before it pins highlights.
  const ocr = ensureOcr(docId, cfg);
  ocr.catch(() => {});
  const done = await Promise.race([ocr, new Promise((r) => setTimeout(() => r(null), cfg.ocrWaitMs ?? 20000))]);
  const words = new Map((done ? done.images : []).map((im) => [im.id, im.words]));
  return {
    docId,
    characters: doc.text.length,
    text: doc.text,
    images: meta.map((m) => ({
      id: m.id,
      width: m.width,
      height: m.height,
      context: contextBefore(doc.text, m.id),
      ...(words.has(m.id) ? { visibleText: words.get(m.id).map((w) => w.text).join(' ').slice(0, 400) } : {}),
    })),
  };
}

const pendingOcr = new Map();

/** OCR every image of a document once (three at a time, one thread each) and store the words in doc.json. */
function ensureOcr(docId, cfg) {
  if (pendingOcr.has(docId)) return pendingOcr.get(docId);
  const task = (async () => {
    const file = path.join(cfg.docsDir, docId, 'doc.json');
    const doc = JSON.parse(await fs.readFile(file, 'utf8'));
    if (doc.ocrDone) return doc;
    let next = 0;
    const worker = async () => {
      while (next < doc.images.length) {
        const im = doc.images[next];
        next += 1;
        im.words = await ocrWords(path.join(cfg.docsDir, docId, im.file));
      }
    };
    await Promise.all([1, 2, 3].map(worker));
    const updated = { ...doc, ocrDone: true };
    await fs.writeFile(file, JSON.stringify(updated));
    return updated;
  })().finally(() => pendingOcr.delete(docId));
  pendingOcr.set(docId, task);
  return task;
}

async function loadDoc(docId, cfg) {
  if (!/^[A-Za-z0-9_-]{8,32}$/.test(docId || '')) throw new ApiError(400, 'BAD_REQUEST', '"docId" is invalid');
  try {
    return JSON.parse(await fs.readFile(path.join(cfg.docsDir, docId, 'doc.json'), 'utf8'));
  } catch {
    throw new ApiError(404, 'DOC_NOT_FOUND', 'No document with that docId (documents are kept 48 hours); ingest it again');
  }
}

module.exports = { ingest, loadDoc, readDocx, ensureOcr };
