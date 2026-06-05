/* BioAI-Pulse — app.js v3 (OLED redesign + all features) */

if (window.Chart) { Chart.defaults.animation = false; Chart.defaults.font.family = "'Inter', system-ui, sans-serif"; }

const State = {
  token: localStorage.getItem("pulse_token") || null,
  goal: localStorage.getItem("pulse_goal") || "maintain",
  data: null, report: null, tab: "today", plan: "sport",
  chat: [], charts: {}, map: null, checkedGoals: [],
  timePeriod: "T", trendMetric: "activity",
};

const $ = (s) => document.querySelector(s);
const el = (h) => { const t = document.createElement("template"); t.innerHTML = h.trim(); return t.content.firstElementChild; };
const PL_M = ["sty","lut","mar","kwi","maj","cze","lip","sie","wrz","paź","lis","gru"];
const PL_D = ["ndz","pon","wt","śr","czw","pt","sb"];
const fmtDate = (iso) => { const d=new Date(iso); return `${PL_D[d.getDay()]}, ${d.getDate()} ${PL_M[d.getMonth()]}`; };
const hm = (m) => m==null?"—":`${Math.floor(m/60)}h ${Math.round(m%60)}min`;
const timeOf = (iso) => { if(!iso) return "—"; const d=new Date(iso); return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`; };
const num = (n,d=0) => n==null?"—":Number(n).toLocaleString("pl-PL",{maximumFractionDigits:d});
const esc = (s) => String(s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const ZONE = { sleep:"#7C5CFC", activity:"#FF8C42", resilience:"#26C6DA", nutrition:"#4CAF7D" };

function toast(msg) { const t=el(`<div class="toast">${msg}</div>`); document.body.appendChild(t); setTimeout(()=>t.remove(),2800); }

/* API */
async function api(path, opts={}) {
  const res = await fetch(path, { ...opts, headers: { "Content-Type":"application/json", ...(State.token?{Authorization:`Bearer ${State.token}`}:{}), ...(opts.headers||{}) } });
  if (res.status===401 && !path.includes("login")) { logout(); throw new Error("unauthorized"); }
  return res.json();
}

/* LOGIN */
let pinBuf = "";
function setupLogin() {
  const dots=$("#pinDots").children, err=$("#pinError");
  const paint=()=>{ for(let i=0;i<4;i++) dots[i].classList.toggle("on",i<pinBuf.length); };
  $("#keypad").addEventListener("click", async(e)=>{
    const b=e.target.closest("button"); if(!b) return;
    const k=b.dataset.k; err.textContent="";
    if(k==="del") pinBuf=pinBuf.slice(0,-1);
    else if(k==="clear") pinBuf="";
    else if(pinBuf.length<4) pinBuf+=k;
    paint();
    if(pinBuf.length===4){
      const pin=pinBuf;
      const r=await api("/api/login",{method:"POST",body:JSON.stringify({pin})}).catch(()=>({ok:false}));
      if(r.ok){State.token=r.token;localStorage.setItem("pulse_token",r.token);pinBuf="";paint();enterApp();}
      else{err.textContent="Błędny PIN";pinBuf="";paint();navigator.vibrate&&navigator.vibrate(120);}
    }
  });
}
function logout(){State.token=null;localStorage.removeItem("pulse_token");$("#app").classList.add("hidden");$("#login").classList.remove("hidden");}

/* BOOT */
async function enterApp(){
  $("#login").classList.add("hidden");$("#app").classList.remove("hidden");
  $("#view").innerHTML=`<div class="skeleton">Ładowanie…</div>`;
  try{ await loadData(); }catch{return;}
  if(State.data.is_demo) $("#demoBanner").classList.remove("hidden");
  render();
}
async function loadData(){
  [State.data,State.report]=await Promise.all([
    api(`/api/data?goal=${State.goal}`),
    api("/api/report").catch(()=>null),
  ]);
  const ch=await api("/api/goals/check").catch(()=>({checked:[]}));
  State.checkedGoals=ch.checked||[];
}

/* RING HELPERS */
function ringGeneric(pct, color, size=200, stroke=16) {
  const r=(size-stroke)/2, c=2*Math.PI*r, p=Math.max(0,Math.min(100,pct||0))/100;
  return `<svg width="${size}" height="${size}"><circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="#242424" stroke-width="${stroke}"/><circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${color}" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c*(1-p)}" style="transition:stroke-dashoffset 1s"/></svg>`;
}
function deltaB(val,base,inv=false,unit=""){
  if(val==null||base==null) return "";
  const d=val-base,good=inv?d<0:d>0,cls=Math.abs(d)<0.5?"delta-flat":good?"delta-up":"delta-dn",s=d>0?"+":"";
  return `<span class="t-delta ${cls}">${s}${num(d,1)}${unit}</span>`;
}

/* SPARKLINE — full-width SVG with area fill */
function sparkline(vals, color) {
  if(!vals||vals.length<2) return "";
  const clean = vals.filter(v=>v!=null);
  if(clean.length<2) return "";
  const W=200, H=46, pad=3;
  const mn=Math.min(...clean), mx=Math.max(...clean), rng=mx-mn||1;
  const pts = clean.map((v,i)=>({
    x: i/(clean.length-1)*W,
    y: H - pad - ((v-mn)/rng)*(H-pad*2),
  }));
  // Smooth path (Bezier)
  let d = `M ${pts[0].x} ${pts[0].y}`;
  for(let i=1;i<pts.length;i++){
    const prev=pts[i-1], cur=pts[i];
    const cpx=(prev.x+cur.x)/2;
    d += ` C ${cpx} ${prev.y} ${cpx} ${cur.y} ${cur.x} ${cur.y}`;
  }
  // Area fill
  const areaD = `${d} L ${pts[pts.length-1].x} ${H} L ${pts[0].x} ${H} Z`;
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
    <defs><linearGradient id="sg${color.replace('#','')}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity="0.4"/>
      <stop offset="100%" stop-color="${color}" stop-opacity="0.0"/>
    </linearGradient></defs>
    <path d="${areaD}" fill="url(#sg${color.replace('#','')})" stroke="none"/>
    <path d="${d}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}

/* Navigate to Trends and select a specific metric */
function openMetricDetail(zone, metKey) {
  State.trendMetric = zone;
  State.selMet = metKey;
  State.timePeriod = "M"; // Miesiąc — więcej kontekstu
  switchTab("trends");
}

/* POGODA — Open-Meteo (darmowe, bez klucza, Gdynia) */
let _weather = null;
async function fetchWeather() {
  if (_weather) return _weather;
  try {
    const url = "https://api.open-meteo.com/v1/forecast?latitude=54.52&longitude=18.53&current=temperature_2m,apparent_temperature,weathercode,wind_speed_10m&timezone=Europe%2FWarsaw&forecast_days=1";
    const r = await fetch(url, {cache:"default"});
    const d = await r.json();
    const c = d.current || {};
    const codes = {0:"☀️ Bezchmurnie",1:"🌤️ Słonecznie",2:"⛅ Częściowe zachmurzenie",3:"☁️ Zachmurzenie",45:"🌫️ Mgła",48:"🌫️ Mgła",51:"🌦️ Mżawka",61:"🌧️ Deszcz",71:"❄️ Śnieg",80:"🌧️ Przelotny deszcz",95:"⛈️ Burza"};
    const wcode = c.weathercode || 0;
    const desc = codes[wcode] || codes[Math.floor(wcode/10)*10] || "🌡️";
    const temp = Math.round(c.temperature_2m || 0);
    const feel = Math.round(c.apparent_temperature || temp);
    const wind = Math.round(c.wind_speed_10m || 0);
    _weather = { temp, feel, wind, desc, code: wcode };
    return _weather;
  } catch(_) { return null; }
}

function weatherAdvice(w, readiness) {
  if (!w) return "";
  const { temp, feel, wind, code } = w;
  if (feel >= 32) return "🌡️ Upał — trenuj wcześnie rano lub w pomieszczeniu.";
  if (feel <= -5) return "🥶 Mróz — rozgrzewaj się dłużej, skróć sesję.";
  if (code >= 95) return "⛈️ Burza — zostań w domu, trening wewnętrzny.";
  if (code >= 80 && wind > 30) return "🌧️ Deszcz i wiatr — lepiej trening w hali.";
  if (feel >= 25 && readiness >= 70) return "☀️ Idealne warunki na trening na zewnątrz!";
  return "";
}

/* AI BANNER — insight + pogoda */
async function aiBannerAsync(d) {
  const r=d.readiness||{}, ins=d.insights||{};
  const score=r.score||50;
  let text="", detail="";
  if(ins.length){
    const warn=ins.find(i=>i.type==="warning");
    if(warn){text=warn.title;detail=warn.text.split(".")[0]+".";}
  }
  if(!text){
    if(score>=80) text=`Gotowość <strong>${score}/100</strong> — możesz dać z siebie wszystko.`;
    else if(score>=60) text=`Solidna forma (<strong>${score}/100</strong>). Trenuj normalnie.`;
    else text=`Niska gotowość (<strong>${score}/100</strong>). Lepszy dzień na odpoczynek.`;
    detail=r.summary||"";
  }

  // Pobierz pogodę
  const w = await fetchWeather();
  const weatherTip = weatherAdvice(w, score);
  const weatherLine = w ? `<div class="ab-weather">${w.desc} ${w.temp}°C (odczuwalnie ${w.feel}°C)</div>` : "";

  const card=el(`<div class="ai-banner"><div class="ab-icon">✨</div><div style="flex:1">
    <div class="ab-text">${text}</div>
    ${weatherLine}
    ${weatherTip ? `<div class="ab-cta" style="color:var(--warn)">${weatherTip}</div>` : detail ? `<div class="ab-cta">${detail}</div>` : ""}
  </div><span style="font-size:18px;color:var(--txt2)">›</span></div>`);
  card.addEventListener("click",()=>switchTab("coach"));
  return card;
}

// Synchronous fallback dla renderToday (zastępujemy async wersją)
function aiBanner(d) {
  const card=el(`<div class="ai-banner"><div class="ab-icon">✨</div><div style="flex:1"><div class="ab-text">Ładuję analizę…</div></div></div>`);
  aiBannerAsync(d).then(real=>{ if(card.parentNode) card.parentNode.replaceChild(real,card); });
  return card;
}

/* TODAY */
function renderToday(){
  const d=State.data, t=d.today||{}, b=d.baselines||{};
  const s=t.sleep||{}, st=s.stages_minutes||{}, hr=t.heart_rate_bpm||{};
  const wrap=el(`<div></div>`);

  // Header
  wrap.appendChild(el(`<div class="page-header"><div class="greeting"><h2>Cześć, Franek 👋</h2><div class="date">${fmtDate(t.fetched_at)}</div></div><div class="avatar">F</div></div>`));

  // AI Banner
  wrap.appendChild(aiBanner(d));

  // Cardio Load Ring
  const load=t.cardio_load||0, loadTarget=500;
  const loadPct=Math.min(100,Math.round(load/loadTarget*100));
  const gradSvg='<svg style="position:absolute;width:0;height:0"><defs><linearGradient id="cardioGrad" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#FFD54F"/><stop offset="1" stop-color="#FF8C42"/></linearGradient></defs></svg>';
  const rc=el(`<div class="cardio-ring-card">
    <h3>Obciążenie Kardio</h3>
    <div class="ring-container">${ringGeneric(loadPct,"url(#cardioGrad)")}${gradSvg}
      <div class="ring-inner">
        <div class="ring-big">${loadPct}<span style="font-size:20px">%</span></div>
        <div class="ring-label">${load} / ${loadTarget} pkt</div>
      </div>
    </div>
    <div class="ring-stats">
      <div class="ring-stat"><div class="rsv" style="color:var(--activity)">${num(t.steps)}</div><div class="rsl">kroków</div></div>
      <div class="ring-stat"><div class="rsv" style="color:var(--warn)">${num(t.calories_kcal,0)}</div><div class="rsl">kcal</div></div>
      <div class="ring-stat"><div class="rsv" style="color:var(--resilience)">${t.active_zone_minutes||0}</div><div class="rsl">min AZM</div></div>
    </div>
  </div>`);
  wrap.appendChild(rc);

  // Metric Tiles
  const hist=d.history||[];
  const tileData=[
    {zone:"sleep",    metKey:"score",    label:"Sleep Score", val:s.sleep_score,           unit:"/100",  sub:hm(s.total_minutes),               spark:hist.map(e=>(e.sleep||{}).sleep_score),  base:b.sleep_score},
    {zone:"sleep",    metKey:"duration", label:"Sen",         val:s.total_minutes?+(s.total_minutes/60).toFixed(1):null, unit:"h", sub:`${timeOf(s.sleep_start)} → ${timeOf(s.sleep_end)}`, spark:hist.map(e=>+(((e.sleep||{}).total_minutes||0)/60).toFixed(1))},
    {zone:"resilience",metKey:"hrv",    label:"HRV",         val:t.hrv_rmssd,             unit:"ms",    sub:"zmienność tętna",                  spark:hist.map(e=>e.hrv_rmssd),               base:b.hrv},
    {zone:"resilience",metKey:"rhr",    label:"Tętno spocz.",val:t.resting_hr_bpm,         unit:"bpm",   sub:`norma ${num(b.rhr,0)}`,            spark:hist.map(e=>e.resting_hr_bpm),          base:b.rhr,inv:true},
    {zone:"activity",  metKey:"steps",  label:"Kroki",       val:t.steps,                  unit:"",      sub:`${num(t.active_zone_minutes)} AZM`, spark:hist.map(e=>e.steps),                   base:b.steps},
    {zone:"resilience",metKey:"spo2",   label:"SpO2",        val:t.spo2_pct,               unit:"%",     sub:"natlenienie krwi",                 spark:hist.map(e=>e.spo2_pct),                base:b.spo2},
    {zone:"resilience",metKey:"resp",   label:"Oddech",      val:t.respiration_rate,       unit:"/min",  sub:"nocna częstotliwość",              spark:hist.map(e=>e.respiration_rate)},
    {zone:"sleep",     metKey:"score",  label:"Temp. skóry", val:t.skin_temp_variation_c!=null?(t.skin_temp_variation_c>=0?"+":"")+num(t.skin_temp_variation_c,1):null, unit:"°C", sub:"odchylenie od normy", spark:hist.map(e=>e.skin_temp_variation_c)},
  ];
  const grid=el(`<div class="tiles-grid"></div>`);
  tileData.forEach(tile=>{
    const col=ZONE[tile.zone];
    const delt=tile.base!=null?deltaB(tile.val,tile.base,tile.inv):"";
    const valStr=tile.val!=null?String(tile.val):"—";
    const spark14=(tile.spark||[]).slice(-14);
    const td=el(`<div class="tile ${tile.zone}">
      <div class="tile-body">
        <div class="t-label">
          <span class="t-dot"></span>${tile.label}${delt}
          <span class="t-arrow">›</span>
        </div>
        <div class="t-value-row">
          <span class="t-value">${valStr}</span><span class="t-unit">${tile.unit}</span>
        </div>
        <div class="t-sub">${tile.sub}</div>
      </div>
      <div class="t-spark-area">${sparkline(spark14,col)}</div>
    </div>`);
    td.addEventListener("click",()=>openMetricDetail(tile.zone, tile.metKey));
    grid.appendChild(td);
  });
  wrap.appendChild(grid);

  // Insights
  if(d.insights&&d.insights.length){
    const ic=el(`<div class="card"><h3>Spostrzeżenia</h3></div>`);
    d.insights.forEach(i=>ic.appendChild(el(`<div class="insight ${i.type}"><div class="ic">${i.icon}</div><div><div class="it">${i.title}</div><div class="ix">${i.text}</div></div></div>`)));
    wrap.appendChild(ic);
  }

  // Correlation Card
  wrap.appendChild(renderCorrelations(d));

  return wrap;
}

/* CORRELATIONS */
function renderCorrelations(d){
  const hist=d.history||[];
  if(hist.length<7) return el(`<div></div>`);
  const corrs=[];
  // AZM → Deep sleep
  const pairs1=hist.slice(-14).map(e=>({x:e.active_zone_minutes||0,y:((e.sleep||{}).stages_minutes||{}).deep||0})).filter(p=>p.x>0&&p.y>0);
  if(pairs1.length>=5){
    const avgX=pairs1.reduce((a,p)=>a+p.x,0)/pairs1.length;
    const avgY=pairs1.reduce((a,p)=>a+p.y,0)/pairs1.length;
    const highX=pairs1.filter(p=>p.x>avgX), lowX=pairs1.filter(p=>p.x<=avgX);
    const avgDeepHigh=highX.reduce((a,p)=>a+p.y,0)/(highX.length||1);
    const avgDeepLow=lowX.reduce((a,p)=>a+p.y,0)/(lowX.length||1);
    if(avgDeepHigh>avgDeepLow+5){
      corrs.push({icon:"🔗",title:"Trening → głębszy sen",text:`W dni z wysokimi AZM (>${Math.round(avgX)} min) masz śr. ${Math.round(avgDeepHigh)} min snu głębokiego vs ${Math.round(avgDeepLow)} min w inne dni.`,strength:"corr-strong"});
    }
  }
  // RHR → Readiness next day
  const pairs2=hist.slice(-10).map((e,i,arr)=>i>0?{x:arr[i-1].resting_hr_bpm||0,y:(e.daily_readiness||{}).score||0}:null).filter(Boolean).filter(p=>p.x>0&&p.y>0);
  if(pairs2.length>=4){
    const avgX=pairs2.reduce((a,p)=>a+p.x,0)/pairs2.length;
    const highRHR=pairs2.filter(p=>p.x>avgX), lowRHR=pairs2.filter(p=>p.x<=avgX);
    const avgReadHigh=highRHR.reduce((a,p)=>a+p.y,0)/(highRHR.length||1);
    const avgReadLow=lowRHR.reduce((a,p)=>a+p.y,0)/(lowRHR.length||1);
    if(avgReadHigh<avgReadLow-5){
      corrs.push({icon:"📈",title:"Wyższe RHR → niższa gotowość",text:`Gdy tętno spoczynkowe przekracza ${Math.round(avgX)} bpm, Twoja gotowość dnia następnego spada o ~${Math.round(avgReadLow-avgReadHigh)} pkt.`,strength:"corr-moderate"});
    }
  }
  // HRV trend long
  const hrvs=hist.slice(-14).map(e=>e.hrv_rmssd).filter(v=>v!=null);
  if(hrvs.length>=7){
    const first=hrvs.slice(0,3).reduce((a,v)=>a+v,0)/3;
    const last=hrvs.slice(-3).reduce((a,v)=>a+v,0)/3;
    if(Math.abs(last-first)>4){
      const dir=last>first?"rośnie":"spada";
      corrs.push({icon:"📉",title:`HRV ${dir} w ciągu 2 tygodni`,text:`Twoje HRV ${dir} z ${Math.round(first)} do ${Math.round(last)} ms. ${dir==="spada"?"Możliwy sygnał przetrenowania — zaplanuj regenerację.":"Dobry znak — adaptacja do treningów."}`,strength:dir==="rośnie"?"corr-strong":"corr-moderate"});
    }
  }
  if(!corrs.length) return el(`<div></div>`);
  const card=el(`<div class="card"><h3>Korelacje (AI)</h3></div>`);
  corrs.forEach(c=>card.appendChild(el(`<div class="corr-row"><div class="corr-icon">${c.icon}</div><div class="corr-text"><div class="ct">${c.title} <span class="corr-badge ${c.strength}">${c.strength.includes("strong")?"silna":"umiarkowana"}</span></div><div class="cs">${c.text}</div></div></div>`)));
  return card;
}

/* TRENDS */
const TREND_METRICS_V3={
  activity:{label:"Aktywność",zone:"activity",metrics:[
    {key:"steps",label:"Kroki",get:e=>e.steps},
    {key:"azm",label:"AZM",get:e=>e.active_zone_minutes},
    {key:"calories",label:"Kalorie",get:e=>e.calories_kcal},
    {key:"distance",label:"Dystans km",get:e=>e.distance_km},
  ]},
  sleep:{label:"Sen",zone:"sleep",metrics:[
    {key:"score",label:"Sleep Score",get:e=>(e.sleep||{}).sleep_score},
    {key:"duration",label:"Czas snu h",get:e=>((e.sleep||{}).total_minutes||0)/60},
    {key:"deep",label:"Głęboki min",get:e=>((e.sleep||{}).stages_minutes||{}).deep},
    {key:"rem",label:"REM min",get:e=>((e.sleep||{}).stages_minutes||{}).rem},
  ]},
  resilience:{label:"Serce & HRV",zone:"resilience",metrics:[
    {key:"rhr",label:"RHR bpm",get:e=>e.resting_hr_bpm},
    {key:"hrv",label:"HRV ms",get:e=>e.hrv_rmssd},
    {key:"spo2",label:"SpO2 %",get:e=>e.spo2_pct},
    {key:"readiness",label:"Gotowość",get:e=>(e.daily_readiness||{}).score},
  ]},
  nutrition:{label:"Zdrowie",zone:"nutrition",metrics:[
    {key:"load",label:"Cardio Load",get:e=>e.cardio_load},
    {key:"resp",label:"Oddech /min",get:e=>e.respiration_rate},
    {key:"temp",label:"Temp. skóry °C",get:e=>e.skin_temp_variation_c},
  ]},
};

function filterByPeriod(hist,period){
  if(period==="D") return hist.slice(-1);
  if(period==="T") return hist.slice(-7);
  if(period==="M") return hist.slice(-30);
  return hist;
}

function renderTrends(){
  const d=State.data, wrap=el(`<div></div>`);
  wrap.appendChild(el(`<div class="page-header"><div class="greeting"><h2>Trendy</h2></div></div>`));

  // Czas
  const timeTabs=el(`<div class="time-tabs"></div>`);
  ["D","T","M","R"].forEach(p=>{
    const btn=el(`<button class="${p===State.timePeriod?"active":""}">${{D:"Dziś",T:"Tydzień",M:"Miesiąc",R:"Rok"}[p]}</button>`);
    btn.addEventListener("click",()=>{State.timePeriod=p;render();});
    timeTabs.appendChild(btn);
  });
  wrap.appendChild(timeTabs);

  // Kategoria metryk
  const seg=el(`<div class="metric-seg"></div>`);
  Object.entries(TREND_METRICS_V3).forEach(([k,m])=>{
    const btn=el(`<button class="${k===State.trendMetric?`active ${m.zone}`:""}">${m.label}</button>`);
    btn.addEventListener("click",()=>{State.trendMetric=k;render();});
    seg.appendChild(btn);
  });
  wrap.appendChild(seg);

  const hist=filterByPeriod(d.history||[],State.timePeriod);
  const labels=hist.map(e=>{const dt=new Date(e.fetched_at);return `${dt.getDate()}.${dt.getMonth()+1}`;});
  const group=TREND_METRICS_V3[State.trendMetric]||TREND_METRICS_V3.activity;
  const col=ZONE[group.zone]||"#7C5CFC";
  const base=d.baselines||{};

  // Submetric buttons
  const metBtn=el(`<div class="metric-seg"></div>`);
  let selMet=State.selMet||group.metrics[0].key;
  group.metrics.forEach(m=>{
    const btn=el(`<button class="${m.key===selMet?`active ${group.zone}`:""}">${m.label}</button>`);
    btn.addEventListener("click",()=>{State.selMet=m.key;render();});
    metBtn.appendChild(btn);
  });
  wrap.appendChild(metBtn);

  const curMet=group.metrics.find(m=>m.key===selMet)||group.metrics[0];
  const vals=hist.map(curMet.get);

  // Chart
  wrap.appendChild(el(`<div class="card"><h3>${curMet.label}</h3><div class="chart-box"><canvas id="cMain"></canvas></div></div>`));
  setTimeout(()=>{
    const gc={color:"rgba(255,255,255,.06)"}, tc="#909090";
    const ds=[{data:vals,borderColor:col,backgroundColor:col+"25",fill:true,tension:.4,pointRadius:hist.length>14?0:3,borderWidth:2.5}];
    // Add baseline if available
    const bKey={rhr:"rhr",hrv:"hrv",spo2:"spo2",score:"readiness",duration:"sleep",steps:"steps"}[selMet];
    if(bKey&&base[bKey]) ds.push({data:labels.map(()=>base[bKey]),borderColor:"#555",borderDash:[4,4],pointRadius:0,borderWidth:1.5,fill:false});
    mkChart("cMain",{type:"line",data:{labels,datasets:ds},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{color:gc.color},ticks:{color:tc,maxTicksLimit:7,maxRotation:0}},y:{grid:{color:gc.color},ticks:{color:tc}}}}});
  },30);

  // Summary stats — jako lista z oddzielnikami, nie kafelki
  const clean=vals.filter(v=>v!=null);
  if(clean.length>=2){
    const avg=clean.reduce((a,b)=>a+b,0)/clean.length;
    const mn=Math.min(...clean), mx=Math.max(...clean), last=clean[clean.length-1];
    const trend=clean.length>=4?(last>avg*1.03?"📈 rosnący":last<avg*0.97?"📉 malejący":"➡️ stabilny"):"";
    const col=ZONE[group.zone]||"#fff";
    wrap.appendChild(el(`<div class="card"><h3>Statystyki — ${curMet.label}</h3>
      <div class="stats-list">
        <div class="stat-row"><span class="sr-label">Średnia</span><span class="sr-val" style="color:${col}">${num(avg,1)}</span></div>
        <div class="stat-row"><span class="sr-label">Minimum</span><span class="sr-val">${num(mn,1)}</span></div>
        <div class="stat-row"><span class="sr-label">Maksimum</span><span class="sr-val">${num(mx,1)}</span></div>
        <div class="stat-row"><span class="sr-label">Ostatni</span><span class="sr-val">${num(last,1)}</span></div>
        ${trend?`<div class="stat-row"><span class="sr-label">Trend</span><span style="font-size:14px;font-weight:700">${trend}</span></div>`:""}
      </div>
    </div>`));
  }

  // Weekly summary
  const w=d.weekly;
  if(w){
    const targetLabel = w.is_personalized_target ? "cel (Twój, adaptacyjny)" : "cel (domyślny, kalibracja 2 tyg.)";
    const zones = w.hr_zones_week||{};
    const zTotal=(zones.fat_burn||0)+(zones.cardio||0)+(zones.peak||0);
    wrap.appendChild(el(`<div class="card"><h3>Tydzień — podsumowanie</h3><div class="week-grid">
      <div class="week-stat"><div class="wv" style="color:var(--activity)">${num(w.total_steps)}</div><div class="wl">kroków łącznie</div></div>
      <div class="week-stat"><div class="wv">${w.workouts_count}</div><div class="wl">treningów</div></div>
      <div class="week-stat"><div class="wv">${num(w.total_azm)}</div><div class="wl">min AZM</div></div>
      <div class="week-stat"><div class="wv">${w.avg_sleep_score||"—"}</div><div class="wl">śr. Sleep Score</div></div>
    </div>
    <div class="load-bar">
      <div class="lb"><span>Cardio Load</span><span class="muted" style="font-size:11px">${w.total_cardio_load} / ${w.cardio_load_target} pkt · ${targetLabel}</span></div>
      <div class="lbr"><i style="width:${w.cardio_load_pct}%"></i></div>
    </div>
    ${zTotal>0?`<div style="margin-top:12px"><div class="muted" style="font-size:11px;margin-bottom:6px;text-transform:uppercase;letter-spacing:.4px">Strefy tętna — tydzień</div>
    <div class="zone-chart-bar">
      <div style="width:${(zones.fat_burn||0)/zTotal*100}%;background:var(--nutrition)"></div>
      <div style="width:${(zones.cardio||0)/zTotal*100}%;background:var(--activity)"></div>
      <div style="width:${(zones.peak||0)/zTotal*100}%;background:var(--bad)"></div>
    </div>
    <div class="zone-legend">
      <span class="zl-item"><span class="zl-dot" style="background:var(--nutrition)"></span>Spalanie ${zones.fat_burn||0}min</span>
      <span class="zl-item"><span class="zl-dot" style="background:var(--activity)"></span>Cardio ${zones.cardio||0}min</span>
      <span class="zl-item"><span class="zl-dot" style="background:var(--bad)"></span>Szczyt ${zones.peak||0}min</span>
    </div></div>`:""}
    </div>`));
  }

  return wrap;
}

/* WORKOUTS */
const WK_EMOJI={Bieg:"🏃",Rower:"🚴",Spacer:"🚶",Siłownia:"🏋️",HIIT:"💥",Stretch:"🧘",Joga:"🧘",Pompki:"💪"};
async function renderWorkouts(){
  const d=State.data, wrap=el(`<div></div>`);
  const hd=el(`<div class="page-header"><div class="greeting"><h2>Treningi</h2><div class="date">Ostatnie 14 dni</div></div><button class="goal-chip" id="newWkt">+ AI Trening</button></div>`);
  wrap.appendChild(hd);
  const all=[];
  (d.history||[]).slice(-14).forEach(e=>(e.workouts||[]).forEach(w=>all.push({...w,source:"opaska"})));
  try{
    const jd=await api("/api/journal");
    (jd.journal||[]).forEach(j=>(j.manual_workouts||[]).forEach(w=>all.push({...w,start:w.completed_at||j.date,source:"manual",type:w.type||"Trening"})));
  }catch(_){}
  all.sort((a,b)=>new Date(b.start||0)-new Date(a.start||0));
  setTimeout(()=>document.querySelector("#newWkt")?.addEventListener("click",()=>openWorkoutGenerator(d)),20);
  if(!all.length){ wrap.appendChild(el(`<div class="card"><div class="muted" style="text-align:center;padding:24px">Brak treningów. Powiedz coachowi "zrób mi trening" albo kliknij "+ AI Trening".</div></div>`)); return wrap; }
  all.slice(0,20).forEach(w=>{
    const dist=w.distance_km?`${num(w.distance_km,1)} km`:w.duration_min?`${w.duration_min} min`:"";
    const big=w.distance_km?num(w.distance_km,1):w.duration_min||"—";
    const lbl=w.distance_km?"km":"min";
    const src=w.source==="manual"?" ✏️":"";
    const card=el(`<div class="wk"><div class="we">${WK_EMOJI[w.type]||"🏅"}</div><div class="wmain"><div class="wtitle">${w.type}${src}</div><div class="wsub">${fmtDate(w.start)} · ${w.avg_hr||"—"} bpm</div></div><div class="wstat"><div class="wbig" style="color:var(--activity)">${big}</div><div class="wlbl">${lbl}</div></div></div>`);
    card.addEventListener("click",()=>w.route&&w.route.length>1?showWorkoutDetail(w):null);
    wrap.appendChild(card);
  });
  return wrap;
}

function showWorkoutDetail(w){
  const v=$("#view");
  if(State.map){State.map.remove();State.map=null;}
  Object.values(State.charts).forEach(c=>c&&c.destroy()); State.charts={};
  const wrap=el(`<div class="fade"></div>`);
  const back=el(`<div class="page-header"><div class="greeting"><h2>${WK_EMOJI[w.type]||"🏅"} ${w.type}</h2><div class="date">${fmtDate(w.start)}</div></div><button class="goal-chip" id="wkBack">← wróć</button></div>`);
  wrap.appendChild(back);
  if(w.route&&w.route.length>1) wrap.appendChild(el(`<div id="map"></div>`));
  const vt=(label,val,unit="")=>`<div class="vital"><div class="vt">${label}</div><div class="vv">${val||"—"}<small>${unit?" "+unit:""}</small></div></div>`;
  wrap.appendChild(el(`<div class="card"><h3>Szczegóły</h3><div class="wk-detail-grid">${vt("Czas",w.duration_min,"min")}${w.distance_km?vt("Dystans",num(w.distance_km,2),"km"):""}${w.pace_min_km?vt("Tempo",num(w.pace_min_km,2),"min/km"):""}${vt("Tętno śr.",w.avg_hr,"bpm")}${vt("Tętno max",w.max_hr,"bpm")}${vt("Kalorie",num(w.calories),"kcal")}${w.elevation_gain_m?vt("Wzniesienie",w.elevation_gain_m,"m"):""}</div></div>`));

  // Wykres stref tętna po treningu
  const zones = w.hr_zones_minutes || {};
  const zTotal = (zones.fat_burn||0)+(zones.cardio||0)+(zones.peak||0);
  if(zTotal > 0) {
    const zCard = el(`<div class="card"><h3>Strefy tętna — szczegóły</h3>
      <div class="zone-chart-bar">
        <div style="width:${(zones.fat_burn||0)/zTotal*100}%;background:var(--nutrition)" title="Spalanie ${zones.fat_burn||0}min"></div>
        <div style="width:${(zones.cardio||0)/zTotal*100}%;background:var(--activity)" title="Cardio ${zones.cardio||0}min"></div>
        <div style="width:${(zones.peak||0)/zTotal*100}%;background:var(--bad)" title="Szczyt ${zones.peak||0}min"></div>
      </div>
      <div class="zone-legend">
        <span class="zl-item"><span class="zl-dot" style="background:var(--nutrition)"></span>Spalanie <strong>${zones.fat_burn||0} min</strong></span>
        <span class="zl-item"><span class="zl-dot" style="background:var(--activity)"></span>Cardio <strong>${zones.cardio||0} min</strong></span>
        <span class="zl-item"><span class="zl-dot" style="background:var(--bad)"></span>Szczyt <strong>${zones.peak||0} min</strong></span>
      </div>
      <div class="card" style="margin-top:12px;padding:12px"><div style="font-size:12px;color:var(--txt2)"><strong>Spalanie tłuszczu:</strong> 65-75% max HR · <strong>Cardio:</strong> 76-85% · <strong>Szczyt:</strong> 86-95%</div></div>
    </div>`);
    // Mini donut chart z Chart.js
    const chartWrap = el(`<div style="height:180px;margin:12px 0"><canvas id="zoneDonut"></canvas></div>`);
    zCard.insertBefore(chartWrap, zCard.querySelector('.zone-chart-bar'));
    wrap.appendChild(zCard);
    setTimeout(()=>{
      mkChart("zoneDonut",{type:"doughnut",data:{labels:["Spalanie","Cardio","Szczyt"],datasets:[{data:[zones.fat_burn||0,zones.cardio||0,zones.peak||0],backgroundColor:["#4CAF7D","#FF8C42","#FF5252"],borderWidth:0,borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,cutout:"70%",plugins:{legend:{display:true,position:"bottom",labels:{color:"#909090",font:{size:12},padding:16}}}}});
    },60);
  }
  v.innerHTML=""; v.appendChild(wrap);
  $("#wkBack").addEventListener("click",()=>render());
  if(w.route&&w.route.length>1) loadLeaflet().then(()=>{
    if(!document.getElementById("map")) return;
    const m=L.map("map",{attributionControl:false,zoomControl:false}); State.map=m;
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",{maxZoom:19}).addTo(m);
    const line=L.polyline(w.route,{color:ZONE.activity,weight:4}).addTo(m);
    m.fitBounds(line.getBounds(),{padding:[24,24]});
    L.circleMarker(w.route[0],{radius:6,color:ZONE.nutrition,fillOpacity:1}).addTo(m);
    L.circleMarker(w.route[w.route.length-1],{radius:6,color:ZONE.bad,fillOpacity:1}).addTo(m);
  });
}

let _leafletPromise=null;
function loadLeaflet(){
  if(window.L) return Promise.resolve();
  if(_leafletPromise) return _leafletPromise;
  _leafletPromise=new Promise(resolve=>{
    const css=document.createElement("link"); css.rel="stylesheet"; css.href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"; document.head.appendChild(css);
    const js=document.createElement("script"); js.src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"; js.onload=resolve; js.onerror=resolve; document.head.appendChild(js);
  });
  return _leafletPromise;
}

/* POST-WORKOUT AI SUMMARY */
function showWorkoutSummary(workout, rpe, aiSummary) {
  const dur = workout.duration_min || 0;
  const cal = Math.round(dur * 6.5);
  const rpeColor = rpe >= 8 ? "var(--bad)" : rpe >= 6 ? "var(--activity)" : "var(--nutrition)";
  const rpeLabel = rpe >= 9 ? "Maksymalny" : rpe >= 7 ? "Intensywny" : rpe >= 5 ? "Umiarkowany" : "Lekki";

  const modal = el(`<div class="player-overlay fade" style="justify-content:center;padding:24px">
    <div style="background:var(--surface);border-radius:var(--r-lg);padding:24px;width:100%;max-width:400px;border:1px solid var(--border)">
      <div style="text-align:center;margin-bottom:20px">
        <div style="font-size:48px;margin-bottom:8px">🏆</div>
        <h2 style="margin:0;font-size:22px">Trening zakończony!</h2>
        <div style="color:var(--txt2);font-size:14px;margin-top:4px">${esc(workout.title||"Trening")}</div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:20px">
        <div style="background:var(--surface2);border-radius:14px;padding:12px;text-align:center;border:1px solid var(--border)">
          <div style="font-size:22px;font-weight:900;color:var(--activity)">${dur}</div>
          <div style="font-size:11px;color:var(--txt2)">minut</div>
        </div>
        <div style="background:var(--surface2);border-radius:14px;padding:12px;text-align:center;border:1px solid var(--border)">
          <div style="font-size:22px;font-weight:900;color:var(--warn)">${cal}</div>
          <div style="font-size:11px;color:var(--txt2)">kcal</div>
        </div>
        <div style="background:var(--surface2);border-radius:14px;padding:12px;text-align:center;border:1px solid var(--border)">
          <div style="font-size:22px;font-weight:900;color:${rpeColor}">${rpe||"—"}</div>
          <div style="font-size:11px;color:var(--txt2)">RPE ${rpe?`(${rpeLabel})`:""}</div>
        </div>
      </div>

      <div style="background:linear-gradient(135deg,rgba(124,92,252,.12),rgba(38,198,218,.08));border:1px solid rgba(124,92,252,.3);border-radius:16px;padding:16px;margin-bottom:20px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <span style="font-size:18px">✨</span>
          <span style="font-size:12px;font-weight:700;color:var(--sleep);text-transform:uppercase;letter-spacing:.5px">Analiza AI — Pulse</span>
        </div>
        <div style="font-size:14px;line-height:1.6;color:var(--txt)">${esc(aiSummary)}</div>
      </div>

      <button class="btn primary" id="closeSummary">Gotowe</button>
    </div>
  </div>`);

  modal.querySelector("#closeSummary").addEventListener("click", ()=>{
    modal.remove();
    // Odśwież dane i pokaż w Treningach
    loadData().then(()=>{ switchTab("workouts"); });
  });
  document.body.appendChild(modal);
}

/* WORKOUT PLAYER */
let _playerRpe=null;
function openPlayer(workout){
  _playerRpe=null;
  const overlay=el(`<div class="player-overlay fade"></div>`);
  const header=el(`<div class="player-header"><h2>${esc(workout.title||"Trening")}<br><span style="font-size:12px;color:var(--txt2);font-weight:400">${workout.duration_min} min</span></h2><button class="player-close">✕ Zakończ</button></div>`);
  const body=el(`<div class="player-body"></div>`);
  const footer=el(`<div class="player-footer"><div class="muted" style="font-size:13px;margin-bottom:8px">Jak trudny był trening? RPE 1–10</div><div class="rpe-pick" id="rpePick"></div><button class="btn activity-btn" id="saveWkt" style="margin-top:12px">Zapisz trening</button></div>`);
  const doneSets=new Set();
  (workout.sections||[]).forEach(sec=>{
    body.appendChild(el(`<div class="section-title">${esc(sec.name)} · ${sec.duration_min} min</div>`));
    (sec.exercises||[]).forEach((ex,ei)=>{
      const id=`${sec.name}-${ei}`;
      const meta=[ex.sets&&`${ex.sets}×${ex.reps}`,ex.weight,ex.rest_sec&&`przerwa ${ex.rest_sec}s`].filter(Boolean).join(" · ");
      const row=el(`<div class="ex-row" data-id="${id}"><div class="ex-check"></div><div class="ex-info"><div class="ex-name">${esc(ex.name)}</div><div class="ex-meta">${meta}</div>${ex.note?`<div class="ex-note">${esc(ex.note)}</div>`:""}</div></div>`);
      row.addEventListener("click",()=>{
        doneSets.has(id)?doneSets.delete(id):doneSets.add(id);
        row.classList.toggle("done",doneSets.has(id));
        row.querySelector(".ex-check").textContent=doneSets.has(id)?"✓":"";
      });
      body.appendChild(row);
    });
  });
  for(let i=1;i<=10;i++){
    const btn=el(`<button>${i}</button>`);
    btn.addEventListener("click",()=>{_playerRpe=i;footer.querySelectorAll(".rpe-pick button").forEach(b=>b.classList.toggle("active",b.textContent==i));});
    footer.querySelector("#rpePick").appendChild(btn);
  }
  header.querySelector(".player-close").addEventListener("click",()=>overlay.remove());
  footer.querySelector("#saveWkt").addEventListener("click",async()=>{
    // Zmień przycisk na "Zapisuję..."
    const saveBtn = footer.querySelector("#saveWkt");
    saveBtn.textContent = "Zapisuję i analizuję…";
    saveBtn.disabled = true;

    const res = await api("/api/workout/log",{method:"POST",body:JSON.stringify({
      title:workout.title, duration_min:workout.duration_min,
      rpe:_playerRpe, calories:Math.round((workout.duration_min||30)*6.5)
    })});

    overlay.remove();

    // Pokaż AI podsumowanie po treningu
    if(res.summary) {
      showWorkoutSummary(workout, _playerRpe, res.summary);
    } else {
      toast(`Trening zapisany!${_playerRpe?` RPE ${_playerRpe}/10`:""}`);
    }
  });
  overlay.appendChild(header);overlay.appendChild(body);overlay.appendChild(footer);
  document.body.appendChild(overlay);
}

/* WORKOUT GENERATOR MODAL */
async function openWorkoutGenerator(d){
  const ready=d?.readiness?.score||70;
  const overlay=el(`<div class="player-overlay fade"></div>`);
  const header=el(`<div class="player-header"><h2>Generator Treningu AI</h2><button class="player-close">✕</button></div>`);
  const body=el(`<div class="player-body"></div>`);
  const form=el(`<div class="gen-form">
    <select id="gType"><option value="siłowy">💪 Siłowy</option><option value="cardio">🏃 Cardio</option><option value="HIIT">💥 HIIT</option><option value="stretch">🧘 Rozciąganie / Joga</option><option value="mieszany">⚡ Mieszany</option></select>
    <select id="gEquip"><option value="brak">Bez sprzętu</option><option value="hantle">Hantle</option><option value="sztanga,hantle">Sztanga + hantle</option><option value="maszyny siłowni">Maszyny siłowni</option><option value="gumy oporowe">Gumy oporowe</option></select>
    <input id="gFocus" placeholder="Skupienie (np. klata i plecy, nogi, core)" value="całe ciało"/>
    <select id="gDuration"><option value="20">20 min</option><option value="30">30 min</option><option value="45" selected>45 min</option><option value="60">60 min</option></select>
    <select id="gLevel"><option value="lekki">Lekki</option><option value="sredni" selected>Średni</option><option value="zaawansowany">Zaawansowany</option></select>
    <div class="muted" style="font-size:13px;text-align:center">Gotowość: ${ready}/100 — ${ready>=75?"intensywny":ready>=50?"umiarkowany":"lekki"}</div>
    <button class="btn activity-btn" id="genBtn">⚙️ Wygeneruj trening AI</button>
  </div>`);
  body.appendChild(form);
  header.querySelector(".player-close").addEventListener("click",()=>overlay.remove());
  form.querySelector("#genBtn").addEventListener("click",async()=>{
    form.innerHTML=`<div class="generating"><div class="spin">⚙️</div><div style="margin-top:14px">AI generuje trening…<br><span style="font-size:13px;color:var(--txt2)">może potrwać ~15 sekund</span></div></div>`;
    const res=await api("/api/workout/generate",{method:"POST",body:JSON.stringify({type:overlay.querySelector("#gType")?.value||"mieszany",equipment:overlay.querySelector("#gEquip")?.value||"brak",focus:overlay.querySelector("#gFocus")?.value||"całe ciało",duration_min:parseInt(overlay.querySelector("#gDuration")?.value||"45"),level:overlay.querySelector("#gLevel")?.value||"sredni",readiness_score:ready})}).catch(()=>({error:"Błąd sieci"}));
    overlay.remove();
    if(res.ok&&res.workout) openPlayer(res.workout);
    else toast("Nie udało się — spróbuj ponownie.");
  });
  overlay.appendChild(header);overlay.appendChild(body);
  document.body.appendChild(overlay);
}

/* COACH */
function renderCoach(){
  const d=State.data, wrap=el(`<div></div>`);
  const g=d.goals_catalog?.[State.goal]||{label:State.goal,emoji:"🎯"};
  wrap.appendChild(el(`<div class="coach-header"><h2>Coach AI ✨</h2><div class="sub">Cel: ${g.emoji} ${g.label}</div></div>`));

  // Goal grid
  const gg=el(`<div class="card" style="margin-bottom:12px"><h3>Mój cel</h3><div class="goal-grid" id="goalGrid"></div><div class="muted" style="font-size:12.5px;margin-top:10px">Wybierz cel lub opisz coachowi co chcesz robić — dostosuje całą apkę.</div></div>`);
  const grid=gg.querySelector("#goalGrid");
  const BUILTIN=["maintain","running","cycling","swimming","strength","weight_loss","sleep"];
  BUILTIN.forEach(id=>{
    const gc=d.goals_catalog?.[id]; if(!gc) return;
    const btn=el(`<div class="goal-tile ${id===State.goal?"active":""}"><div class="ge">${gc.emoji}</div><div class="gl">${gc.label}</div></div>`);
    btn.addEventListener("click",()=>setGoal(id));
    grid.appendChild(btn);
  });
  const custom=d.custom_goal||(d.goals_catalog?.[State.goal]?.custom?d.goals_catalog[State.goal]:null);
  if(custom&&!BUILTIN.includes(custom.goal)){
    const btn=el(`<div class="goal-tile ${custom.goal===State.goal?"active":""}"><div class="ge">${custom.emoji}</div><div class="gl">${custom.label}</div></div>`);
    btn.addEventListener("click",()=>setGoal(custom.goal));
    grid.appendChild(btn);
  }
  wrap.appendChild(gg);

  // Generator button
  const genCard=el(`<div class="card" style="margin-bottom:12px"><h3>Generator Treningu AI</h3><div class="muted" style="font-size:13px;margin-bottom:12px">Gotowość dziś: ${d.readiness?.score||"—"}/100 · AI dobierze intensywność automatycznie.</div><button class="btn activity-btn" id="openGen">⚙️ Stwórz trening na dziś</button></div>`);
  genCard.querySelector("#openGen").addEventListener("click",()=>openWorkoutGenerator(d));
  wrap.appendChild(genCard);

  // Chat
  const chatCard=el(`<div class="chat-container"></div>`);
  const msgs=el(`<div class="chat-messages" id="chat"></div>`);
  chatCard.appendChild(msgs);

  // Suggestion pills
  const pillsEl=el(`<div class="chat-pills" id="chatPills"></div>`);
  const pills=generatePills(d);
  pills.forEach(p=>{
    const btn=el(`<div class="pill">${p}</div>`);
    btn.addEventListener("click",()=>{const inp=$("#chatIn");if(inp){inp.value=p;sendChat();}});
    pillsEl.appendChild(btn);
  });
  chatCard.appendChild(pillsEl);

  const inputRow=el(`<div class="chat-input-row"><div class="chat-cam" id="camBtn">📷</div><input id="chatIn" placeholder="Napisz coachowi…"/><button class="chat-send" id="chatSend">↑</button></div>`);
  chatCard.appendChild(inputRow);
  wrap.appendChild(chatCard);

  // Insights
  if(d.insights&&d.insights.length){
    const ic=el(`<div class="card"><h3>Spostrzeżenia</h3></div>`);
    d.insights.forEach(i=>ic.appendChild(el(`<div class="insight ${i.type}"><div class="ic">${i.icon}</div><div><div class="it">${i.title}</div><div class="ix">${i.text}</div></div></div>`)));
    wrap.appendChild(ic);
  }

  // Plans
  if(d.action_plans&&d.action_plans.length){
    const pc=el(`<div class="card"><h3>Plan na dziś</h3><div class="plan-tabs" id="planTabs"></div><div id="planBody"></div></div>`);
    const tabs=pc.querySelector("#planTabs");
    d.action_plans.forEach(p=>{ const btn=el(`<button data-id="${p.id}" class="${p.id===State.plan?"active":""}">${p.icon} ${p.title}</button>`); btn.addEventListener("click",()=>{State.plan=p.id;renderPlanBody(pc.querySelector("#planBody"),tabs);}); tabs.appendChild(btn); });
    wrap.appendChild(pc);
    renderPlanBody(pc.querySelector("#planBody"),tabs);
  }

  // Report
  if(State.report?.text){
    const src=State.report.source==="groq"?"Llama 3.3 70B":"analiza lokalna";
    wrap.appendChild(el(`<div class="card"><h3 style="display:flex;justify-content:space-between">Raport Pulse <span style="color:var(--txt2);font-size:11px;font-weight:400">${src}</span></h3><div class="bubble ai" style="max-width:100%;font-size:12.5px;font-family:ui-monospace,Menlo,monospace;white-space:pre-wrap">${esc(State.report.text)}</div></div>`));
  }

  setTimeout(()=>{
    paintChat();
    $("#chatSend")?.addEventListener("click",sendChat);
    $("#chatIn")?.addEventListener("keydown",e=>{if(e.key==="Enter")sendChat();});
    $("#camBtn")?.addEventListener("click",openCamera);
  },20);
  return wrap;
}

function generatePills(d){
  const pills=[];
  const s=d.today?.sleep||{};
  const r=d.readiness||{};
  if(s.sleep_score&&s.sleep_score<70) pills.push("Dlaczego mój sen był słaby?");
  if(r.score&&r.score<60) pills.push("Niska gotowość — co robić?");
  if(r.score&&r.score>=80) pills.push("Zrób mi trening na dziś");
  pills.push("Analizuj moje trendy tygodniowe");
  pills.push("Zaproponuj plan na jutro");
  if(d.insights?.length) pills.push(`${d.insights[0].icon} ${d.insights[0].title}`);
  return pills.slice(0,5);
}

function renderPlanBody(body,tabs){
  [...tabs.children].forEach(b=>b.classList.toggle("active",b.dataset.id===State.plan));
  const p=(State.data?.action_plans||[]).find(x=>x.id===State.plan); body.innerHTML="";
  if(!p) return;
  if(p.headline) body.appendChild(el(`<div class="plan-head">${p.headline}</div>`));
  const ul=el(`<ul class="plan"></ul>`);
  (p.items||[]).forEach(i=>ul.appendChild(el(`<li>${i}</li>`)));
  body.appendChild(el(`<div class="plan"></div>`)).appendChild(ul);
}

function stripSetGoal(text){return text.replace(/<<SET_GOAL:[\s\S]*?>>?/g,"").trim();}
function paintChat(){
  const c=$("#chat"); if(!c) return; c.innerHTML="";
  if(!State.chat.length) c.appendChild(el(`<div class="bubble ai">Cześć Franek! Napisz mi o czym marzysz — "zrób mi trening siłowy", "jak mój sen?", albo cokolwiek innego. Analizuję Twoje dane na bieżąco.</div>`));
  for(const m of State.chat){
    if(m.role==="__workout"&&m.workout){
      const w=m.workout;
      const wb=el(`<div class="bubble ai" style="padding:10px 12px"><div style="font-weight:800;font-size:15px;margin-bottom:4px">🏋️ ${esc(w.title||"Trening")}</div><div class="muted" style="font-size:12px;margin-bottom:10px">${w.duration_min} min · ${(w.sections||[]).length} sekcje · ${(w.sections||[]).reduce((a,s)=>a+(s.exercises||[]).length,0)} ćwiczeń</div><button class="btn activity-btn" style="font-size:13px;padding:10px">▶ Otwórz Workout Player</button></div>`);
      wb.querySelector("button").addEventListener("click",()=>openPlayer(w));
      c.appendChild(wb); continue;
    }
    const isAI=m.role==="ai"||m.role==="assistant";
    const txt=isAI?stripSetGoal(m.content):m.content;
    const cls=m.role==="user"?"me":"ai";
    const style=m.role==="error"?' style="opacity:.6"':"";
    if(txt) c.appendChild(el(`<div class="bubble ${cls}"${style}>${esc(txt)}</div>`));
  }
  c.scrollTop=c.scrollHeight;
}

async function sendChat(){
  const inp=$("#chatIn"); const text=inp?.value?.trim(); if(!text) return;
  if(inp) inp.value="";
  State.chat.push({role:"user",content:text}); paintChat();
  const c=$("#chat"); const typing=el(`<div class="typing">Pulse pisze…</div>`); c?.appendChild(typing); if(c) c.scrollTop=c.scrollHeight;
  try{
    const toSend=State.chat.filter(m=>m.role!=="error"&&m.role!=="__workout");
    const wCtx = _weather ? `${_weather.desc} ${_weather.temp}°C, odczuwalnie ${_weather.feel}°C, wiatr ${_weather.wind} km/h` : "";
    const r=await api("/api/chat",{method:"POST",body:JSON.stringify({messages:toSend,goal:State.goal,weather_ctx:wCtx})});
    typing?.remove();
    const reply=stripSetGoal(r.reply||"").trim()||"(brak odpowiedzi)";
    State.chat.push({role:"ai",content:reply});
    if(r.workout?.sections) State.chat.push({role:"__workout",workout:r.workout,content:"__workout__"});
    paintChat();
    if(r.set_goal?.goal) await setGoal(r.set_goal.goal,true);
  }catch(e){typing?.remove();State.chat.push({role:"error",content:"⚠️ Błąd — spróbuj ponownie."});paintChat();}
}

async function setGoal(id,fromChat=false){
  State.goal=id;localStorage.setItem("pulse_goal",id);
  await loadData();
  const g=State.data?.goals_catalog?.[id]||State.data?.custom_goal||{emoji:"🎯",label:id};
  toast(`Cel: ${g.emoji} ${g.label}`);
  render();
}

/* CAMERA — food/workout scanning via Groq vision */
function openCamera(){
  const ov=el(`<div class="cam-overlay"><h3>📷 Skanuj zdjęcie</h3><p>Zrób zdjęcie posiłku lub rozpiski treningowej — AI przetworzy je na dane w aplikacji.</p><label class="cam-label" for="camFile">Wybierz zdjęcie</label><input type="file" id="camFile" accept="image/*" capture="environment"/><div class="cam-close" id="camClose">Anuluj</div></div>`);
  document.body.appendChild(ov);
  ov.querySelector("#camClose").addEventListener("click",()=>ov.remove());
  ov.querySelector("#camFile").addEventListener("change",async(e)=>{
    const file=e.target.files?.[0]; if(!file) return;
    const ph=ov.querySelector(".cam-processing")||el(`<div class="cam-processing">Przetwarzam zdjęcie…</div>`);
    ov.appendChild(ph);
    const reader=new FileReader();
    reader.onload=async(ev)=>{
      const b64=ev.target.result.split(",")[1];
      const res=await api("/api/scan-image",{method:"POST",body:JSON.stringify({image_b64:b64,mime_type:file.type})}).catch(()=>({ok:false}));
      ov.remove();
      if(res.ok&&res.result){
        toast("Zdjęcie przeanalizowane!");
        State.chat.push({role:"ai",content:`📷 Analiza: ${res.result}`});
        switchTab("coach"); setTimeout(paintChat,100);
      } else toast(res.error||"Nie udało się przetworzyć zdjęcia.");
    };
    reader.readAsDataURL(file);
  });
}

/* PROFILE */
async function renderProfile(){
  const d=State.data, b=d.baselines||{}, wrap=el(`<div></div>`);
  const g=d.goals_catalog?.[State.goal]||{label:State.goal,emoji:"🎯"};
  wrap.appendChild(el(`<div class="page-header"><div class="greeting"><h2>Profil</h2><div class="date">Franek</div></div><div class="goal-chip">${g.emoji} ${g.label}</div></div>`));

  // Journal
  const jCard=el(`<div class="card"><h3>Dziennik dziś</h3></div>`);
  const jd=await api("/api/journal").catch(()=>({today:{},journal:[]}));
  const jt=jd.today||{};
  const MOODS=["😞","😐","🙂","😊","😁"];
  let selMood=jt.mood||0;
  const wRow=el(`<div class="row"><div><div class="k">⚖️ Waga</div></div><div class="num-input"><input type="number" id="jWeight" placeholder="kg" step="0.1" value="${jt.weight_kg||""}" style="width:80px"/><span>kg${jt.weight_kg?` · BMI ${(jt.weight_kg/3.1684).toFixed(1)}`:""}</span></div></div>`);
  jCard.appendChild(wRow);
  const mRow=el(`<div style="padding:12px 0;border-bottom:1px solid var(--border)"><div class="k" style="margin-bottom:8px">😊 Nastrój</div><div class="mood-pick" id="moodPick"></div></div>`);
  let moodPick;
  MOODS.forEach((em,i)=>{const btn=el(`<button class="mood-btn ${selMood===i+1?"active":""}">${em}</button>`);btn.addEventListener("click",()=>{selMood=i+1;(moodPick||mRow.querySelector("#moodPick")).querySelectorAll(".mood-btn").forEach((b,j)=>b.classList.toggle("active",j===i));});mRow.querySelector("#moodPick").appendChild(btn);});
  jCard.appendChild(mRow);
  jCard.appendChild(el(`<div class="row"><div class="k">💧 Woda</div><div class="num-input"><input type="number" id="jWater" min="0" max="20" value="${jt.water_glasses||""}" style="width:60px"/><span>szklanek</span></div></div>`));
  jCard.appendChild(el(`<div style="padding:12px 0;border-bottom:1px solid var(--border)"><div class="k" style="margin-bottom:8px">🍽️ Kalorie i makra</div><div style="display:flex;flex-wrap:wrap;gap:8px">
    <div class="num-input"><input type="number" id="jCal" placeholder="kcal" value="${jt.calories_eaten||""}" style="width:80px"/><span>kcal</span></div>
    <div class="num-input"><input type="number" id="jProt" placeholder="białko" value="${jt.protein_g||""}" style="width:65px"/><span>g B</span></div>
    <div class="num-input"><input type="number" id="jCarbs" placeholder="węgle" value="${jt.carbs_g||""}" style="width:65px"/><span>g W</span></div>
    <div class="num-input"><input type="number" id="jFat" placeholder="tłuszcz" value="${jt.fat_g||""}" style="width:65px"/><span>g T</span></div>
  </div></div>`));
  const saveJ=el(`<button class="btn primary" style="margin-top:12px">Zapisz dziennik</button>`);
  saveJ.addEventListener("click",async()=>{
    const body={};
    const w=parseFloat(jCard.querySelector("#jWeight")?.value);if(!isNaN(w)&&w>0) body.weight_kg=w;
    if(selMood) body.mood=selMood;
    const wtr=parseInt(jCard.querySelector("#jWater")?.value);if(!isNaN(wtr)) body.water_glasses=wtr;
    const cal=parseInt(jCard.querySelector("#jCal")?.value);if(!isNaN(cal)) body.calories_eaten=cal;
    const prot=parseInt(jCard.querySelector("#jProt")?.value);if(!isNaN(prot)) body.protein_g=prot;
    const carbs=parseInt(jCard.querySelector("#jCarbs")?.value);if(!isNaN(carbs)) body.carbs_g=carbs;
    const fat=parseInt(jCard.querySelector("#jFat")?.value);if(!isNaN(fat)) body.fat_g=fat;
    await api("/api/journal",{method:"POST",body:JSON.stringify(body)});
    toast("Dziennik zapisany ✓");
  });
  jCard.appendChild(saveJ);
  wrap.appendChild(jCard);

  // Baselines
  wrap.appendChild(el(`<div class="card"><h3>Twoje linie bazowe</h3>
    <div class="row"><span class="k">Tętno spoczynkowe</span><span class="v" style="color:var(--resilience)">${num(b.rhr,0)} bpm</span></div>
    <div class="row"><span class="k">HRV</span><span class="v" style="color:var(--resilience)">${num(b.hrv,0)} ms</span></div>
    <div class="row"><span class="k">Średni sen</span><span class="v" style="color:var(--sleep)">${hm(b.sleep)}</span></div>
    <div class="row"><span class="k">Średnie kroki</span><span class="v" style="color:var(--activity)">${num(b.steps,0)}</span></div>
    <div class="row"><span class="k">Sleep Score śr.</span><span class="v" style="color:var(--sleep)">${num(b.sleep_score,0)}/100</span></div>
  </div>`));

  // Reminders
  const rc=el(`<div class="card"><h3>Przypominajki</h3><div class="row"><div><div class="k">Powiadomienia push</div><div class="ksub" id="pushStatus">Włącz w Safari po instalacji</div></div><button class="goal-chip" id="pushBtn">Włącz</button></div><div id="remList"></div><button class="btn ghost" id="testPush" style="margin-top:12px">Wyślij testowe</button></div>`);
  wrap.appendChild(rc);

  // Install
  wrap.appendChild(el(`<div class="card"><h3>Zainstaluj na iPhone</h3><ol class="install-steps"><li>Otwórz w <strong>Safari</strong>.</li><li>Dotknij <strong>Udostępnij</strong> (kwadrat ze strzałką).</li><li>Wybierz <strong>„Do ekranu początkowego"</strong>.</li><li>Otwórz z ikony — wtedy działają push.</li></ol></div>`));

  const exp=el(`<button class="btn ghost">⬇ Pobierz dane (JSON)</button>`);
  exp.addEventListener("click",async()=>{const d=await api("/api/export");const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:"application/json"}));a.download="bioaipulse.json";a.click();});
  wrap.appendChild(exp);
  const out=el(`<button class="btn danger">Wyloguj</button>`);out.addEventListener("click",logout);wrap.appendChild(out);
  wrap.appendChild(el(`<div class="muted" style="text-align:center;margin-top:16px;font-size:11px">BioAI-Pulse · dane chronione · nie jest urządzeniem medycznym</div>`));

  setTimeout(async()=>{
    const remData=await api("/api/reminders").catch(()=>({items:[]}));
    State.reminders=remData.items||[];
    const list=$("#remList"); if(!list) return;
    State.reminders.forEach((it,idx)=>{
      const when=it.kind==="daily"?`codziennie ${it.time}`:`co ${Math.round(it.every_min/60*10)/10}h (${it.from}–${it.to})`;
      const row=el(`<div class="row"><div><div class="k">${it.emoji} ${it.label}</div><div class="ksub">${when}</div></div><label class="switch"><input type="checkbox" ${it.enabled?"checked":""}><span class="sl"></span></label></div>`);
      row.querySelector("input").addEventListener("change",async(e)=>{State.reminders[idx].enabled=e.target.checked;await api("/api/reminders",{method:"POST",body:JSON.stringify({items:State.reminders})});toast("Zapisano");});
      list.appendChild(row);
    });
    $("#testPush")?.addEventListener("click",async()=>{const r=await api("/api/push/test",{method:"POST"}).catch(()=>({ok:false}));toast(r.ok?`Wysłano (${r.sent})`:(r.error||"Włącz push najpierw"));});
    $("#pushBtn")?.addEventListener("click",enablePush);
  },30);
  return wrap;
}

