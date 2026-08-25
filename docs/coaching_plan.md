# Post-Draft Coach — build plan

Spec for the post-draft coaching feature. Supersedes the original
`dota_coaching.md` planning doc, which has been deleted — everything still
relevant from it was folded in here, corrected against the actual codebase and
the live Stratz API. `proj_obj.txt` covers Phase 1/2 (the shipped draft
suggester); `progress.md` has current status and gotchas.

## What this is

A coach that fires **once a draft is complete** — both teams have 5 heroes —
and tells you how to play the game you just got. Deterministic context first,
LLM synthesis later.

**This is a separate product from the existing draft suggester.** The
suggester answers "who should I pick next?" with partial information during
the draft and is unchanged by any of this. The coach answers "how do I win
this specific 5v5?" after picking is over.

## Locked decisions

| Decision | Value | Why |
|---|---|---|
| Time basis | Rolling 2 weeks, everywhere | Matches `hero_wr`/`wr_a_b`. Mixed time bases are the documented cause of "numbers look off" — see progress.md |
| `patch` column | **Dropped** from all new tables | Current patch 7.40b has been live since 2025-12-24 (~8 months), so patch-partitioning yields one giant bucket anyway |
| Trigger | Complete 5v5 draft | Not incremental. The suggester owns the incremental case |
| Existing suggester | Untouched | No edits to `hero_matchup_advantage`, `stratz_hero_win_week`, `/draft-suggestions`, or `index.html`'s existing panels |
| UI location | Panel on `index.html`, unlocks at 5v5 | Reuses the chips already on screen; natural flow out of drafting |
| Lane/position source | `heroStats.stats` empirical positions | `hero_role.csv` stays scoped to the pick-suggestion feature and is not consulted by the coach. `my_role` is never inferred — it is an optional input, collected again in Phase G where it first affects output. See B3 |
| Branches (orig. Phase 5) | Deferred | Revisit after the LLM phase works |

## Verified findings

Checked live against the Stratz API and the production DB on 2026-08-24. These
correct the original doc, all in our favour.

**We ingest no match-level data at all.** The original doc assumes OpenDota
`/publicMatches`. We have none — everything is pre-aggregated hero-level stats.
This turns out not to matter, because Stratz pre-aggregates what Phase 0 needs.

**`stratz_hero_win_week.duration_minute` is a dead all-zeros column.** It is in
the table's primary key ([load_stratz_heroes.py:164](../src/app/ingestion/load_stratz_heroes.py#L164))
but `fetch_win_week` never passes a `groupBy`, so Stratz returns 0 for every
row. Verified in production: 2,540 rows, `SELECT DISTINCT duration_minute` →
`[0]`.

**Duration win rates are one query argument away.** `winWeek(groupBy:
HERO_ID_DURATION_MINUTES)` returns per-bucket counts, all 127 heroes in a
single API call. Verified output:

```
Anti-Mage  bucket 2: 45.4%  →  bucket 12: 52.0%   (rises)
Pudge      bucket 2: 54.3%  →  bucket 12: 49.2%   (falls)
Rubick     bucket 2: 53.7%  →  bucket 12: 48.2%   (falls)
```

`durationMinute` is a **bucket index (0–14), not a minute value**. Buckets
present: `[0, 2, 3, …, 14]` — 1 is absent entirely. A2 pinned the mapping at
5 minutes wide: bucket `b` = `[5b, 5b+5)`, bucket 14 = 70+. See A2 for how
that was established and why the obvious cross-check doesn't work.

**Item timings do NOT need parsed matches.** The original doc says they require
`purchase_log` and suggests approximating from GPM ÷ item cost. Wrong for us:
`heroStats.itemFullPurchase(heroId)` works on the free token and returns the
full per-minute purchase-time distribution with `matchCount`/`winCount` (491
rows for Anti-Mage). We get real medians. `heroId` is singular → 127 calls,
trivial against 2000/hr.

**Lane distribution is one call.** `heroStats.stats(heroIds:[…],
groupByPosition:true)` returns counts per POSITION_1..5 (Anti-Mage: 90% pos 1).
It will disagree with the hand-curated `hero_role.csv`; step E1 the final decision is to go with heroStats.stats and ignore hero_role.csv which is applicable to hero pick suggestion feature only.

**`take` on `winWeek` counts weeks, not rows.** Checked because the existing
`take: 2000` looked like it might truncate 2,394 rows. It does not — `take=2`
returns 2 weeks for every hero requested. No bug in the existing pipeline.

## ⚠️ The landmine

