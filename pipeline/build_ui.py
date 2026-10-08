"""Render data/scores.json into the Dailies grading artifact (out/dailies.html).

Static HTML/CSS/JS, no build step, no library. The film pool is baked in as a
JSON blob at publish time; grading state lives in the artifact's own `db`
capability so it persists across sessions and is readable back by the
pipeline (see pipeline/pull_grades.py).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

BUILD_TOP = int(os.environ.get("BUILD_TOP", "80"))
ITER = os.environ.get("ITER", "01")


def main():
    with open(os.path.join(common.DATA, "scores.json"), encoding="utf-8") as fh:
        S = json.load(fh)
    CFG = common.config()

    # Fresh candidates lead; anything already starred keeps a trailing slot so
    # it's still visible (dimmed, stamped) if you want to revisit a weight.
    fresh = [f for f in S["films"] if not f["already_graded"]]
    reviewed = [f for f in S["films"] if f["already_graded"]]
    selected = (fresh + reviewed)[:BUILD_TOP]

    poster_dir = os.path.join(common.DATA, "posters")
    films = []
    for f in selected:
        c = f["channels"]
        has_poster = os.path.exists(os.path.join(poster_dir, f["slug"] + ".jpg"))
        films.append({
            "slug": f["slug"], "title": f["title"], "year": f["year"],
            "score": f["score"], "g": c["g"], "t": c["t"], "p": c["p"], "q": c["q"],
            "pop": f["pop_adj"], "rating": f["rating"], "count": f["rating_count"],
            "genres": f["genres"], "mini": f["mini_themes"][:3],
            "dirs": f["directors"], "cast": f.get("cast_billed") or f["cast"][:6],
            "viaSeeds": f["via_seeds"][:3], "shared": f["shared_tokens"][:3],
            "viaPeople": f["via_people"][:3],
            "imdb": f.get("imdb"), "tmdb": f.get("tmdb"),
            "synopsis": f.get("synopsis") or "",
            "runtime": f.get("runtime"),
            "poster": ("posters/%s.jpg" % f["slug"]) if has_poster else None,
        })

    people = [p for p in S["people"][:16] if p["score"] >= 0.5]

    payload = {
        "iteration": ITER, "pool": S["pool"], "scored": S["scored"],
        "seeds": S["seed_count"], "weights": CFG["weights"],
        "films": films, "people": people,
    }
    data_json = json.dumps(payload, ensure_ascii=False)

    html = HTML_TEMPLATE.replace("__DATA_JSON__", data_json).replace("__ITER__", ITER)

    os.makedirs(common.OUT, exist_ok=True)
    out_path = os.path.join(common.OUT, "dailies.html")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    n_posters = sum(1 for f in films if f["poster"])
    print("wrote %s (%d films, %d with posters, %d bytes of embedded data)"
          % (out_path, len(films), n_posters, len(data_json)))


HTML_TEMPLATE = r"""<title>Dailies</title>
<style>
:root{
  --bg:#eef0ef; --surface:#ffffff; --surface-2:#e4e6e4; --border:#d3d6d3;
  --text:#17191a; --text-dim:#5b5f60; --text-faint:#8a8e8e;
  --accent:#b6702a; --accent-soft:rgba(182,112,42,.12); --accent-strong:#8f5a21;
  --teal:#2f8276; --teal-soft:rgba(47,130,118,.14);
  --plus:#3f8a52; --plus-soft:rgba(63,138,82,.14);
  --minus:#b3433b; --minus-soft:rgba(179,67,59,.13);
  --shadow:0 1px 2px rgba(20,20,18,.06), 0 6px 20px -8px rgba(20,20,18,.12);
  --sprocket:#cfd2cf;
  color-scheme: light;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0e1011; --surface:#17191b; --surface-2:#1e2123; --border:#2b2e30;
    --text:#ece9e2; --text-dim:#9a9d9f; --text-faint:#6c6f71;
    --accent:#e0a059; --accent-soft:rgba(224,160,89,.14); --accent-strong:#f0b571;
    --teal:#5db8aa; --teal-soft:rgba(93,184,170,.14);
    --plus:#6cb97e; --plus-soft:rgba(108,185,126,.16);
    --minus:#d9726a; --minus-soft:rgba(217,114,106,.15);
    --shadow:0 1px 2px rgba(0,0,0,.3), 0 10px 28px -10px rgba(0,0,0,.55);
    --sprocket:#2f3234;
    color-scheme: dark;
  }
}
:root[data-theme="dark"]{
  --bg:#0e1011; --surface:#17191b; --surface-2:#1e2123; --border:#2b2e30;
  --text:#ece9e2; --text-dim:#9a9d9f; --text-faint:#6c6f71;
  --accent:#e0a059; --accent-soft:rgba(224,160,89,.14); --accent-strong:#f0b571;
  --teal:#5db8aa; --teal-soft:rgba(93,184,170,.14);
  --plus:#6cb97e; --plus-soft:rgba(108,185,126,.16);
  --minus:#d9726a; --minus-soft:rgba(217,114,106,.15);
  --shadow:0 1px 2px rgba(0,0,0,.3), 0 10px 28px -10px rgba(0,0,0,.55);
  --sprocket:#2f3234;
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--text);
  font-family:"IBM Plex Sans",system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  padding:0 20px; padding-block:28px 72px;
}
.wrap{max-width:860px; margin:0 auto}
h1,h2,h3{font-family:"Fraunces",Georgia,serif; text-wrap:balance; margin:0}
.mono{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace}
a{color:var(--accent-strong)}

