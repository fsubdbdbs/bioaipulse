/* BioAI-Pulse — logika PWA (v2) */

const State = {
  token: localStorage.getItem("pulse_token") || null,
  goal: localStorage.getItem("pulse_goal") || "maintain",
  data: null, report: null, tab: "today", plan: "sport",
  chat: [], charts: {}, map: null, trendMetric: "readiness",
};

if (window.Chart) { Chart.defaults.animation = false; Chart.defaults.font.family = "-apple-system, system-ui, sans-serif"; }

const $ = (s) => document.querySelector(s);
const el = (h) => { const t = document.createElement("template"); t.innerHTML = h.trim(); return t.content.firstElementChild; };
const PL_M = ["stycznia","lutego","marca","kwietnia","maja","czerwca","lipca","sierpnia","września","października","listopada","grudnia"];
const PL_D = ["niedziela","poniedziałek","wtorek","środa","czwartek","piątek","sobota"];
const fmtDate = (iso) => { const d = new Date(iso); return `${PL_D[d.getDay()]}, ${d.getDate()} ${PL_M[d.getMonth()]}`; };
const hm = (m) => m == null ? "—" : `${Math.floor(m/60)}h ${Math.round(m%60)}min`;
const timeOf = (iso) => { if (!iso) return "—"; const d = new Date(iso); return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`; };
const num = (n,d=0) => n == null ? "—" : Number(n).toLocaleString("pl-PL",{maximumFractionDigits:d});
const esc = (s) => s.replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

function toast(msg) {
  const t = el(`<div class="toast">${msg}</div>`); document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

/* API */
async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { "Content-Type":"application/json", ...(State.token?{Authorization:`Bearer ${State.token}`}:{}) , ...(opts.headers||{}) } });
  if (res.status === 401 && !path.includes("login")) { logout(); throw new Error("unauthorized"); }
  return res.json();
}

/* LOGIN */
let pinBuf = "";
function setupLogin() {
  const dots = $("#pinDots").children, err = $("#pinError");
  const paint = () => { for (let i=0;i<4;i++) dots[i].classList.toggle("on", i<pinBuf.length); };
  $("#keypad").addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const k = b.dataset.k; err.textContent = "";
    if (k==="del") pinBuf = pinBuf.slice(0,-1);
    else if (k==="clear") pinBuf = "";
    else if (pinBuf.length<4) pinBuf += k;
    paint();
    if (pinBuf.length===4) {
      const pin = pinBuf;
      const r = await api("/api/login",{method:"POST",body:JSON.stringify({pin})}).catch(()=>({ok:false}));
      if (r.ok) { State.token=r.token; localStorage.setItem("pulse_token",r.token); pinBuf=""; paint(); enterApp(); }
      else { err.textContent="Błędny PIN"; pinBuf=""; paint(); navigator.vibrate&&navigator.vibrate(120); }
    }
  });
}
function logout() { State.token=null; localStorage.removeItem("pulse_token"); $("#app").classList.add("hidden"); $("#login").classList.remove("hidden"); }

/* BOOT */
async function enterApp() {
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
  $("#view").innerHTML = `<div class="skeleton">Ładowanie danych…</div>`;
  try { await loadData(); } catch { return; }
  if (State.data.is_demo) $("#demoBanner").classList.remove("hidden");
  render();
}
async function loadData() {
  [State.data, State.report] = await Promise.all([
    api(`/api/data?goal=${State.goal}`),
    api("/api/report").catch(()=>null),
  ]);
  // zaznaczone cele na dziś
  const ch = await api("/api/goals/check").catch(()=>({checked:[]}));
  State.checkedGoals = ch.checked || [];
}

/* RINGS */
function ring(score, size=196, stroke=16) {
  const r=(size-stroke)/2, c=2*Math.PI*r, pct=Math.max(0,Math.min(100,score||0))/100;
  const col = score>=80?"#2dd4a7":score>=60?"#19d3a2":score>=40?"#f5a524":"#f25f5c";
  return `<svg width="${size}" height="${size}"><circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="var(--ringbg)" stroke-width="${stroke}"/><circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${col}" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c*(1-pct)}" style="transition:stroke-dashoffset 1s"/></svg>`;
}
function miniRing(val, goal, color, size=62, stroke=7) {
  const r=(size-stroke)/2, c=2*Math.PI*r, pct=Math.max(0,Math.min(1,(val||0)/goal));
  return `<span class="mr-svg"><svg width="${size}" height="${size}" style="transform:rotate(-90deg)"><circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="var(--ringbg)" stroke-width="${stroke}"/><circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${color}" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c*(1-pct)}"/></svg></span>`;
}
function deltaB(val, base, invert=false, unit="") {
  if (val==null||base==null) return "";
  const d=val-base, good=invert?d<0:d>0, cls=Math.abs(d)<0.5?"flat":good?"up":"down", s=d>0?"+":"";
  return `<span class="delta ${cls}">${s}${num(d,1)}${unit}</span>`;
}
function vital(label, value, unit="", delta="") {
  return `<div class="vital"><div class="vt">${label}</div><div class="vv">${value}<small>${unit?" "+unit:""}</small>${delta}</div></div>`;
}

/* ROUTER */
async function render() {
  const v = $("#view");
  Object.values(State.charts).forEach(c => c&&c.destroy()); State.charts = {};
  if (State.map) { State.map.remove(); State.map = null; }
  const map = { today:renderToday, trends:renderTrends, workouts:renderWorkouts, coach:renderCoach, profile:renderProfile };
  v.innerHTML = "";
  const result = map[State.tab]();
  const node = result instanceof Promise ? await result : result;
  node.classList.add("fade"); v.appendChild(node);
}

function goalChip() {
  const g = State.data.goals_catalog[State.goal] || {label:"Utrzymanie",emoji:"⚖️"};
  return `<div class="goal-chip">${g.emoji} ${g.label}</div>`;
}

/* TODAY — konfigurowalny ekran główny (widgety) */
const byScore = (v) => v>=80?"#2dd4a7":v>=60?"#19d3a2":v>=40?"#f5a524":"#f25f5c";
function ringGeneric(pct, color, size=196, stroke=16) {
  const r=(size-stroke)/2, c=2*Math.PI*r, p=Math.max(0,Math.min(100,pct||0))/100;
  return `<svg width="${size}" height="${size}"><circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="var(--ringbg)" stroke-width="${stroke}"/><circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${color}" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c*(1-p)}" style="transition:stroke-dashoffset 1s var(--ease-out)"/></svg>`;
}
const HERO_METRICS = {
  readiness:   {title:"Daily Readiness", tag:()=>"z opaski", val:d=>d.readiness.score, big:v=>v, sub:d=>d.readiness.label||"", pct:(d,v)=>v, color:(d,v)=>byScore(v)},
  sleep_score: {title:"Sleep Score", tag:()=>"z opaski", val:d=>(d.today.sleep||{}).sleep_score, big:v=>v, sub:()=>"jakość snu", pct:(d,v)=>v, color:(d,v)=>byScore(v)},
  steps:       {title:"Kroki", tag:()=>"cel 8 000", val:d=>d.today.steps, big:v=>num(v), sub:()=>"kroki / 8 000", pct:(d,v)=>v/8000*100, color:()=>"#6d7cff"},
  azm:         {title:"Minuty strefy", tag:()=>"cel 30", val:d=>d.today.active_zone_minutes, big:v=>num(v), sub:()=>"min / 30", pct:(d,v)=>v/30*100, color:()=>"#19d3a2"},
  hrv:         {title:"HRV", tag:()=>"regeneracja", val:d=>d.today.hrv_rmssd, big:v=>num(v), sub:()=>"ms (RMSSD)", pct:(d,v)=>v/((d.baselines.hrv||60)*1.5)*100, color:()=>"#2dd4a7"},
  cardio_load: {title:"Obciążenie kardio", tag:()=>"trening", val:d=>d.today.cardio_load, big:v=>num(v), sub:()=>"Cardio Load", pct:(d,v)=>v/200*100, color:()=>"#f5a524"},
};
const DEFAULT_LAYOUT = ["hero","goals_today","weekly","coach_tip","activity","sleep","fitness","resilience","vitals","zones","hr247"];

function wHero(d) {
  const m = HERO_METRICS[State.heroMetric] || HERO_METRICS.readiness;
  const v = m.val(d), pct = v==null?0:m.pct(d,v), color = v==null?"#f25f5c":m.color(d,v);
  const card = el(`<div class="card ready-card">
    <h3 style="display:flex;justify-content:space-between;align-items:center">${m.title} <span class="src-tag">${m.tag(d)}</span></h3>
    ${State.editMode?heroPicker():""}
    <div class="ring-wrap">${ringGeneric(pct,color)}<div class="ring-center"><div class="big">${v==null?"—":m.big(v)}</div><div class="lbl">${m.sub(d,v)}</div></div></div>
    ${State.heroMetric==="readiness"?`<div class="ready-summary">${d.readiness.summary||""}</div><div class="factors">${(d.readiness_factors||[]).map(f=>`<div class="factor"><span class="fd ${f.status}"></span>${f.name} <span class="fn">${f.note}</span></div>`).join("")}</div>`:""}
  </div>`);
  card.querySelectorAll(".hero-metric-pick button").forEach(btn=>btn.addEventListener("click",(e)=>{e.stopPropagation();State.heroMetric=btn.dataset.hm;saveLayout();render();}));
  return card;
}
function heroPicker(){ return `<div class="hero-metric-pick">${Object.entries(HERO_METRICS).map(([k,m])=>`<button data-hm="${k}" class="${k===State.heroMetric?"active":""}">${m.title}</button>`).join("")}</div>`; }

function wActivity(d){ const t=d.today; return el(`<div class="card"><h3>Aktywność dziś</h3><div class="rings3">
  <div class="mini-ring">${miniRing(t.steps,8000,"#6d7cff")}<div class="rv">${num(t.steps)}</div><div class="rl">kroki / 8 000</div></div>
  <div class="mini-ring">${miniRing(t.active_zone_minutes,30,"#19d3a2")}<div class="rv">${num(t.active_zone_minutes)}</div><div class="rl">min strefy / 30</div></div>
  <div class="mini-ring">${miniRing(t.calories_kcal,2600,"#f5a524")}<div class="rv">${num(t.calories_kcal)}</div><div class="rl">kcal / 2 600</div></div>
  </div><div class="sub" style="text-align:center;margin-top:12px">Dystans ${num(t.distance_km,2)} km · ${num(t.active_minutes)} min ruchu</div></div>`); }

function wSleep(d){ const s=d.today.sleep||{}, st=s.stages_minutes||{}, total=s.total_minutes||0;
  const deepPct=total?Math.round(((st.deep||0)+(st.rem||0))/total*100):0;
  const sc=el(`<div class="card"><h3 style="display:flex;justify-content:space-between">Sen <span class="src-tag">Sleep Score: ${s.sleep_score??"—"}/100</span></h3><div class="sleep-big"><div class="h">${hm(total)}</div><div class="sub">${timeOf(s.sleep_start)} → ${timeOf(s.sleep_end)}</div></div></div>`);
  [["Głęboki","deep","#5b67ff"],["REM","rem","#a855f7"],["Lekki","light","#38bdf8"],["Czuwanie","awake","#64748b"]].forEach(([nm,k,col])=>{const mn=st[k]||0,pct=total?Math.round(mn/total*100):0;sc.appendChild(el(`<div class="stage-row"><span class="dot" style="background:${col}"></span><span class="nm">${nm}</span><span class="bar"><i style="width:${pct}%;background:${col}"></i></span><span class="mn">${mn}min</span></div>`));});
  sc.appendChild(el(`<div class="sub" style="margin-top:8px">Deep + REM: ${deepPct}% · regularność: ${d.consistency?d.consistency.label.toLowerCase():"—"}</div>`)); return sc; }

function wVitals(d){ const t=d.today,b=d.baselines; return el(`<div class="card"><h3>Parametry życiowe</h3><div class="vitals">
  ${vital("Tętno spocz.",num(t.resting_hr_bpm),"bpm",deltaB(t.resting_hr_bpm,b.rhr,true))}
  ${vital("HRV",num(t.hrv_rmssd),"ms",deltaB(t.hrv_rmssd,b.hrv,false))}
  ${vital("SpO2",num(t.spo2_pct,0),"%",deltaB(t.spo2_pct,b.spo2,false))}
  ${vital("Oddech",num(t.respiration_rate,1),"/min","")}
  ${vital("Temp. skóry",(t.skin_temp_variation_c>=0?"+":"")+num(t.skin_temp_variation_c,1),"°C","")}
  ${vital("Obciążenie",num(t.cardio_load),"","")}
  </div></div>`); }

function wZones(d){ const z=d.today.hr_zones_minutes||{},zmax=Math.max(1,z.fat_burn||0,z.cardio||0,z.peak||0);
  return el(`<div class="card"><h3>Strefy tętna dziś</h3><div class="zones">
  <div class="zone"><span class="zn">Spalanie</span><span class="zbar"><i style="width:${(z.fat_burn||0)/zmax*100}%;background:#19d3a2"></i></span><span class="zm">${z.fat_burn||0} min</span></div>
  <div class="zone"><span class="zn">Cardio</span><span class="zbar"><i style="width:${(z.cardio||0)/zmax*100}%;background:#f5a524"></i></span><span class="zm">${z.cardio||0} min</span></div>
  <div class="zone"><span class="zn">Szczytowa</span><span class="zbar"><i style="width:${(z.peak||0)/zmax*100}%;background:#f25f5c"></i></span><span class="zm">${z.peak||0} min</span></div>
  </div><div class="sub" style="margin-top:10px">Rytm serca: ${d.today.afib_status}</div></div>`); }

function wHr247(d){ if(!(d.today.hr_series&&d.today.hr_series.length)) return null; return el(`<div class="card"><h3>Tętno 24/7</h3><div class="chart-box"><canvas id="cHr247"></canvas></div></div>`); }

function wInsights(d){ if(!(d.insights&&d.insights.length)) return null; const c=el(`<div class="card"><h3>Spostrzeżenia</h3></div>`); d.insights.forEach(i=>c.appendChild(el(`<div class="insight ${i.type}" style="margin-bottom:8px"><div class="ic">${i.icon}</div><div><div class="it">${i.title}</div><div class="ix">${i.text}</div></div></div>`))); return c; }

function wCoachTip(d){ const sport=d.action_plans.find(p=>p.id==="sport"), ins=(d.insights||[])[0];
  const card=el(`<div class="card coach-tip"><h3>Coach — na teraz</h3></div>`);
  card.appendChild(el(`<div class="ct-row"><span class="ct-ic">🧠</span><div><b>${d.readiness.label||"Gotowość"}:</b> ${d.readiness.summary||""}</div></div>`));
  if(sport) card.appendChild(el(`<div class="ct-row"><span class="ct-ic">${sport.icon}</span><div><b>${sport.headline||"Plan"}:</b> ${sport.items[0]}</div></div>`));
  if(ins) card.appendChild(el(`<div class="ct-row"><span class="ct-ic">${ins.icon}</span><div>${ins.title}</div></div>`));
  const ask=el(`<button class="btn ghost ask">Zapytaj coacha →</button>`); ask.addEventListener("click",()=>switchTab("coach")); card.appendChild(ask); return card; }

/* ---- WIDGET: Cele na dziś ---- */
function wGoalsToday(d) {
  const tasks = d.daily_goals || [];
  if (!tasks.length) return null;
  const checked = State.checkedGoals || [];
  const done = tasks.filter(t => checked.includes(t.id)).length;
  const pct = Math.round(done / tasks.length * 100);

  const card = el(`<div class="card"><h3>Cele na dziś</h3>
    <div class="goals-progress">
      <div class="gp-bar"><i style="width:${pct}%"></i></div>
      <span class="gp-lbl">${done}/${tasks.length}</span>
    </div>
    <div class="goals-today" id="gtList"></div>
  </div>`);

  const list = card.querySelector("#gtList");
  tasks.forEach(t => {
    const isDone = checked.includes(t.id);
    const row = el(`<div class="gtask ${isDone ? "done" : ""}" data-id="${t.id}">
      <span class="gt-ic">${t.icon}</span>
      <div style="flex:1"><div class="gt-text">${t.text}</div><div class="gt-cat">${t.cat}</div></div>
      <span class="gt-check">${isDone ? "✓" : ""}</span>
    </div>`);
    row.addEventListener("click", () => toggleGoal(t.id, card, d));
    list.appendChild(row);
  });
  return card;
}

async function toggleGoal(id, card, d) {
  const ch = State.checkedGoals || [];
  const idx = ch.indexOf(id);
  if (idx >= 0) ch.splice(idx, 1); else ch.push(id);
  State.checkedGoals = ch;
  // persist
  api("/api/goals/check", { method: "POST", body: JSON.stringify({ checked: ch }) }).catch(() => {});
  // re-render just this widget
  const fresh = wGoalsToday(d);
  if (fresh && card.parentNode) card.parentNode.replaceChild(fresh, card);
}

function wWorkoutMini(d){ let last=null; d.history.slice(-7).forEach(e=>(e.workouts||[]).forEach(w=>last=w)); if(!last) return null;
  const c=el(`<div class="card"><h3>Ostatni trening</h3></div>`);
  const row=el(`<div class="wk" style="margin:0"><div class="we">${WK_EMOJI[last.type]||"🏅"}</div><div class="wmain"><div class="wtitle">${last.type}</div><div class="wsub">${fmtDate(last.start)} · ${last.duration_min} min · ${last.avg_hr} bpm</div></div><div class="wstat"><div class="wbig">${last.distance_km?num(last.distance_km,1):last.duration_min}</div><div class="wlbl">${last.distance_km?"km":"min"}</div></div></div>`);
  row.addEventListener("click",()=>showWorkout(last)); c.appendChild(row); return c; }

/* ---- WIDGET: Resilience ---- */
function wResilience(d) {
  const r = d.resilience; if (!r || r.score == null) return null;
  const col = r.score>=75?"#2dd4a7":r.score>=50?"#f5a524":"#f25f5c";
  const c = r.components||{};
  const card = el(`<div class="card"><h3>Odporność (Resilience)</h3>
    <div class="resilience">
      <div class="res-ring">${ringGeneric(r.score, col, 80, 9)}</div>
      <div class="res-text"><div class="rl">${r.label}</div><div class="rd">${r.description||""}</div></div>
    </div>
    <div class="res-bars">
      <div class="res-bar"><span class="rb-lbl">Trend HRV</span><span class="rb"><i style="width:${c.hrv_trend||0}%;background:var(--accent)"></i></span><span class="rb-val">${c.hrv_trend||0}</span></div>
      <div class="res-bar"><span class="rb-lbl">Reg. snu</span><span class="rb"><i style="width:${c.sleep_regularity||0}%;background:var(--accent2)"></i></span><span class="rb-val">${c.sleep_regularity||0}</span></div>
      <div class="res-bar"><span class="rb-lbl">Gotowość śr.</span><span class="rb"><i style="width:${c.readiness_avg||0}%;background:#a855f7"></i></span><span class="rb-val">${c.readiness_avg||0}</span></div>
    </div>
  </div>`); return card;
}

/* ---- WIDGET: Weekly Summary ---- */
function wWeekly(d) {
  const w = d.weekly; if (!w) return null;
  return el(`<div class="card"><h3>Ten tydzień (${w.days} dni)</h3>
    <div class="wk-grid">
      <div class="wk-stat"><div class="wv">${num(w.total_steps)}</div><div class="wl">kroków łącznie</div></div>
      <div class="wk-stat"><div class="wv">${w.workouts_count}</div><div class="wl">treningów</div></div>
      <div class="wk-stat"><div class="wv">${num(w.total_azm)}</div><div class="wl">min strefy</div></div>
      <div class="wk-stat"><div class="wv">${w.avg_sleep_score??'—'}</div><div class="wl">śr. Sleep Score</div></div>
    </div>
    <div class="load-bar">
      <div class="lb"><span>Obciążenie kardio</span><span class="muted">${w.total_cardio_load}/${w.cardio_load_target} pkt</span></div>
      <div class="lbr"><i style="width:${w.cardio_load_pct}%"></i></div>
    </div>
  </div>`);
}

/* ---- WIDGET: VO2Max + Sleep Efficiency ---- */
function wFitness(d) {
  const eff = d.sleep_efficiency, vo2 = d.vo2max;
  if (!eff && !vo2) return null;
  return el(`<div class="card"><h3>Kondycja</h3><div class="vitals">
    ${eff ? vital("Wydajność snu", num(eff,1), "%", "") : ""}
    ${vo2 ? vital("VO2 Max (szac.)", num(vo2,1), "ml/kg/min", "") : ""}
  </div><div class="sub" style="margin-top:8px;font-size:12px">Wydajność snu = czas snu / czas w łóżku · VO2Max szacunkowy z tętna</div></div>`);
}

const WIDGETS = {
  hero:       {title:"Główny wskaźnik",  render:wHero},
  goals_today:{title:"Cele na dziś",     render:wGoalsToday},
  weekly:     {title:"Tydzień",          render:wWeekly},
  coach_tip:  {title:"Porada coacha",    render:wCoachTip},
  activity:   {title:"Aktywność",        render:wActivity},
  sleep:      {title:"Sen",              render:wSleep},
  vitals:     {title:"Parametry",        render:wVitals},
  fitness:    {title:"Kondycja",         render:wFitness},
  resilience: {title:"Odporność",        render:wResilience},
  zones:      {title:"Strefy tętna",     render:wZones},
  hr247:      {title:"Tętno 24/7",       render:wHr247},
  insights:   {title:"Spostrzeżenia",    render:wInsights},
  workout:    {title:"Ostatni trening",  render:wWorkoutMini},
};

function renderToday() {
  const d=State.data;
  if(!State.layout) State.layout = JSON.parse(localStorage.getItem("pulse_layout")||"null") || [...DEFAULT_LAYOUT];
  if(!State.heroMetric) State.heroMetric = localStorage.getItem("pulse_hero") || "readiness";
  const wrap=el(`<div></div>`);
  const head=el(`<div class="head"><div><h2>Cześć, Franek</h2><div class="date">${fmtDate(d.today.fetched_at)}</div></div></div>`);
  const eb=el(`<button class="edit-toggle ${State.editMode?"on":""}" aria-label="Dostosuj ekran">${State.editMode?"Gotowe":"✎"}</button>`);
  eb.addEventListener("click",()=>{State.editMode=!State.editMode;render();}); head.appendChild(eb);
  wrap.appendChild(head);
  const g=d.goals_catalog[State.goal]||{label:"Utrzymanie",emoji:"⚖️"};
  const gb=el(`<button class="goal-bar"><span>${g.emoji} Cel: <b>${g.label}</b></span><span class="ga">zmień →</span></button>`);
  gb.addEventListener("click",()=>switchTab("coach")); wrap.appendChild(gb);

  State.layout.forEach((id,idx)=>{ const def=WIDGETS[id]; if(!def) return; const node=def.render(d); if(!node) return;
    wrap.appendChild(State.editMode?wrapEditing(node,idx):node); });

  if(State.editMode){
    const avail=Object.keys(WIDGETS).filter(k=>!State.layout.includes(k));
    if(avail.length){ const add=el(`<div class="add-widgets"><h3>Dodaj widget</h3><div class="add-grid"></div></div>`); const g=add.querySelector(".add-grid");
      avail.forEach(k=>{const ch=el(`<div class="add-chip">＋ ${WIDGETS[k].title}</div>`);ch.addEventListener("click",()=>{State.layout.push(k);saveLayout();render();});g.appendChild(ch);}); wrap.appendChild(add); }
    const rs=el(`<button class="btn ghost">↺ Przywróć domyślny układ</button>`); rs.addEventListener("click",()=>{State.layout=[...DEFAULT_LAYOUT];State.heroMetric="readiness";saveLayout();render();}); wrap.appendChild(rs);
  }
  setTimeout(()=>paintTodayCharts(d),30);
  return wrap;
}
function wrapEditing(node,idx){ node.classList.add("widget","editing");
  const ctl=el(`<div class="wctl"></div>`);
  const up=el(`<button ${idx===0?"disabled style=opacity:.3":""}>↑</button>`); up.addEventListener("click",()=>moveWidget(idx,-1));
  const dn=el(`<button ${idx===State.layout.length-1?"disabled style=opacity:.3":""}>↓</button>`); dn.addEventListener("click",()=>moveWidget(idx,1));
  const rm=el(`<button class="rm">✕</button>`); rm.addEventListener("click",()=>{State.layout.splice(idx,1);saveLayout();render();});
  ctl.append(up,dn,rm); node.appendChild(ctl); return node; }
function moveWidget(idx,dir){ const t=idx+dir; if(t<0||t>=State.layout.length) return; const a=State.layout; [a[idx],a[t]]=[a[t],a[idx]]; saveLayout(); render(); }
function saveLayout(){ localStorage.setItem("pulse_layout",JSON.stringify(State.layout)); localStorage.setItem("pulse_hero",State.heroMetric); }
function paintTodayCharts(d){ const t=d.today;
  if(document.getElementById("cHr247")&&t.hr_series){ const lab=t.hr_series.map(p=>timeOf(p.t)),data=t.hr_series.map(p=>p.bpm);
    mkChart("cHr247",{type:"line",data:{labels:lab,datasets:[{data,borderColor:"#f25f5c",backgroundColor:"#f25f5c22",fill:true,tension:.4,pointRadius:0,borderWidth:2}]},options:baseOpts({scales:{x:{grid:gc,ticks:{color:tc,maxTicksLimit:6}},y:{grid:gc,ticks:{color:tc}}}})}); } }
function switchTab(name){ State.tab=name; document.querySelectorAll(".tab").forEach(t=>t.classList.toggle("active",t.dataset.tab===name)); render(); window.scrollTo(0,0); }

/* CHART helpers */
const gc = {color:"rgba(255,255,255,.05)"}, tc = "#8b9ac0";
function baseOpts(extra={}) { return { responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{grid:gc,ticks:{color:tc,maxTicksLimit:7,maxRotation:0}},y:{grid:gc,ticks:{color:tc}}}, ...extra }; }
function mkChart(id,cfg){ const cv=document.getElementById(id); if(cv) State.charts[id]=new Chart(cv.getContext("2d"),cfg); }
const labelsOf = (h)=>h.map(e=>{const d=new Date(e.fetched_at);return `${d.getDate()}.${d.getMonth()+1}`;});

/* TRENDS */
const TREND_METRICS = {
  readiness: {label:"Gotowość", color:"#6d7cff", get:e=>(e.daily_readiness||{}).score, base:b=>b.readiness, type:"line"},
  sleep_score: {label:"Sleep Score", color:"#a855f7", get:e=>(e.sleep||{}).sleep_score, base:b=>b.sleep_score, type:"line"},
  sleep: {label:"Sen (h)", color:"#38bdf8", get:e=>((e.sleep||{}).total_minutes||0)/60, type:"barSleep"},
  rhr: {label:"Tętno spocz.", color:"#f25f5c", get:e=>e.resting_hr_bpm, base:b=>b.rhr, type:"line"},
  hrv: {label:"HRV", color:"#2dd4a7", get:e=>e.hrv_rmssd, base:b=>b.hrv, type:"line"},
  steps: {label:"Kroki", color:"#6d7cff", get:e=>e.steps, type:"bar"},
  spo2: {label:"SpO2", color:"#19d3a2", get:e=>e.spo2_pct, base:b=>b.spo2, type:"line"},
  cardio_load: {label:"Obciążenie", color:"#f5a524", get:e=>e.cardio_load, type:"bar"},
};
function renderTrends() {
  const d=State.data, hist=d.history.slice(-14), labels=labelsOf(hist), wrap=el(`<div></div>`);
  wrap.appendChild(el(`<div class="head"><div><h2>Trendy</h2><div class="date">Ostatnie 14 dni</div></div></div>`));
  const seg=el(`<div class="seg"></div>`);
  Object.entries(TREND_METRICS).forEach(([k,m])=>{
    const btn=el(`<button class="${k===State.trendMetric?"active":""}">${m.label}</button>`);
    btn.addEventListener("click",()=>{State.trendMetric=k; render();});
    seg.appendChild(btn);
  });
  wrap.appendChild(seg);
  const m=TREND_METRICS[State.trendMetric];
  wrap.appendChild(el(`<div class="card"><h3>${m.label}</h3><div class="chart-box"><canvas id="cTrend"></canvas></div></div>`));
  setTimeout(()=>{
    const data=hist.map(m.get);
    if (m.type==="barSleep") {
      mkChart("cTrend",{type:"bar",data:{labels,datasets:[{data,backgroundColor:data.map(h=>h>=7?"#2dd4a7":h>=6?"#f5a524":"#f25f5c"),borderRadius:6}]},options:baseOpts({scales:{y:{suggestedMin:0,suggestedMax:10,grid:gc,ticks:{color:tc}},x:{grid:gc,ticks:{color:tc,maxTicksLimit:7}}}})});
    } else if (m.type==="bar") {
      mkChart("cTrend",{type:"bar",data:{labels,datasets:[{data,backgroundColor:m.color,borderRadius:6}]},options:baseOpts()});
    } else {
      const ds=[{data,borderColor:m.color,backgroundColor:m.color+"22",fill:true,tension:.35,pointRadius:2,borderWidth:2}];
      const base=m.base?m.base(d.baselines):null;
      if (base!=null) ds.push({data:labels.map(()=>base),borderColor:tc,borderDash:[5,5],pointRadius:0,borderWidth:1,fill:false});
      mkChart("cTrend",{type:"line",data:{labels,datasets:ds},options:baseOpts()});
    }
  },30);
  // mini-podsumowanie
  const vals=hist.map(m.get).filter(v=>v!=null);
  if (vals.length){
    const avg=vals.reduce((a,c)=>a+c,0)/vals.length, mn=Math.min(...vals), mx=Math.max(...vals);
    wrap.appendChild(el(`<div class="card"><h3>Statystyki (14 dni)</h3><div class="vitals">
      ${vital("Średnia",num(avg,1))}${vital("Min",num(mn,1))}${vital("Max",num(mx,1))}${vital("Ostatnio",num(vals[vals.length-1],1))}</div></div>`));
  }
  return wrap;
}

/* WORKOUTS */
const WK_EMOJI = {Bieg:"🏃",Rower:"🚴",Spacer:"🚶",Siłownia:"🏋️"};
async function renderWorkouts() {
  const d=State.data, wrap=el(`<div></div>`);
  wrap.appendChild(el(`<div class="head"><div><h2>Treningi</h2><div class="date">Ostatnie 14 dni</div></div>
    <button class="goal-chip" id="newWkt">+ Stwórz</button></div>`));

  const all=[];
  // Treningi z opaski
  d.history.slice(-14).forEach(e=>(e.workouts||[]).forEach(w=>all.push({...w, source:'opaska'})));
  // Ręcznie zalogowane z dziennika
  try {
    const jData = await api('/api/journal');
    (jData.journal||[]).forEach(j=>(j.manual_workouts||[]).forEach(w=>all.push({
      ...w, start: w.completed_at||j.date, source:'manual', type: w.type||'Trening'
    })));
  } catch(_){}

  all.sort((a,b)=>new Date(b.start||0)-new Date(a.start||0));

  setTimeout(()=>{ document.querySelector('#newWkt')?.addEventListener('click',()=>openWorkoutGenerator(d)); }, 20);

  if (!all.length) { wrap.appendChild(el(`<div class="card"><div class="sub" style="text-align:center;padding:20px 0">Brak treningów. Użyj "Stwórz" żeby wygenerować trening AI.</div></div>`)); return wrap; }
  all.forEach((w,idx)=>{
    const dist=w.distance_km?`${num(w.distance_km,2)} km`:"trening";
    const big=w.distance_km?`${num(w.distance_km,1)}`:`${w.duration_min}`;
    const lbl=w.distance_km?"km":"min";
    const card=el(`<div class="wk"><div class="we">${WK_EMOJI[w.type]||"🏅"}</div><div class="wmain"><div class="wtitle">${w.type}</div><div class="wsub">${fmtDate(w.start)} · ${w.duration_min} min · ${w.avg_hr} bpm</div></div><div class="wstat"><div class="wbig">${big}</div><div class="wlbl">${lbl}</div></div></div>`);
    card.addEventListener("click",()=>showWorkout(w));
    wrap.appendChild(card);
  });
  return wrap;
}
function showWorkout(w) {
  const v=$("#view");
  if (State.map){State.map.remove();State.map=null;}
  Object.values(State.charts).forEach(c=>c&&c.destroy()); State.charts={};
  const wrap=el(`<div class="fade"></div>`);
  const back=el(`<div class="head"><div><h2>${WK_EMOJI[w.type]||"🏅"} ${w.type}</h2><div class="date">${fmtDate(w.start)} · ${timeOf(w.start)}</div></div><button class="goal-chip" id="wkBack">← wróć</button></div>`);
  wrap.appendChild(back);
  if (w.route && w.route.length>1) wrap.appendChild(el(`<div id="map"></div>`));
  wrap.appendChild(el(`<div class="card"><h3>Szczegóły</h3><div class="wk-detail-grid">
    ${vital("Czas",w.duration_min,"min")}
    ${w.distance_km?vital("Dystans",num(w.distance_km,2),"km"):""}
    ${w.pace_min_km?vital("Tempo",num(w.pace_min_km,2),"min/km"):""}
    ${vital("Tętno śr.",w.avg_hr,"bpm")}
    ${vital("Tętno max",w.max_hr,"bpm")}
    ${vital("Kalorie",num(w.calories),"kcal")}
    ${w.distance_km?vital("Przewyższenie",w.elevation_gain_m,"m"):""}
  </div></div>`));
  v.innerHTML=""; v.appendChild(wrap);
  $("#wkBack").addEventListener("click",()=>render());
  if (w.route && w.route.length>1) loadLeaflet().then(()=>{
    if (!document.getElementById("map")) return;
    const m=L.map("map",{attributionControl:false,zoomControl:false}); State.map=m;
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",{maxZoom:19}).addTo(m);
    const line=L.polyline(w.route,{color:"#6d7cff",weight:4}).addTo(m);
    m.fitBounds(line.getBounds(),{padding:[24,24]});
    L.circleMarker(w.route[0],{radius:6,color:"#2dd4a7",fillOpacity:1}).addTo(m);
    L.circleMarker(w.route[w.route.length-1],{radius:6,color:"#f25f5c",fillOpacity:1}).addTo(m);
  });
}

let _leafletPromise = null;
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (_leafletPromise) return _leafletPromise;
  _leafletPromise = new Promise((resolve) => {
    const css = document.createElement("link");
    css.rel = "stylesheet"; css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(css);
    const js = document.createElement("script");
    js.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    js.onload = () => resolve(); js.onerror = () => resolve();
    document.head.appendChild(js);
  });
  return _leafletPromise;
}

/* ---- WORKOUT PLAYER ---- */
let _playerRpe = null;
function openPlayer(workout) {
  _playerRpe = null;
  const overlay = el(`<div class="player-overlay fade"></div>`);
  const header = el(`<div class="player-header"><h2>${esc(workout.title||"Trening")}<br><span style="font-size:13px;color:var(--muted);font-weight:400">${workout.duration_min} min</span></h2><button class="player-close">✕ Zakończ</button></div>`);
  const body = el(`<div class="player-body"></div>`);
  const footer = el(`<div class="player-footer"><div class="sub" style="margin-bottom:8px">Jak trudny był trening? (RPE 1–10)</div><div class="rpe-pick" id="rpePick"></div><button class="btn primary" id="saveWkt" style="margin-top:12px">Zapisz trening</button></div>`);

  const doneSets = new Set();
  let total = 0, doneCount = 0;

  (workout.sections||[]).forEach(sec => {
    body.appendChild(el(`<div class="section-title">${esc(sec.name)} · ${sec.duration_min} min</div>`));
    (sec.exercises||[]).forEach((ex, ei) => {
      total++;
      const id = `${sec.name}-${ei}`;
      const meta = [ex.sets&&`${ex.sets}×${ex.reps}`, ex.weight, ex.rest_sec&&`przerwa ${ex.rest_sec}s`].filter(Boolean).join(' · ');
      const row = el(`<div class="ex-row" data-id="${id}"><div class="ex-check"></div><div class="ex-info"><div class="ex-name">${esc(ex.name)}</div><div class="ex-meta">${meta}</div>${ex.note?`<div class="ex-note">${esc(ex.note)}</div>`:''}</div></div>`);
      row.addEventListener("click", () => {
        if (doneSets.has(id)) { doneSets.delete(id); doneCount--; } else { doneSets.add(id); doneCount++; }
        row.classList.toggle("done", doneSets.has(id));
        row.querySelector(".ex-check").textContent = doneSets.has(id) ? "✓" : "";
      });
      body.appendChild(row);
    });
  });

  for (let i=1; i<=10; i++) {
    const btn = el(`<button>${i}</button>`);
    btn.addEventListener("click", () => { _playerRpe=i; footer.querySelectorAll(".rpe-pick button").forEach(b=>b.classList.toggle("active",b.textContent==i)); });
    footer.querySelector("#rpePick").appendChild(btn);
  }

  header.querySelector(".player-close").addEventListener("click", () => overlay.remove());
  footer.querySelector("#saveWkt").addEventListener("click", async () => {
    await api("/api/workout/log", {method:"POST", body:JSON.stringify({title:workout.title, duration_min:workout.duration_min, rpe:_playerRpe, calories: Math.round((workout.duration_min||30)*6.5)})});
    toast(`Trening zapisany!${_playerRpe?` RPE ${_playerRpe}/10`:""}`);
    overlay.remove();
  });

  overlay.appendChild(header); overlay.appendChild(body); overlay.appendChild(footer);
  document.body.appendChild(overlay);
}

/* ---- WORKOUT GENERATOR ---- */
async function openWorkoutGenerator(d) {
  const ready = d.readiness?.score || 70;
  const overlay = el(`<div class="player-overlay fade"></div>`);
  const header = el(`<div class="player-header"><h2>Generator treningu</h2><button class="player-close">✕</button></div>`);
  const body = el(`<div class="player-body"></div>`);
  const form = el(`<div class="gen-form">
    <select id="gType"><option value="siłowy">Siłowy</option><option value="cardio">Cardio</option><option value="HIIT">HIIT</option><option value="stretch">Rozciąganie / Joga</option><option value="mieszany">Mieszany</option></select>
    <select id="gEquip"><option value="brak">Bez sprzętu</option><option value="hantle">Hantle</option><option value="sztanga,hantle">Sztanga + hantle</option><option value="maszyny siłowni">Maszyny siłowni</option><option value="gumy oporowe">Gumy oporowe</option></select>
    <input id="gFocus" placeholder="Skupienie (np. klata i plecy, nogi, core)" value="całe ciało"/>
    <select id="gDuration"><option value="20">20 min</option><option value="30">30 min</option><option value="45" selected>45 min</option><option value="60">60 min</option></select>
    <select id="gLevel"><option value="lekki">Lekki</option><option value="średni" selected>Średni</option><option value="zaawansowany">Zaawansowany</option></select>
    <button class="btn primary" id="genBtn">🤖 Wygeneruj trening AI</button>
  </div>`);
  body.appendChild(form);
  header.querySelector(".player-close").addEventListener("click", ()=>overlay.remove());
  form.querySelector("#genBtn").addEventListener("click", async () => {
    form.innerHTML = `<div class="generating"><div class="spin">⚙️</div><div style="margin-top:12px">AI generuje trening…</div></div>`;
    const res = await api("/api/workout/generate", {method:"POST", body:JSON.stringify({
      type: overlay.querySelector("#gType")?.value || "mieszany",
      equipment: overlay.querySelector("#gEquip")?.value || "brak",
      focus: overlay.querySelector("#gFocus")?.value || "całe ciało",
      duration_min: parseInt(overlay.querySelector("#gDuration")?.value||"45"),
      level: overlay.querySelector("#gLevel")?.value || "średni",
      readiness_score: ready,
    })}).catch(()=>({error:"Błąd sieci"}));
    overlay.remove();
    if (res.ok && res.workout) openPlayer(res.workout);
    else toast("Nie udało się wygenerować — spróbuj ponownie.");
  });
  overlay.appendChild(header); overlay.appendChild(body);
  document.body.appendChild(overlay);
}

/* COACH */
function renderCoach() {
  const d=State.data, wrap=el(`<div></div>`);
  const activeGoalData = d.goals_catalog[State.goal] || d.custom_goal || {label: State.goal, emoji:"🎯"};
  wrap.appendChild(el(`<div class="head"><div><h2>Coach AI</h2><div class="date">Cel: ${activeGoalData.emoji} ${activeGoalData.label}</div></div></div>`));

  // Goal grid — predefiniowane + max 1 custom slot
  const gg=el(`<div class="card"><h3>Mój cel</h3><div class="goalgrid"></div><div class="sub" style="margin-top:10px">Wybierz cel albo napisz coachowi niżej — dostosuje całą apkę.</div></div>`);
  const grid=gg.querySelector(".goalgrid");
  // Predefiniowane (stałe)
  const BUILTIN = ["maintain","running","cycling","swimming","strength","weight_loss","sleep"];
  BUILTIN.forEach(id=>{
    const g=d.goals_catalog[id]; if(!g) return;
    const btn=el(`<div class="goalbtn ${id===State.goal?"active":""}"><div class="ge">${g.emoji}</div><div class="gl">${g.label}</div></div>`);
    btn.addEventListener("click",()=>setGoal(id)); grid.appendChild(btn);
  });
  // Custom — jeden slot (jeśli jest i to nie predefiniowany)
  const custom = d.custom_goal || (d.goals_catalog[State.goal]?.custom ? d.goals_catalog[State.goal] : null);
  if(custom && !BUILTIN.includes(custom.goal)){
    const btn=el(`<div class="goalbtn ${custom.goal===State.goal?"active":""}" style="position:relative"><div class="ge">${custom.emoji}</div><div class="gl">${custom.label}</div></div>`);
    btn.addEventListener("click",()=>setGoal(custom.goal)); grid.appendChild(btn);
  }
  wrap.appendChild(gg);

  // Chat
  const chatCard=el(`<div class="card"><h3>Porozmawiaj z coachem</h3><div class="chat" id="chat"></div><div class="chat-input"><input id="chatIn" placeholder="np. chcę zacząć biegać…" /><button id="chatSend">↑</button></div></div>`);
  wrap.appendChild(chatCard);

  // Generator treningu
  const genCard = el(`<div class="card"><h3>Generator treningu AI</h3>
    <div class="sub" style="margin-bottom:12px">AI wygeneruje pełny trening (rozgrzewka + blok + schłodzenie) dopasowany do Twojej dzisiejszej gotowości ${d.readiness?.score??'—'}/100.</div>
    <button class="btn primary" id="openGen">⚙️ Stwórz trening dla mnie</button>
  </div>`);
  genCard.querySelector("#openGen").addEventListener("click", ()=>openWorkoutGenerator(d));
  wrap.appendChild(genCard);

  // Insights
  if (d.insights && d.insights.length) {
    const ic=el(`<div class="card"><h3>Na co zwrócić uwagę</h3></div>`);
    d.insights.forEach(i=>ic.appendChild(el(`<div class="insight ${i.type}"><div class="ic">${i.icon}</div><div><div class="it">${i.title}</div><div class="ix">${i.text}</div></div></div>`)));
    wrap.appendChild(ic);
  }

  // Plans
  const pc=el(`<div class="card"><h3>Plan na dziś</h3><div class="plan-tabs" id="planTabs"></div><div id="planBody"></div></div>`);
  const tabs=pc.querySelector("#planTabs");
  d.action_plans.forEach(p=>{ const btn=el(`<button data-id="${p.id}" class="${p.id===State.plan?"active":""}">${p.icon} ${p.title}</button>`); btn.addEventListener("click",()=>{State.plan=p.id; renderPlanBody(pc.querySelector("#planBody"),tabs);}); tabs.appendChild(btn); });
  wrap.appendChild(pc);
  renderPlanBody(pc.querySelector("#planBody"),tabs);

  // Report
  if (State.report && State.report.text) {
    const src=State.report.source==="groq"?"Llama 3.3 70B":"analiza lokalna";
    wrap.appendChild(el(`<div class="card"><h3 style="display:flex;justify-content:space-between">Raport Pulse <span class="src-tag">${src}</span></h3><div class="bubble ai" style="max-width:100%;font-family:ui-monospace,Menlo,monospace;font-size:12.5px">${esc(State.report.text)}</div></div>`));
  }

  setTimeout(()=>{ paintChat(); $("#chatSend").addEventListener("click",sendChat); $("#chatIn").addEventListener("keydown",e=>{if(e.key==="Enter")sendChat();}); },20);
  return wrap;
}
function renderPlanBody(body,tabs){
  [...tabs.children].forEach(b=>b.classList.toggle("active",b.dataset.id===State.plan));
  const p=State.data.action_plans.find(x=>x.id===State.plan); body.innerHTML="";
  if (p.headline) body.appendChild(el(`<div class="plan-head">${p.headline}</div>`));
  const ul=el(`<ul class="plan"></ul>`); p.items.forEach(i=>ul.appendChild(el(`<li>${i}</li>`))); body.appendChild(ul);
}
function stripSetGoal(text) {
  // Safety net: usuń blok <<SET_GOAL:...>> z wyświetlanego tekstu
  return text.replace(/<<SET_GOAL:[\s\S]*?>>?/g, '').trim();
}
function paintChat() {
  const c=$("#chat"); if(!c) return; c.innerHTML="";
  if (!State.chat.length) c.appendChild(el(`<div class="bubble ai">Cześć Franek! Napisz mi o czym marzysz — np. "chcę zacząć biegać" albo "jak mój dzisiejszy sen?"</div>`));
  State.chat.forEach(m=>{
    const isAI = m.role==="ai" || m.role==="assistant";
    const txt = isAI ? stripSetGoal(m.content) : m.content;
    const cls = m.role==="user" ? "me" : "ai";
    const style = m.role==="error" ? ' style="opacity:.6"' : '';
    if (txt) c.appendChild(el(`<div class="bubble ${cls}"${style}>${esc(txt)}</div>`));
  });
  c.scrollTop=c.scrollHeight;
}
async function sendChat() {
  const inp=$("#chatIn"); const text=inp.value.trim(); if(!text) return;
  inp.value=""; State.chat.push({role:"user",content:text}); paintChat();
  const c=$("#chat"); const typing=el(`<div class="typing">Pulse pisze…</div>`); c.appendChild(typing); c.scrollTop=c.scrollHeight;
  try {
    // Wyślij tylko prawdziwe wiadomości (bez komunikatów błędów frontendu)
    const toSend = State.chat.filter(m=>m.role!=="error");
    const r=await api("/api/chat",{method:"POST",body:JSON.stringify({messages:toSend,goal:State.goal})});
    typing.remove();
    const reply = stripSetGoal(r.reply||"").trim() || "(brak odpowiedzi)";
    State.chat.push({role:"ai",content:reply}); paintChat();
    if (r.set_goal && r.set_goal.goal) { await setGoal(r.set_goal.goal, true); }
  } catch(e) { typing.remove(); State.chat.push({role:"error",content:"⚠️ Błąd połączenia — spróbuj ponownie."}); paintChat(); }
}
async function setGoal(id, fromChat=false) {
  State.goal=id; localStorage.setItem("pulse_goal",id);
  await loadData();
  const g = State.data.goals_catalog[id] || State.data.custom_goal || {emoji:"🎯", label:id};
  toast(`Cel: ${g.emoji} ${g.label}`);
  render();
}

/* PROFILE */
async function renderProfile() {
  const d=State.data, b=d.baselines, wrap=el(`<div></div>`);
  wrap.appendChild(el(`<div class="head"><div><h2>Profil</h2><div class="date">Franek</div></div>${goalChip()}</div>`));

  // Reminders + push
  const rc=el(`<div class="card"><h3>Przypominajki i powiadomienia</h3>
    <div class="row"><div><div class="k">Powiadomienia push</div><div class="ksub" id="pushStatus">Włącz, by dostawać przypominajki na telefon</div></div><button class="goal-chip" id="pushBtn">Włącz</button></div>
    <div id="remList"></div>
    <button class="btn ghost" id="testPush" style="margin-top:14px">Wyślij testowe powiadomienie</button>
  </div>`);
  wrap.appendChild(rc);

  wrap.appendChild(el(`<div class="card"><h3>Twoje linie bazowe</h3>
    <div class="row"><span class="k">Tętno spoczynkowe</span><span class="v">${num(b.rhr,0)} bpm</span></div>
    <div class="row"><span class="k">HRV</span><span class="v">${num(b.hrv,0)} ms</span></div>
    <div class="row"><span class="k">Średni sen</span><span class="v">${hm(b.sleep)}</span></div>
    <div class="row"><span class="k">Średnie kroki</span><span class="v">${num(b.steps,0)}</span></div>
    <div class="row"><span class="k">Średni Sleep Score</span><span class="v">${num(b.sleep_score,0)}/100</span></div>
  </div>`));

  // Journal
  const jCard = el(`<div class="card"><h3>Dziennik dziś</h3></div>`);
  const jData = await api("/api/journal").catch(()=>({today:{},journal:[]}));
  const jt = jData.today || {};
  const MOODS = ["😞","😐","🙂","😊","😁"];
  jCard.appendChild(el(`<div class="sub" style="margin-bottom:10px">Waga, nastrój i makroskładniki — zapisują się automatycznie.</div>`));
  // Waga
  const wRow = el(`<div class="row"><div><div class="k">⚖️ Waga</div><div class="ksub">BMI obliczany automatycznie (wzrost 178 cm)</div></div><div class="num-input"><input type="number" id="jWeight" placeholder="kg" step="0.1" value="${jt.weight_kg||''}" style="width:80px"/><span>kg</span></div></div>`);
  jCard.appendChild(wRow);
  // Nastrój
  const mRow = el(`<div style="padding:12px 0;border-bottom:1px solid var(--line)"><div class="k">😊 Nastrój</div><div class="mood-pick" id="moodPick"></div></div>`);
  let selMood = jt.mood || 0;
  MOODS.forEach((em,i)=>{const btn=el(`<button class="mood-btn ${selMood===i+1?"active":""}">${em}</button>`);btn.addEventListener("click",()=>{selMood=i+1;mRow.querySelectorAll(".mood-btn").forEach((b,j)=>b.classList.toggle("active",j===i));});mRow.querySelector("#moodPick").appendChild(btn);});
  jCard.appendChild(mRow);
  // Woda
  const wtrRow = el(`<div class="row"><div class="k">💧 Woda</div><div class="num-input"><input type="number" id="jWater" placeholder="0" min="0" max="20" value="${jt.water_glasses||''}" style="width:60px"/><span>szklanek</span></div></div>`);
  jCard.appendChild(wtrRow);
  // Kalorie + makro
  const macroRow = el(`<div class="row" style="flex-wrap:wrap;gap:8px"><div class="k" style="width:100%">🍽️ Kalorie i makra</div>
    <div class="num-input"><input type="number" id="jCal" placeholder="kcal" value="${jt.calories_eaten||''}" style="width:80px"/><span>kcal</span></div>
    <div class="num-input"><input type="number" id="jProt" placeholder="białko" value="${jt.protein_g||''}" style="width:70px"/><span>g B</span></div>
    <div class="num-input"><input type="number" id="jCarbs" placeholder="węgle" value="${jt.carbs_g||''}" style="width:70px"/><span>g W</span></div>
    <div class="num-input"><input type="number" id="jFat" placeholder="tłuszcz" value="${jt.fat_g||''}" style="width:70px"/><span>g T</span></div>
  </div>`);
  jCard.appendChild(macroRow);
  const saveJBtn = el(`<button class="btn primary" style="margin-top:12px">Zapisz dziennik</button>`);
  saveJBtn.addEventListener("click", async ()=>{
    const body = {};
    const w = parseFloat(jCard.querySelector("#jWeight")?.value); if(!isNaN(w)&&w>0) body.weight_kg=w;
    if (selMood) body.mood=selMood;
    const wtr = parseInt(jCard.querySelector("#jWater")?.value); if(!isNaN(wtr)) body.water_glasses=wtr;
    const cal = parseInt(jCard.querySelector("#jCal")?.value); if(!isNaN(cal)) body.calories_eaten=cal;
    const prot = parseInt(jCard.querySelector("#jProt")?.value); if(!isNaN(prot)) body.protein_g=prot;
    const carbs = parseInt(jCard.querySelector("#jCarbs")?.value); if(!isNaN(carbs)) body.carbs_g=carbs;
    const fat = parseInt(jCard.querySelector("#jFat")?.value); if(!isNaN(fat)) body.fat_g=fat;
    await api("/api/journal",{method:"POST",body:JSON.stringify(body)});
    toast("Dziennik zapisany ✓");
  });
  jCard.appendChild(saveJBtn);
  wrap.appendChild(jCard);

  wrap.appendChild(el(`<div class="card"><h3>Zainstaluj na iPhonie</h3><ol class="install-steps">
    <li>Otwórz tę stronę w <b>Safari</b>.</li>
    <li>Dotknij <b>Udostępnij</b> (kwadrat ze strzałką).</li>
    <li>Wybierz <b>„Do ekranu początkowego”</b>.</li>
    <li>Otwórz apkę z ikony — dopiero wtedy działają powiadomienia push.</li>
  </ol></div>`));

  const exp=el(`<button class="btn ghost">⬇︎ Pobierz moje dane (JSON)</button>`); exp.addEventListener("click",exportData); wrap.appendChild(exp);
  const out=el(`<button class="btn danger">Wyloguj</button>`); out.addEventListener("click",logout); wrap.appendChild(out);
  wrap.appendChild(el(`<div class="sub" style="text-align:center;margin-top:16px;font-size:12px">BioAI-Pulse · dane chronione PIN-em · nie jest urządzeniem medycznym</div>`));

  setTimeout(initReminders,20);
  return wrap;
}

async function initReminders() {
  // status push
  const supported = "serviceWorker" in navigator && "PushManager" in window;
  const statusEl=$("#pushStatus"), btn=$("#pushBtn");
  if (!supported) { statusEl.textContent="Twoja przeglądarka nie wspiera push (na iPhonie zainstaluj apkę z ekranu początkowego)."; btn.style.display="none"; }
  else if (Notification.permission==="granted") { statusEl.textContent="Powiadomienia włączone ✅"; btn.textContent="Włączone"; }
  btn.addEventListener("click",enablePush);
  $("#testPush").addEventListener("click",async()=>{
    const r=await api("/api/push/test",{method:"POST"}).catch(()=>({ok:false}));
    toast(r.ok?`Wysłano (${r.sent}/${r.subscriptions})`:(r.error||"Błąd — najpierw włącz powiadomienia"));
  });
  // reminders list
  const data=await api("/api/reminders").catch(()=>({items:[]}));
  State.reminders=data.items||[];
  const list=$("#remList"); list.innerHTML="";
  State.reminders.forEach((it,idx)=>{
    const when = it.kind==="daily" ? `codziennie ${it.time}` : `co ${Math.round(it.every_min/60*10)/10}h (${it.from}–${it.to})`;
    const row=el(`<div class="row"><div><div class="k">${it.emoji} ${it.label}</div><div class="ksub">${when}</div></div><label class="switch"><input type="checkbox" ${it.enabled?"checked":""}/><span class="sl"></span></label></div>`);
    row.querySelector("input").addEventListener("change",async(e)=>{ State.reminders[idx].enabled=e.target.checked; await api("/api/reminders",{method:"POST",body:JSON.stringify({items:State.reminders})}); toast("Zapisano"); });
    list.appendChild(row);
  });
}

function urlB64ToUint8(base64) {
  const pad="=".repeat((4-base64.length%4)%4);
  const b64=(base64+pad).replace(/-/g,"+").replace(/_/g,"/");
  const raw=atob(b64); return Uint8Array.from([...raw].map(c=>c.charCodeAt(0)));
}
async function enablePush() {
  try {
    const keyRes=await api("/api/push/key");
    if (!keyRes.configured) { toast("Push nie skonfigurowany na serwerze (klucze VAPID)."); return; }
    const perm=await Notification.requestPermission();
    if (perm!=="granted") { toast("Nie udzielono zgody na powiadomienia."); return; }
    const reg=await navigator.serviceWorker.ready;
    const sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:urlB64ToUint8(keyRes.key)});
    await api("/api/push/subscribe",{method:"POST",body:JSON.stringify(sub)});
    toast("Powiadomienia włączone ✅"); $("#pushStatus").textContent="Powiadomienia włączone ✅"; $("#pushBtn").textContent="Włączone";
  } catch(e) { toast("Nie udało się włączyć push: "+e.message); }
}

async function exportData() {
  const data=await api("/api/export");
  const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});
  const a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download="bioaipulse-dane.json"; a.click();
}

/* TABBAR */
document.querySelector(".tabbar").addEventListener("click",(e)=>{
  const b=e.target.closest(".tab"); if(!b) return;
  document.querySelectorAll(".tab").forEach(t=>t.classList.remove("active")); b.classList.add("active");
  State.tab=b.dataset.tab; render(); window.scrollTo(0,0);
});

/* INIT */
setupLogin();
if (State.token) enterApp(); else $("#login").classList.remove("hidden");
if ("serviceWorker" in navigator) window.addEventListener("load",()=>navigator.serviceWorker.register("/sw.js").catch(()=>{}));