**Any "latest 2 weeks" rollup on `stratz_hero_duration_wr` must filter on
*weeks*, not rows.** That table holds 14 rows per hero-week, so
`ROW_NUMBER() ... <= 2` returns two duration buckets of a single week. Use
`DENSE_RANK() OVER (ORDER BY week DESC) <= 2`, as
[draft_context.py](../src/app/engine/draft_context.py)'s `load_bucket_stats`
does. Confirmed empirically on the real table, not theoretical.

**Superseded, kept for context.** This warning was originally aimed at
`compute_hero_matchup_advantage.py`, which computed `hero_wr` with that
`ROW_NUMBER` pattern against `stratz_hero_win_week` — so writing duration rows
into that table would have silently corrupted `hero_wr` → `xwr_a_b` →
`advantage`, i.e. all of Objective 1 and 2. Commit `01529a2` (which landed on
`main` while Phase A–C was being built) rebased `hero_wr` onto
`stratz_hero_matchups`, so that consumer no longer reads the week table and
that specific hazard no longer exists.

The separate-table decision still stands on its own: writing bucket rows into
`stratz_hero_win_week` would collide bucket 0 with the existing per-week total
row on the same primary key. The existing pipeline still gets zero edits from
this work.

---

## Phase A — Duration data · me · ~1–1.5 hours

Cheap because the discovery cost is already paid: the `groupBy` argument,
`take`'s week semantics, bucket density, and the free-tier limits were all
confirmed against the live API before this plan was written. A1 is ~40 minutes
of mechanical work adapted from existing loaders; A2 carries the only real
uncertainty in the phase.

**A1.** New `src/app/ingestion/load_stratz_hero_duration.py` → new table:

```sql
stratz_hero_duration_wr (
    hero_id         INTEGER REFERENCES stratz_heroes(id),
    week            BIGINT,
    duration_bucket INTEGER,
    games_played    INTEGER,
    wins            INTEGER,
    PRIMARY KEY (hero_id, week, duration_bucket)
)
```

**Scope: all heroes, all available weeks** — 33,782 rows (127 heroes × 19 weeks
× 14 buckets). The grid is perfectly dense: every hero-week has exactly 14
buckets, so there is no missing-bucket case to handle at ingest.

Hero ids come from `stratz_heroes`, never a hardcoded range. The planning
probe used `range(1, 150)` and silently missed **Largo (id 155)** — one hero's
entire 266-row grid — which is why the pre-build estimate said 33,516.

Stores raw weeks like `stratz_hero_win_week` does; the 2-week rollup happens at
query time, same convention as the rest of the pipeline. Fetching all weeks
rather than just 2 costs the same single API call (`take` counts weeks, not
rows) and means a later change to the window needs no re-ingest.

> ⚠️ **The landmine applies here too, in a new form.** This table has 14 rows
> per hero-week, so any consumer rolling up "the latest 2 weeks" must filter on
> *weeks* — `DENSE_RANK() OVER (ORDER BY week DESC) <= 2`, or an explicit
> `week IN (...)` — never `ROW_NUMBER() <= 2`, which would silently return two
> duration buckets of a single week. Same trap as
> `compute_hero_matchup_advantage.py`, different table.

> **Verify — done 2026-08-24, all passing:** 33,782 rows, 127 × 19 × 14, grid
> density min = max = 14. Anti-Mage rises (bucket 2: 45.4% → 12: 52.0%),
> Pudge falls (54.3% → 49.2%), Rubick falls (53.7% → 48.2%) — matching the API
> probe exactly, so the DB round-trip is lossless. `stratz_hero_win_week`
> unchanged at 2,540 and `hero_matchup_advantage` unchanged at 14,868.
> The landmine was also confirmed empirically: `ROW_NUMBER() <= 2` on the new
> table keeps 2 rows spanning 1 week and 2 buckets, exactly as warned.

**A2.** Pin the bucket→minute mapping and document it in progress.md.

**Result: bucket `b` = minutes `[5b, 5b+5)`, bucket 14 = 70+.**

> **Verify — done 2026-08-24, with a caveat.** The mapping rests on a
> *structural* argument, not a direct measurement. Stratz's per-minute data
> caps at 75 min (`stats` with `minTime:60, maxTime:100` returns only rows
> 60..75) and `winWeek` exposes bucket indices 0..14 — width 5 is the only
> width whose top bucket lands on that cap (width 4 caps at 60, width 6 needs
> 90). Corroborated by the median falling in bucket 7 → 35-40 min.
>
> The planned cross-check against `heroStats.stats` **does not work and should
> not be retried**: that endpoint covers only ~31% of the matches `winWeek`
> does for the same hero and week (231,702 vs 745,573) because it is a
> parsed-match subset, which skews longer (median 42 min). Inverting its
> survival CDF against bucket fractions gives incoherent widths drifting
> 3.1→6.1 min. No available argument reconciles the two populations.

