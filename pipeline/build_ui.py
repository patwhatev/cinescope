"""Render data/scores.json into the Dailies grading page (out/dailies.html).

Static HTML/CSS/JS, no build step, no library. The film pool is baked in as a
JSON blob at publish time. Grading state's storage is swappable via MODE:

  MODE=artifact (default) -- writes through the Claude Artifact `db`
    capability. Only works served from claude.ai.
  MODE=local -- writes through a tiny JSON API (see pipeline/serve.py),
    for self-hosting. Run pipeline/serve.py and open http://localhost:8420.

Either way the film data and grading UI are identical; only the storage
backend's ~20 lines of JS differ (see ARTIFACT_BACKEND_JS / LOCAL_BACKEND_JS
below). pipeline/pull_grades.py reads the result back for tuning either way.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

BUILD_TOP = int(os.environ.get("BUILD_TOP", "80"))
ITER = os.environ.get("ITER", "01")
MODE = os.environ.get("MODE", "artifact")


def main():
    with open(os.path.join(common.DATA, "scores.json"), encoding="utf-8") as fh:
        S = json.load(fh)
    CFG = common.config()

    # Fresh candidates lead; anything already starred keeps a trailing slot so
    # it's still visible (dimmed, stamped) if you want to revisit a weight.
    selected = common.select_for_reel(S["films"], BUILD_TOP)

    # Anything graded that the reel doesn't carry -- promoted seeds, films
    # that fell out of the top slice -- trails at the end so it can still be
    # re-triaged as seen / unseen. Seeds aren't scored, so they come straight
    # from films.jsonl with no channel data.
    byslug = {f["slug"]: f for f in S["films"]}
    recs = common.load_films()
    triage = []
    for slug in common.triage_slugs([f["slug"] for f in selected]):
        if slug in byslug:
            triage.append(byslug[slug])
        elif slug in recs:
            triage.append(unscored(recs[slug]))

    poster_dir = os.path.join(common.DATA, "posters")
    films = []
    for f in selected + triage:
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
            "triage": f in triage,
        })

    people = [p for p in S["people"][:16] if p["score"] >= 0.5]

    payload = {
        "iteration": ITER, "pool": S["pool"], "scored": S["scored"],
        "seeds": S["seed_count"], "weights": CFG["weights"],
        "films": films, "people": people,
    }
    data_json = json.dumps(payload, ensure_ascii=False)

    backend_js = LOCAL_BACKEND_JS if MODE == "local" else ARTIFACT_BACKEND_JS
    html = (HTML_TEMPLATE
            .replace("__DATA_JSON__", data_json)
            .replace("__ITER__", ITER)
            .replace("__BACKEND_JS__", backend_js))

    os.makedirs(common.OUT, exist_ok=True)
    out_path = os.path.join(common.OUT, "dailies.html")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    n_posters = sum(1 for f in films if f["poster"])
    print("wrote %s [mode=%s] (%d films + %d to re-triage, %d with posters, "
          "%d bytes of embedded data)"
          % (out_path, MODE, len(selected), len(triage), n_posters, len(data_json)))


def unscored(rec):
    """A films.jsonl record shaped like a scores.json entry, for a graded film
    that isn't a candidate any more (i.e. it was promoted to a seed)."""
    names = lambda k: [n for _, n in rec.get(k) or []]
    return {
        "slug": rec["slug"], "title": rec.get("title") or rec["slug"],
        "year": rec.get("year"), "score": None,
        "channels": {"g": 0, "t": 0, "p": 0, "q": 0}, "pop_adj": None,
        "rating": rec.get("rating"), "rating_count": rec.get("rating_count"),
        "genres": names("genres"), "mini_themes": names("mini_themes"),
        "directors": names("directors"), "cast": names("cast")[:6],
        "cast_billed": rec.get("cast_billed"),
        "via_seeds": [], "shared_tokens": [], "via_people": [],
        "imdb": rec.get("imdb"), "tmdb": rec.get("tmdb"),
        "synopsis": rec.get("synopsis"), "runtime": rec.get("runtime"),
    }


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
.card.cold{opacity:.7}
.card.want{border-color:var(--accent)}
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
.stamp.want{color:var(--accent-strong); background:var(--accent-soft)}
.stamp.cold{color:var(--text-dim); background:var(--surface-2)}
.stamp.hint{color:var(--text-faint); background:transparent; border:1px dashed var(--border); font-weight:600}

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
.btn{font-family:"IBM Plex Sans",sans-serif; font-size:13px; font-weight:600; border-radius:20px;
  padding:7px 15px; border:1px solid var(--border); background:var(--surface-2); color:var(--text);
  cursor:pointer; display:flex; align-items:center; gap:6px; transition:all .12s}
.btn:hover{filter:brightness(1.05)}
.btn:active{transform:scale(.97)}
.seen-q{display:flex; align-items:center; gap:6px}
.seen-q .q{font-size:12.5px; color:var(--text-dim); font-weight:600; margin-right:2px}
.seg{font-family:"IBM Plex Sans",sans-serif; font-size:12.5px; font-weight:600; padding:5px 13px;
  border:1px solid var(--border); background:transparent; color:var(--text-dim); cursor:pointer;
  border-radius:20px; transition:all .12s}
