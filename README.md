# muse — Muse lanes for Claude Code

A Claude Code plugin that runs Meta's Muse CLI (`muse exec`) agents as supervised background
lanes. You start a lane from a Claude session. A detached supervisor runs it to the end, retrying through outages and stalls, then runs your
acceptance command. The session gets exactly one prompt when the lane finishes, so nobody has to poll.

Claude stays the lead that plans and reviews, and Muse does the long, checkable work: a mechanical change across many files, a failing test suite, a scripted migration.

## What you get

- **Tools:**
  - `lane_start` starts a lane. A lane is one or more steps, each a brief file or inline prompt, run in order in one
    working directory, with an optional acceptance command, Muse pre-review, mid-step consults, a Claude
    advisor, a path scope, and a gate box.
  - `lane_status` shows the active view (live lanes plus those ended in the last 24 h, with a count of older
    lanes), one lane by id, or every lane with `all: true`.
  - `lane_summary` gives attempts, commits, acceptance output, pre-review rounds, consults, each step's final
    answer, and for a finished lane the ready-to-merge evidence.
  - `lane_answer` is the lead's reply to a lane that needs it: `text` answers an escalated question, `box` moves
    a lane that is waiting on a busy box to another box (refused once the lane holds its box).
  - `lane_boxes` lists gate boxes: the lane holding each, the lanes queued for it, and the lease file's holder.
  - `lane_stop` stops a lane; `lane_resume` continues a lane whose supervisor died.
- **Pane:** `/muse` opens a pane (it also opens on `lane_start` when the window is wide enough). A header counts
  running lanes, lanes that need the lead, and lanes ready to merge. A Boxes section shows each box's holder,
  queue and lease. Each lane gets a row: a needs-lead flag, label, status, phase and its elapsed time, box,
  total time, idle minutes, pre-review verdict, then commits with the last subject and branch, then the
  needs-lead detail or failed accept tail. Lanes that need the lead come first, then this session's working
  lanes. The `▸` toggle expands a row with its summary (or live status), the merge evidence, and `stop`,
  `resume` and `refresh` buttons.