> ⚠️ **Chart buckets 3-13 only (15-70 min, 98.3% of games).** Bucket 0 is
> anomalous — 1.05% of games, larger than bucket 2 (0.46%), while bucket 1 has
> exactly zero rows in all 33,782. That reads as a catch-all bucket, not a
> literal 0-5 min bin. Bucket 14 (70+) is a 0.12% tail. Phase C's axis should
> run 15→70 min and leave the edge buckets out.

## Phase B — Context builder + endpoint · me · ~1 evening

**B1.** `src/app/engine/draft_context.py` — a pure function:

```python
build_context(my_hero_id, my_role, ally_picks, enemy_picks) -> DraftContext
```

**v1 holds the power curve only**: my team's summed win rate per bucket,
theirs, the delta, the crossover bucket, and a `tempo_verdict`. No
`predicted_lane`, no `enemy_clocks`, no comp tags — those are Phase G inputs,
not chart inputs, and holding them back is what keeps this to one evening.

The full shape, which Phase E4 builds toward and Phase G consumes:

```json
{
  "power_curve": { "0-25": 4.1, "25-35": 1.2, "35-45": -3.8, "45+": -6.2 },
  "tempo_verdict": "you_are_faster",
  "predicted_lane": { "vs": ["Abaddon", "Bane"], "with": ["Warlock"],
                      "matchup_delta": -2.4 },
  "enemy_clocks": [ { "hero": "Anti-Mage", "item": "Manta", "min": 24 } ],
  "my_comp":    { "lockdown": 3, "save": 1, "waveclear": 2, "tower_dmg": 1 },
  "their_comp": { "lockdown": 2, "save": 2, "dispel": 2, "silence": 1 }
}
```

Bucket keys above are illustrative — the real ones come from Stratz's 14
buckets once A2 pins the mapping. `matchup_delta` and the `with` figures come
from the already-shipped `hero_matchup_advantage` and `stratz_hero_synergy`
paths, not a reimplementation.

**B2.** **pytest — the first tests in this repo.** Synthetic fixtures, no DB.
B1 is deterministic by construction, which is what finally makes this easy.

> **Verify:** green suite covering crossover detection, missing buckets,
> sign-flip, and the no-crossover case.

**B3.** `POST /draft-analysis`:

```json
{ "my_hero_id": 1, "my_role": null,
  "ally_picks": [5 ids], "enemy_picks": [5 ids] }
```

Exactly 5 and 5 required — that is the whole point of the post-draft trigger.
`my_hero_id` must appear in `ally_picks`. Validation otherwise mirrors
[draft.py](../src/app/api/routers/draft.py). New endpoint, not an extension of
`/draft-suggestions`.