/* ---- masthead ---- */
.masthead{display:flex; justify-content:space-between; align-items:flex-end;
  gap:16px; flex-wrap:wrap; border-bottom:1px solid var(--border); padding-bottom:18px; margin-bottom:18px}
.masthead .eyebrow{font-size:12px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--accent-strong); font-weight:600; margin-bottom:6px}
.masthead h1{font-size:40px; font-weight:600; font-variation-settings:"SOFT" 60,"WONK" 1}
.masthead .sub{color:var(--text-dim); font-size:14.5px; margin-top:4px; max-width:46ch}
.stats{display:flex; gap:18px; flex-wrap:wrap}
.stat{text-align:right}
.stat .n{font-size:22px; font-weight:600}
.stat .l{font-size:10.5px; letter-spacing:.08em; text-transform:uppercase; color:var(--text-faint)}

/* ---- methodology strip ---- */
details.method{background:var(--surface); border:1px solid var(--border); border-radius:10px;
  padding:12px 16px; margin-bottom:16px; box-shadow:var(--shadow)}
details.method summary{cursor:pointer; font-size:13px; font-weight:600; color:var(--text-dim);
  list-style:none; display:flex; align-items:center; gap:8px}
details.method summary::-webkit-details-marker{display:none}
details.method summary::before{content:"\25B8"; color:var(--accent); transition:transform .15s}
details.method[open] summary::before{transform:rotate(90deg)}
.method-body{padding-top:12px; font-size:13px; color:var(--text-dim); line-height:1.55}
.chan-legend{display:flex; flex-wrap:wrap; gap:14px; margin-top:10px}
.chan-legend .ch{display:flex; align-items:center; gap:6px; font-size:12px}
.chan-legend .sw{width:10px; height:10px; border-radius:2px}

/* ---- tally bar ---- */
.tally{position:sticky; top:0; z-index:5; display:flex; align-items:center; gap:18px;
  background:var(--surface); border:1px solid var(--border); border-radius:10px;
  padding:10px 16px; margin-bottom:18px; box-shadow:var(--shadow); flex-wrap:wrap}
.tally .t-item{display:flex; align-items:baseline; gap:6px; font-size:13px; color:var(--text-dim)}
.tally .t-item b{font-size:16px; color:var(--text); font-family:"IBM Plex Mono",monospace}
.tally .spacer{flex:1}
.tally label{display:flex; align-items:center; gap:6px; font-size:12.5px; color:var(--text-dim); cursor:pointer}

/* ---- people strip ---- */
.people{display:flex; flex-wrap:wrap; gap:7px; margin-bottom:22px}
.people .chip{font-size:12px; padding:5px 10px; border-radius:20px; background:var(--surface-2);
  border:1px solid var(--border); color:var(--text-dim)}
.people .chip b{color:var(--text); font-weight:600}

