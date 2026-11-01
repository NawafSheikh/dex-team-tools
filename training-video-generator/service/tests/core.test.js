'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const JSZip = require('jszip');
const { parsePlan, checkImages } = require('../server/plan-schema');
const { parseIngestBody, parseRenderBody } = require('../server/envelope');
const { sentenceTimes, captionChunks, layout } = require('../server/timing');
const { findPhrase } = require('../server/ocr');
const { readDocx } = require('../server/ingest');
const { trimPcm, pauses } = require('../server/tts');
const { compileProject } = require('../server/compile');
const { zoomFor } = require('../server/scenes');

const plan = () => ({
  title: 'Submit an expense',
  scenes: [
    { type: 'title', heading: 'How to submit an expense', narration: 'This video shows how to submit an expense.' },
    { type: 'step', heading: 'Open a new expense', image: 'img1', highlights: [{ text: 'New expense' }], narration: 'Select New expense. A form opens.' },
    { type: 'recap', heading: 'Done', bullets: ['Opened the form', 'Submitted it'], narration: 'You opened the form. Then you submitted it.' },
  ],
});

test('plan: a valid plan parses, from an object or a JSON string', () => {
  assert.equal(parsePlan(plan()).scenes.length, 3);
  assert.equal(parsePlan(JSON.stringify(plan())).title, 'Submit an expense');
});

test('plan: every problem is reported at once with a path', () => {
  const bad = plan();
  bad.scenes[0].type = 'step';
  bad.scenes[1].heading = 'one two three four five six seven eight nine ten eleven';
  bad.scenes[2].bullets = ['only one'];
  let err;
  try { parsePlan(bad); } catch (e) { err = e; }
  assert.equal(err.code, 'PLAN_INVALID');
  const paths = err.extra.errors.map((e) => e.path);
  assert.ok(paths.includes('$.scenes.0.type'));
  assert.ok(paths.includes('$.scenes.1.heading'));
  assert.ok(paths.includes('$.scenes.2.bullets'));
});

test('plan: highlights need an image, images must exist in the document', () => {
  const p = plan();
  delete p.scenes[1].image;
  assert.throws(() => parsePlan(p), /problem/);
  assert.throws(() => checkImages(parsePlan(plan()), ['img2']), (e) => e.extra.errors[0].message.includes('img1 is not in this document'));
});

test('envelope: ingest needs a file or text; the file wins over text', () => {
  assert.equal(parseIngestBody({ fileName: 'a.docx', fileBase64: 'AAAA', text: 'x'.repeat(50) }, 1e6).fileName, 'a.docx');
  assert.throws(() => parseIngestBody({ fileName: 'a.docx' }, 1e6), /either/);
  assert.throws(() => parseIngestBody({ fileName: 'a.exe', fileBase64: 'AAAA' }, 1e6), /docx/);
  assert.equal(parseIngestBody({ text: 'Step one. Open the app and select New expense in the corner.' }, 1e6).text.length > 40, true);
  assert.throws(() => parseIngestBody({ fileName: 'a.docx', fileBase64: Buffer.alloc(2000).toString('base64') }, 1000), /limit/);
});

test('envelope: render takes flat brand fields and rejects unknown voices', () => {
  const r = parseRenderBody({ docId: 'abcdefgh12', plan: JSON.stringify(plan()), brandName: 'Brightwater', brandColor: '#0F766E' });
  assert.deepEqual(r.brand, { name: 'Brightwater', primary: '#0F766E' });
  assert.equal(r.voice, 'Sulafat');
  assert.throws(() => parseRenderBody({ docId: 'abcdefgh12', plan: plan(), voice: 'Nope' }), /voice/);
  assert.throws(() => parseRenderBody({ docId: 'abcdefgh12', plan: plan(), brandColor: 'teal' }), /brand/);
});

test('timing: sentence boundaries snap to real pauses, captions stay inside their sentence', () => {
  const s = sentenceTimes('Select New expense. A form opens.', 3, [{ start: 1.5, end: 1.8 }]);
  assert.equal(s.length, 2);
  assert.equal(s[0].end, 1.5);
  assert.equal(s[1].start, 1.8);
  const chunks = captionChunks({ text: 'one two three four five six seven eight nine', start: 0, end: 3 });
  assert.equal(chunks.length, 2);
  assert.ok(Math.abs(chunks[1].end - 3) < 1e-9);
});

test('timing: scenes follow narration length and never overlap', () => {
  const p = parsePlan(plan());
  const voices = p.scenes.map(() => ({ seconds: 3, pauses: [] }));
  const film = layout(p, voices);
  film.scenes.forEach((sc, i) => {
    if (i) assert.ok(Math.abs(sc.start - (film.scenes[i - 1].start + film.scenes[i - 1].duration)) < 1e-6);
    assert.ok(sc.voiceAt > sc.start && sc.voiceAt + 3 < sc.start + sc.duration);
  });
  assert.equal(film.scenes[2].cues.length, 2);
  assert.ok(film.scenes[2].cues[1] > film.scenes[2].cues[0]);
});

