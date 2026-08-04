# The once-per-ET-date guard cancels the night's real sweep

**Found:** 2026-08-04 · **Status:** diagnosed, fix NOT applied (schedule behaviour — David's call)

## What happened

`run_nightly_autonomous.sh` holds a once-per-ET-date lock so launchd
cannot double-fire the cycle on wake. Correct instinct, wrong grain.

A **manual** run at 06:50 ET on 2026-08-03 wrote
`state/schedule_guards/nightly.json → last_et_date: 2026-08-03`. When the
**scheduled** nightly came around at 23:00 ET the same evening, the ET
date still read 2026-08-03, so it matched the guard and skipped.

Consequence: a single manual run in the morning silently cancels that
night's real sweep, and the published feed goes ~37 hours without a
refresh instead of ~24. On 2026-08-03 that meant the feed kept serving a
snapshot taken during a city-API outage — an empty drop — all of the
following day.

## Why it matters more than it looks

The manual run is usually a *diagnostic*, often on a partly-broken
system. The scheduled run is the real one. The current guard lets the
diagnostic consume the slot reserved for the real thing, and does it
silently — nothing in any log says "tonight's sweep was cancelled by
this morning's manual run".

## Options (needs David — this is schedule behaviour, AGENTS.md)

1. **Record the trigger, guard only the scheduled path.** Write
   `trigger: "manual" | "scheduled"` into the guard, and let a scheduled
   run proceed if the day's only claim came from a manual one. Keeps the
   double-fire protection that motivated the lock. *Recommended.*
2. **Guard on a rolling window** — skip only if a cycle completed within
   the last N hours (say 12), rather than within the calendar date.
3. **Leave it, but say so.** At minimum log a line, and surface it in the
   snapshot, when a scheduled cycle is skipped because of an earlier
   claim — so a stale feed always has a visible reason.

Any of the three is a small change. Doing none of them means every
manual diagnostic silently costs a night.