- **Wake-ups:** the session is woken when one of its lanes ends or needs the lead, never for routine progress.
  Several events in one poll arrive as one digest prompt. See [Needs-lead events](#needs-lead-events).
- **Status line:** `muse: <label> <phase>` with one working lane, else `muse: N running · M need lead`.
- **Toasts:** only for lanes that need the lead or ended other than `done`.

## Requirements

- Claude Code with plugin module support (`claude plugin validate` must accept `hooks/index.tsx`).
- The Muse CLI as `muse` on `PATH`, or its path in `MUSE_BIN`.
- Python 3 for the runner, `bin/muse-lane`. It uses the standard library only.
- macOS or Linux. It has only been run on macOS.

## Install

```bash
claude plugin marketplace add alexanderradahl/muse-lanes
claude plugin install muse@muse-lanes
```

If Muse authenticates with an API key, point the plugin at a dotenv file that holds it:

```bash
claude plugin install muse@muse-lanes --config envFile=$HOME/.config/muse/.env
```

You can also set it later with `/plugin configure muse@muse-lanes`. The runner passes the file's values to `muse exec`.
It redacts them as `***` from every file it writes and never logs them. Leave `envFile` empty if `muse` is already
logged in.

## How a lane runs

1. `lane_start` writes the lane into `~/.muse-lanes/<id>/` (or `$MUSE_LANES_ROOT`). The folder is `0700` and its
   files are `0600`. It then starts the supervisor as a detached process that outlives the Claude session.
2. Each step runs `muse exec --json` at reasoning effort `max` unless you pass `effort`. Muse's sandbox
   has no network; remote steps belong in the unsandboxed `accept`.
3. A step counts as stalled when its event log, its git tree and its process CPU are all quiet for `stall_min`
   minutes (40 by default). A stalled attempt is killed and retried.
4. Failures are classified before any retry:

   | Failure | Handling |
   | --- | --- |
   | Stall, timeout, 429, 5xx, network error | Retried with backoff (2, 5, 10, 20, 30, 30 min), up to 6 attempts |
   | Model `failed` or `cancelled` | Retried once |
   | Authentication failure, or `muse` missing | Not retried |

5. After the last step, `accept` runs in the working directory under a 2-hour timeout. Its exit code decides
   whether the lane ends `done` or `failed`. While it runs, lines matching `^LANE-PHASE: (\S+)` set the lane's
   phase so long remote checks stay visible (see below).
6. With `review` set and a passing accept, a fresh Muse session pre-reviews the diff (see below). A FAIL
   re-runs the last step with the findings appended, then the accept and the review again, up to `rounds`
   fix re-runs (default 1; 0 reviews once with no fix).
7. The plugin checks the runner's active view every 20 seconds. When one of its lanes reaches a final state it
   records the announcement, then submits the summary.

The runner works without Claude too:

```bash
bin/muse-lane --help
bin/muse-lane status --active
bin/muse-lane status --json --active --limit 10
```

## Muse pre-review

One Muse review runs BEFORE the work reaches the Opus lead, so the lead spends fewer tokens on review rounds.
The Muse pass is a pre-filter, labelled "Muse pre-review (not the independent review)" everywhere it appears;
Opus still does the final review.

Pass `review: true` to `lane_start` (or `{brief, rounds}` with extra instructions and up to `rounds` fix
re-runs after a FAIL, default 1; 0 reviews once with no fix). After the last step and a passing accept, the
runner starts a FRESH `muse exec` session — no shared context, `--disable-write` — with a generated brief
holding the step briefs, `git diff <head_start>..HEAD --stat` plus the full diff (capped; past the cap it
lists files and asks the reviewer to read them), the accept output tail, and any `control/*` branches created
since `head_start`. The brief asks for: each brief requirement checked against the diff, writes outside the
named allowlist, tests that would pass without the change, missing or toothless controls, and behaviour the
accept didn't exercise. The reviewer returns the verdict as its final answer text (first line `PASS` or `FAIL`,
then numbered findings with severity and file:line); the supervisor records it as `.lane/REVIEW-<round>.md` itself.
Each finding is a blocker, a should-fix, or a nit: any blocker or should-fix means `FAIL`, and a `PASS` that
lists one is overridden to `FAIL` and runs the fix round like any other `FAIL`.

On FAIL with fix re-runs left, the runner archives the last step's attempts, appends the findings to its brief,
re-runs it and the accept, and reviews again (round N of `rounds + 1`). A FAIL on the last review ends the lane
as `review_failed`, which the hook treats like `failed`. A review session that crashes or times out records
`review_error` and does not block a passing accept — unless it changed HEAD or a tracked file, which ends the
lane `failed` instead (the changed paths are listed in the summary; nothing is reverted). Every round's verdict
and findings appear in `lane_summary` under the pre-review heading.

## Mid-step consults

While a step runs, Muse may write `.lane/ASK.md` with a question (plus paths worth reading). The supervisor
notices on its next poll, renames it to `.lane/ASK-<n>.md`, runs a short helper `muse exec` — fresh session,
`--disable-write`, `--reasoning-effort high`, 15-minute timeout — whose final answer the supervisor saves to
`.lane/ANSWER-<n>.md`, then writes `.lane/ANSWER.md` for the step to read. Each step's brief starts with three lines describing the protocol
(write `ASK.md`, wait for `ANSWER.md`, keep working meanwhile if it can). At most `consult_max` answers per step
(default 3); past it, `ANSWER.md` says the limit was reached. Each exchange is logged in the summary.

## Accept phases

Steps set phase `step:<n>` and review rounds set `review:<n>`. While the accept runs, any line matching
`^LANE-PHASE: (\S+)` sets the lane's phase and its start time, so the panel and status line show what a long
accept is doing.