.seg:hover{color:var(--text)}
.seg.on.yes{color:var(--teal); border-color:var(--teal); background:var(--teal-soft)}
.seg.on.no{color:var(--accent-strong); border-color:var(--accent); background:var(--accent-soft)}
.pips button{font-size:15px; padding:4px 3px}
.pips button.lit{color:var(--accent)}
.pips button.lit.bad{color:var(--text-faint)}
.scale-lab{font-size:10.5px; letter-spacing:.06em; text-transform:uppercase; color:var(--text-faint); margin-right:4px}
.btn.never{background:transparent; font-weight:500; color:var(--text-faint); padding:5px 12px; font-size:12.5px}
.btn.never.on{color:var(--minus); border-color:var(--minus); background:var(--minus-soft)}
.hint{font-size:11.5px; color:var(--text-faint)}
.triage-head{margin:26px 0 4px; font-size:12px; letter-spacing:.12em; text-transform:uppercase;
  color:var(--text-faint); font-weight:600}
.btn[disabled]{opacity:.5; cursor:wait}
.gen-tags{font-size:11.5px; color:var(--text-faint); margin-left:2px}
.btn.review{background:var(--accent-soft); border-color:var(--accent); color:var(--accent-strong)}
.btn.reweigh{background:var(--teal-soft); border-color:var(--teal); color:var(--teal)}
.btn.reweigh[disabled]{opacity:.6; cursor:wait}
.tally .t-link{font:inherit; background:none; border:none; padding:0; cursor:pointer}
.tally .t-link:hover{text-decoration:underline; color:var(--text)}
.tally .t-link b{font-size:16px; color:var(--text); font-family:"IBM Plex Mono",monospace}

/* ---- shared modal shell (review session, watchlist, re-weigh) ---- */
.modal-overlay{position:fixed; inset:0; background:rgba(10,10,10,.6); z-index:50;
  display:none; align-items:center; justify-content:center; padding:20px}
.modal-overlay.open{display:flex}
.modal-card{background:var(--surface); border:1px solid var(--border); border-radius:16px;
  box-shadow:0 20px 60px -10px rgba(0,0,0,.4); width:100%; max-height:92vh;
  overflow-y:auto; padding:20px 24px 24px}
.modal-top{display:flex; justify-content:space-between; align-items:center; margin-bottom:14px}
.modal-exit{background:none; border:none; color:var(--text-faint); font-size:13px; cursor:pointer;
  padding:4px 8px}
.modal-exit:hover{color:var(--text)}

/* ---- review session ---- */
.session-card{max-width:560px}
.session-progress{font-family:"IBM Plex Mono",monospace; font-size:12.5px; color:var(--text-faint)}
.session-body{display:flex; gap:18px; margin-bottom:18px}
.session-poster{flex:none; width:140px; height:210px; border-radius:10px; overflow:hidden;
  background:var(--surface-2); box-shadow:var(--shadow)}
.session-poster img{width:100%; height:100%; object-fit:cover; display:block}
.session-poster .ph{width:100%; height:100%; display:flex; align-items:center; justify-content:center;
  font-family:"Fraunces",Georgia,serif; font-size:48px; color:var(--text-faint)}
.session-info{flex:1; min-width:0}
.session-info .title{font-size:24px; display:block}
.session-info .year{font-size:15px}
.session-info .meta{margin-top:6px}
.session-info .synopsis{margin-top:10px}
.session-info .why{margin-top:10px}
.session-stage{border-top:1px solid var(--border); padding-top:16px}
.session-prompt{font-family:"Fraunces",Georgia,serif; font-size:17px; margin-bottom:12px}
.session-row{display:flex; gap:10px; flex-wrap:wrap; align-items:center}
.session-big{font-family:"IBM Plex Sans",sans-serif; font-size:14.5px; font-weight:600;
  border-radius:12px; padding:14px 18px; border:1px solid var(--border); background:var(--surface-2);
  color:var(--text); cursor:pointer; flex:1; text-align:center; transition:all .12s}
.session-big:hover{filter:brightness(1.06)}
.session-big:active{transform:scale(.98)}
.session-big.no:hover{border-color:var(--accent); color:var(--accent-strong)}
.session-big.yes:hover{border-color:var(--teal); color:var(--teal)}
.session-stars{display:flex; gap:6px}
.session-stars button{background:var(--surface-2); border:1px solid var(--border); border-radius:10px;
  width:46px; height:46px; font-size:20px; color:var(--text-faint); cursor:pointer; transition:all .1s}
.session-stars button:hover{transform:scale(1.08)}
.session-stars.rating button:hover, .session-stars.rating button.preview{color:var(--accent); border-color:var(--accent)}
.session-stars.interest button:hover, .session-stars.interest button.preview{color:var(--teal); border-color:var(--teal)}
.session-never{background:transparent; border:1px solid var(--border); border-radius:10px;
  padding:0 16px; height:46px; color:var(--text-faint); font-weight:600; cursor:pointer}
.session-never:hover{border-color:var(--minus); color:var(--minus)}
.session-hint{font-size:11.5px; color:var(--text-faint); margin-top:10px}
.session-done{text-align:center; padding:30px 10px}
.session-done h2{margin-bottom:8px}
.session-done p{color:var(--text-dim); font-size:14px; margin-bottom:20px}
@media (max-width:480px){
  .session-body{flex-direction:column}
  .session-poster{width:100%; height:200px}
  .session-stars button{width:38px; height:38px; font-size:17px}
}

