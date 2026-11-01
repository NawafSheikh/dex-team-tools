"""Live run board: a light page that shows the workday as it runs, made to be filmed.

Missions, the agents working on them in parallel, best-of-both duels and the judge's pick, verifier stamps,
a timeline of who worked when, and a finale when the day is verified. Everything on it is the real run state.
"""
from __future__ import annotations

import html

from . import store
from .kinds import KINDS


def _pick(m: dict) -> str:
    """One line for a best-of-both mission: who the judge picked and why, or what was promoted."""
    bob = m.get("bob") or {}
    return bob.get("why") or ((bob.get("judge") or {}).get("reasons") and
                              f"Judge picked {bob['judge'].get('winner')}: {bob['judge']['reasons']}") or ""


def _duel(m: dict) -> dict | None:
    bob = m.get("bob") or {}
    if m.get("mode") != "best_of_both":
        return None
    state = {True: "passed", False: "failed", None: "working"}
    cands = {a: state[(c.get("verdict") or {}).get("passed")] for a, c in (bob.get("candidates") or {}).items()}
    judge = bob.get("judge") or {}
    return {"round": bob.get("round", 1), "phase": bob.get("phase", ""), "candidates": cands,
            "winner": judge.get("winner", ""), "merge": bool((bob.get("merge") or {}).get("job_id")),
            "final": bob.get("final", "")}


def data(state: dict, events: list[dict], shared: list[str]) -> dict:
    now = store.now_epoch()
    missions = []
    for m in state["missions"]:
        attempts = m.get("attempts", [])
        last = attempts[-1] if attempts else {}
        missions.append({
            "id": m["id"], "title": m["title"], "kind": KINDS[m["kind"]]["label"], "status": m["status"],
            "agent": m["agent"], "why": m["why_agent"], "depends_on": m.get("depends_on", []),
            "chain": [{"agent": a["agent"], "n": a["n"], "reason": a.get("reason", ""), "role": a.get("role", ""),
                       "passed": (a.get("verdict") or {}).get("passed"),
                       "start": a.get("started_epoch"), "end": a.get("finished_epoch")} for a in attempts],
            "mode": m.get("mode", "single"), "pick": _pick(m), "duel": _duel(m), "desk": m.get("desk", ""),
            "started": m.get("started_epoch"), "finished": m.get("finished_epoch"),
            "checks": KINDS[m["kind"]]["checks"],
            "failed": (last.get("verdict") or {}).get("failed", []),
            "packet": m.get("packet", ""),
        })
    return {"run_id": state["run_id"], "title": state["title"], "request": state["request"],
            "status": state["status"], "started": state.get("started_epoch"), "finished": state.get("finished_epoch"),
            "now": now, "missions": missions, "facts": state.get("facts", {}), "shared": shared,
            "events": [{"t": e["epoch"], "event": e["event"], "mission": e.get("mission", ""),
                        "agent": e.get("agent") or e.get("to", ""), "failed": e.get("failed", []),
                        "passed": e.get("passed")} for e in events]}


