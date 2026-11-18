"""Manage profiles (people) and their pools (rough taste groups). No accounts:
a profile is just a folder under profiles/, private to this machine.

  python3 pipeline/profiles.py new alex [--scale standard|top-heavy] [--pool main]
  python3 pipeline/profiles.py list
  python3 pipeline/profiles.py use alex                 # default profile for scripts/server
  python3 pipeline/profiles.py show                     # settings, pools, seed counts

  python3 pipeline/profiles.py pool add comfort-comedy "dumb fun, rewatchable"
  python3 pipeline/profiles.py pool default comfort-comedy
  python3 pipeline/profiles.py seed comfort-comedy "Step Brothers|2008" "Hot Rod|2007"
  python3 pipeline/profiles.py seed comfort-comedy step-brothers   # a letterboxd slug works too

  python3 pipeline/profiles.py assign [--pool P]        # where each verdict lands, and why
  python3 pipeline/profiles.py move <slug> <pool>       # pin a verdict to a pool
  python3 pipeline/profiles.py suggest                  # pools that look like two tastes in one

Every command works on CINESCOPE_PROFILE, or --profile NAME, or the active one.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import pools

SEEDS_HEADER = """# Seeds for this pool -- films that define it. One per line:
#   letterboxd-slug | weight | note
# weight is enthusiasm, 0.0-2.0 (1.0 = a defining film). Drop a line to remove.
# Add by title with:  python3 pipeline/profiles.py seed <pool> "Title|Year"
"""


def check_name(name, what):
    if not common.NAME_RE.match(name or ""):
        sys.exit("%s name %r: use lowercase letters, digits, - or _" % (what, name))


def add_pool(profile, name, description=""):
    check_name(name, "pool")
    prof = common.load_profile(profile)
    pools_ = prof.setdefault("pools", {})
    if name in pools_:
        sys.exit("pool %r already exists" % name)
    pools_[name] = {"description": description, "settings": {}}
    prof.setdefault("default_pool", name)
    common.save_profile(prof, profile)
    P = common.paths(profile, name)
    os.makedirs(P.pool_dir, exist_ok=True)
    if not os.path.exists(P.seeds):
        with open(P.seeds, "w", encoding="utf-8") as fh:
            fh.write(SEEDS_HEADER)
    print("pool %s/%s -> %s" % (profile, name, P.pool_dir))


def cmd_new(args):
    check_name(args.name, "profile")
    if args.name in common.list_profiles():
        sys.exit("profile %r already exists" % args.name)
    if args.scale not in common.SCALES:
        sys.exit("scale must be one of: %s" % ", ".join(common.SCALES))
    os.makedirs(common.profile_dir(args.name), exist_ok=True)
    common.save_profile({
        "name": args.name,
        "settings": {"scale": args.scale},
        "default_pool": args.pool,
        "pools": {},
    }, args.name)
    add_pool(args.name, args.pool, "")
    if not common.list_profiles()[1:] or args.use:
        with open(os.path.join(common.PROFILES, ".active"), "w") as fh:
            fh.write(args.name)
    print("created profile %s. Next: seed its first pool, e.g.\n"
          "  python3 pipeline/profiles.py --profile %s seed %s \"Some Film|1999\"\n"
          "or import from letterboxd:\n"
          "  python3 pipeline/import_letterboxd.py <letterboxd-user> --profile %s\n"
          "then:  ./run.sh %s" % (args.name, args.name, args.pool, args.name, args.name))


def cmd_list(args):
    active = None
    try:
        active = common.profile_name()
    except SystemExit:
        pass
    for name in common.list_profiles():
        print("%s %-16s pools: %s" % ("*" if name == active else " ", name,
                                      ", ".join(common.pools(name)) or "-"))


def cmd_use(args):
    if args.name not in common.list_profiles():
        sys.exit("no profile %r" % args.name)
    with open(os.path.join(common.PROFILES, ".active"), "w") as fh:
        fh.write(args.name)
    print("active profile: %s" % args.name)


def cmd_show(args):
    profile = common.profile_name()
    prof = common.load_profile(profile)
    rows = common.read_db_grades(profile)
    asg = pools.assign(profile, rows)
    print("profile %s  (scale: %s)" % (profile, common.scale(common.config(profile=profile)).get(
        "description")))
    for k, v in sorted((prof.get("settings") or {}).items()):
        print("  %-26s %s" % (k, v))
    for name, entry in (prof.get("pools") or {}).items():
        seeds = common.read_seeds(common.paths(profile, name).seeds)
        n = sum(1 for p in asg.values() if p == name)
        print("pool %-20s %3d seeds  %4d verdicts  %s%s" % (
            name, len(seeds), n, entry.get("description") or "",
            "  (default)" if name == prof.get("default_pool") else ""))
        for k, v in sorted((entry.get("settings") or {}).items()):
            print("    %-24s %s" % (k, v))


def cmd_pool(args):
    profile = common.profile_name()
    if args.action == "add":
        add_pool(profile, args.name, " ".join(args.rest))
    elif args.action == "default":
        prof = common.load_profile(profile)
        if args.name not in (prof.get("pools") or {}):
            sys.exit("no pool %r" % args.name)
        prof["default_pool"] = args.name
        common.save_profile(prof, profile)
        print("default pool: %s" % args.name)
    elif args.action == "describe":
        prof = common.load_profile(profile)
        if args.name not in (prof.get("pools") or {}):
            sys.exit("no pool %r" % args.name)
        prof["pools"][args.name]["description"] = " ".join(args.rest)
        common.save_profile(prof, profile)


def cmd_seed(args):
    import resolve
    profile = common.profile_name()
    if args.pool not in common.pools(profile):
        sys.exit("no pool %r in %s (have: %s)" % (args.pool, profile, ", ".join(common.pools(profile))))
    P = common.paths(profile, args.pool)
    have = {s for s, _ in common.read_seeds(P.seeds)}
    text = open(P.seeds, encoding="utf-8").read() if os.path.exists(P.seeds) else SEEDS_HEADER
    head, marker, tail = text.partition(common.SEED_MARKER)
    added = []
    for item in args.films:
        if "|" in item:
            title, year = [x.strip() for x in item.rsplit("|", 1)]
            slug, rec = resolve.resolve(title, year)
            if not slug:
                print("  ? couldn't find %r on letterboxd -- try its slug" % item)
                continue
            if rec["year"] != str(year):
                print("  ! %r matched %s (%s) -- check it" % (item, rec["title"], rec["year"]))
            note = "%s (%s)" % (rec["title"], rec["year"])
        else:
            slug, note = item.strip(), ""
            if not re.match(r"^[a-z0-9-]+$", slug):
                print("  ? %r isn't a slug; use \"Title|Year\"" % item)
                continue
        if slug in have:
            print("  = %s already seeded" % slug)
            continue
        line = "%-34s | %.1f | %s" % (slug, args.weight, note)
        head = head.rstrip("\n") + "\n" + line + "\n"
        have.add(slug)
        added.append(slug)
        print("  + %s" % line)
    with open(P.seeds, "w", encoding="utf-8") as fh:
        fh.write(head + ("\n" + marker + tail if marker else ""))
    print("%d seed(s) added to %s/%s" % (len(added), profile, args.pool))


def cmd_assign(args):
    profile = common.profile_name()
    rows = common.read_db_grades(profile)
    films = common.load_films()
    det = pools.assign(profile, rows, films, detail=True)
    sc = common.scale(common.config(profile=profile))
    counts = {}
    for slug, (p, how, margin) in sorted(det.items(), key=lambda kv: (kv[1][0] or "", kv[1][1], kv[0])):
        counts[(p, how)] = counts.get((p, how), 0) + 1
        if args.pool and p != args.pool:
            continue
        if args.all or how in ("auto", "default"):
            v = common.verdict(rows[slug], sc)
            print("  %-16s %-8s %5.2f  %-6s %s" % (
                p, how, margin, (v[0] if v else "-")[:6],
                common.label(films.get(slug) or {"slug": slug, "title": rows[slug].get("title")})))
    print()
    for (p, how), n in sorted(counts.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
        print("  %-16s %-8s %d" % (p, how, n))
    print("\n(tagged = graded in that pool's reel; seed = hand-seeded there; auto = nearest "
          "pool by theme + graph; default = nothing to go on yet.)  Pin one with: move <slug> <pool>")


def cmd_move(args):
    profile = common.profile_name()
    if args.pool not in common.pools(profile):
        sys.exit("no pool %r" % args.pool)
    conn = common.grades_db(profile)
    cur = conn.execute("UPDATE grades SET pool=? WHERE slug=?", (args.pool, args.slug))
    conn.commit()
    conn.close()
    if not cur.rowcount:
        sys.exit("no verdict for %r in %s" % (args.slug, profile))
    print("%s -> %s" % (args.slug, args.pool))


def cmd_suggest(args):
    profile = common.profile_name()
    rows = common.read_db_grades(profile)
    films = common.load_films()
    any_ = False
    for name in common.pools(profile):
        sug = pools.split_suggestion(profile, name, rows, films)
        if not sug:
            print("%s: reads as one taste" % name)
            continue
        any_ = True
        strength = "clearly" if sug["gain"] >= 0.12 else "possibly"
        print("%s: %s two tastes (within-pool similarity %.2f, +%.2f if split)"
              % (name, strength, sug["cohesion"], sug["gain"]))
        for i, g in enumerate(sug["groups"], 1):
            print("  group %d (%d films) -- %s" % (i, len(g["films"]), ", ".join(g["themes"])))
            for t in g["films"][:8]:
                print("      %s" % t)
            if len(g["films"]) > 8:
                print("      ... +%d more" % (len(g["films"]) - 8))
    if any_:
        print("\nTo split: pool add <new-pool>, move that group's hand seeds into its seeds.txt,"
              "\nand `move` any verdicts you want pinned; the rest re-home automatically.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new"); p.add_argument("name")
    p.add_argument("--scale", default="standard"); p.add_argument("--pool", default="main")
    p.add_argument("--use", action="store_true", help="make it the active profile")
    sub.add_parser("list")
    p = sub.add_parser("use"); p.add_argument("name")
    sub.add_parser("show")
    p = sub.add_parser("pool"); p.add_argument("action", choices=["add", "default", "describe"])
    p.add_argument("name"); p.add_argument("rest", nargs="*")
    p = sub.add_parser("seed"); p.add_argument("pool"); p.add_argument("films", nargs="+")
    p.add_argument("--weight", type=float, default=1.0)
    p = sub.add_parser("assign"); p.add_argument("--pool"); p.add_argument("--all", action="store_true")
    p = sub.add_parser("move"); p.add_argument("slug"); p.add_argument("pool")
    sub.add_parser("suggest")
    args = ap.parse_args()
    if args.profile:
        os.environ["CINESCOPE_PROFILE"] = args.profile
    {"new": cmd_new, "list": cmd_list, "use": cmd_use, "show": cmd_show, "pool": cmd_pool,
     "seed": cmd_seed, "assign": cmd_assign, "move": cmd_move, "suggest": cmd_suggest}[args.cmd](args)


if __name__ == "__main__":
    main()