/* ---- watchlist ---- */
.watchlist-card{max-width:620px}
.wl-empty{color:var(--text-dim); font-size:14px; padding:20px 4px}
.wl-row{display:flex; gap:12px; align-items:center; padding:10px 0;
  border-bottom:1px solid var(--border)}
.wl-row:last-child{border-bottom:none}
.wl-poster{flex:none; width:44px; height:66px; border-radius:5px; overflow:hidden;
  background:var(--surface-2)}
.wl-poster img{width:100%; height:100%; object-fit:cover; display:block}
.wl-poster .ph{width:100%; height:100%; display:flex; align-items:center; justify-content:center;
  font-family:"Fraunces",Georgia,serif; font-size:18px; color:var(--text-faint)}
.wl-info{flex:1; min-width:0}
.wl-info .title{font-family:"Fraunces",Georgia,serif; font-size:15.5px; font-weight:600}
.wl-info .year{color:var(--text-faint); font-size:12.5px; margin-left:4px}
.wl-info .meta{color:var(--text-dim); font-size:12px; margin-top:2px}
.wl-dots{flex:none; display:flex; gap:2px; font-size:13px}
.wl-dots span{color:var(--border)}
.wl-dots span.lit{color:var(--accent)}

/* ---- re-weigh ---- */
.reweigh-card{max-width:640px}
.reweigh-intro{color:var(--text-dim); font-size:13.5px; line-height:1.55; margin-bottom:14px}
.reweigh-status{display:flex; align-items:center; gap:10px; margin-bottom:10px; font-size:13px}
.reweigh-spinner{width:14px; height:14px; border-radius:50%; border:2px solid var(--border);
  border-top-color:var(--teal); animation:rw-spin .8s linear infinite}
@keyframes rw-spin{to{transform:rotate(360deg)}}
.reweigh-step{font-weight:600; color:var(--teal)}
.reweigh-log{background:var(--surface-2); border:1px solid var(--border); border-radius:8px;
  padding:10px 12px; font-family:"IBM Plex Mono",monospace; font-size:11.5px; line-height:1.6;
  color:var(--text-dim); max-height:320px; overflow-y:auto; white-space:pre-wrap}
.reweigh-error{color:var(--minus); font-size:13px; margin-top:10px; font-weight:600}
.reweigh-done{color:var(--plus); font-size:13px; margin-top:10px; font-weight:600}

footer{margin-top:40px; padding-top:18px; border-top:1px solid var(--border);
  color:var(--text-faint); font-size:12px; line-height:1.6}

@media (max-width:480px){
  .masthead h1{font-size:30px}
  .stats{gap:12px}
  .card{padding:12px 12px 12px 22px; gap:10px}
  .poster{width:52px; height:78px}
  .synopsis{max-width:none}
  .stars button{font-size:18px}
  .hint{width:100%; order:10}
}
</style>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght,SOFT,WONK@9..144,300..700,0..100,0..1&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">

<div class="wrap">

  <div class="masthead">
    <div>
      <div class="eyebrow">Reel __ITER__ &middot; Screening Notes</div>
      <h1>Dailies</h1>
      <div class="sub">Candidates pulled from your letterboxd taste graph. Seen it? Star how much you
        enjoyed it. Not yet? Say how much you want to &mdash; or mark it never.</div>
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
      <div style="margin-top:8px"><b>Seen it &mdash; stars are enjoyment.</b> 5&#9733; promotes the film
        into the seed set at full weight, 4&#9733; at half weight, 3&#9733; is noted, 1&ndash;2&#9733;
        trains the channel weights as a miss.</div>
      <div style="margin-top:8px"><b>Not seen &mdash; dots are how inclined you are to watch it,
        not a rating.</b> 2 is "maybe later" (barely trains the weights), 3 is "I'll likely watch
        it," 4&ndash;5 is "I've been meaning to and I know it should be good" &mdash; and the
        training weight climbs with it, from token at 1&ndash;2 up to nearly as strong as an
        actual rating at 5. Still never becomes a seed on its own, though &mdash; that still
        wants a real watch. 3&ndash;5 lands on your watchlist. <b>Never</b> counts as a firm miss.</div>
      <div style="margin-top:8px">Cards graded before this split show their old star as a dashed
        hint and count as unreviewed until you answer &ldquo;seen it?&rdquo;. Change your mind any time.</div>
      <div style="margin-top:8px">Note: letterboxd files a few limited series (Twin Peaks: The Return,
        Baby Reindeer) under /film/ &mdash; pass on those if TV isn't what you're after.</div>
    </div>
  </details>

  <div class="tally">
    <div class="t-item">seen &amp; rated <b id="t-rated">0</b></div>
    <button class="t-item t-link" id="btn-watchlist">watchlist <b id="t-watch">0</b></button>
    <div class="t-item">never <b id="t-never">0</b></div>
    <div class="t-item">to re-triage <b id="t-legacy">0</b></div>
    <div class="t-item">reviewed <b id="t-graded">0</b> / <span id="t-total" class="mono">0</span></div>
    <div class="spacer"></div>
    <button class="btn review" id="btn-review-session">&#9654; Run Review Session</button>
    <button class="btn reweigh" id="btn-reweigh">&#8635; Re-weigh &amp; Generate New Pool</button>
    <label><input type="checkbox" id="hide-reviewed"> hide reviewed</label>
  </div>

  <div class="people" id="people"></div>

  <div class="reel" id="reel"></div>

  <div class="modal-overlay" id="session-overlay"><div class="modal-card session-card" id="session-card"></div></div>
  <div class="modal-overlay" id="watchlist-overlay"><div class="modal-card watchlist-card" id="watchlist-card"></div></div>
  <div class="modal-overlay" id="reweigh-overlay"><div class="modal-card reweigh-card" id="reweigh-card"></div></div>

  <footer>
    Calls save to this page's own store &mdash; they sync back across sessions and
    are what the next reel is cut from. Tapping a lit call again clears it.
  </footer>
