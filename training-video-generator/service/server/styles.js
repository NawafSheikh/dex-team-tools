'use strict';

/** Hex to rgba string. */
const rgba = (hex, a) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
};

/** The whole look in one stylesheet, re-themed by the brand colour. Light only. */
function css(primary) {
  return `
:root { --brand: ${primary}; --brand-08: ${rgba(primary, 0.08)}; --brand-14: ${rgba(primary, 0.14)}; --brand-30: ${rgba(primary, 0.3)};
  --ink: #0F172A; --muted: #475569; --line: #E2E8F0; --paper: #F8FAFC; --amber: #B45309; --amber-08: rgba(180, 83, 9, 0.09); }
* { box-sizing: border-box; }
html, body { margin: 0; width: 1920px; height: 1080px; background: var(--paper); }
body { font-family: Inter, sans-serif; color: var(--ink); -webkit-font-smoothing: antialiased; }
#root { position: relative; width: 100%; height: 100%; overflow: hidden; background: var(--paper); }
.bg { position: absolute; inset: 0; background:
  radial-gradient(1100px 700px at 88% -10%, var(--brand-08), transparent 70%),
  radial-gradient(900px 600px at -5% 110%, var(--brand-08), transparent 70%), var(--paper); }
.scene { position: absolute; inset: 0; }
.wrap { position: absolute; inset: 0; }
.topbar { opacity: 0; position: absolute; left: 120px; right: 120px; top: 56px; height: 40px; display: flex; align-items: center; gap: 18px; }
.mark { display: flex; align-items: center; gap: 12px; font-weight: 700; font-size: 28px; letter-spacing: -0.01em; color: var(--ink); }
.mark i { display: block; width: 14px; height: 14px; border-radius: 4px; background: var(--brand); }
.crumb { font-size: 28px; color: var(--muted); font-weight: 500; }
.progress { opacity: 0; position: absolute; right: 120px; top: 74px; display: flex; gap: 8px; }
.progress b { display: block; width: 46px; height: 6px; border-radius: 3px; background: var(--line); overflow: hidden; }
.progress b span { display: block; width: 100%; height: 100%; background: var(--brand); transform-origin: left center; }
.eyebrow { font-size: 28px; font-weight: 600; color: var(--brand); letter-spacing: 0.02em; text-transform: uppercase; }
h1 { margin: 0; font-size: 84px; line-height: 1.04; letter-spacing: -0.03em; font-weight: 750; }
h2 { margin: 0; font-size: 58px; line-height: 1.08; letter-spacing: -0.025em; font-weight: 720; }
.sub { font-size: 32px; line-height: 1.4; color: var(--muted); font-weight: 450; }
.chip { display: inline-flex; align-items: center; gap: 10px; height: 52px; padding: 0 24px; border-radius: 26px; background: #fff;
  border: 1px solid var(--line); font-size: 28px; font-weight: 600; color: var(--muted); }
.chip i { width: 9px; height: 9px; border-radius: 50%; background: var(--brand); display: block; }
.title-text { position: absolute; left: 140px; top: 290px; width: 760px; display: flex; flex-direction: column; gap: 30px; }
.title-text.solo { width: 1300px; }
.card { position: absolute; background: #fff; border-radius: 22px; overflow: hidden; border: 1px solid var(--line);
  box-shadow: 0 30px 80px -30px rgba(15, 23, 42, 0.28), 0 8px 24px -12px rgba(15, 23, 42, 0.12); }
.card .chrome { height: 40px; background: #F1F5F9; border-bottom: 1px solid var(--line); display: flex; align-items: center; gap: 8px; padding-left: 18px; }
.card .chrome i { width: 12px; height: 12px; border-radius: 50%; background: #CBD5E1; display: block; }
.viewport { position: absolute; left: 0; right: 0; bottom: 0; overflow: hidden; }
.stage { position: absolute; left: 0; top: 0; transform-origin: 0 0; }
.stage img { display: block; width: 100%; height: 100%; }
.ring { position: absolute; border-radius: 12px; border: 4px solid var(--brand); box-shadow: 0 0 0 6px var(--brand-30), 0 0 0 3000px rgba(15, 23, 42, 0.16); opacity: 0; }
.steptext { position: absolute; left: 120px; top: 230px; width: 560px; display: flex; flex-direction: column; gap: 28px; }
.steptext.solo { left: 260px; width: 1400px; top: 330px; }
.num { width: 92px; height: 92px; border-radius: 26px; background: var(--brand); color: #fff; display: flex; align-items: center; justify-content: center;
  font-size: 48px; font-weight: 750; box-shadow: 0 16px 36px -14px var(--brand); }
.body { font-size: 34px; line-height: 1.42; color: var(--muted); font-weight: 450; }
.list { display: flex; flex-direction: column; gap: 22px; margin-top: 18px; }
.row { display: flex; align-items: center; gap: 26px; height: 96px; padding: 0 34px; background: #fff; border: 1px solid var(--line);
  border-radius: 20px; font-size: 36px; font-weight: 560; box-shadow: 0 10px 30px -18px rgba(15, 23, 42, 0.2); }
.row .n { width: 52px; height: 52px; border-radius: 15px; background: var(--brand-14); color: var(--brand); display: flex; align-items: center;
  justify-content: center; font-size: 26px; font-weight: 750; flex: none; }
.row svg { width: 52px; height: 52px; flex: none; }
.listscene { position: absolute; left: 260px; right: 260px; top: 190px; display: flex; flex-direction: column; gap: 14px; }
.note { position: absolute; left: 330px; right: 330px; top: 260px; padding: 64px 72px; background: #fff; border-radius: 28px; border: 1px solid var(--line);
  box-shadow: 0 30px 80px -34px rgba(15, 23, 42, 0.3); display: flex; flex-direction: column; gap: 26px; }
.note.important { border-left: 10px solid var(--amber); }
.note.tip { border-left: 10px solid var(--brand); }
.tag { align-self: flex-start; height: 46px; padding: 0 22px; border-radius: 23px; display: flex; align-items: center; font-size: 28px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; }
.important .tag { background: var(--amber-08); color: var(--amber); }
.tip .tag { background: var(--brand-14); color: var(--brand); }
.note .body { font-size: 40px; color: var(--ink); font-weight: 500; }
.closing { font-size: 34px; color: var(--brand); font-weight: 650; margin-top: 18px; }
.captions { position: absolute; left: 0; right: 0; bottom: 64px; height: 120px; }
.cap { position: absolute; left: 0; right: 0; bottom: 0; display: flex; justify-content: center; }
.cap span { max-width: 1400px; padding: 12px 30px; border-radius: 16px; background: rgba(255, 255, 255, 0.96); color: var(--ink); font-size: 38px;
  border: 1px solid var(--line); box-shadow: 0 12px 30px -14px rgba(15, 23, 42, 0.3);
  line-height: 1.3; font-weight: 550; text-align: center; letter-spacing: -0.005em; }
`;
}

module.exports = { css, rgba };
