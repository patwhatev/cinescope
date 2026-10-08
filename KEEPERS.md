# Keepers

The running list of films confirmed via Dailies grading — every 4★ or 5★ call,
across every iteration. This file is additive: nothing already on it is
removed, and `pipeline/update_keepers.py` is what appends to it (don't hand-edit
the table below the fold; add notes in prose instead).

**Weight**: 5★ promotes a film into `seeds.txt` at full weight (1.0, as
diagnostic as an originally-stated seed); 4★ at half weight (0.5). Both feed
the next crawl. `pipeline/promote_seeds.py` regenerates the promoted block of
`seeds.txt` from `out/grades.csv` every run — raise or lower a star later and
it's picked up next sync.

## Iteration 01 — 2026-10-07/08, 29 kept of 47 graded (all 5★ — no 4★ tier existed yet)

| Film | Year | Director | Mini-theme | Score |
|---|---|---|---|---|
| Bully | 2001 | Larry Clark | Challenging or sexual themes & twists | 77.2 | <!--slug:bully-->
| Dahmer | 2002 | David Jacobson | Graphic violence and brutal revenge | 75.9 | <!--slug:dahmer-->
| Kids | 1995 | Larry Clark | Challenging or sexual themes & twists | 72.7 | <!--slug:kids-->
| L.I.E. | 2001 | Michael Cuesta | Emotional teen coming-of-age stories | 72.1 | <!--slug:lie-2001-->
| Nymphomaniac: Vol. I | 2013 | Lars von Trier | Erotic relationships and desire | 70.2 | <!--slug:nymphomaniac-volume-i-->
| Maniac | 2012 | Franck Khalfoun | Gory, gruesome, and slasher horror | 67.3 | <!--slug:maniac-2012-->
| Dogtooth | 2009 | Yorgos Lanthimos | Challenging or sexual themes & twists | 64.2 | <!--slug:dogtooth-->
| Mulholland Drive | 2001 | David Lynch | Dreamlike, quirky, and surreal storytelling | 62.8 | <!--slug:mulholland-drive-->
| Tetsuo: The Iron Man | 1989 | Shinya Tsukamoto | Graphic violence and brutal revenge | 61.4 | <!--slug:tetsuo-the-iron-man-->
| Vanilla Sky | 2001 | Cameron Crowe | Dreamlike, quirky, and surreal storytelling | 60.7 | <!--slug:vanilla-sky-->
| Last Tango in Paris | 1972 | Bernardo Bertolucci | Erotic relationships and desire | 59.0 | <!--slug:last-tango-in-paris-->
| Capote | 2005 | Bennett Miller | Gripping, intense violent crime | 58.9 | <!--slug:capote-->
| Donnie Darko | 2001 | Richard Kelly | Surreal, thought-provoking visions of life & death | 57.8 | <!--slug:donnie-darko-->
| Maniac | 1980 | William Lustig | Gory, gruesome, and slasher horror | 57.4 | <!--slug:maniac-1980-->
| Inland Empire | 2006 | David Lynch | Dreamlike, quirky, and surreal storytelling | 56.3 | <!--slug:inland-empire-->
| Eyes Wide Shut | 1999 | Stanley Kubrick | Erotic relationships and desire | 55.3 | <!--slug:eyes-wide-shut-->
| Visitor Q | 2001 | Takashi Miike | Challenging or sexual themes & twists | 54.0 | <!--slug:visitor-q-->
| In Cold Blood | 1967 | Richard Brooks | Gripping, intense violent crime | 52.4 | <!--slug:in-cold-blood-->
| Midnight Cowboy | 1969 | John Schlesinger | Powerful stories of heartbreak and suffering | 50.2 | <!--slug:midnight-cowboy-->
| The Killing of a Sacred Deer | 2017 | Yorgos Lanthimos | Twisted dark psychological thriller | 49.9 | <!--slug:the-killing-of-a-sacred-deer-->
| River's Edge | 1986 | Tim Hunter | Student coming-of-age challenges | 49.2 | <!--slug:rivers-edge-->
| Baby Reindeer | 2024 | Tofilska / Bornebusch | Challenging or sexual themes & twists | 49.0 | <!--slug:baby-reindeer-->
| Hereditary | 2018 | Ari Aster | Terrifying, haunted, supernatural horror | 49.0 | <!--slug:hereditary-->
| Dead Ringers | 1988 | David Cronenberg | Challenging or sexual themes & twists | 48.9 | <!--slug:dead-ringers-->
| Spring Breakers | 2012 | Harmony Korine | Challenging or sexual themes & twists | 48.9 | <!--slug:spring-breakers-->
| Halloween | 2007 | Rob Zombie | Gory, gruesome, and slasher horror | 47.5 | <!--slug:halloween-->
| Crash | 1996 | David Cronenberg | Erotic relationships and desire | 47.4 | <!--slug:crash-->
| Love Streams | 1984 | John Cassavetes | Powerful stories of heartbreak and suffering | 46.4 | <!--slug:love-streams-->
| High Tension | 2003 | Alexandre Aja | Gory, gruesome, and slasher horror | 46.1 | <!--slug:high-tension-->