</div>

<script>
const DATA = __DATA_JSON__;
// slug -> {grade, status, rating, interest, never}. `grade` is the pre-split
// star; `status` is 'seen' | 'unseen' | null.
let grades = {};

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

function normalize(v){
  return {grade: v.grade ?? null, status: v.status ?? null, rating: v.rating ?? null,
          interest: v.interest ?? null, never: !!v.never};
}
function cardState(slug){ return grades[slug] || normalize({}); }
function isReviewed(st){
  if(st.status === 'seen') return !!st.rating;
  if(st.status === 'unseen') return !!(st.interest || st.never);
  return false;
}

function runtimeStr(mins){
  if(!mins) return null;
  const h = Math.floor(mins/60), m = mins%60;
  return h ? `${h}h ${m}m` : `${m}m`;
}

const RATING_TIPS = {5:'loved it — weighs heavy as a seed', 4:'liked it — weighs light as a seed',
  3:'fine — noted, not promoted', 2:'didn\'t like it', 1:'hated it'};
// Calibrated to how these actually get used, not generic "interest" levels --
// each number is a distinct confidence claim, and the training weight (see
// common.INTEREST_WEIGHTS) scales with it: 2 is barely more than noise, 4-5
// is nearly as strong a signal as an actual rating.
const INTEREST_TIPS = {5:'been meaning to — I know it should be good', 4:'been meaning to, probably good',
  3:'I\'ll likely watch it', 2:'yeah, maybe later', 1:'no real pull yet'};

function verdictLabel(st){
  if(st.status === 'seen'){
    const r = st.rating;
    if(r===5) return {cls:'heavy', stamp:'loved — heavy seed', note:RATING_TIPS[5]};
    if(r===4) return {cls:'light', stamp:'liked — light seed', note:RATING_TIPS[4]};
    if(r===3) return {cls:'', stamp:'seen — fine', note:RATING_TIPS[3]};
    if(r) return {cls:'minus', stamp:'seen — miss', note:RATING_TIPS[r]};
    return {cls:'', stamp:null, note:'how much did you enjoy it?'};
  }
  if(st.status === 'unseen'){
    if(st.never) return {cls:'minus', stamp:'never', note:'firm no — off the watchlist'};
    const i = st.interest;
    if(i>=4) return {cls:'want', stamp:'watchlist', note:INTEREST_TIPS[i]};
    if(i===3) return {cls:'', stamp:'watchlist — likely', note:INTEREST_TIPS[3]};
    if(i) return {cls:'cold', stamp:'low interest', note:INTEREST_TIPS[i]};
    return {cls:'', stamp:null, note:'how inclined are you to watch it?'};
  }
  if(st.grade) return {cls:'', stamp:'earlier ' + '\u2605'.repeat(st.grade), stampCls:'hint', note:''};
  return {cls:'', stamp:null, note:''};
}