test('timing: reveal cues are film times inside their own scene', () => {
  const p = parsePlan(plan());
  const film = layout(p, p.scenes.map(() => ({ seconds: 3, pauses: [] })));
  film.scenes.forEach((sc) => sc.cues.forEach((c) => {
    assert.ok(c >= sc.voiceAt && c <= sc.start + sc.duration, `cue ${c} outside scene ${sc.start}..${sc.start + sc.duration}`);
  }));
});

test('ocr: a phrase is found on one line, topmost first', () => {
  const words = [
    { text: 'New', x: 100, y: 50, w: 40, h: 20, line: '1.1.1' }, { text: 'expense', x: 145, y: 50, w: 80, h: 20, line: '1.1.1' },
    { text: 'New', x: 100, y: 400, w: 40, h: 20, line: '1.2.1' }, { text: 'expense', x: 145, y: 400, w: 80, h: 20, line: '1.2.1' },
  ];
  assert.deepEqual(findPhrase(words, '+ New expense'), { x: 90, y: 40, w: 145, h: 40 });
  assert.equal(findPhrase(words, 'Submit for approval'), null);
});

test('zoom: only small targets zoom, the image always covers the viewport', () => {
  assert.equal(zoomFor({ x: 0, y: 0, w: 900, h: 300 }, { w: 1000, h: 600 }), null);
  const z = zoomFor({ x: 900, y: 20, w: 80, h: 30 }, { w: 1000, h: 600 });
  assert.ok(z.scale <= 2.0 && z.scale > 1.15);
  assert.ok(z.x <= 0 && z.x >= 1000 - 1000 * z.scale);
  assert.ok(z.y <= 0);
});

test('tts helpers: silence is trimmed and pauses are found', () => {
  const rate = 24000;
  const pcm = Buffer.alloc(rate * 2 * 2); // 2 s
  for (let i = 0; i < rate * 2; i += 1) {
    const t = i / rate;
    const loud = (t > 0.5 && t < 0.9) || (t > 1.2 && t < 1.6);
    pcm.writeInt16LE(loud ? Math.round(8000 * Math.sin(i / 3)) : 0, i * 2);
  }
  const trimmed = trimPcm(pcm);
  assert.ok(Math.abs((trimmed.length >> 1) / rate - 1.22) < 0.05);
  const ps = pauses(trimmed);
  assert.equal(ps.length, 1);
  assert.ok(ps[0].end - ps[0].start > 0.2);
});

test('docx: paragraphs, headings, lists and embedded images come out in order', async () => {
  const zip = new JSZip();
  const png = Buffer.from('89504e470d0a1a0a0000000d4948445200000280000001e00806000000', 'hex');
  zip.file('word/document.xml', '<w:document><w:body>'
    + '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Submit an expense</w:t></w:r></w:p>'
    + '<w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>Select New expense &amp; wait.</w:t></w:r></w:p>'
    + '<w:p><w:r><w:drawing><a:blip r:embed="rId5"/></w:drawing></w:r></w:p></w:body></w:document>');
  zip.file('word/_rels/document.xml.rels', '<Relationships><Relationship Id="rId5" Target="media/image1.png"/></Relationships>');
  zip.file('word/media/image1.png', png);
  const r = await readDocx(await zip.generateAsync({ type: 'nodebuffer' }));
  assert.equal(r.text, '# Submit an expense\n- Select New expense & wait.\n[image:img1]');
  assert.equal(r.images.length, 1);
});

test('compile: writes a deterministic HyperFrames project with captions', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'tv-'));
  const docDir = path.join(dir, 'doc');
  await fs.mkdir(docDir);
  await fs.writeFile(path.join(docDir, 'img1.png'), Buffer.from('89504e47', 'hex'));
  const p = parsePlan(plan());
  const doc = { images: [{ id: 'img1', file: 'img1.png', width: 1600, height: 900, words: [{ text: 'New', x: 1300, y: 40, w: 50, h: 22, line: 'a' }, { text: 'expense', x: 1356, y: 40, w: 90, h: 22, line: 'a' }] }] };
  const voices = p.scenes.map(() => ({ seconds: 3, pauses: [] }));
  const a = await compileProject({ plan: p, brand: { name: 'Brightwater' }, voices, doc, docDir, outDir: path.join(dir, 'a') });
  const b = await compileProject({ plan: p, brand: { name: 'Brightwater' }, voices, doc, docDir, outDir: path.join(dir, 'b') });
  const ha = await fs.readFile(path.join(dir, 'a', 'index.html'), 'utf8');
  assert.equal(ha, await fs.readFile(path.join(dir, 'b', 'index.html'), 'utf8'));
  assert.match(ha, /window\.__timelines\["main"\] = tl/);
  assert.match(ha, /class="ring"/);
  assert.deepEqual(a.warnings, []);
  assert.ok((await fs.readFile(path.join(dir, 'a', 'captions.srt'), 'utf8')).startsWith('1\n00:00:01,100 --> '));
  assert.equal(a.duration, b.duration);
});

