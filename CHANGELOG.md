# Changelog

## 0.3.1 — 2026-11-07

- Pane grouped into sections: Needs you and Running always show; Ready to merge, Ended, Stale and Boxes
  fold, closed until pressed (`muse/sections` remembers what is open).
- Orphans quiet for over a day move to Stale instead of flagging the lead; the wake-ups are unchanged.
- One line per lane with a coloured mark and plain words for the phase; a second line only for what to act
  on or a running lane's progress. Durations past a day read in days.
- Boxes fold to a count of busy and free; free boxes without a lease share one line.

## 0.3.0 — 2026-11-06

One lead runs a fleet of lanes directly. Design: [docs/v0.3-plan.md](docs/v0.3-plan.md).

- Needs-lead events: typed `needs_lead` facts (`question`, `review_failed`, `accept_failed_code`,
  `accept_failed_harness`, `box_wait_timeout`, `scope_violation`), claimed once with `ack --lead <seq>`.
  Accepts report their kind with `LANE-NEEDS-LEAD:` lines or `accept_exit_kinds`.
- `scope` globs on `lane_start`; a change outside them ends the lane `scope_violation`.
- Claude advisor for consults (`advisor: {model, max}`), read-only, budgeted per lane; any consult answer
  starting `ESCALATE:` raises a `question` instead of deciding for the lead.
- Box queue: `box` on `lane_start`, ticket files ordered by queue time, liveness from supervisor locks (no
  process-name matching), `LANE_BOX` for the accept, `box_wait_timeout` past budget. `boxes --json` adds the
  lease file holder.
- `answer` / `lane_answer` (text, box) and `lane_boxes`.
- Done lanes carry ready-to-merge evidence (branch, head, commits, accept log, review files).
- Config file (`$MUSE_LANES_CONFIG` or `<root>/config.json`) with a SimGoodie adapter in `examples/`.
- Hook: one prompt per poll from a persisted outbox (digest for several events), the submit never awaited, a
  dropped one resent next poll; toasts and notifications only for needs-lead events; status line counts lanes
  that need the lead; the pane gains a header, a Boxes section, needs-lead flags and per-lane drill-down.

## 0.2.3 — 2026-11-05

- Final-answer extraction is one shared helper: the last non-blank completed terminal text, falling back
  to the joined `run.output.delta` stream when muse 1.3 emits an empty terminal event. Consult, review and
  step finals all use it. Fixes consult answers lost when a stray empty run followed the real one (the
  supervisor logged "ok" while `ANSWER.md` said the helper failed).
- A consult that completes with no answer text anywhere is now logged `failed` with the reason, never `ok`.
- Pre-review severity rule: the generated brief says any blocker or should-fix finding means FAIL and PASS
  only when the findings are nits or none. A PASS whose numbered findings carry blocker/should-fix severity
  is overridden to FAIL (`PASS overridden: should-fix findings` in the summary) and runs the fix round.

## 0.2.2 — 2026-11-05

- `status --active` and `--limit` now filter from cheap state (status, ended time) before building
  per-lane objects, and the `git log -1` behind `last_subject` runs only for live lanes (running,
  retry_wait, accepting, queued, orphaned); ended lanes report a null subject. Listing output is
  otherwise unchanged. Fixes 38 s+ polls with hundreds of lanes stacking across sessions.
- Plugin test pins that stacked polls behind one slow status fetch issue a single fetch (the
  single-flight guard stands).

## 0.2.1 — 2026-11-05

- Pre-review `rounds` now counts fix re-runs, not reviews: the default `rounds: 1` reviews, and on FAIL re-runs
  the last step with the findings, re-runs the accept, and reviews again. A FAIL after the last fix ends the
  lane as `review_failed`. `rounds: 0` reviews once with no fix; negative values are rejected.
- Review and consult sessions run with `--disable-write`. The reviewer returns the verdict as its final answer
  text and the supervisor writes `.lane/REVIEW-<round>.md` itself; the consult helper's final answer is saved
  to `.lane/ANSWER-<n>.md` and `.lane/ANSWER.md` by the supervisor.
- A review session that changes HEAD or a tracked file ends the lane `failed` (`review session changed tracked
  files`); the summary lists the changed paths and nothing is reverted.
- `lane_start` passes `review.rounds: 0` through to the runner.

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