function renderCard(f, idx){
  const st = cardState(f.slug);
  const card = el('div','card');
  card.dataset.slug = f.slug;
  const gl = verdictLabel(st);
  if(gl.cls) card.classList.add(gl.cls);
  card.appendChild(el('div','sprockets'));

  if(gl.stamp) card.appendChild(el('div','stamp '+(gl.stampCls||gl.cls||'maybe'), gl.stamp));

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
  top.appendChild(el('div','score', f.score==null ? 'seed' : f.score.toFixed(1)));
  body.appendChild(top);

  const rt = runtimeStr(f.runtime);
  body.appendChild(el('div','meta',
    `dir. ${f.dirs.join(', ')||'&mdash;'} &middot; starring ${(f.cast||[]).slice(0,4).join(', ')||'&mdash;'}<br>`+
    `${f.genres.join(', ')||'&mdash;'}${rt?` &middot; ${rt}`:''} &middot; `+
    `${f.rating??'&ndash;'}&#9733; from ${(f.count||0).toLocaleString()} ratings`));

  if(f.synopsis) body.appendChild(el('div','synopsis', f.synopsis));

  if(f.score == null) body.appendChild(el('div','why', 'a seed now &mdash; promoted from an earlier reel'));
  else {
    body.appendChild(el('div','why', why(f)));
    body.appendChild(el('div','meter',
      bar('G',f.g,'g')+bar('T',f.t,'t')+bar('P',f.p,'p')+bar('Q',f.q,'q')));
  }

  const actions = el('div','actions');

  const q = el('div','seen-q');
  q.appendChild(el('span','q','Seen it?'));
  for(const [val, lab, cls] of [['seen','Yes','yes'], ['unseen','No','no']]){
    const b = el('button','seg '+cls, lab);
    if(st.status === val) b.classList.add('on');
    b.onclick = () => setStatus(f, val);
    q.appendChild(b);
  }
  actions.appendChild(q);

  if(st.status === 'seen'){
    const stars = el('div','stars');
    for(let i=1;i<=5;i++){
      const b = el('button','','&#9733;');
      b.title = RATING_TIPS[i];
      if(st.rating && i<=st.rating){
        b.classList.add('lit');
        if(st.rating<=2) b.classList.add('bad');
        else if(st.rating===4) b.classList.add('weak');
      }
      b.onclick = () => setRating(f, i);
      stars.appendChild(b);
    }
    actions.appendChild(stars);
  } else if(st.status === 'unseen'){
    const pips = el('div','stars pips');
    pips.appendChild(el('span','scale-lab','want to see'));
    for(let i=1;i<=5;i++){
      const b = el('button','','&#9679;');
      b.title = INTEREST_TIPS[i];
      if(st.interest && i<=st.interest){
        b.classList.add('lit');
        if(st.interest<=2) b.classList.add('bad');
      }
      b.onclick = () => setInterest(f, i);
      pips.appendChild(b);
    }
    actions.appendChild(pips);
    const nv = el('button','btn never','never');
    nv.title = 'garbage / bad signal / would never watch';
    if(st.never) nv.classList.add('on');
    nv.onclick = () => toggleNever(f);
    actions.appendChild(nv);
  }
  const note = gl.note || (st.grade && !st.status ? 'earlier call, before seen/unseen split' : '');
  if(note) actions.appendChild(el('span','hint', note));

  body.appendChild(actions);
  card.appendChild(body);
  return card;
}

function renderReel(){
  const reel = $('#reel'); reel.innerHTML = '';
  const hideReviewed = $('#hide-reviewed').checked;
  let headed = false;
  DATA.films.forEach((f, i) => {
    const st = cardState(f.slug);
    if(hideReviewed && isReviewed(st)) return;
    if(f.triage && !headed){
      reel.appendChild(el('div','triage-head','From earlier reels &mdash; re-triage'));
      headed = true;
    }
    reel.appendChild(renderCard(f, i));
  });
  renderTally();
}

// ---- state changes (storage-agnostic; the backend supplies saveDoc) ----
function update(f, patch){
  grades[f.slug] = Object.assign({}, cardState(f.slug), patch);
  renderReel();
  writeDoc(f.slug);
}
function setStatus(f, val){
  const st = cardState(f.slug);
  if(st.status === val) return update(f, {status:null, rating:null, interest:null, never:false});
  // Switching sides drops the other side's answer, so a stale value can't linger.
  update(f, val === 'seen' ? {status:'seen', interest:null, never:false}
                           : {status:'unseen', rating:null});
}
function setRating(f, i){ update(f, {rating: cardState(f.slug).rating === i ? null : i}); }
function setInterest(f, i){ update(f, {interest: cardState(f.slug).interest === i ? null : i, never:false}); }
function toggleNever(f){ update(f, {never: !cardState(f.slug).never, interest:null}); }

// Writes queue per film rather than dropping while one is in flight -- the
// seen/unseen flow is two quick taps, and the second must not be lost. Each
// write sends the state as of when it runs, so the last one always wins.
const queues = {};
function writeDoc(slug){
  const f = DATA.films.find(x=>x.slug===slug);
  queues[slug] = (queues[slug] || Promise.resolve()).then(() =>
    saveDoc(slug, Object.assign({slug, title: f?f.title:slug}, cardState(slug), {ts: Date.now()}))
  ).catch(e => console.warn('grade write failed', e));
}

function renderTally(){
  let rated=0, watch=0, never=0, legacy=0, graded=0;
  for(const f of DATA.films){
    const st = cardState(f.slug);
    if(st.status === 'seen' && st.rating) rated++;
    if(st.status === 'unseen' && st.interest >= 3) watch++;
    if(st.status === 'unseen' && st.never) never++;
    if(st.grade && !isReviewed(st)) legacy++;
    if(isReviewed(st)) graded++;
  }
  $('#t-rated').textContent = rated;
  $('#t-watch').textContent = watch;
  $('#t-never').textContent = never;
  $('#t-legacy').textContent = legacy;
  $('#t-graded').textContent = graded;
}

// ---- review session: one card at a time, keyboard-driven -------------
// Flow: "seen it?" (<-/-> or click) -> rate (seen: 1-5 enjoyment; unseen:
// 1-5 want-to-see, or X / click for a hard never). Each answer saves through
// the exact same setStatus/setRating/setInterest/toggleNever calls the list
// view uses, so the list behind the overlay is always in sync.
let session = null; // {queue, idx, stage, stats}

function sessionStageFor(f){
  return cardState(f.slug).status ? 'rate' : 'seen';
}