test('ocr: fuzzy phrase match finds misread button labels, exact still wins', () => {
  const words = [
    { text: 'Submit', x: 10, y: 500, w: 60, h: 20, line: 'b1' }, { text: 'for', x: 75, y: 500, w: 30, h: 20, line: 'b1' }, { text: 'aovrova', x: 110, y: 500, w: 80, h: 20, line: 'b1' },
    { text: 'Submit', x: 10, y: 900, w: 60, h: 20, line: 'p9' }, { text: 'claims', x: 75, y: 900, w: 60, h: 20, line: 'p9' },
  ];
  const box = findPhrase(words, 'Submit for approval');
  assert.equal(box.y, 490);
  assert.equal(findPhrase(words, 'Cancel'), null);
});

test('plan: an empty scene list is a 400 with errors, not a crash', () => {
  assert.throws(() => parsePlan({ title: 'x', scenes: [] }), (e) => e.code === 'PLAN_INVALID' && e.extra.errors.length >= 1);
});

test('ocr: a capitalised label beats the same word inside a sentence higher up', () => {
  const words = [
    { text: 'Add', x: 10, y: 100, w: 30, h: 20, line: 'p1' }, { text: 'the', x: 45, y: 100, w: 30, h: 20, line: 'p1' }, { text: 'receipt', x: 80, y: 100, w: 70, h: 20, line: 'p1' },
    { text: 'Receipt', x: 10, y: 300, w: 70, h: 20, line: 'p2' },
  ];
  assert.equal(findPhrase(words, 'Receipt').y, 290);
});

test('envelope: a quoted data URI from Power Fx JSON() is accepted as the file bytes', () => {
  const b64 = Buffer.from('hello world file').toString('base64');
  const r = parseIngestBody({ fileName: 'a.docx', fileBase64: `"data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,${b64}"` }, 1e6);
  assert.equal(r.buffer.toString(), 'hello world file');
});

test('tts: only the WAV data chunk is audio; the C2PA chunk after it is dropped', () => {
  const { pcmFrom, fadeEdges, wav } = require('../server/tts');
  const samples = Buffer.alloc(4800, 1);
  const c2pa = Buffer.concat([Buffer.from('C2PA'), Buffer.from([16, 0, 0, 0]), Buffer.alloc(16, 0x7f)]);
  const file = Buffer.concat([wav(samples, 24000), c2pa]);
  file.writeUInt32LE(file.length - 8, 4);
  const r = pcmFrom(file, 'audio/wav');
  assert.equal(r.rate, 24000);
  assert.equal(r.pcm.length, samples.length);
  assert.equal(pcmFrom(samples, 'audio/L16;codec=pcm;rate=24000').pcm.length, samples.length);
  const loud = Buffer.alloc(2400 * 2);
  for (let i = 0; i < 2400; i += 1) loud.writeInt16LE(10000, i * 2);
  const f = fadeEdges(loud, 24000);
  assert.equal(f.readInt16LE(0), 0);
  assert.equal(f.readInt16LE(f.length - 2), 0);
  assert.equal(f.readInt16LE(1200 * 2), 10000);
});

test('plan: em and en dashes become commas everywhere (house style: no em dashes)', () => {
  const p = plan();
  p.scenes[0].heading = 'Expenses \u2014 the new way';
  p.scenes[0].sub = 'For all staff\u2014how to claim';
  p.scenes[0].narration = 'Learn this \u2013 quickly.';
  const r = parsePlan(JSON.stringify(p));
  assert.equal(r.scenes[0].heading, 'Expenses, the new way');
  assert.equal(r.scenes[0].sub, 'For all staff, how to claim');
  assert.equal(r.scenes[0].narration, 'Learn this, quickly.');
});

test('timing: sentence boundaries never run backwards after a late pause', () => {
  const s = sentenceTimes('Open. Click. Done.', 3, [{ start: 1.8, end: 2.4 }]);
  s.forEach((x, i) => {
    assert.ok(x.end > x.start, JSON.stringify(x));
    if (i) assert.ok(x.start >= s[i - 1].end);
  });
});

test('jobs: queued renders report their real queue position', async () => {
  const os = require('node:os');
  const fsp = require('node:fs/promises');
  const { createJobs } = require('../server/jobs');
  const dir = await fsp.mkdtemp(path.join(os.tmpdir(), 'tvjobs-'));
  const cfg = { jobsDir: dir, maxQueue: 5, initialRenderSecPerVideoMin: 300, workDir: dir, outDir: dir, deskLockFile: '' };
  const jobs = createJobs({ cfg, log: () => {} });
  const input = { plan: { title: 't', scenes: [] }, doc: { docId: 'd' }, brand: {}, voice: 'Kore', estimateSec: 60 };
  const views = [];
  for (let i = 0; i < 3; i += 1) views.push(await jobs.submit(input));
  const positions = views.map((v) => v.queuePosition);
  assert.ok(positions[2] > 0, `positions ${positions}`);
});
