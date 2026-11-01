'use strict';
// Prototype: compile a hand-written plan with fake narration timings, for looking at frames.
const path = require('node:path');
const { parsePlan } = require('../server/plan-schema');
const { compileProject } = require('../server/compile');

const plan = parsePlan({
  title: 'Submit an expense',
  scenes: [
    { type: 'title', heading: 'How to submit an expense', sub: 'Get your money back in under two minutes, the right way.', image: 'img1', narration: 'This short video shows you how to submit an expense in the new app. It takes about two minutes.' },
    { type: 'overview', heading: 'What you will do', bullets: ['Open a new expense', 'Add the receipt', 'Fill in the details', 'Submit for approval'], narration: 'Here is the plan. First you open a new expense. Then you add the receipt. Next you fill in the details. Finally you submit it for approval.' },
    { type: 'step', heading: 'Open a new expense', body: 'Select New expense in the top right corner.', image: 'img1', highlights: [{ box: [0.80, 0.08, 0.12, 0.05] }], narration: 'Start on the My expenses page. In the top right corner, select New expense. A blank form opens.' },
    { type: 'step', heading: 'Add your receipt', body: 'Drag the photo of your receipt into the upload box.', image: 'img2', narration: 'Drag the photo of your receipt into the upload box. You need a receipt for anything over twenty five euros.' },
    { type: 'note', kind: 'important', heading: 'Submit within 30 days', body: 'Expenses older than 30 days need your manager to approve an exception.', narration: 'One rule to remember. Submit every expense within thirty days, or your manager has to approve an exception.' },
    { type: 'recap', heading: 'You are done', bullets: ['New expense', 'Receipt attached', 'Details filled in', 'Submitted for approval'], closing: 'Questions? Ask Finance in the Expenses channel.', narration: 'That is it. You opened a new expense, attached the receipt, filled in the details and submitted it for approval. Questions go to Finance in the Expenses channel.' },
  ],
});
const fake = (t) => { const s = t.split(/\s+/).length / 2.6; return { seconds: s, pauses: [] }; };
const doc = { images: [{ id: 'img1', file: 'img1.png', width: 1920, height: 1080, words: [] }, { id: 'img2', file: 'img2.png', width: 1920, height: 1080, words: [] }] };
compileProject({ plan, brand: { name: 'Brightwater Logistics', primary: '#0F766E' }, voices: plan.scenes.map((s) => fake(s.narration)), doc,
  docDir: path.resolve(__dirname, '../../work/proto_doc'), outDir: path.resolve(__dirname, '../../work/proto') })
  .then((r) => console.log(JSON.stringify({ duration: r.duration, warnings: r.warnings, starts: r.film.scenes.map((s) => [s.start, s.duration, s.cues]) })));