function openSession(){
  const queue = DATA.films.filter(f => !isReviewed(cardState(f.slug)));
  if(!queue.length){
    alert("Nothing left to review — everything's either rated, watchlisted, or marked never.");
    return;
  }
  session = {queue, idx: 0, stats: {seen:0, unseen:0, never:0}};
  session.stage = sessionStageFor(queue[0]);
  $('#session-overlay').classList.add('open');
  document.addEventListener('keydown', sessionKeydown);
  renderSession();
}

function closeSession(){
  session = null;
  $('#session-overlay').classList.remove('open');
  document.removeEventListener('keydown', sessionKeydown);
}

function sessionAdvance(){
  session.idx++;
  if(session.idx >= session.queue.length){ renderSessionDone(); return; }
  session.stage = sessionStageFor(session.queue[session.idx]);
  renderSession();
}

// Stage 1, "seen it?" -- a plain yes/no, same either way: set status, move
// to stage 2. No verdict is recorded yet; that's stage 2's job.
function sessionSetSeen(f, val){
  if(cardState(f.slug).status !== val) setStatus(f, val);
  session.stats[val]++;
  session.stage = 'rate';
  renderSession();
}

// Stage 2, unseen branch: "how inclined are you to watch?" 1-5 is interest;
// left arrow (or X) is the zero case -- don't want to see it at all, full
// exclude from the weighting, not a low number on the interest scale.
function sessionRate(f, i){
  if(cardState(f.slug).status === 'seen') setRating(f, i); else setInterest(f, i);
  sessionAdvance();
}

function sessionNever(f){
  const st = cardState(f.slug);
  if(st.status === 'seen') setRating(f, 1);       // no separate "never" for a seen film --
  else { toggleNever(f); session.stats.never++; } // 1-star already means "hated it"
  sessionAdvance();
}

function sessionKeydown(e){
  if(!session) return;
  if(e.key === 'Escape'){ e.preventDefault(); closeSession(); return; }
  if(session.idx >= session.queue.length) return; // done screen: only Escape does anything
  const f = session.queue[session.idx];
  if(session.stage === 'seen'){
    if(e.key === 'ArrowLeft'){ e.preventDefault(); sessionSetSeen(f, 'unseen'); }
    else if(e.key === 'ArrowRight'){ e.preventDefault(); sessionSetSeen(f, 'seen'); }
  } else if(session.stage === 'rate'){
    if(/^[1-5]$/.test(e.key)){ e.preventDefault(); sessionRate(f, parseInt(e.key, 10)); }
    else if(e.key.toLowerCase() === 'x'){ e.preventDefault(); sessionNever(f); }
    else if(e.key === 'ArrowLeft' && cardState(f.slug).status === 'unseen'){
      e.preventDefault(); sessionNever(f);
    }
  }
}

function renderSession(){
  const f = session.queue[session.idx];
  const card = $('#session-card');
  card.innerHTML = '';

  const top = el('div','modal-top');
  top.appendChild(el('span','session-progress', `Reviewing ${session.idx+1} of ${session.queue.length}`));
  const exit = el('button','modal-exit','✕ Exit (Esc)');
  exit.onclick = closeSession;
  top.appendChild(exit);
  card.appendChild(top);

  const bodyRow = el('div','session-body');
  const poster = el('div','session-poster');
  if(f.poster){
    const img = el('img','',''); img.src = f.poster; img.alt = f.title; poster.appendChild(img);
  } else poster.appendChild(el('div','ph', f.title.charAt(0)));
  bodyRow.appendChild(poster);

  const info = el('div','session-info');
  info.innerHTML = `<span class="title">${f.title}</span> <span class="year">${f.year}</span>`;
  const rt = runtimeStr(f.runtime);
  info.appendChild(el('div','meta',
    `dir. ${f.dirs.join(', ')||'&mdash;'} &middot; starring ${(f.cast||[]).slice(0,4).join(', ')||'&mdash;'}<br>`+
    `${f.genres.join(', ')||'&mdash;'}${rt?` &middot; ${rt}`:''} &middot; `+
    `${f.rating??'&ndash;'}&#9733; from ${(f.count||0).toLocaleString()} ratings`));
  if(f.synopsis) info.appendChild(el('div','synopsis', f.synopsis));
  if(f.score != null) info.appendChild(el('div','why', why(f)));
  bodyRow.appendChild(info);
  card.appendChild(bodyRow);

  const stage = el('div','session-stage');
  if(session.stage === 'seen'){
    stage.appendChild(el('div','session-prompt','Seen it?'));
    const row = el('div','session-row');
    const no = el('button','session-big no','\u2190 No, haven\u2019t seen it');
    no.onclick = () => sessionSetSeen(f, 'unseen');
    const yes = el('button','session-big yes','Yes, seen it \u2192');
    yes.onclick = () => sessionSetSeen(f, 'seen');
    row.appendChild(no); row.appendChild(yes);
    stage.appendChild(row);
    stage.appendChild(el('div','session-hint','\u2190 / \u2192 keys, or click'));
  } else {
    const seen = cardState(f.slug).status === 'seen';
    stage.appendChild(el('div','session-prompt', seen ? 'How much did you enjoy it?' : 'How inclined are you to watch?'));
    const row = el('div','session-row');
    const stars = el('div','session-stars ' + (seen ? 'rating' : 'interest'));
    const tips = seen ? RATING_TIPS : INTEREST_TIPS;
    for(let i=1;i<=5;i++){
      const b = el('button','', seen ? '\u2605' : '\u25cf');
      b.title = tips[i];
      b.onclick = () => sessionRate(f, i);
      stars.appendChild(b);
    }
    row.appendChild(stars);
    if(!seen){
      const nv = el('button','session-never','\u2190 Not at all / Never');
      nv.title = "don't want to see it at all -- excluded from weighting, not rated";
      nv.onclick = () => sessionNever(f);
      row.appendChild(nv);
    }
    stage.appendChild(row);
    stage.appendChild(el('div','session-hint', seen ? 'press 1-5, or X for hated it' : 'press 1-5, or \u2190 / X for not at all'));
  }
  card.appendChild(stage);
}

