# Changelog

## 0.2.0 — 2026-11-05

- Muse pre-review: `lane_start` takes `review` (`true` or `{brief, rounds}`); after a passing accept a fresh
  Muse session reviews the diff and writes `.lane/REVIEW-<round>.md` (`PASS`/`FAIL` plus findings). FAIL
  re-runs the last step with the findings appended, up to `rounds`; no rounds left ends the lane as
  `review_failed`. Crashes and timeouts record `review_error` without blocking a passing accept. The summary
  labels every round "Muse pre-review (not the independent review)".
- Mid-step consults: a step may write `.lane/ASK.md`; the supervisor answers via a fresh read-only helper into
  `.lane/ANSWER.md` (at most `consult_max` per step, default 3). Briefs carry a three-line protocol prefix.
- Accept phases: `LANE-PHASE: <name>` lines during the accept set the lane's phase; steps set `step:<n>` and
  review rounds `review:<n>`.
- Active view: `status --json` takes `--active` and `--limit`; the hook polls the active view and a bare
  `lane_status` shows it plus an older-lanes count (`all: true` lists everything).
- Panel rows show phase and elapsed times, idle minutes marked past 75% of the stall budget, commits with the
  last subject, and the last accept lines on failure, own lanes first. The status line names one owned lane's
  label and phase.
- Runner passes `--sandbox-network restricted` to every `muse exec` (no network inside Muse's sandbox).

## 0.1.1 — 2026-10-01

- Plugin tests: `tests/plugin.test.ts` runs under `claude plugin test`, faking the
  runner beneath the plugin (status, summary and ack semantics) and pinning the
  `$.state.set(ref, value)` shape.
- Status line: `muse: N running` while this session owns running or retry-waiting
  lanes, cleared when there are none, updated on each poll.
- Toast: a one-line toast naming the lane and its end state when an owned lane
  ends, alongside the wake-up prompt.

## 0.1.0 — 2026-10-01

First release.

- `lane_start`, `lane_status`, `lane_summary`, `lane_stop` and `lane_resume` tools, and a `/muse` panel.
- Detached supervisor: chained steps, an acceptance command, stall detection, failure classes with backoff,
  and a per-lane lock so a resume never starts a second Muse beside a live one.
- One wake-up per finished lane, delivered only to the session that started it.
- Env-file values redacted from every lane file; lane folders are `0700`, files `0600`.