`my_role` is **optional, and still never inferred**. It began as a required
field with a dropdown beside the "which one is me" selector, but the role
selector was removed after Phase C shipped: the power curve doesn't read role
at all, so the control sat there doing nothing. Rather than infer a value —
`hero_role.csv` is scoped out of this feature and E1's position data would be
guessing at something you already know — the field simply accepts `null`, and
is validated only when supplied. **Phase G brings the selector back**, because
that is where role first changes the output. E1's position data stays reserved
for `predicted_lane` (working out the *enemies'* likely lanes), which is what
it is actually good for.

> **Verify:** live smoke test against the real DB, one draft's numbers
> hand-checked end to end.

## Phase C — Ship the chart · me · ~1 evening

**C1.** Panel on `index.html`, unlocking when both chip lists reach 5, plus a
"which one is me" selector. No new pick UI.

**C2.** Two-line chart across the buckets with the crossover marked. Inline
SVG, no library — matches the existing no-framework `web/` stack.

**C3.** Headless-Playwright verification, same approach as the ally-picks and
player-history work.

**C4.** Deploy: push, `docker compose up -d --build api` on the Droplet,
Cloudflare auto-deploys `web/`. Confirm before pushing.

> **Labelling constraint:** five heroes' summed duration win rates are a
> heuristic, not a team win probability — all interaction effects live in the
> synergy and matchup tables instead. The UI says "power curve," never "win
> chance." Otherwise this becomes the next number that looks off.

## Phase D — GATE · you · 20 games

Play with just the curve before a single line of prompt gets written. If the
curve doesn't change your decisions, Phases E–H are wasted effort — and that
costs one evening to find out instead of six.

## Phase E — Remaining context signals · only if D passes

| Step | Who | Work |
|---|---|---|
| E1 `hero_lane_dist` | me | 1 call (`stats(groupByPosition:true)`) → `predicted_lane`. Source decided: empirical positions only, `hero_role.csv` is not consulted |
| E2 `hero_threat_timing` | me | 127 calls to `itemFullPurchase`, real medians → `enemy_clocks` |
| E3 `hero_tags.csv` | **you** | 127 heroes × 10 booleans (lockdown, save, dispel, waveclear, tower_dmg, silence, break, cheap_ult, illusion, summons). I generate the skeleton with hero names pre-filled; you fill the values |
| E4 loader + fold in | me | `load_hero_tags.py` mirroring `load_heroes_roles.py`, then extend `build_context` + tests |

E3 stays hand-authored deliberately — the original doc is right that a derived
version would be worse, and `hero_role.csv` is the existing precedent.

### E3 tag definitions

`data/hero_tags.csv` is generated with all 127 heroes in alphabetical order and
10 empty tag columns. **Put `1` where the tag applies and leave the cell blank
otherwise** — blank is read as 0, and blank-vs-0 carries no meaning. Judge from
the hero's own abilities and talents, **not** from items they commonly buy
(otherwise every hero has `break` via Silver Edge and the column says nothing).

| Tag | Means |
|---|---|
| `lockdown` | A reliable targeted disable that stops a fleeing or channelling hero — stun, hex, root, leash. Slows don't count |
| `save` | Can rescue an ally who would otherwise die: a shield, heal-through-burst, invulnerability, or a reposition |
| `dispel` | Can remove buffs or debuffs, basic or strong, on allies or enemies |
| `waveclear` | Can delete a creep wave with one or two casts from roughly level 6 without needing items |
| `tower_dmg` | Takes buildings unusually fast — high base damage, siege summons, or a building-focused ability |
| `silence` | Has a silence or mute in the kit |
| `break` | Has a **native** break, i.e. disables passives without Silver Edge |
| `cheap_ult` | Ultimate is up for nearly every fight — low cooldown or low mana, no long windows without it |
| `illusion` | Creates illusions |
| `summons` | Creates controllable units (not illusions) |

A hero can carry several tags; there's no cap and no requirement that every
hero has at least one. Where a tag is arguable, prefer marking it only when the
hero is *known* for that thing — the point is to separate lineups that clearly
have a capability from ones that clearly don't.

## Phase F — Patch blob · ~½ evening

Source: **https://www.dota2.com/patches**. Still worth doing for the LLM
prompt even though `patch` was dropped as a column — the version string pins
what the model is allowed to assume.

- **you:** confirm whether to scrape that page or paste the notes once.
- **me:** store the blob with the version string from `constants.gameVersions`
  (currently `{id: 182, name: "7.40b"}`).

## Phase G — LLM synthesis · ~2 evenings

- **you:** pick provider/model, confirm the spend.
- **me:** one call — context JSON + patch blob + strict output schema. Central
  prohibition: *every number in the output must come from the supplied context;
  if a timing or win rate isn't in the input, don't state one.* Cache keyed on
  `sha256(sorted_heroes + my_hero + role + patch_version)`.

Output shape:

```json
{ "frame": "one sentence: who wins long, who must force",
  "lane":  { "instruction": "...", "first_item": "...", "risk": "..." },
  "clock": { "your_window": "...", "their_spike": "..." },
  "wincon": "one sentence",
  "detail": { "early": "...", "mid": "...", "late": "..." } }
```

> **Verify:** 15 real drafts, zero hallucinated numbers. **You** are the judge
> — I can't grade my own output here.

## Phase H — Coach UI · ~1 evening

Default view is four lines — `frame` / `lane` / `clock` / `wincon` — targeting
**under 90 seconds of reading**. `detail` lives behind an expand, the same
glanceable-then-drill pattern as the existing bar rows.

**Fire the call automatically when the 10th hero is picked, not on a button**,
so it has already resolved by the time you look at it. This is why the cache in
Phase G matters: an auto-fire on every completed draft is only affordable if
repeat drafts are free.

---

## Critical path

**Step 0 → A → B → C is roughly three evenings**, then the 20-game gate.
Everything from E onward depends on what D says.

## Deferred

**Branches** (original Phase 5). Pre-generate three lane outcomes (won / even /
lost) and two mid-game states (ahead / behind), either in a single follow-up
call at draft time or lazily on tap. In-game this is a **segmented toggle,
never a text box** — you will not type at minute 14. Revisit after G.

**Outcome logging** — the original doc's "did any of this work?" check, and the
only real defence against a coach that is fluent and wrong. Method: from Phase
G onward, log every generated plan keyed by `match_id`; once a week pull those
matches from OpenDota and check one thing — did the games where you followed
the plan's clock go better than the ones where you didn't?

Blocked on two things. It needs per-match ingestion
(`/players/{id}/matches`, which extends `load_players.py` but is real new
work), and `players_id.txt` currently has only one public player — King Arthas
and Parma are still private — so the sample would be n=1 for a while.