def page(run_id: str, key: str) -> str:
    return PAGE.replace("__RUN__", html.escape(run_id)).replace("__KEY__", html.escape(key))


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Workday board</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--mute:#6e6e73;--line:#e6e3dd;--accent:#ff5b2e;--ok:#1f9d55;--bad:#d93025;
--warn:#9a6700;--claude:#c96442;--codex:#2f3a4a;--judge:#6b5bd2}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 "Segoe UI",Carlito,system-ui,sans-serif;overflow-x:hidden}
header{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;padding:20px 32px 14px;border-bottom:1px solid var(--line);background:#fff}
h1{margin:0;font-size:24px;font-weight:600}.req{color:var(--mute);margin-top:4px;max-width:1000px}
.live{display:flex;align-items:center;gap:8px;margin-top:10px;font-size:13px;color:var(--mute);flex-wrap:wrap;min-height:24px}
.live b{color:var(--ink)}.pulse{width:9px;height:9px;border-radius:50%;background:var(--accent);animation:pulse 1.2s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(255,91,46,.55)}100%{box-shadow:0 0 0 10px rgba(255,91,46,0)}}
.clock{text-align:right;white-space:nowrap}.clock b{display:block;font:600 44px/1 "Segoe UI",Carlito,sans-serif;font-variant-numeric:tabular-nums}
.clock span{color:var(--mute);font-size:13px}.score{font-size:15px;margin-top:4px}.score b{display:inline;font-size:15px;color:var(--ok)}
main{display:grid;grid-template-columns:1fr 340px;gap:20px;padding:18px 32px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(350px,1fr));gap:14px;align-content:start}
.card{position:relative;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;overflow:hidden;transition:border-color .4s,box-shadow .4s}
.card.run{border-color:#ffd2c4;box-shadow:0 2px 14px rgba(255,91,46,.10)}
.card.run::before{content:"";position:absolute;left:0;top:0;height:3px;width:40%;background:linear-gradient(90deg,transparent,var(--accent),transparent);animation:shimmer 1.6s linear infinite}
@keyframes shimmer{from{left:-40%}to{left:100%}}
.card.done{border-color:#bfe5cf}.card.flash{animation:flash 1.4s ease-out}
@keyframes flash{0%{box-shadow:0 0 0 0 rgba(31,157,85,.55);background:#e8f6ee}100%{box-shadow:0 0 0 18px rgba(31,157,85,0);background:#fff}}
.stamp{position:absolute;left:50%;top:50%;width:120px;height:120px;margin:-60px 0 0 -60px;border-radius:50%;border:5px solid var(--ok);color:var(--ok);
display:grid;place-items:center;font-weight:800;font-size:19px;letter-spacing:.05em;background:rgba(255,255,255,.92);pointer-events:none;
animation:stamp 2.8s cubic-bezier(.2,1.6,.4,1) forwards}
@keyframes stamp{0%{transform:scale(2.6) rotate(-14deg);opacity:0}18%{transform:scale(1) rotate(-14deg);opacity:1}75%{opacity:1}100%{transform:scale(1) rotate(-14deg);opacity:0}}
.vtag{font-size:11px;font-weight:700;color:var(--ok);border:1.5px solid var(--ok);border-radius:5px;padding:0 6px;margin-left:8px;letter-spacing:.04em}
.top{display:flex;justify-content:space-between;align-items:center;gap:8px}
.mid{font-weight:600}.id{color:var(--mute);font-weight:600;margin-right:6px}
.pill{font-size:12px;border-radius:999px;padding:2px 10px;border:1px solid var(--line);white-space:nowrap}
.s-done{background:#e8f6ee;color:var(--ok);border-color:#bfe5cf}.s-failed,.s-blocked{background:#fdecea;color:var(--bad);border-color:#f5c2bd}
.s-running,.s-verifying,.s-judging,.s-merging{background:#fff1ec;color:var(--accent);border-color:#ffd2c4}
.s-retrying,.s-rerouted,.s-waiting_desk{background:#fff7e0;color:var(--warn);border-color:#f1dc9c}.s-planned{color:var(--mute)}
.agent{font-size:12px;font-weight:600;color:#fff;border-radius:6px;padding:1px 7px;margin-right:4px;white-space:nowrap}
.a-claude{background:var(--claude)}.a-codex{background:var(--codex)}.a-judge{background:var(--judge)}
.a-both,.a-merge{background:linear-gradient(90deg,var(--claude) 50%,var(--codex) 50%)}
.bob{font-size:11px;font-weight:600;color:var(--judge);border:1px solid #d9d3f7;border-radius:999px;padding:1px 8px;margin-left:6px}
.why{color:var(--mute);font-size:13px;margin:6px 0}.chain{margin:6px 0;font-size:13px}.arrow{color:var(--mute);margin:0 4px}
.reason{font-size:12px;color:var(--warn);margin-top:2px}.pick{font-size:12.5px;color:var(--judge);margin-top:4px}
.duel{display:grid;grid-template-columns:1fr auto 1fr;gap:8px;align-items:center;margin:8px 0 4px}
.lane{border:1px solid var(--line);border-radius:10px;padding:6px 8px;font-size:12.5px;display:flex;justify-content:space-between;align-items:center;gap:6px}
.lane.win{border-color:var(--judge);box-shadow:0 0 0 2px #e9e5fb}.lane .st{font-size:11.5px;color:var(--mute)}
.lane .st.passed{color:var(--ok)}.lane .st.failed{color:var(--bad)}.lane .st.working::after{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--accent);margin-left:5px;animation:pulse 1.2s infinite}
.vs{font-size:11px;font-weight:700;color:var(--mute)}.tag{font-size:10px;font-weight:700;color:#fff;background:var(--judge);border-radius:4px;padding:0 5px;margin-left:4px}
ul{margin:6px 0 0;padding-left:0;list-style:none;font-size:13px}li{padding:2px 0}
li.ok::before{content:"\2713  ";color:var(--ok);font-weight:700}li.bad::before{content:"\2717  ";color:var(--bad);font-weight:700}li.wait::before{content:"\25CB  ";color:var(--mute)}
.meta{display:flex;justify-content:space-between;color:var(--mute);font-size:12px;margin-top:8px;font-variant-numeric:tabular-nums}
.stopwatch{font-weight:600;color:var(--ink);font-size:14px}
aside .card{margin-bottom:14px}aside h2,.tl h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin:0 0 8px}
.ev{font-size:13px;padding:3px 0;border-bottom:1px dashed var(--line)}.ev time{color:var(--mute);font-variant-numeric:tabular-nums;margin-right:6px}
a{color:var(--ink)}.facts div{font-size:13px;padding:2px 0;transition:background 1s}.facts div.new{background:#fff1ec}.facts b{font-weight:600}
.tl{margin:0 32px 28px;background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.row{display:grid;grid-template-columns:230px 1fr;align-items:center;gap:10px;height:26px}.row .lbl{font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.track{position:relative;height:16px;background:#f3f1ec;border-radius:6px}.bar{position:absolute;top:2px;height:12px;border-radius:5px;opacity:.95}
.bar.open{background-image:linear-gradient(90deg,rgba(255,255,255,0) 60%,rgba(255,255,255,.55));background-blend-mode:normal}
.bar.claude{background-color:var(--claude)}.bar.codex{background-color:var(--codex)}.bar.judge{background-color:var(--judge)}
.bar.fail{outline:2px solid var(--bad);outline-offset:-1px}.bar.half{height:6px}.bar.lane0{top:2px}.bar.lane1{top:9px}.nowline{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--accent)}
#toasts{position:fixed;right:24px;top:160px;display:flex;flex-direction:column;gap:10px;z-index:20}
.toast{background:#fff;border:1px solid var(--line);border-left:5px solid var(--ok);border-radius:10px;padding:10px 14px;min-width:300px;max-width:420px;
box-shadow:0 8px 28px rgba(0,0,0,.12);font-size:14px;animation:tin .4s ease-out}.toast.bad{border-left-color:var(--bad)}.toast.judge{border-left-color:var(--judge)}
.toast.warn{border-left-color:#e3a008}.toast small{display:block;color:var(--mute);font-size:12px}@keyframes tin{from{transform:translateX(120%)}to{transform:none}}
#finale{position:fixed;inset:0;display:none;place-items:center;background:rgba(246,245,242,.86);z-index:30}
#finale .box{background:#fff;border:1px solid var(--line);border-radius:22px;padding:34px 54px;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.15);animation:pop .6s cubic-bezier(.2,1.5,.4,1)}
#finale h3{margin:0;font-size:40px}#finale p{margin:8px 0 0;color:var(--mute);font-size:18px}#finale .big{font:600 64px/1.1 "Segoe UI",Carlito,sans-serif;color:var(--accent);font-variant-numeric:tabular-nums;margin-top:10px}
@keyframes pop{from{transform:scale(.6);opacity:0}to{transform:none;opacity:1}}
.conf{position:fixed;top:-12px;width:9px;height:14px;z-index:31;border-radius:2px;animation:fall linear forwards}
@keyframes fall{to{transform:translateY(110vh) rotate(720deg)}}
</style></head><body>
<header><div><h1 id="title">Workday</h1><div class="req" id="req"></div><div class="live" id="live"></div></div>
<div class="clock"><span>Workday clock</span><b id="clock">0:00</b><div class="score" id="score"></div></div></header>
<main><section class="grid" id="grid"></section>
<aside><div class="card"><h2>Shared state</h2><div class="facts" id="facts"></div></div>
<div class="card"><h2>Deliverables</h2><div id="files"></div></div>
<div class="card"><h2>Activity</h2><div id="events"></div></div></aside></main>
<section class="tl"><h2>Who worked when</h2><div id="timeline"></div></section>
<div id="toasts"></div><div id="finale"><div class="box"><h3 id="fin-title">Workday done</h3><p id="fin-sub"></p><div class="big" id="fin-time"></div></div></div>
<script>
const RUN="__RUN__",KEY="__KEY__";let D=null,skew=0,prev=null,prevFacts=null,finaleShown=false;
const fmt=s=>{if(s==null)return"-";s=Math.max(0,Math.floor(s));const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;return h?`${h}:${String(m).padStart(2,"0")}:${String(x).padStart(2,"0")}`:`${m}:${String(x).padStart(2,"0")}`};
const esc=t=>String(t??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
const now=()=>Date.now()/1000+skew;const tm=e=>new Date(e*1000).toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
const cap=s=>s?s[0].toUpperCase()+s.slice(1):s;const RUNNING=new Set(["running","verifying","judging","merging","retrying","rerouted"]);
const label={run_created:"Workday opened",mission_added:"planned",run_started:"Workday started",mission_dispatched:"handed to",worker_finished:"worker finished",mission_verified:"verified",mission_retry:"retry by",mission_reroute:"rerouted to",mission_failed:"failed",mission_blocked:"blocked",run_finished:"Workday finished",best_of_both_judging:"blind judge compares both",best_of_both_pick:"picked",best_of_both_merging:"merges the best of both:",best_of_both_merge_rejected:"merge failed the verifier, kept",best_of_both_final:"final result from",desk_waiting:"waiting for the desk screen",desk_acquired:"has the desk screen",desk_released:"gave the desk screen back"};
function toast(html,cls){const t=document.createElement("div");t.className="toast "+(cls||"");t.innerHTML=html;document.getElementById("toasts").prepend(t);setTimeout(()=>t.remove(),9000)}
function confetti(){const cols=["#ff5b2e","#c96442","#2f3a4a","#6b5bd2","#1f9d55","#f2b705"];for(let i=0;i<90;i++){const c=document.createElement("div");c.className="conf";c.style.left=Math.random()*100+"vw";c.style.background=cols[i%cols.length];c.style.animationDuration=(2.4+Math.random()*2.2)+"s";c.style.animationDelay=Math.random()*0.8+"s";document.body.appendChild(c);setTimeout(()=>c.remove(),6000)}}
function transitions(){if(!prev){prev=Object.fromEntries(D.missions.map(m=>[m.id,m]));return}
 for(const m of D.missions){const p=prev[m.id];if(!p)continue;const who=m.chain.length?m.chain[m.chain.length-1].agent:m.agent;
  if(p.status!=="done"&&m.status==="done"){toast(`<b>${m.id} verified</b> &middot; ${esc(m.title)}<small>independent verifier &middot; ${fmt((m.finished||now())-m.started)}${m.duel&&m.duel.final?` &middot; final: ${esc(m.duel.final)}`:` &middot; ${esc(cap(who))}`}</small>`);m._flash=true}
  else if(p.status!=="failed"&&m.status==="failed")toast(`<b>${m.id} failed</b> &middot; ${esc(m.title)}<small>${esc((m.failed[0]||{}).name||"")}</small>`,"bad");
  else if(m.status==="rerouted"&&p.status!=="rerouted")toast(`<b>${m.id} rerouted to ${esc(cap(who))}</b><small>${esc((p.failed[0]||{}).name||"failed check")}</small>`,"warn");
  else if(m.status==="retrying"&&p.status!=="retrying")toast(`<b>${m.id} retry</b> &middot; ${esc(cap(who))}<small>${esc((p.failed[0]||{}).name||"")}</small>`,"warn");
  if(m.duel&&m.duel.winner&&!(p.duel&&p.duel.winner))toast(`<b>${m.id}: judge picked ${esc(cap(m.duel.winner))}</b><small>${esc(m.pick).slice(0,140)}</small>`,"judge")}
 prev=Object.fromEntries(D.missions.map(m=>[m.id,m]))}
function card(m){const run=RUNNING.has(m.status),done=m.status==="done";
 const checks=m.checks.map(c=>`<li class="${done?"ok":"wait"}">${esc(c)}</li>`).join("");
 const fails=m.failed.map(f=>`<li class="bad">${esc(f.name)}${f.detail?`: ${esc(f.detail)}`:""}</li>`).join("");
 let chain;if(m.chain.length){chain=m.chain.map((a,i)=>`${i?(a.role==="candidate"&&m.chain[i-1].role==="candidate"?'<span class="arrow">+</span>':'<span class="arrow">&rarr;</span>'):""}<span class="agent a-${a.agent}">${a.agent}</span>${a.passed===true?"&#10003;":a.passed===false?"&#10007;":""}`).join("")}else chain=`<span class="agent a-${m.agent}">${m.agent}</span>`;
 let duel="";if(m.duel){const c=m.duel.candidates,w=m.duel.winner||(m.duel.final&&m.duel.final!=="merge"?m.duel.final:"");
  const lane=a=>`<div class="lane ${w===a?"win":""}"><span><span class="agent a-${a}">${a}</span>${w===a?'<span class="tag">WINNER</span>':""}</span><span class="st ${c[a]||(m.status==="planned"?"waiting":"working")}">${c[a]||(m.status==="planned"?"waiting":"working")}</span></div>`;
  duel=`<div class="duel">${lane("claude")}<span class="vs">VS</span>${lane("codex")}</div>`}
 const short=t=>t.length>150?t.slice(0,147).replace(/\s+\S*$/,"")+" ...":t;
 const reason=m.pick?`<div class="pick" title="${esc(m.pick)}">${esc(short(m.pick))}</div>`:(m.chain.length>1&&!m.duel?`<div class="reason">${esc(m.chain[m.chain.length-1].reason)}</div>`:"");
 const desk=m.desk==="waiting"?'<div class="reason">waiting for the desk screen</div>':"";
 const sw=m.started?fmt((m.finished||now())-m.started):"-";
 return `<div class="card ${run?"run":""} ${done?"done":""} ${m._flash?"flash":""}" id="c-${m.id}"><div class="top"><div class="mid"><span class="id">${m.id}</span>${esc(m.title)}${m.mode==="best_of_both"?'<span class="bob">best of both</span>':""}</div><span class="pill s-${m.status}">${m.status}</span></div>
 <div class="chain">${chain}</div>${duel}${reason}${desk}<div class="why">${esc(m.why)}</div><ul>${fails||checks}</ul>
 ${m._flash?'<div class="stamp">VERIFIED</div>':""}
 <div class="meta"><span>${m.depends_on.length?"after "+m.depends_on.join(", "):"no dependencies"}</span><span><span class="stopwatch">${sw}</span>${done?'<span class="vtag">VERIFIED</span>':""}</span></div></div>`}
function timeline(){const t0=D.started;if(!t0){document.getElementById("timeline").innerHTML='<div class="why">Starts when the workday starts</div>';return}
 const t1=Math.max(D.finished||now(),t0+60),span=t1-t0,pct=t=>Math.min(100,Math.max(0,(t-t0)/span*100));
 document.getElementById("timeline").innerHTML=D.missions.map(m=>`<div class="row"><div class="lbl"><b>${m.id}</b> ${esc(m.title)}</div><div class="track">${m.chain.map(a=>{if(!a.start)return"";const e=a.end||(m.finished||now());
  const lane=a.role==="candidate"?` half lane${a.agent==="codex"?1:0}`:"";
  return `<div class="bar ${a.agent}${lane} ${a.end?"":"open"} ${a.passed===false?"fail":""}" title="${esc(a.agent)} ${fmt(e-a.start)}" style="left:${pct(a.start)}%;width:${Math.max(.6,pct(e)-pct(a.start))}%"></div>`}).join("")}${D.finished?"":`<div class="nowline" style="left:${pct(now())}%"></div>`}</div></div>`).join("")}
function render(){if(!D)return;
 document.getElementById("title").textContent=D.title;document.getElementById("req").textContent=D.request;
 document.getElementById("clock").textContent=fmt(D.started?((D.finished||now())-D.started):0);
 const done=D.missions.filter(m=>m.status==="done").length;document.getElementById("score").innerHTML=`<b>${done}</b> of ${D.missions.length} verified &middot; ${esc(D.status)}`;
 const active=D.missions.filter(m=>RUNNING.has(m.status));const workers=active.flatMap(m=>m.duel&&m.duel.phase==="candidates"?Object.keys(m.duel.candidates).filter(a=>m.duel.candidates[a]==="working").map(a=>[a,m.id]):[[m.chain.length?m.chain[m.chain.length-1].agent:m.agent,m.id]]);
 document.getElementById("live").innerHTML=workers.length?`<span class="pulse"></span><b>${workers.length>1?workers.length+" agents working in parallel":"1 agent working"}</b> ${workers.map(([a,id])=>`<span class="agent a-${a}">${a} ${id}</span>`).join("")}`:(D.finished?"":'<span>Waiting for the next mission</span>');
 document.getElementById("grid").innerHTML=D.missions.map(card).join("");D.missions.forEach(m=>delete m._flash);
 const facts=Object.entries(D.facts);document.getElementById("facts").innerHTML=facts.map(([k,v])=>`<div class="${prevFacts&&!(k in prevFacts)?"new":""}"><b>${esc(k.replace(/_/g," "))}</b>: ${esc(v)}</div>`).join("")||'<div class="why">Filled in as missions are verified</div>';
 document.getElementById("files").innerHTML=D.shared.map(p=>`<div class="ev"><a href="../files/${RUN}/${encodeURI(p).replace(/[#?"]/g,encodeURIComponent)}?k=${KEY}">${esc(p.replace("shared/",""))}</a></div>`).join("")||'<div class="why">None yet</div>';
 document.getElementById("events").innerHTML=D.events.slice().reverse().slice(0,16).map(e=>`<div class="ev"><time>${tm(e.t)}</time>${e.mission?`<b>${e.mission}</b> `:""}${label[e.event]||e.event}${e.agent?` <span class="agent a-${e.agent}">${e.agent}</span>`:""}${e.event==="mission_verified"?(e.passed?" &#10003; done":` &#10007; ${esc(e.failed.join(", "))}`):""}</div>`).join("");
 timeline()}
function finale(){if(finaleShown||!D.finished||!D.started)return;finaleShown=true;const ok=D.missions.filter(m=>m.status==="done").length;
 document.getElementById("fin-title").textContent=ok===D.missions.length?"Workday done":"Workday finished";
 document.getElementById("fin-sub").textContent=`${ok} of ${D.missions.length} missions verified by the independent verifier`;
 document.getElementById("fin-time").textContent=fmt(D.finished-D.started);const f=document.getElementById("finale");f.style.display="grid";
 if(ok===D.missions.length)confetti();setTimeout(()=>f.style.display="none",14000)}
async function poll(){try{const r=await fetch(`${RUN}/data?k=${KEY}`);if(r.ok){const first=!D;D=await r.json();skew=D.now-Date.now()/1000;transitions();render();
 prevFacts=Object.fromEntries(Object.entries(D.facts));if(first&&D.finished)finaleShown=true;else finale()}}catch(e){}}
poll();setInterval(poll,2000);setInterval(()=>{if(D){document.getElementById("clock").textContent=fmt(D.started?((D.finished||now())-D.started):0);
 timeline();document.querySelectorAll(".stopwatch").forEach((el,i)=>{const m=D.missions[i];if(m&&m.started)el.textContent=fmt((m.finished||now())-m.started)})}},500);
</script></body></html>"""