function renderSessionDone(){
  const card = $('#session-card');
  const s = session.stats;
  card.innerHTML = '';
  const done = el('div','session-done');
  done.appendChild(el('h2','','All caught up'));
  done.appendChild(el('p','', `This round: ${s.seen} marked seen, ${s.unseen} added to the watchlist pile, ${s.never} ruled out.`));
  const btn = el('button','session-big yes','Done');
  btn.style.flex = 'none';
  btn.onclick = closeSession;
  done.appendChild(btn);
  card.appendChild(done);
}

// ---- watchlist: unseen films flagged interest>=3, sorted by how much you
// want to see them. Pure client-side read of the same grades/DATA.films
// state the list view already has -- no extra round trip. ------------------
function watchlistItems(){
  const items = [];
  for(const f of DATA.films){
    const st = cardState(f.slug);
    if(st.status === 'unseen' && st.interest >= 3) items.push({f, interest: st.interest});
  }
  items.sort((a,b) => (b.interest - a.interest) || ((b.f.score||0) - (a.f.score||0)));
  return items;
}

function openWatchlist(){
  renderWatchlist();
  $('#watchlist-overlay').classList.add('open');
  document.addEventListener('keydown', watchlistKeydown);
}
function closeWatchlist(){
  $('#watchlist-overlay').classList.remove('open');
  document.removeEventListener('keydown', watchlistKeydown);
}
function watchlistKeydown(e){ if(e.key === 'Escape'){ e.preventDefault(); closeWatchlist(); } }

function renderWatchlist(){
  const card = $('#watchlist-card');
  card.innerHTML = '';
  const top = el('div','modal-top');
  top.appendChild(el('span','session-progress','Watchlist \u2014 by how much you want to see it'));
  const exit = el('button','modal-exit','\u2715 Close (Esc)');
  exit.onclick = closeWatchlist;
  top.appendChild(exit);
  card.appendChild(top);

  const items = watchlistItems();
  if(!items.length){
    card.appendChild(el('div','wl-empty',
      'Nothing here yet \u2014 in the list or the review session, rate an unseen film 3\u20135 on '+
      '\u201chow inclined are you to watch?\u201d and it lands here.'));
    return;
  }
  for(const {f, interest} of items){
    const row = el('div','wl-row');
    const poster = el('div','wl-poster');
    if(f.poster){ const img = el('img','',''); img.src = f.poster; img.alt = f.title; poster.appendChild(img); }
    else poster.appendChild(el('div','ph', f.title.charAt(0)));
    row.appendChild(poster);
    const info = el('div','wl-info');
    info.innerHTML = `<span class="title">${f.title}</span><span class="year">${f.year}</span>`;
    info.appendChild(el('div','meta', `dir. ${f.dirs.join(', ')||'&mdash;'} &middot; ${f.genres.join(', ')||'&mdash;'}`));
    row.appendChild(info);
    const dots = el('div','wl-dots');
    for(let i=1;i<=5;i++) dots.appendChild(el('span','', i<=interest ? '\u25cf' : '\u25cb'));
    row.appendChild(dots);
    card.appendChild(row);
  }
}

// ---- re-weigh: triggers the full pipeline (pull grades -> tune -> promote
// seeds -> re-crawl -> score -> build) as a background job on the server,
// polls for progress, reloads onto the new pool when it finishes. Local
// mode only -- wired in LOCAL_BACKEND_JS, hidden in artifact mode (no
// server to run a subprocess pipeline on claude.ai). ------------------------
let reweighTimer = null;

function openReweigh(){
  if(!confirm('This re-crawls letterboxd from your updated grading and can take '+
              'several minutes. Start it now?')) return;
  renderReweighShell();
  $('#reweigh-overlay').classList.add('open');
  $('#btn-reweigh').disabled = true;
  fetch('/api/reweigh', {method:'POST'}).then(r => r.json()).then(d => {
    if(d.error && d.error !== 'already running'){ reweighShowFatal(d.error); return; }
    pollReweigh();
    reweighTimer = setInterval(pollReweigh, 1500);
  }).catch(e => reweighShowFatal(String(e)));
}

function closeReweigh(){
  $('#reweigh-overlay').classList.remove('open');
  // Closing the modal only stops this tab's polling -- the job is a
  // server-side background thread and keeps running either way.
  if(reweighTimer){ clearInterval(reweighTimer); reweighTimer = null; }
}