function urlB64ToUint8(base64){const pad="=".repeat((4-base64.length%4)%4),b64=(base64+pad).replace(/-/g,"+").replace(/_/g,"/"),raw=atob(b64);return Uint8Array.from([...raw].map(c=>c.charCodeAt(0)));}
async function enablePush(){
  try{
    const keyRes=await api("/api/push/key");
    if(!keyRes.configured){toast("Push nie skonfigurowany na serwerze.");return;}
    const perm=await Notification.requestPermission();
    if(perm!=="granted"){toast("Brak zgody na powiadomienia.");return;}
    const reg=await navigator.serviceWorker.ready;
    const sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:urlB64ToUint8(keyRes.key)});
    await api("/api/push/subscribe",{method:"POST",body:JSON.stringify(sub)});
    toast("Powiadomienia włączone ✅");
    $("#pushStatus").textContent="Powiadomienia włączone ✅";
    $("#pushBtn").textContent="Włączone";
  }catch(e){toast("Błąd push: "+e.message);}
}

/* GOALS WIDGET */
async function toggleGoal(id,card,d){
  const ch=State.checkedGoals||[];
  const idx=ch.indexOf(id);
  if(idx>=0) ch.splice(idx,1);else ch.push(id);
  State.checkedGoals=ch;
  api("/api/goals/check",{method:"POST",body:JSON.stringify({checked:ch})}).catch(()=>{});
  const fresh=wGoalsToday(d);
  if(fresh&&card.parentNode) card.parentNode.replaceChild(fresh,card);
}
function wGoalsToday(d){
  const tasks=d.daily_goals||[];if(!tasks.length) return null;
  const checked=State.checkedGoals||[];
  const done=tasks.filter(t=>checked.includes(t.id)).length;
  const pct=Math.round(done/tasks.length*100);
  const card=el(`<div class="card"><h3>Cele na dziś</h3><div class="goals-progress"><div class="gp-bar"><i style="width:${pct}%"></i></div><span class="gp-lbl">${done}/${tasks.length}</span></div><div class="goals-today" id="gtList"></div></div>`);
  const list=card.querySelector("#gtList");
  tasks.forEach(t=>{
    const isDone=checked.includes(t.id);
    const row=el(`<div class="gtask ${isDone?"done":""}" data-id="${t.id}"><span class="gt-ic">${t.icon}</span><div style="flex:1"><div class="gt-text">${t.text}</div><div class="gt-cat">${t.cat}</div></div><span class="gt-check">${isDone?"✓":""}</span></div>`);
    row.addEventListener("click",()=>toggleGoal(t.id,card,d));
    list.appendChild(row);
  });
  return card;
}