/* ---- reel / cards ---- */
.reel{display:flex; flex-direction:column; gap:10px}
.card{position:relative; background:var(--surface); border:1px solid var(--border);
  border-radius:12px; padding:14px 18px 14px 28px; box-shadow:var(--shadow);
  display:flex; gap:14px; align-items:flex-start;
  transition:opacity .15s, transform .15s;}
.card.heavy{border-color:var(--plus); box-shadow:var(--shadow), inset 3px 0 0 -1px var(--plus)}
.card.light{border-color:var(--teal)}
.card.minus{opacity:.46}
.card .sprockets{position:absolute; left:0; top:0; bottom:0; width:12px;
  background-image:radial-gradient(circle, var(--sprocket) 2.5px, transparent 2.6px);
  background-size:12px 16px; background-position:center top 10px; background-repeat:repeat-y;
  border-right:1px solid var(--border); border-radius:12px 0 0 12px}
.poster{flex:none; width:70px; height:105px; border-radius:6px; overflow:hidden;
  background:var(--surface-2); box-shadow:var(--shadow)}
.poster img{width:100%; height:100%; object-fit:cover; display:block}
.poster .ph{width:100%; height:100%; display:flex; align-items:center; justify-content:center;
  font-family:"Fraunces",Georgia,serif; font-size:26px; color:var(--text-faint)}
.card-body{flex:1; min-width:0}
.card-top{display:flex; justify-content:space-between; gap:14px; align-items:flex-start}
.card-head{display:flex; gap:10px; align-items:baseline; flex-wrap:wrap}
.rank{font-family:"IBM Plex Mono",monospace; color:var(--text-faint); font-size:13px; min-width:2.4em}
.title{font-family:"Fraunces",Georgia,serif; font-size:19px; font-weight:600}
.year{color:var(--text-faint); font-size:13px}
.score{font-family:"IBM Plex Mono",monospace; font-size:13px; color:var(--accent-strong); font-weight:600; flex:none}
.meta{color:var(--text-dim); font-size:13px; margin-top:3px}
.synopsis{color:var(--text); font-size:13.5px; margin-top:7px; line-height:1.5; max-width:62ch}
.why{color:var(--text-dim); font-size:12.5px; margin-top:7px; line-height:1.5}
.why b{color:var(--text)}
.stamp{position:absolute; top:12px; right:18px; font-size:11px; font-weight:700;
  letter-spacing:.06em; text-transform:uppercase; padding:3px 8px; border-radius:5px}
.stamp.heavy{color:var(--plus); background:var(--plus-soft)}
.stamp.light{color:var(--teal); background:var(--teal-soft)}
.stamp.minus{color:var(--minus); background:var(--minus-soft)}
.stamp.maybe{color:var(--text-faint); background:var(--surface-2)}

