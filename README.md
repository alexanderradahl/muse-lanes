# muse — Muse lanes for Claude Code

A Claude Code plugin that runs Meta's Muse CLI (`muse exec`) agents as supervised background
lanes. You start a lane from a Claude session. A detached supervisor runs it to the end, retrying through outages and stalls, then runs your
acceptance command. The session gets exactly one prompt when the lane finishes, so nobody has to poll.

Claude stays the lead that plans and reviews, and Muse does the long, checkable work: a mechanical change across many files, a failing test suite, a scripted migration.

## What you get

- **Tools:**
  - `lane_start` starts a lane. A lane is one or more steps, each a brief file or inline prompt, run in order in one
    working directory, with an optional acceptance command, an optional Muse pre-review, and mid-step consults.
  - `lane_status` shows the active view (live lanes plus those ended in the last 24 h, with a count of older
    lanes), one lane by id, or every lane with `all: true`.
  - `lane_summary` gives attempts, commits, acceptance output, pre-review rounds, consults, and each step's final answer.
  - `lane_stop` stops a lane.
  - `lane_resume` continues a lane whose supervisor died, from the step it recorded.
- **Panel:** `/muse` opens a pane listing your lanes: status, step/attempt, phase and its elapsed time, total
  elapsed, idle minutes (marked past 75% of the stall budget), commits with the last subject, and the last
  accept lines on failure. This session's lanes come first.
- **Wake-up:** when one of this session's lanes ends, the plugin submits its summary as a prompt. Each lane
  wakes the session that started it once, and no other session. A one-line toast names the lane and its end
  state alongside the prompt.
- **Status line:** with exactly one owned working lane the plugin pins `muse: <label> <phase>` under the
  prompt; with more it pins `muse: N running`. It clears when none remain.

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
then numbered findings with file:line); the supervisor records it as `.lane/REVIEW-<round>.md` itself.

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

## Known limits

- **A wake-up can be lost.** The announcement is recorded just before the prompt is delivered, so a plugin
  reload in that moment loses the wake-up. `lane_status` still shows the lane as finished.
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