/* RENDER ENGINE */
const mkChart=(id,cfg)=>{const cv=document.getElementById(id);if(cv) State.charts[id]=new Chart(cv.getContext("2d"),cfg);};

async function render(){
  const v=$("#view");
  Object.values(State.charts).forEach(c=>c&&c.destroy()); State.charts={};
  if(State.map){State.map.remove();State.map=null;}
  const map={today:renderToday,trends:renderTrends,workouts:renderWorkouts,coach:renderCoach,profile:renderProfile};
  v.innerHTML="";
  const result=map[State.tab]();
  const node=result instanceof Promise?await result:result;
  node.classList.add("fade");
  v.appendChild(node);
  window.scrollTo(0,0);
}

function switchTab(tab){
  State.tab=tab;
  document.querySelectorAll(".tab").forEach(t=>t.classList.toggle("active",t.dataset.tab===tab));
  render();
}

document.querySelector(".tabbar")?.addEventListener("click",e=>{
  const b=e.target.closest(".tab");if(!b) return;
  switchTab(b.dataset.tab);
});

/* INIT */
setupLogin();
if(State.token) enterApp(); else $("#login").classList.remove("hidden");
if("serviceWorker" in navigator) window.addEventListener("load",()=>navigator.serviceWorker.register("/sw.js").catch(()=>{}));