*Note: Baby Reindeer is a limited series, not a film — letterboxd files it under
`/film/`. Keeping it on the list since you kept it, flagging for awareness.*

---

## Passed, for the record (iteration 01)

Graphed below because *why* something was rejected is as useful as why
something was kept — see the questions in chat. Not part of the recommender's
positive seed set.

21 Grams · Beau Is Afraid · Boyhood · Boys Don't Cry · Cake · Ed Gein ·
Fight Club · I'm Thinking of Ending Things · Mr. Nobody · Remember Me ·
Sling Blade · The Butterfly Effect · The Devil's Rejects ·
The Haunting of Hill House · The Poughkeepsie Tapes · The Woman · Waves ·
What Dreams May Come

---

## Decisions from iteration 01 grading

- **Seed promotion**: resolved by adding a 4★/5★ weight tier (see above)
  instead of promoting everything at equal weight — keeps the canon-adjacent
  kept titles (Halloween, Midnight Cowboy) from outweighing the original
  obscure/extreme core (Sombre, Angst, Teorema) in graph convergence. All 29
  above went in at 1.0 since that's what a flat "keep" meant before the
  weight tier existed; revisit any of them to 4★ in Dailies if "light" is
  what you actually meant.
- **Grief/family-drama cluster** (Boys Don't Cry, 21 Grams, Boyhood, Cake,
  Remember Me, Waves, Mr. Nobody, The Butterfly Effect): called as execution,
  not a taste-level aversion to earnest heartbreak drama. No theme penalty
  added — left to the channel reweighting.
- **Fight Club / Boyhood**: confirmed genuine taste mismatch, not
  familiarity fatigue — graded straight, no exclusion from channel tuning.
- **Found-footage / mockumentary style** (The Poughkeepsie Tapes): confirmed
  not a format-level aversion — just a weak film. No new signal added; the
  existing quality channel already penalizes thinly-reviewed titles like it.

## Iteration 02 — 2026-10-08, 9 newly kept

| Film | Year | Weight | Score | |
|---|---|---|---|---|
| Lost Highway | 1997 | heavy (1.0) | 79.2 | <!--slug:lost-highway--> |
| The Texas Chain Saw Massacre | 1974 | heavy (1.0) | 61.06 | <!--slug:the-texas-chain-saw-massacre--> |
| Scenes from a Marriage | 1974 | heavy (1.0) | 51.88 | <!--slug:scenes-from-a-marriage--> |
| Audition | 1999 | heavy (1.0) | 50.66 | <!--slug:audition--> |
| Ichi the Killer | 2001 | heavy (1.0) | 46.48 | <!--slug:ichi-the-killer--> |
| Alps | 2011 | light (0.5) | 50.61 | <!--slug:alps--> |
| Wild at Heart | 1990 | light (0.5) | 49.06 | <!--slug:wild-at-heart--> |
| Saw | 2004 | light (0.5) | 47.13 | <!--slug:saw--> |
| The House That Jack Built | 2018 | light (0.5) | 46.66 | <!--slug:the-house-that-jack-built-2018--> |