.meter{display:flex; gap:3px; margin-top:10px; align-items:center}
.meter .seg{display:flex; align-items:center; gap:4px}
.meter .lab{font-family:"IBM Plex Mono",monospace; font-size:10px; color:var(--text-faint); width:9px}
.meter .bar{width:46px; height:6px; border-radius:3px; background:var(--surface-2); overflow:hidden}
.meter .bar i{display:block; height:100%; border-radius:3px}
.meter .g i{background:var(--accent)}
.meter .t i{background:var(--teal)}
.meter .p i{background:#9b7fd4}
.meter .q i{background:var(--text-faint)}

.actions{display:flex; gap:12px; align-items:center; margin-top:12px; flex-wrap:wrap}
.stars{display:flex; gap:2px; align-items:center}
.stars button{background:none; border:none; padding:2px; cursor:pointer; font-size:21px; line-height:1;
  color:var(--border); transition:transform .1s, color .1s}
.stars button:hover{transform:scale(1.15)}
.stars button.lit{color:var(--accent)}
.stars button.lit.weak{color:var(--teal)}
.stars button.lit.bad{color:var(--minus)}
.stars-label{font-size:11.5px; color:var(--text-faint); min-width:7.5em}
.btn{font-family:"IBM Plex Sans",sans-serif; font-size:13px; font-weight:600; border-radius:20px;
  padding:7px 15px; border:1px solid var(--border); background:var(--surface-2); color:var(--text);
  cursor:pointer; display:flex; align-items:center; gap:6px; transition:all .12s}
.btn:hover{filter:brightness(1.05)}
.btn:active{transform:scale(.97)}
.btn.seen{margin-left:auto; background:transparent; font-weight:500; color:var(--text-faint)}
.btn.seen.active-seen{color:var(--teal); border-color:var(--teal); background:var(--teal-soft)}
.btn[disabled]{opacity:.5; cursor:wait}
.gen-tags{font-size:11.5px; color:var(--text-faint); margin-left:2px}

footer{margin-top:40px; padding-top:18px; border-top:1px solid var(--border);
  color:var(--text-faint); font-size:12px; line-height:1.6}

@media (max-width:480px){
  .masthead h1{font-size:30px}
  .stats{gap:12px}
  .card{padding:12px 12px 12px 22px; gap:10px}
  .poster{width:52px; height:78px}
  .synopsis{max-width:none}
  .stars button{font-size:18px}
  .stars-label{min-width:0; width:100%; order:10}
}
</style>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght,SOFT,WONK@9..144,300..700,0..100,0..1&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">

<div class="wrap">

  <div class="masthead">
    <div>
      <div class="eyebrow">Reel __ITER__ &middot; Screening Notes</div>
      <h1>Dailies</h1>
      <div class="sub">Candidates pulled from your letterboxd taste graph. Star each one &mdash;
        5&#9733; feeds back heavy, 4&#9733; light, 1&ndash;2&#9733; is a pass &mdash; every call retunes the next reel.</div>
    </div>
    <div class="stats">
      <div class="stat"><div class="n mono" id="stat-pool">&ndash;</div><div class="l">pool</div></div>
      <div class="stat"><div class="n mono" id="stat-scored">&ndash;</div><div class="l">scored</div></div>
      <div class="stat"><div class="n mono" id="stat-seeds">&ndash;</div><div class="l">seeds</div></div>
    </div>
  </div>

  <details class="method">
    <summary>How this reel is cut</summary>
    <div class="method-body">
      Four signal channels score every candidate against your seed films, each normalized
      independently, then blended by the weights below &mdash; your grading is what moves them.
      A popularity correction then damps films so canonical they sit adjacent to everything,
      and lifts the deep cuts, since that's where this profile actually lives.
      <div class="chan-legend">
        <div class="ch"><span class="sw" style="background:var(--accent)"></span>
          <b>graph</b>&nbsp;&mdash; how many seeds converge on it, letterboxd similarity edges</div>
        <div class="ch"><span class="sw" style="background:var(--teal)"></span>
          <b>theme</b>&nbsp;&mdash; cosine match on letterboxd's mini-theme taxonomy</div>
        <div class="ch"><span class="sw" style="background:#9b7fd4"></span>
          <b>people</b>&nbsp;&mdash; director / writer / cast overlap with your over-represented people</div>
        <div class="ch"><span class="sw" style="background:var(--text-faint)"></span>
          <b>quality</b>&nbsp;&mdash; letterboxd rating, shrunk toward the mean by rating count</div>
      </div>
      <div style="margin-top:8px"><b>Stars feed the next crawl directly:</b> 5&#9733; promotes a film
        into the seed set at full weight, 4&#9733; at half weight, 3&#9733; is noted but not promoted,
        1&ndash;2&#9733; trains the channel weights as a miss. Change your mind any time &mdash; the
        star you set is the star that's stored.</div>
      <div style="margin-top:8px">Note: letterboxd files a few limited series (Twin Peaks: The Return,
        Baby Reindeer) under /film/ &mdash; pass on those if TV isn't what you're after.</div>
    </div>
  </details>

  <div class="tally">
    <div class="t-item">&#9733;&#9733;&#9733;&#9733;&#9733; heavy <b id="t-heavy">0</b></div>
    <div class="t-item">&#9733;&#9733;&#9733;&#9733; light <b id="t-light">0</b></div>
    <div class="t-item">&minus; passed <b id="t-minus">0</b></div>
    <div class="t-item">already seen <b id="t-seen">0</b></div>
    <div class="t-item">graded <b id="t-graded">0</b> / <span id="t-total" class="mono">0</span></div>
    <div class="spacer"></div>
    <label><input type="checkbox" id="hide-reviewed"> hide reviewed</label>
  </div>

  <div class="people" id="people"></div>

  <div class="reel" id="reel"></div>

  <footer>
    Grades save to this page's own store &mdash; they sync back across sessions and
    are what the next reel is cut from. Toggling a call off returns a card to neutral.
  </footer>
</div>

<script>
const DATA = __DATA_JSON__;
let grades = {}; // slug -> {grade, seen}
let db = null;
const pending = new Set();

function $(s, el=document){ return el.querySelector(s); }
function el(tag, cls, html){ const e=document.createElement(tag); if(cls) e.className=cls; if(html!=null) e.innerHTML=html; return e; }

function renderStats(){
  $('#stat-pool').textContent = DATA.pool;
  $('#stat-scored').textContent = DATA.scored;
  $('#stat-seeds').textContent = DATA.seeds;
  $('#t-total').textContent = DATA.films.length;
}

function renderPeople(){
  const wrap = $('#people'); wrap.innerHTML = '';
  for(const p of DATA.people){
    wrap.appendChild(el('div','chip', `<b>${p.name}</b> &middot; ${p.score.toFixed(2)}`));
  }
}

function bar(label, val, cls){
  const pct = Math.max(0, Math.min(100, val*100));
  return `<div class="seg"><span class="lab">${label}</span><span class="bar ${cls}"><i style="width:${pct}%"></i></span></div>`;
}

function why(f){
  const bits = [];
  if(f.viaSeeds && f.viaSeeds.length){
    bits.push(`converges from <b>${f.viaSeeds.length}</b> seeds (${f.viaSeeds.map(s=>s[0]).join(', ')})`);
  }
  if(f.shared && f.shared.length) bits.push(`shares ${f.shared.slice(0,2).join('; ').toLowerCase()}`);
  if(f.viaPeople && f.viaPeople.length) bits.push(`people: ${f.viaPeople.slice(0,2).join(', ')}`);
  return bits.join(' &middot; ') || 'theme-vector match only';
}

function cardState(slug){ return grades[slug] || {grade:null, seen:false}; }

function runtimeStr(mins){
  if(!mins) return null;
  const h = Math.floor(mins/60), m = mins%60;
  return h ? `${h}h ${m}m` : `${m}m`;
}

function gradeLabel(g){
  if(g===5) return {cls:'heavy', stamp:'kept — heavy', note:'weighs heavy as a seed'};
  if(g===4) return {cls:'light', stamp:'kept — light', note:'weighs light as a seed'};
  if(g===3) return {cls:'', stamp:'maybe', note:'noted, not promoted'};
  if(g) return {cls:'minus', stamp:'passed', note:''};
  return {cls:'', stamp:null, note:''};
}

function renderCard(f, idx){
  const st = cardState(f.slug);
  const card = el('div','card');
  card.dataset.slug = f.slug;
  const gl = gradeLabel(st.grade);
  if(gl.cls) card.classList.add(gl.cls);
  card.appendChild(el('div','sprockets'));

  if(gl.stamp) card.appendChild(el('div','stamp '+(gl.cls||'maybe'), gl.stamp));

  const poster = el('div','poster');
  if(f.poster){
    const img = el('img','',''); img.src = f.poster; img.alt = f.title; img.loading = 'lazy';
    poster.appendChild(img);
  } else {
    poster.appendChild(el('div','ph', f.title.charAt(0)));
  }
  card.appendChild(poster);

  const body = el('div','card-body');

  const top = el('div','card-top');
  const head = el('div','card-head');
  head.innerHTML = `<span class="rank mono">${String(idx+1).padStart(2,'0')}</span>
    <span class="title">${f.title}</span><span class="year">${f.year}</span>`;
  top.appendChild(head);
  top.appendChild(el('div','score',f.score.toFixed(1)));
  body.appendChild(top);

  const rt = runtimeStr(f.runtime);
  body.appendChild(el('div','meta',
    `dir. ${f.dirs.join(', ')||'&mdash;'} &middot; starring ${(f.cast||[]).slice(0,4).join(', ')||'&mdash;'}<br>`+
    `${f.genres.join(', ')||'&mdash;'}${rt?` &middot; ${rt}`:''} &middot; `+
    `${f.rating??'&ndash;'}&#9733; from ${(f.count||0).toLocaleString()} ratings`));

  if(f.synopsis) body.appendChild(el('div','synopsis', f.synopsis));

  body.appendChild(el('div','why', why(f)));

  body.appendChild(el('div','meter',
    bar('G',f.g,'g')+bar('T',f.t,'t')+bar('P',f.p,'p')+bar('Q',f.q,'q')));

  const actions = el('div','actions');

  const stars = el('div','stars');
  for(let i=1;i<=5;i++){
    const s = el('button','','&#9733;');
    s.title = i===5?'heavy — weighs full as a seed' : i===4?'light — weighs half as a seed'
      : i===3?'maybe — noted, not promoted' : i===2?'not really' : 'pass';
    if(st.grade && i<=st.grade){
      s.classList.add('lit');
      if(st.grade<=2) s.classList.add('bad');
      else if(st.grade===4) s.classList.add('weak');
    }
    s.onclick = () => toggleGrade(f, i);
    stars.appendChild(s);
  }
  actions.appendChild(stars);
  actions.appendChild(el('span','stars-label', gradeLabel(st.grade).note || 'tap a star to grade'));

  const seenBtn = el('button','btn seen','already seen');
  if(st.seen) seenBtn.classList.add('active-seen');
  seenBtn.onclick = () => toggleSeen(f, seenBtn);
  actions.appendChild(seenBtn);

  body.appendChild(actions);
  card.appendChild(body);
  return card;
}

function renderReel(){
  const reel = $('#reel'); reel.innerHTML = '';
  const hideReviewed = $('#hide-reviewed').checked;
  DATA.films.forEach((f, i) => {
    const st = cardState(f.slug);
    if(hideReviewed && st.grade) return;
    reel.appendChild(renderCard(f, i));
  });
  renderTally();
}

function renderTally(){
  let heavy=0, light=0, minus=0, seen=0, graded=0;
  for(const f of DATA.films){
    const st = cardState(f.slug);
    if(st.grade === 5) heavy++;
    if(st.grade === 4) light++;
    if(st.grade && st.grade <= 2) minus++;
    if(st.seen) seen++;
    if(st.grade) graded++;
  }
  $('#t-heavy').textContent = heavy;
  $('#t-light').textContent = light;
  $('#t-minus').textContent = minus;
  $('#t-seen').textContent = seen;
  $('#t-graded').textContent = graded;
}

async function writeDoc(slug, patch){
  if(!db) return;
  if(pending.has(slug)) return;
  pending.add(slug);
  const f = DATA.films.find(x=>x.slug===slug);
  const body = Object.assign({slug, title: f?f.title:slug}, cardState(slug), patch, {ts: Date.now()});
  try{ await db.collection('grades').doc(slug).set(body); }
  catch(e){ console.warn('grade write failed', e); }
  pending.delete(slug);
}

function toggleGrade(f, val){
  const st = cardState(f.slug);
  const next = (st.grade === val) ? null : val;
  grades[f.slug] = Object.assign({}, st, {grade: next});
  renderReel();
  writeDoc(f.slug, {grade: next});
}

function toggleSeen(f, btn){
  const st = cardState(f.slug);
  const next = !st.seen;
  grades[f.slug] = Object.assign({}, st, {seen: next});
  renderReel();
  writeDoc(f.slug, {seen: next});
}

$('#hide-reviewed').addEventListener('change', renderReel);

async function boot(){
  renderStats();
  renderPeople();
  renderReel();
  try{
    db = await claude.use('db');
    if(db){
      db.collection('grades').onSnapshot(snap => {
        const next = {};
        snap.docs.forEach(d => { const v = d.data(); if(v && v.slug) next[v.slug] = {grade: v.grade ?? null, seen: !!v.seen}; });
        grades = next;
        renderReel();
      }, err => console.warn('grades snapshot error', err));
    }
  }catch(e){ console.warn('db unavailable', e); }
}
boot();
</script>
"""

if __name__ == "__main__":
    main()