The intended pattern for long remote checks: run them inside the accept — for example a box gate script over
ssh — and print a `LANE-PHASE` line before each. The accept is unsandboxed (Muse's own sandbox has no network),
the checks cost no Claude tokens while they run, and the lead reads only the verdict:

```bash
lane_start(..., accept="""
  echo 'LANE-PHASE: unit';   ./gate.sh unit   || exit 1
  echo 'LANE-PHASE: device'; ./gate.sh device || exit 1
""")
```

## Needs-lead events

The runner records a typed fact when a lane needs a decision only the lead can make:

| Kind | Raised when | Lane after |
| --- | --- | --- |
| `question` | A consult answer starts `ESCALATE: <reason>` | Keeps working; `lane_answer` with `text` replies |
| `review_failed` | Pre-review FAIL after the last fix round | Ends `review_failed` |
| `accept_failed_code` | Accept exits nonzero with no other mapping | Ends `failed` |
| `accept_failed_harness` | Accept exit code mapped to it, or a `LANE-NEEDS-LEAD:` line | Ends `failed` |
| `box_wait_timeout` | The box queue waited past its budget, or an accept exit mapped to it | Queue: keeps its place; `lane_answer` with `box` moves it |
| `scope_violation` | A step changed a path outside the lane's `scope` globs | Ends `failed` |

An accept reports its own failure kind with `LANE-NEEDS-LEAD: <kind> <detail>` (the last line wins) or through
`accept_exit_kinds` in the config. The runner never guesses a kind from log text.

Each event is claimed exactly once and goes into an outbox kept in the session's state. One prompt carries the
outbox: a single event in full, several as a digest with one block per lane and a pointer to `lane_summary`. A
lane that ends `done` reads **READY TO MERGE** with its branch, head, commits, accept log and review files. The
plugin never merges; the lead does, with its own merge script.

## Advisor

`advisor: {model, max}` on `lane_start` routes a lane's consults to a read-only Claude session (`sonnet` by
default, `opus` when the brief needs it, `max` calls per lane, default 3) before the Muse helper. The advisor
reads files only, runs with mods and hooks off, and sees the lane's accept command and scope. It may not change
either: a question that needs a different acceptance, scope or product decision comes back `ESCALATE:` and
wakes the lead. Every call is logged in the summary with who answered and whether it escalated.

## Boxes

`box` on `lane_start` hands the lane a gate box. Before each accept the supervisor takes a ticket in
`<root>/_boxes/<box>/` and waits, in phase `box_wait`, until its ticket is the oldest whose lane is alive. It
checks liveness through each lane's supervisor lock (pid plus start time), never by matching process names: two
`pgrep -f` waiters once deadlocked on each other's command text. The accept sees `LANE_BOX` and holds the box
until it ends. Past `box_wait_max_min` the lane wakes the lead with `box_wait_timeout` and keeps its place.

The queue orders this plugin's lanes only. The project's gate script still claims the real box; the pane reads
the project's lease file to show who holds it.

## Config

The runner reads `$MUSE_LANES_CONFIG`, else `<lanes root>/config.json`, and copies it into each lane at start.
Keys: `accept_exit_kinds`, `box_wait_max_min`, `lease_file`, `lease_claim_re`, `lease_release_re`
(named groups `box`, `who`, `what`, `at`), `advisor_cmd`, `advisor_timeout_min`. The core names no project;
[`examples/simgoodie.json`](examples/simgoodie.json) is the SimGoodie adapter (gate exit 5 = harness, 6 = box
wait timeout, `LEASES.md` claims).

## Known limits

- **A queued wake-up can be lost.** An event is queued before it is claimed and leaves the queue when its prompt
  is submitted. A dropped prompt goes back and is retried after 20 s, doubling to 10 min. If the host drops the
  prompt after a plugin reload or a session restart, the wake-up is lost; `lane_status` still shows the lane.
- **No OS banner in the Desktop app.** `$.ui.notify` reaches terminals only; a `Notification` settings hook
  (type `plugin_notification`) can raise a banner there.
- **Only the starting session is woken.** A lane started before a Claude Code restart is not announced to the new
  session; use `lane_status`.
- **Marketplace installs are lightly tested.** Installing from the marketplace was tested; loading the tools
  from a marketplace install was not, since it was developed as a local plugin.

## Development

```bash
python3 bin/test_muse_lane.py      # runner tests, about 40 s, using a fake muse
claude plugin test .
claude plugin validate --strict .
```

`tsconfig.json` is for editors only and extends `.claude-plugin/types/`, which Claude Code's plugin tooling
generates. That folder is not committed.

## License

MIT. See [LICENSE](LICENSE). Muse is Meta's product, and this plugin is not affiliated with Meta or Anthropic.