function reweighShowFatal(msg){
  $('#btn-reweigh').disabled = false;
  $('#reweigh-card').appendChild(el('div','reweigh-error', '\u26a0 could not start: ' + msg));
}

function renderReweighShell(){
  const card = $('#reweigh-card');
  card.innerHTML = '';
  const top = el('div','modal-top');
  top.appendChild(el('span','session-progress','Re-weighing & generating new pool'));
  const exit = el('button','modal-exit','\u2715 Close');
  exit.onclick = closeReweigh;
  top.appendChild(exit);
  card.appendChild(top);
  card.appendChild(el('div','reweigh-intro',
    'Pulls your grading into the model, retunes the four channel weights, folds confirmed '+
    'keepers into the seed set, re-crawls letterboxd and rescores everything. Several minutes, '+
    'typically. Closing this window does not stop it \u2014 keep grading, check back any time.'));
  const status = el('div','reweigh-status');
  status.appendChild(el('div','reweigh-spinner'));
  status.appendChild(el('span','','starting\u2026'));
  card.appendChild(status);
  card.appendChild(el('div','reweigh-log',''));
}

function pollReweigh(){
  fetch('/api/reweigh').then(r => r.json()).then(d => {
    const card = $('#reweigh-card');
    if(!card) return;
    let status = card.querySelector('.reweigh-status');
    const log = card.querySelector('.reweigh-log');
    if(!status){ renderReweighShell(); status = card.querySelector('.reweigh-status'); }
    status.innerHTML = '';
    if(d.running){
      status.appendChild(el('div','reweigh-spinner'));
      status.appendChild(el('span','','running: '));
      status.appendChild(el('span','reweigh-step', d.step || '\u2026'));
    } else {
      status.appendChild(el('span','', d.error ? 'stopped' : 'finished'));
    }
    if(log){ log.textContent = (d.log||[]).join('\n'); log.scrollTop = log.scrollHeight; }

    if(!d.running){
      if(reweighTimer){ clearInterval(reweighTimer); reweighTimer = null; }
      $('#btn-reweigh').disabled = false;
      if(!card.querySelector('.reweigh-error, .reweigh-done')){
        if(d.error) card.appendChild(el('div','reweigh-error', '\u26a0 ' + d.error));
        else {
          card.appendChild(el('div','reweigh-done','Done \u2014 reloading onto the new pool\u2026'));
          setTimeout(() => location.reload(), 1200);
        }
      }
    }
  }).catch(() => {});
}

__BACKEND_JS__
</script>
"""

ARTIFACT_BACKEND_JS = r"""let db = null;

async function saveDoc(slug, body){
  if(!db) return;
  await db.collection('grades').doc(slug).set(body);
}

$('#hide-reviewed').addEventListener('change', renderReel);
$('#btn-review-session').addEventListener('click', openSession);
$('#btn-watchlist').addEventListener('click', openWatchlist);
$('#btn-reweigh').style.display = 'none'; // no server to run a pipeline on claude.ai

async function boot(){
  renderStats();
  renderPeople();
  renderReel();
  try{
    db = await claude.use('db');
    if(db){
      db.collection('grades').onSnapshot(snap => {
        const next = {};
        snap.docs.forEach(d => { const v = d.data(); if(v && v.slug) next[v.slug] = normalize(v); });
        grades = next;
        renderReel();
      }, err => console.warn('grades snapshot error', err));
    }
  }catch(e){ console.warn('db unavailable', e); }
}
boot();"""

LOCAL_BACKEND_JS = r"""async function fetchGrades(){
  const res = await fetch('/api/grades');
  if(!res.ok) throw new Error('fetch /api/grades: ' + res.status);
  const rows = await res.json();
  const next = {};
  rows.forEach(v => { if(v && v.slug) next[v.slug] = normalize(v); });
  return next;
}

async function saveDoc(slug, body){
  const res = await fetch('/api/grades/' + encodeURIComponent(slug), {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
  });
  if(!res.ok) throw new Error('POST /api/grades: ' + res.status);
}

$('#hide-reviewed').addEventListener('change', renderReel);
$('#btn-review-session').addEventListener('click', openSession);
$('#btn-watchlist').addEventListener('click', openWatchlist);
$('#btn-reweigh').addEventListener('click', openReweigh);

async function boot(){
  renderStats();
  renderPeople();
  renderReel();
  try{ grades = await fetchGrades(); renderReel(); }
  catch(e){ console.warn('grades fetch failed', e); }
  // Light polling, not a push subscription -- picks up a grade set from
  // another tab or device (e.g. grading from your phone on the same wifi)
  // within a few seconds.
  setInterval(async () => {
    try{ grades = await fetchGrades(); renderReel(); }
    catch(e){ /* server probably just not running yet -- keep trying */ }
  }, 4000);
  // A re-weigh started before a reload (or from another tab) keeps running
  // server-side -- resume watching it instead of leaving the button idle.
  try{
    const d = await (await fetch('/api/reweigh')).json();
    if(d.running){
      renderReweighShell();
      $('#reweigh-overlay').classList.add('open');
      $('#btn-reweigh').disabled = true;
      pollReweigh();
      reweighTimer = setInterval(pollReweigh, 1500);
    }
  }catch(e){ /* fine, just means nothing to resume */ }
}
boot();"""

if __name__ == "__main__":
    main()
