# muse — Muse lanes for Claude Code

A Claude Code plugin that runs Meta's Muse CLI (`muse exec`) agents as supervised background
lanes. You start a lane from a Claude session. A detached supervisor runs it to the end, retrying through outages and stalls, then runs your
acceptance command. The session gets exactly one prompt when the lane finishes, so nobody has to poll.

Claude stays the lead that plans and reviews, and Muse does the long, checkable work: a mechanical change across many files, a failing test suite, a scripted migration.

## What you get

- **Tools:**
  - `lane_start` starts a lane. A lane is one or more steps, each a brief file or inline prompt, run in order in one
    working directory, with an optional acceptance command.
  - `lane_status` lists lanes or shows one.
  - `lane_summary` gives attempts, commits, acceptance output, and each step's final answer.
  - `lane_stop` stops a lane.
  - `lane_resume` continues a lane whose supervisor died, from the step it recorded.
- **Panel:** `/muse` opens a pane listing your lanes.
- **Wake-up:** when one of this session's lanes ends, the plugin submits its summary as a prompt. Each lane
  wakes the session that started it once, and no other session.

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
2. Each step runs `muse exec --json` at reasoning effort `max` unless you pass `effort`.
3. A step counts as stalled when its event log, its git tree and its process CPU are all quiet for `stall_min`
   minutes (40 by default). A stalled attempt is killed and retried.
4. Failures are classified before any retry:

   | Failure | Handling |
   | --- | --- |
   | Stall, timeout, 429, 5xx, network error | Retried with backoff (2, 5, 10, 20, 30, 30 min), up to 6 attempts |
   | Model `failed` or `cancelled` | Retried once |
   | Authentication failure, or `muse` missing | Not retried |

5. After the last step, `accept` runs in the working directory under a 2-hour timeout. Its exit code decides
   whether the lane ends `done` or `failed`.
6. The plugin checks the runner every 20 seconds. When one of its lanes reaches a final state it records the
   announcement, then submits the summary.

The runner works without Claude too:

```bash
bin/muse-lane --help
bin/muse-lane status
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
claude plugin validate --strict .
```

`tsconfig.json` is for editors only and extends `.claude-plugin/types/`, which Claude Code's plugin tooling
generates. That folder is not committed.

## License

MIT. See [LICENSE](LICENSE). Muse is Meta's product, and this plugin is not affiliated with Meta or Anthropic.
