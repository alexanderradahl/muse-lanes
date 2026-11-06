#!/usr/bin/env python3
"""Tests for bin/muse-lane. Stdlib unittest only."""
import importlib.util
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

LANE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "muse-lane")

FAKE_MUSE = r"""#!/usr/bin/env python3
import json, os, sys, time, subprocess
_argv_file = os.environ.get("FAKE_ARGV_FILE", "")
if _argv_file:
    try:
        with open(_argv_file, "a") as _af:
            _af.write(json.dumps(sys.argv) + "\n")
    except Exception:
        pass
def get_arg(name):
    a = sys.argv
    if name in a:
        i = a.index(name)
        if i + 1 < len(a):
            return a[i+1]
    return ""
prompt_file = get_arg("--prompt-file")
mode = os.environ.get("FAKE_MODE", "complete")
def emit(text):
    obj = {"payload_type": "run.terminal.completed", "payload": {"terminal": "completed", "text": text}}
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
def emit_log():
    sys.stdout.write(json.dumps({"payload_type": "run.log", "payload": {}}) + "\n")
    sys.stdout.flush()
_base = os.path.basename(prompt_file)
if _base.startswith("consult-brief"):
    time.sleep(float(os.environ.get("FAKE_CONSULT_SLEEP", "0.1")))
    if os.environ.get("FAKE_CONSULT_NO_ANSWER", "") == "1":
        # muse 1.3 shape with no answer anywhere: one empty terminal event.
        sys.stdout.write(json.dumps({"payload_type": "run.terminal.completed", "payload": {"kind": "run_terminal", "command_id": "cmd-1", "terminal": "completed", "text": ""}}) + "\n")
        sys.stdout.flush()
        sys.exit(0)
    if os.environ.get("FAKE_CONSULT_EMPTY_TERMINAL", "") == "1":
        # muse 1.3 shape: the answer streams as output deltas but the
        # terminal event text is empty.
        _ans = os.environ.get("FAKE_CONSULT_ANSWER", "helper answer 42")
        _mid = max(1, len(_ans) // 2)
        for _chunk in (_ans[:_mid], _ans[_mid:]):
            sys.stdout.write(json.dumps({"payload_type": "run.output.delta", "payload": {"kind": "run_output_delta", "command_id": "cmd-1", "text": _chunk}}) + "\n")
        sys.stdout.write(json.dumps({"payload_type": "run.terminal.completed", "payload": {"kind": "run_terminal", "command_id": "cmd-1", "terminal": "completed", "text": ""}}) + "\n")
        sys.stdout.flush()
        sys.exit(0)
    emit(os.environ.get("FAKE_CONSULT_ANSWER", "helper answer 42"))
    sys.exit(0)
if _base.startswith("review-brief"):
    _rmode = os.environ.get("FAKE_REVIEW_MODE", "")
    if _rmode == "crash":
        sys.stderr.write("review crashed boom\n")
        sys.stderr.flush()
        time.sleep(0.1)
        sys.exit(1)
    if _rmode == "sleep":
        time.sleep(float(os.environ.get("FAKE_REVIEW_SLEEP", "30")))
        sys.exit(1)
    _verdict = os.environ.get("FAKE_REVIEW_VERDICT", "PASS")
    _fails = int(os.environ.get("FAKE_REVIEW_FAILS", "0"))
    _cf = os.environ.get("FAKE_REVIEW_COUNT_FILE", "")
    if _fails > 0 and _cf:
        _n = 0
        if os.path.exists(_cf):
            try:
                with open(_cf) as _f:
                    _n = int((_f.read() or "0").strip() or "0")
            except Exception:
                _n = 0
        _n += 1
        with open(_cf, "w") as _f:
            _f.write(str(_n))
        _verdict = "FAIL" if _n <= _fails else "PASS"
    if os.environ.get("FAKE_REVIEW_DIRTY", "") == "1":
        try:
            with open(os.environ.get("FAKE_REVIEW_DIRTY_FILE", "tracked.txt"), "a") as _df:
                _df.write("reviewer was here\n")
        except Exception as _e:
            sys.stderr.write("dirty write failed: %s\n" % _e)
    _rnd = "".join(ch for ch in _base if ch.isdigit()) or "1"
    _find = os.environ.get("FAKE_REVIEW_FINDINGS_" + _rnd, "") or os.environ.get("FAKE_REVIEW_FINDINGS", "1. main.py:10 missing check")
    time.sleep(float(os.environ.get("FAKE_SLEEP", "0.2")))
    emit(_verdict + "\n" + _find)
    sys.exit(0)
if mode == "complete":
    txt = os.environ.get("FAKE_TEXT", "hello final")
    # include some stderr noise that must be filtered from the tail
    sys.stderr.write("starting up\n")
    sys.stderr.write("example-skill: skill omitted to keep budget\n")
    sys.stderr.write("`skills_catalog` was trimmed to fit its size limit\n")
    sys.stderr.write("real error line\n")
    sys.stderr.flush()
    time.sleep(float(os.environ.get("FAKE_SLEEP", "0.2")))
    emit(txt)
    sys.exit(0)
elif mode == "fail_then_complete":
    count_file = os.environ.get("FAKE_COUNT_FILE", "")
    fails = int(os.environ.get("FAKE_FAILS", "2"))
    n = 0
    if count_file and os.path.exists(count_file):
        try:
            with open(count_file) as f:
                n = int((f.read() or "0").strip() or "0")
        except Exception:
            n = 0
    n += 1
    if count_file:
        with open(count_file, "w") as f:
            f.write(str(n))
    if n <= fails:
        emit_log()
        sys.stderr.write("fake failure attempt %d\n" % n)
        sys.stderr.flush()
        time.sleep(0.1)
        sys.exit(1)
    else:
        time.sleep(0.1)
        emit(os.environ.get("FAKE_TEXT", "recovered final"))
        sys.exit(0)
elif mode == "stall":
    # sleep silently without any output
    time.sleep(float(os.environ.get("FAKE_SLEEP", "10")))
    sys.exit(1)
elif mode == "order":
    order_file = os.environ.get("FAKE_ORDER_FILE", "")
    base = os.path.basename(prompt_file)
    content = ""
    try:
        with open(prompt_file) as f:
            content = f.read()
    except Exception:
        pass
    if order_file:
        with open(order_file, "a") as f:
            f.write(base + "\n")
    time.sleep(0.2)
    emit("final for %s: %s" % (base, content.strip()[:2000]))
    sys.exit(0)
elif mode == "envcheck":
    key = os.environ.get("FAKE_ENV_KEY", "MY_SECRET")
    val = os.environ.get(key, "")
    recv = os.environ.get("FAKE_RECEIVED_FILE", "")
    if recv:
        with open(recv, "w") as f:
            f.write(val)
    sys.stderr.write("stderr leak: %s\n" % val)
    sys.stderr.flush()
    time.sleep(0.1)
    emit("final leak: %s done" % val)
    sys.exit(0)
elif mode == "gitcommit":
    # make one commit in cwd, then complete
    nfile = os.environ.get("FAKE_COMMIT_FILE", "lane-made.txt")
    try:
        with open(nfile, "a") as f:
            f.write("work %s\n" % time.time())
        subprocess.run(["git", "add", nfile], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        subprocess.run(["git", "commit", "-m", "lane work %s" % time.time()],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except Exception as e:
        sys.stderr.write("commit failed: %s\n" % e)
    time.sleep(0.2)
    emit(os.environ.get("FAKE_TEXT", "git done"))
    sys.exit(0)
elif mode == "sleeper":
    time.sleep(float(os.environ.get("FAKE_SLEEP", "30")))
    emit("sleeper done")
    sys.exit(0)
elif mode == "sleep_complete":
    time.sleep(float(os.environ.get("FAKE_SLEEP", "2")))
    emit(os.environ.get("FAKE_TEXT", "slow final"))
    sys.exit(0)
elif mode == "trailing":
    txt = os.environ.get("FAKE_TEXT", "trailing final")
    time.sleep(float(os.environ.get("FAKE_SLEEP", "0.2")))
    sys.stdout.write(json.dumps({"payload_type": "run.terminal.completed", "payload": {"kind": "run_terminal", "command_id": "cmd-1", "terminal": "completed", "text": txt}}) + "\n")
    sys.stdout.flush()
    sys.stdout.write(json.dumps({"payload_type": "session.workspace_branch.observed", "payload": {"kind": "workspace_branch", "command_id": "cmd-1"}}) + "\n")
    sys.stdout.flush()
    sys.exit(0)
elif mode == "authfail":
    sys.stderr.write("Error: 401 Unauthorized - invalid api key\n")
    sys.stderr.flush()
    time.sleep(0.1)
    sys.stdout.write(json.dumps({"payload_type": "run.terminal.failed", "payload": {"kind": "run_terminal", "command_id": "cmd-1", "terminal": "failed", "reason": "401 Unauthorized", "text": ""}}) + "\n")
    sys.stdout.flush()
    sys.exit(1)
elif mode == "model_failed":
    time.sleep(0.1)
    sys.stdout.write(json.dumps({"payload_type": "run.terminal.failed", "payload": {"kind": "run_terminal", "terminal": "failed", "reason": "model refused", "text": ""}}) + "\n")
    sys.stdout.flush()
    sys.exit(1)
elif mode == "complete_then_hang":
    time.sleep(0.2)
    emit(os.environ.get("FAKE_TEXT", "hung final"))
    time.sleep(float(os.environ.get("FAKE_SLEEP", "30")))
    sys.exit(0)
elif mode == "ask":
    _count = int(os.environ.get("FAKE_ASK_COUNT", "1"))
    _wait = float(os.environ.get("FAKE_ASK_WAIT", "25"))
    try:
        os.makedirs(".lane", exist_ok=True)
    except Exception:
        pass
    _got = []
    for _i in range(1, _count + 1):
        try:
            os.remove(".lane/ANSWER.md")
        except Exception:
            pass
        with open(".lane/ASK.md", "w") as _f:
            _f.write("Question %d: how to test?\nPaths: foo.py\n" % _i)
        _ans = ""
        _dead = time.time() + _wait
        while time.time() < _dead:
            if os.path.exists(".lane/ANSWER.md"):
                try:
                    with open(".lane/ANSWER.md") as _f:
                        _ans = _f.read()
                except Exception:
                    pass
                if _ans.strip():
                    break
            time.sleep(0.1)
        _got.append((_ans.strip()[:80] or "NO-ANSWER"))
        if _i < _count:
            time.sleep(float(os.environ.get("FAKE_ASK_GAP", "0")))
    emit("ask final; answers=%s" % ("|".join(_got)))
    sys.exit(0)
elif mode == "writescope":
    try:
        os.makedirs(".lane", exist_ok=True)
    except Exception:
        pass
    try:
        with open(".lane/ASK.md", "w") as _f:
            _f.write("Scope step question: is this file fine?\n")
    except Exception:
        pass
    try:
        os.makedirs("allowed", exist_ok=True)
        with open("allowed/note.txt", "w") as _f:
            _f.write("in scope work\n")
    except Exception:
        pass
    time.sleep(float(os.environ.get("FAKE_SLEEP", "0.2")))
    emit(os.environ.get("FAKE_TEXT", "scope files written"))
    sys.exit(0)
else:
    emit("default final")
    sys.exit(0)
"""

FAKE_CLAUDE = r"""#!/usr/bin/env python3
import json, os, sys, time
_argv_file = os.environ.get("FAKE_ARGV_FILE", "")
if _argv_file:
    try:
        with open(_argv_file, "a") as _af:
            _af.write(json.dumps(sys.argv) + "\n")
    except Exception:
        pass
try:
    _prompt = sys.stdin.read()
except Exception:
    _prompt = ""
_prompt_file = os.environ.get("FAKE_CLAUDE_PROMPT_FILE", "")
if _prompt_file:
    try:
        with open(_prompt_file, "w") as _pf:
            _pf.write(_prompt)
    except Exception:
        pass
time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP", "0.1")))
if os.environ.get("FAKE_CLAUDE_DIRTY", "") == "1":
    try:
        with open(os.environ.get("FAKE_CLAUDE_DIRTY_FILE", "tracked.txt"), "a") as _df:
            _df.write("advisor was here\n")
    except Exception as _e:
        sys.stderr.write("dirty write failed: %s\n" % _e)
try:
    _n = int(os.environ.get("FAKE_CLAUDE_ANSWER_LEN", "0") or "0")
except Exception:
    _n = 0
if _n > 0:
    _ans = "A" * _n
else:
    _ans = os.environ.get("FAKE_CLAUDE_ANSWER", "claude answer 7")
sys.stdout.write(_ans)
sys.stdout.flush()
sys.exit(int(os.environ.get("FAKE_CLAUDE_EXIT", "0") or "0"))
"""


class LaneBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.lanes = os.path.join(self.root, "lanes")
        os.makedirs(self.lanes, exist_ok=True)
        self.cwd = os.path.join(self.root, "cwd")
        os.makedirs(self.cwd, exist_ok=True)
        self.fakebin = os.path.join(self.root, "fakebin")
        os.makedirs(self.fakebin, exist_ok=True)
        self.fake_muse = os.path.join(self.fakebin, "muse")
        with open(self.fake_muse, "w") as f:
            f.write(FAKE_MUSE)
        os.chmod(self.fake_muse, 0o755)
        self.fake_claude = os.path.join(self.fakebin, "claude")
        with open(self.fake_claude, "w") as f:
            f.write(FAKE_CLAUDE)
        os.chmod(self.fake_claude, 0o755)
        self.state_dir = os.path.join(self.root, "state")
        os.makedirs(self.state_dir, exist_ok=True)
        self.base_env = dict(os.environ)
        self.base_env["MUSE_LANES_ROOT"] = self.lanes
        self.base_env["MUSE_BIN"] = self.fake_muse
        self.base_env["MUSE_LANE_POLL_SEC"] = "0.2"
        self.base_env["MUSE_LANE_BACKOFF"] = "0.2,0.2,0.2,0.2,0.2,0.2"
        # default stall: generous unless a test overrides
        self.base_env["MUSE_LANE_STALL_SEC"] = "30"
        self._lanes_started = []

    def tearDown(self):
        # Best-effort kill of any supervisors / children left behind.
        try:
            if os.path.isdir(self.lanes):
                for lid in os.listdir(self.lanes):
                    sp = os.path.join(self.lanes, lid, "state.json")
                    try:
                        with open(sp) as f:
                            st = json.load(f)
                    except Exception:
                        continue
                    for k in ("supervisor_pid", "muse_pid", "accept_pid"):
                        pid = st.get(k)
                        if not pid:
                            continue
                        try:
                            os.killpg(int(pid), signal.SIGKILL)
                        except Exception:
                            pass
                        try:
                            os.kill(int(pid), signal.SIGKILL)
                        except Exception:
                            pass
        except Exception:
            pass
        time.sleep(0.2)
        try:
            self.tmp.cleanup()
        except Exception:
            pass

    def run_lane(self, *args, env_extra=None, timeout=30):
        env = dict(self.base_env)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, LANE] + list(args),
            env=env, capture_output=True, text=True, timeout=timeout,
        )

    def write_brief(self, name, content):
        p = os.path.join(self.root, name)
        with open(p, "w") as f:
            f.write(content)
        return p

    def start_lane(self, briefs, env_extra=None, **kwargs):
        cmd = ["start", "--cwd", self.cwd]
        for b in briefs:
            cmd += ["--brief", b]
        if kwargs.get("id"):
            cmd += ["--id", kwargs["id"]]
        if kwargs.get("label"):
            cmd += ["--label", kwargs["label"]]
        if kwargs.get("accept"):
            cmd += ["--accept", kwargs["accept"]]
        if kwargs.get("effort"):
            cmd += ["--effort", kwargs["effort"]]
        if kwargs.get("env_file"):
            cmd += ["--env-file", kwargs["env_file"]]
        if kwargs.get("accept_env"):
            cmd += ["--accept-env"]
        if kwargs.get("stall_min") is not None:
            cmd += ["--stall-min", str(kwargs["stall_min"])]
        if kwargs.get("owner_session"):
            cmd += ["--owner-session", kwargs["owner_session"]]
        if kwargs.get("review"):
            cmd += ["--review"]
        if kwargs.get("review_rounds") is not None:
            cmd += ["--review-rounds", str(kwargs["review_rounds"])]
        if kwargs.get("review_brief"):
            cmd += ["--review-brief", kwargs["review_brief"]]
        if kwargs.get("consult_max") is not None:
            cmd += ["--consult-max", str(kwargs["consult_max"])]
        if kwargs.get("consult_timeout_min") is not None:
            cmd += ["--consult-timeout-min", str(kwargs["consult_timeout_min"])]
        for sc in (kwargs.get("scope") or []):
            cmd += ["--scope", sc]
        if kwargs.get("box"):
            cmd += ["--box", kwargs["box"]]
        if kwargs.get("advisor_model"):
            cmd += ["--advisor-model", kwargs["advisor_model"]]
        if kwargs.get("advisor_max") is not None:
            cmd += ["--advisor-max", str(kwargs["advisor_max"])]
        r = self.run_lane(*cmd, env_extra=env_extra)
        self.assertEqual(r.returncode, 0, "start failed: %s %s" % (r.stdout, r.stderr))
        lid = r.stdout.strip().splitlines()[-1].strip()
        self.assertTrue(lid)
        self._lanes_started.append(lid)
        return lid

    def lane_path(self, lid, *parts):
        return os.path.join(self.lanes, lid, *parts)

    def read_state(self, lid):
        with open(self.lane_path(lid, "state.json")) as f:
            return json.load(f)

    def read_lane(self, lid):
        with open(self.lane_path(lid, "lane.json")) as f:
            return json.load(f)

    def status_obj(self, lid):
        r = self.run_lane("status", lid, "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)[0]

    def init_git_repo(self):
        subprocess.run(["git", "init"], cwd=self.cwd, capture_output=True,
                       timeout=15, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=self.cwd,
                       capture_output=True, timeout=15)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.cwd,
                       capture_output=True, timeout=15)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.cwd,
                       capture_output=True, timeout=15)
        subprocess.run(["git", "config", "init.defaultBranch", "main"], cwd=self.cwd,
                       capture_output=True, timeout=15)
        with open(os.path.join(self.cwd, "seed.txt"), "w") as f:
            f.write("seed\n")
        subprocess.run(["git", "add", "."], cwd=self.cwd, capture_output=True,
                       timeout=15, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.cwd,
                       capture_output=True, timeout=15, check=True)

    def wait_status(self, lid, want, timeout=30):
        if isinstance(want, str):
            want = {want}
        else:
            want = set(want)
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                with open(self.lane_path(lid, "state.json")) as f:
                    st = json.load(f)
                last = st.get("status")
                if last in want:
                    return st
            except FileNotFoundError:
                pass
            except (OSError, ValueError):
                pass
            time.sleep(0.15)
        self.fail("lane %s never reached %s (last=%s)" % (lid, want, last))

    def wait_file(self, path, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.exists(path):
                return True
            time.sleep(0.15)
        self.fail("file never appeared: %s" % path)

    def wait_state_field(self, lid, field, want, timeout=15):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                last = self.read_state(lid).get(field)
            except (FileNotFoundError, OSError, ValueError):
                last = None
            if last == want:
                return last
            time.sleep(0.1)
        self.fail("lane %s field %s never became %r (last=%r)" % (
            lid, field, want, last))

    def assert_no_secret_in_lane(self, lid, secret):
        ldir = os.path.join(self.lanes, lid)
        bad = []
        for dirpath, _, files in os.walk(ldir):
            for fn in files:
                # brief copies are verbatim user input; the secret lives in the
                # env file, not in briefs, so skip them for this check.
                if fn.startswith("brief"):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except OSError:
                    continue
                if secret and secret in content:
                    bad.append(fp)
        self.assertEqual(bad, [], "secret leaked into lane files: %s" % bad)


class TestCompletes(LaneBase):
    def test_completes_done(self):
        b = self.write_brief("b1.md", "do the thing")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete", "FAKE_TEXT": "FINAL-ONE-42"})
        st = self.wait_status(lid, "done", timeout=20)
        self.wait_file(self.lane_path(lid, "summary.md"), timeout=10)
        st = self.read_state(lid)
        self.assertEqual(st["status"], "done")
        with open(self.lane_path(lid, "step1-final.md")) as f:
            final = f.read()
        self.assertIn("FINAL-ONE-42", final)
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("FINAL-ONE-42", summ)
        self.assertIn("done", summ)
        # stderr tail filtering: noisy lines dropped
        tail = st.get("stderr_tail") or ""
        self.assertNotIn("skill omitted", tail)
        self.assertNotIn("was trimmed to fit", tail)
        self.assertIn("real error line", tail)


class TestRetryThenComplete(LaneBase):
    def test_fails_twice_then_completes(self):
        count = os.path.join(self.state_dir, "count")
        b = self.write_brief("b1.md", "flaky work")
        lid = self.start_lane([b], env_extra={
            "FAKE_MODE": "fail_then_complete", "FAKE_COUNT_FILE": count,
            "FAKE_FAILS": "2", "FAKE_TEXT": "RECOVERED-99",
        })
        st = self.wait_status(lid, "done", timeout=25)
        self.wait_file(self.lane_path(lid, "summary.md"), timeout=10)
        st = self.read_state(lid)
        self.assertEqual(st["attempt"], 3)
        with open(self.lane_path(lid, "step1-final.md")) as f:
            self.assertIn("RECOVERED-99", f.read())
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("RECOVERED-99", summ)
        self.assertIn("attempt 1", summ)
        self.assertIn("attempt 3", summ)
        self.assertIn("exit 1", summ)


class TestStallGaveUp(LaneBase):
    def test_every_attempt_stalls_gives_up(self):
        b = self.write_brief("b1.md", "stall forever")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "stall", "FAKE_SLEEP": "10",
                                              "MUSE_LANE_STALL_SEC": "1"})
        st = self.wait_status(lid, "gave_up", timeout=40)
        self.wait_file(self.lane_path(lid, "summary.md"), timeout=10)
        st = self.read_state(lid)
        self.assertEqual(st["status"], "gave_up")
        self.assertEqual(st["attempt"], 6)
        self.assertEqual(st.get("reason"), "stalled")
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("stalled", summ)
        self.assertIn("gave_up", summ)
        # all six attempt files exist
        for n in range(1, 7):
            self.assertTrue(os.path.exists(self.lane_path(lid, "step1-attempt%d.jsonl" % n)))


class TestTwoBriefsChained(LaneBase):
    def test_two_briefs_run_in_order(self):
        order = os.path.join(self.state_dir, "order.log")
        b1 = self.write_brief("b1.md", "FIRST-BRIEF-CONTENT-AAA")
        b2 = self.write_brief("b2.md", "SECOND-BRIEF-CONTENT-BBB")
        lid = self.start_lane([b1, b2], env_extra={"FAKE_MODE": "order", "FAKE_ORDER_FILE": order})
        st = self.wait_status(lid, "done", timeout=20)
        self.wait_file(self.lane_path(lid, "summary.md"), timeout=10)
        st = self.read_state(lid)
        self.assertEqual(st["steps"], 2)
        with open(self.lane_path(lid, "step1-final.md")) as f:
            f1 = f.read()
        with open(self.lane_path(lid, "step2-final.md")) as f:
            f2 = f.read()
        self.assertIn("FIRST-BRIEF-CONTENT-AAA", f1)
        self.assertIn("SECOND-BRIEF-CONTENT-BBB", f2)
        with open(order) as f:
            lines = [l.strip() for l in f.read().splitlines() if l.strip()]
        self.assertEqual(lines, ["brief1.md", "brief2.md"])
        # briefs were copied: editing the source must not change the running lane
        with open(b1, "w") as f:
            f.write("EDITED-AFTER-START")
        with open(self.lane_path(lid, "brief1.md")) as f:
            self.assertIn("FIRST-BRIEF-CONTENT-AAA", f.read())


class TestAcceptFails(LaneBase):
    def test_accept_exit_1_failed(self):
        b = self.write_brief("b1.md", "work ok")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete", "FAKE_TEXT": "work done"},
                              accept="echo ACCEPT_TAIL_MARKER_123; echo second line; exit 1")
        st = self.wait_status(lid, "failed", timeout=20)
        self.wait_file(self.lane_path(lid, "summary.md"), timeout=10)
        st = self.read_state(lid)
        self.assertEqual(st["accept_exit"], 1)
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("ACCEPT_TAIL_MARKER_123", summ)
        self.assertIn("failed", summ)
        with open(self.lane_path(lid, "accept.log")) as f:
            self.assertIn("ACCEPT_TAIL_MARKER_123", f.read())


class TestStop(LaneBase):
    def test_stop_while_running(self):
        b = self.write_brief("b1.md", "long work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60"})
        st = self.wait_status(lid, {"running", "retry_wait"}, timeout=15)
        sup = st.get("supervisor_pid")
        mus = st.get("muse_pid")
        self.assertTrue(sup)
        r = self.run_lane("stop", lid)
        self.assertEqual(r.returncode, 0, "stop failed: %s %s" % (r.stdout, r.stderr))
        st2 = self.wait_status(lid, "stopped", timeout=20)
        self.assertEqual(st2["status"], "stopped")
        self.assertTrue(os.path.exists(self.lane_path(lid, "summary.md")))
        time.sleep(0.5)
        for pid in (sup, mus):
            if not pid:
                continue
            with self.assertRaises(OSError):
                os.kill(int(pid), 0)


class TestEnvSecrets(LaneBase):
    def test_secret_redacted_but_received(self):
        secret = "s3cr3t-xyz-UNIQUE-7890"
        envf = os.path.join(self.root, "test.env")
        with open(envf, "w") as f:
            f.write("# comment\n\nexport MY_SECRET=\"%s\"\nOTHER=plain\n" % secret)
        received = os.path.join(self.state_dir, "received")
        b = self.write_brief("b1.md", "use env")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "envcheck", "FAKE_ENV_KEY": "MY_SECRET",
                                              "FAKE_RECEIVED_FILE": received},
                              env_file=envf)
        self.wait_status(lid, "done", timeout=20)
        self.wait_file(self.lane_path(lid, "summary.md"), timeout=10)
        # fake muse did receive the secret in its environment
        with open(received) as f:
            self.assertEqual(f.read(), secret)
        # ...but it never appears in any file under the lanes root
        self.assert_no_secret_in_lane(lid, secret)
        # lane.json holds the env file path, never its contents
        with open(self.lane_path(lid, "lane.json")) as f:
            self.assertNotIn(secret, f.read())
        # status and summary output are clean too
        r = self.run_lane("status", lid, "--json")
        self.assertNotIn(secret, r.stdout)
        r2 = self.run_lane("summary", lid)
        self.assertNotIn(secret, r2.stdout)
        self.assertIn("***", r2.stdout)


class TestOrphanedResume(LaneBase):
    def test_orphaned_and_resume_kills_live_orphan(self):
        b = self.write_brief("b1.md", "slow work")
        start_env = {"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60",
                     "MUSE_LANE_STALL_SEC": "60"}
        lid = self.start_lane([b], env_extra=start_env)
        # Wait until a muse child is recorded and alive.
        mus = None
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                st = self.read_state(lid)
            except (FileNotFoundError, OSError, ValueError):
                time.sleep(0.15)
                continue
            mus = st.get("muse_pid")
            if mus:
                try:
                    os.kill(int(mus), 0)
                    break
                except OSError:
                    mus = None
            time.sleep(0.15)
        self.assertTrue(mus, "no live muse child recorded")
        st = self.read_state(lid)
        sup = st.get("supervisor_pid")
        mus_started = st.get("muse_started")
        self.assertTrue(sup)
        self.assertTrue(mus_started, "muse start time not recorded")
        os.kill(int(sup), signal.SIGKILL)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(int(sup), 0)
                time.sleep(0.1)
            except OSError:
                break
        # Leave the old muse running: resume must kill it (verified by
        # start time) before attempt N+1 starts.
        try:
            os.kill(int(mus), 0)
        except OSError:
            self.fail("orphaned muse died on its own; test not deterministic")
        time.sleep(0.5)
        r = self.run_lane("status", lid, "--json")
        self.assertEqual(r.returncode, 0)
        objs = json.loads(r.stdout)
        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0]["status"], "orphaned")
        resume_env = {"FAKE_MODE": "complete", "FAKE_TEXT": "RESUMED-FINAL-7"}
        r2 = self.run_lane("resume", lid, env_extra=resume_env)
        self.assertEqual(r2.returncode, 0, "resume failed: %s %s" % (r2.stdout, r2.stderr))
        # Old orphan must be dead now.
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(int(mus), 0)
                time.sleep(0.1)
            except OSError:
                break
        with self.assertRaises(OSError):
            os.kill(int(mus), 0)
        st2 = self.wait_status(lid, "done", timeout=25)
        self.assertTrue(os.path.exists(self.lane_path(lid, "summary.md")))
        st2 = self.read_state(lid)
        self.assertEqual(st2["status"], "done")
        with open(self.lane_path(lid, "step1-final.md")) as f:
            self.assertIn("RESUMED-FINAL-7", f.read())
        self.assertGreaterEqual(st2["attempt"], 2)
        # Status right after resume must never report orphaned (lock wait).
        # Re-check: resume on a live lane must refuse.
        b2 = self.write_brief("b2.md", "live work")
        lid2 = self.start_lane([b2], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "30"})
        self.wait_status(lid2, {"running", "retry_wait"}, timeout=15)
        r3 = self.run_lane("resume", lid2)
        self.assertNotEqual(r3.returncode, 0)
        self.assertIn("still alive", (r3.stderr or "") + (r3.stdout or ""))


class TestGitCommits(LaneBase):
    def test_commits_counted(self):
        # fresh git repo as cwd
        subprocess.run(["git", "init"], cwd=self.cwd, capture_output=True, timeout=15, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=self.cwd, capture_output=True, timeout=15)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.cwd, capture_output=True, timeout=15)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.cwd, capture_output=True, timeout=15)
        with open(os.path.join(self.cwd, "init.txt"), "w") as f:
            f.write("init\n")
        subprocess.run(["git", "add", "."], cwd=self.cwd, capture_output=True, timeout=15, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.cwd, capture_output=True, timeout=15, check=True)
        b = self.write_brief("b1.md", "make commits")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "gitcommit", "FAKE_TEXT": "GIT-FINAL-1"})
        st = self.wait_status(lid, "done", timeout=20)
        self.wait_file(self.lane_path(lid, "summary.md"), timeout=10)
        st = self.read_state(lid)
        self.assertGreaterEqual(st.get("commits", 0), 1)
        self.assertIsNotNone(st.get("head_start"))
        self.assertIsNotNone(st.get("head"))
        self.assertNotEqual(st.get("head_start"), st.get("head"))
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("lane work", summ)


def _load_lane_module():
    import importlib.machinery
    loader = importlib.machinery.SourceFileLoader("muse_lane", LANE)
    spec = importlib.util.spec_from_loader("muse_lane", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestTrailingCompletion(LaneBase):
    def test_trailing_event_after_completed_counts_as_done(self):
        mod = _load_lane_module()
        fx = os.path.join(self.state_dir, "trailing.jsonl")
        with open(fx, "w") as f:
            f.write(json.dumps({"payload_type": "run.terminal.completed",
                                "payload": {"kind": "run_terminal", "command_id": "c1",
                                            "terminal": "completed", "text": "TRAIL-FINAL"}}) + "\n")
            f.write(json.dumps({"payload_type": "session.workspace_branch.observed",
                                "payload": {"kind": "workspace_branch", "command_id": "c1"}}) + "\n")
        ok, text = mod.check_completion(fx)
        self.assertTrue(ok)
        self.assertIn("TRAIL-FINAL", text)
        v = mod.get_terminal_verdict(fx)
        self.assertEqual(v.get("terminal"), "completed")
        self.assertTrue(v.get("has_event"))
        # Last run_terminal event wins.
        fx2 = os.path.join(self.state_dir, "two-term.jsonl")
        with open(fx2, "w") as f:
            f.write(json.dumps({"payload_type": "run.terminal.completed",
                                "payload": {"kind": "run_terminal", "terminal": "completed",
                                            "text": "first"}}) + "\n")
            f.write(json.dumps({"payload_type": "run.terminal.failed",
                                "payload": {"kind": "run_terminal", "terminal": "failed",
                                            "reason": "later wins", "text": ""}}) + "\n")
        v2 = mod.get_terminal_verdict(fx2)
        self.assertEqual(v2.get("terminal"), "failed")
        self.assertIn("later wins", v2.get("reason"))
        ok2, _ = mod.check_completion(fx2)
        self.assertFalse(ok2)

    def test_e2e_trailing_fake_completes_without_retry(self):
        b = self.write_brief("b1.md", "trailing work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "trailing",
                                              "FAKE_TEXT": "TRAIL-E2E-5"})
        st = self.wait_status(lid, "done", timeout=20)
        self.assertTrue(os.path.exists(self.lane_path(lid, "summary.md")))
        st = self.read_state(lid)
        self.assertEqual(st["status"], "done")
        self.assertEqual(st["attempt"], 1)
        with open(self.lane_path(lid, "step1-final.md")) as f:
            self.assertIn("TRAIL-E2E-5", f.read())
        with open(self.lane_path(lid, "history.json")) as f:
            hist = json.load(f)
        self.assertEqual(hist["1"][0].get("terminal"), "completed")


class TestFinalTextExtraction(LaneBase):
    def _write(self, name, objs):
        fx = os.path.join(self.state_dir, name)
        with open(fx, "w") as f:
            for o in objs:
                f.write(json.dumps(o) + "\n")
        return fx

    def _term(self, text, cmd="c1"):
        return {"payload_type": "run.terminal.completed",
                "payload": {"kind": "run_terminal", "command_id": cmd,
                            "terminal": "completed", "text": text}}

    def _delta(self, text, cmd="c1"):
        return {"payload_type": "run.output.delta",
                "payload": {"kind": "run_output_delta", "command_id": cmd,
                            "text": text}}

    def test_stray_empty_terminal_does_not_hide_answer(self):
        mod = _load_lane_module()
        fx = self._write("stray.jsonl", [self._term("REAL-ANSWER", "main"),
                                         self._term("", "stray")])
        self.assertEqual(mod.get_final_text(fx), "REAL-ANSWER")
        ok, text = mod.check_completion(fx)
        self.assertTrue(ok)
        self.assertEqual(text, "REAL-ANSWER")

    def test_empty_terminal_falls_back_to_deltas(self):
        mod = _load_lane_module()
        fx = self._write("deltas.jsonl", [self._delta("DELTA-"),
                                          self._delta("ANSWER-53"),
                                          self._term("")])
        self.assertEqual(mod.get_final_text(fx), "DELTA-ANSWER-53")
        ok, text = mod.check_completion(fx)
        self.assertTrue(ok)
        self.assertEqual(text, "DELTA-ANSWER-53")

    def test_no_text_anywhere_is_empty(self):
        mod = _load_lane_module()
        fx = self._write("empty.jsonl", [self._term("")])
        self.assertEqual(mod.get_final_text(fx), "")
        ok, text = mod.check_completion(fx)
        self.assertTrue(ok)
        self.assertEqual(text, "")


class TestSupervisorLock(LaneBase):
    def test_lock_liveness_and_resume_refuses_when_live(self):
        import fcntl
        b = self.write_brief("b1.md", "lock work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "30"})
        self.wait_status(lid, {"running", "retry_wait"}, timeout=15)
        ldir = os.path.join(self.lanes, lid)
        # Lock must be held by the supervisor: non-blocking flock fails.
        fd = os.open(os.path.join(ldir, "supervisor.lock"), os.O_RDWR)
        try:
            with self.assertRaises((BlockingIOError, OSError)):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
        # Resume refuses while the lock is held.
        r = self.run_lane("resume", lid)
        self.assertNotEqual(r.returncode, 0)
        # Kill supervisor -> lock free -> orphaned.
        st = self.read_state(lid)
        os.kill(int(st["supervisor_pid"]), signal.SIGKILL)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(int(st["supervisor_pid"]), 0)
                time.sleep(0.1)
            except OSError:
                break
        time.sleep(0.5)
        r2 = self.run_lane("status", lid, "--json")
        self.assertEqual(json.loads(r2.stdout)[0]["status"], "orphaned")
        # Resume returns only after the new supervisor holds the lock, so a
        # status right after resume never reports orphaned.
        r3 = self.run_lane("resume", lid, env_extra={"FAKE_MODE": "sleeper",
                                                     "FAKE_SLEEP": "30"})
        self.assertEqual(r3.returncode, 0, r3.stderr)
        r4 = self.run_lane("status", lid, "--json")
        self.assertNotEqual(json.loads(r4.stdout)[0]["status"], "orphaned")


class TestStopDuringAcceptance(LaneBase):
    def test_stop_kills_acceptance_child(self):
        b = self.write_brief("b1.md", "accept work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "FAKE_TEXT": "acc done"},
                              accept="sleep 60")
        # Wait for accepting with a recorded accept pid.
        apid = None
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                st = self.read_state(lid)
            except (FileNotFoundError, OSError, ValueError):
                time.sleep(0.15)
                continue
            if st.get("status") == "accepting" and st.get("accept_pid"):
                apid = st.get("accept_pid")
                try:
                    os.kill(int(apid), 0)
                    break
                except OSError:
                    apid = None
            time.sleep(0.15)
        self.assertTrue(apid, "no live accept child recorded: %s" % (st,))
        self.assertTrue(st.get("accept_started"))
        r = self.run_lane("stop", lid)
        self.assertEqual(r.returncode, 0, r.stderr)
        st2 = self.wait_status(lid, "stopped", timeout=20)
        self.assertTrue(os.path.exists(self.lane_path(lid, "summary.md")))
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(int(apid), 0)
                time.sleep(0.1)
            except OSError:
                break
        with self.assertRaises(OSError):
            os.kill(int(apid), 0)


class TestStartStopRace(LaneBase):
    def test_start_writes_queued_before_spawn(self):
        b = self.write_brief("b1.md", "queued work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "30"})
        # state.json must exist immediately after start returns.
        sp = self.lane_path(lid, "state.json")
        self.assertTrue(os.path.exists(sp))
        with open(sp) as f:
            st = json.load(f)
        self.assertIn(st.get("status"), ("queued", "running", "retry_wait"))

    def test_stop_without_supervisor_writes_marker_and_stopped(self):
        b = self.write_brief("b1.md", "race work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "30"})
        self.wait_status(lid, {"running", "retry_wait"}, timeout=15)
        st = self.read_state(lid)
        os.kill(int(st["supervisor_pid"]), signal.SIGKILL)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(int(st["supervisor_pid"]), 0)
                time.sleep(0.1)
            except OSError:
                break
        time.sleep(0.5)
        r = self.run_lane("stop", lid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(self.lane_path(lid, "stop.requested")))
        st2 = self.read_state(lid)
        self.assertEqual(st2["status"], "stopped")
        self.assertTrue(os.path.exists(self.lane_path(lid, "summary.md")))


class TestAuthGaveUp(LaneBase):
    def test_auth_error_gives_up_without_backoff(self):
        b = self.write_brief("b1.md", "auth work")
        t0 = time.monotonic()
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "authfail",
                                              "MUSE_LANE_BACKOFF": "30,30,30,30,30,30"})
        st = self.wait_status(lid, "gave_up", timeout=20)
        dt = time.monotonic() - t0
        self.assertLess(dt, 15.0, "auth failure waited for backoff")
        st = self.read_state(lid)
        self.assertEqual(st["attempt"], 1)
        with open(self.lane_path(lid, "history.json")) as f:
            hist = json.load(f)
        e = hist["1"][0]
        self.assertEqual(e.get("class"), "fatal")
        self.assertIn("401", e.get("reason") or "")
        self.assertTrue(os.path.exists(self.lane_path(lid, "summary.md")))


class TestSummaryOrdering(LaneBase):
    def test_summary_exists_when_terminal_appears_and_has_attempt_details(self):
        b = self.write_brief("b1.md", "summary work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "FAKE_TEXT": "SUM-1"})
        # Poll fast; the first terminal observation must already have a summary.
        deadline = time.time() + 20
        seen_terminal = None
        summary_present = False
        while time.time() < deadline:
            try:
                with open(self.lane_path(lid, "state.json")) as f:
                    st = json.load(f)
            except (FileNotFoundError, OSError, ValueError):
                time.sleep(0.05)
                continue
            if st.get("status") in ("done", "failed", "gave_up", "stopped"):
                seen_terminal = st.get("status")
                summary_present = os.path.exists(self.lane_path(lid, "summary.md"))
                break
            time.sleep(0.05)
        self.assertEqual(seen_terminal, "done")
        self.assertTrue(summary_present, "terminal state appeared before summary.md")
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("exit=", summ)
        self.assertIn("terminal=", summ)
        self.assertIn("class=", summ)
        self.assertIn("Final stderr", summ)


class TestRedactionShortValues(LaneBase):
    def test_short_values_kept_json_valid_long_key_redacted(self):
        long_key = "LONG-FAKE-KEY-abcdef-1234567890"
        envf = os.path.join(self.root, "t.env")
        with open(envf, "w") as f:
            f.write("DEBUG=1\nMY_SECRET=%s\n" % long_key)
        received = os.path.join(self.state_dir, "received2")
        b = self.write_brief("b1.md", "redact work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "envcheck",
                                              "FAKE_ENV_KEY": "MY_SECRET",
                                              "FAKE_RECEIVED_FILE": received},
                              env_file=envf)
        self.wait_status(lid, "done", timeout=20)
        self.assertTrue(os.path.exists(self.lane_path(lid, "summary.md")))
        with open(received) as f:
            self.assertEqual(f.read(), long_key)
        # state.json stays parseable (short "1" must not be redacted).
        with open(self.lane_path(lid, "state.json")) as f:
            st = json.load(f)
        self.assertEqual(st["status"], "done")
        # Long key never appears in any lane file.
        self.assert_no_secret_in_lane(lid, long_key)
        r = self.run_lane("status", lid, "--json")
        self.assertNotIn(long_key, r.stdout)
        json.loads(r.stdout)


class TestLanePerms(LaneBase):
    def test_lane_dir_0700_files_0600(self):
        b = self.write_brief("b1.md", "perms work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"})
        self.wait_status(lid, "done", timeout=20)
        ldir = os.path.join(self.lanes, lid)
        self.assertEqual(stat.S_IMODE(os.stat(ldir).st_mode), 0o700)
        for fn in ("lane.json", "state.json", "history.json", "summary.md",
                   "brief1.md", "step1-final.md", "step1-attempt1.jsonl",
                   "step1-attempt1.err", "supervisor.log", "supervisor.lock"):
            fp = os.path.join(ldir, fn)
            if os.path.exists(fp):
                self.assertEqual(stat.S_IMODE(os.stat(fp).st_mode), 0o600, fn)


class TestAcceptEnv(LaneBase):
    def test_acceptance_gets_no_env_without_flag(self):
        secret = "ACCEPT-SECRET-fake-9876543210"
        envf = os.path.join(self.root, "a.env")
        with open(envf, "w") as f:
            f.write("MY_SECRET=%s\n" % secret)
        recv = os.path.join(self.state_dir, "accept-recv")
        b = self.write_brief("b1.md", "accept env work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              env_file=envf,
                              accept="echo -n \"$MY_SECRET\" > %s; exit 0" % recv)
        self.wait_status(lid, "done", timeout=20)
        with open(recv) as f:
            self.assertEqual(f.read(), "")

    def test_acceptance_gets_env_with_flag(self):
        secret = "ACCEPT-SECRET-fake-0123456789"
        envf = os.path.join(self.root, "a2.env")
        with open(envf, "w") as f:
            f.write("MY_SECRET=%s\n" % secret)
        recv = os.path.join(self.state_dir, "accept-recv2")
        b = self.write_brief("b1.md", "accept env work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              env_file=envf, accept_env=True,
                              accept="echo -n \"$MY_SECRET\" > %s; exit 0" % recv)
        self.wait_status(lid, "done", timeout=20)
        with open(recv) as f:
            self.assertEqual(f.read(), secret)


class TestResumeEnv(LaneBase):
    def test_resumed_supervisor_uses_stored_muse_bin(self):
        b = self.write_brief("b1.md", "resume env work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "30"})
        self.wait_status(lid, {"running", "retry_wait"}, timeout=15)
        st = self.read_state(lid)
        os.kill(int(st["supervisor_pid"]), signal.SIGKILL)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(int(st["supervisor_pid"]), 0)
                time.sleep(0.1)
            except OSError:
                break
        time.sleep(0.5)
        # Resumer offers a bogus MUSE_BIN; the resumed supervisor must use
        # the stored one and still complete.
        r = self.run_lane("resume", lid, env_extra={"MUSE_BIN": "/nonexistent-muse",
                                                    "FAKE_MODE": "complete",
                                                    "FAKE_TEXT": "RESUME-ENV-OK"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.wait_status(lid, "done", timeout=25)
        with open(self.lane_path(lid, "step1-final.md")) as f:
            self.assertIn("RESUME-ENV-OK", f.read())


class TestClassifyTable(LaneBase):
    def test_false_positives_not_fatal_and_positives_fatal(self):
        mod = _load_lane_module()
        cf = mod.classify_failure
        long_err = "\n".join(
            ["boom HTTP 401 on line 0"] + ["filler %d" % i for i in range(60)])
        cases = [
            # (terminal, reason, stderr, exit, stalled, spawn, expected, note)
            (None, "stalled", "sha e4013ab fetching", 1, True, False,
             "retryable", "sha in stalled stderr"),
            (None, "stalled", "Error 401 Unauthorized", 1, True, False,
             "retryable", "stalled beats auth"),
            ("interrupted", "inserted 1403 rows", "", 1, False, False,
             "retryable", "row count in interrupted reason"),
            ("failed", "test_403_forbidden", "", 1, False, False,
             "once", "test name"),
            ("failed", "see Assets/Authentication/Login.cs", "", 1, False, False,
             "once", "auth path"),
            ("failed", "model refused", "connection info: pool stats", 1,
             False, False, "once", "connection in stderr only"),
            ("cancelled", "user cancel", "network trace here", 1,
             False, False, "once", "network in stderr only"),
            ("failed", "model refused", long_err, 1, False, False,
             "once", "auth beyond last 40 lines does not count"),
            ("failed", "request failed: HTTP 401", "", 1, False, False,
             "fatal", "HTTP 401"),
            ("failed", "status: 403", "", 1, False, False,
             "fatal", "status 403"),
            ("failed", "401 Unauthorized", "", 1, False, False,
             "fatal", "401 Unauthorized"),
            ("failed", "Invalid API key provided", "", 1, False, False,
             "fatal", "invalid api key"),
            ("failed", "authentication failed for user", "", 1, False, False,
             "fatal", "authentication failed"),
            ("failed", "not authenticated", "", 1, False, False,
             "fatal", "not authenticated"),
            ("failed", "unauthorized access", "", 1, False, False,
             "fatal", "unauthorized word"),
            ("failed", "boom 403 Forbidden here", "", 1, False, False,
             "fatal", "403 Forbidden"),
            ("failed", "429 Too Many Requests", "", 1, False, False,
             "retryable", "rate in model-failure reason"),
            ("failed", "connection refused by peer", "", 1, False, False,
             "retryable", "network in model-failure reason"),
            (None, "", "HTTP 503 Service Unavailable", 1, False, False,
             "retryable", "5xx with context in tail"),
            (None, "", "got 429 from api", 1, False, False,
             "retryable", "429 in tail"),
            (None, "spawn failed: boom", "", None, False, True,
             "fatal", "spawn failure"),
            (None, "exit 1", "", 1, False, False,
             "retryable", "nonzero exit, no terminal"),
            (None, "exit 0 without terminal completion", "", 0, False, False,
             "once", "exit 0, no terminal"),
        ]
        for term, rsn, err, xc, stalled, spawn, want, note in cases:
            cls, _ = cf(term, rsn, err, xc, stalled=stalled,
                         spawn_failed=spawn)
            self.assertEqual(cls, want, "case %r" % (note,))
        # Bare "eof" is not a network signal; "unexpected eof" is.
        self.assertFalse(mod._mentions_network("reached eof marker"))
        self.assertTrue(mod._mentions_network("stream hit unexpected eof"))
        self.assertFalse(mod._mentions_auth("Assets/Authentication/Login.cs"))
        self.assertFalse(mod._mentions_auth("test_403_forbidden"))


class TestResumeRefusesUnverifiable(LaneBase):
    def test_helper_cases(self):
        mod = _load_lane_module()
        self.assertFalse(mod.pid_unverifiable_but_alive(42424242, "whatever"))
        self.assertFalse(mod.pid_unverifiable_but_alive(None, "x"))
        self.assertTrue(mod.pid_unverifiable_but_alive(os.getpid(), None))
        self.assertTrue(mod.pid_unverifiable_but_alive(os.getpid(), ""))
        orig = mod.get_start_time
        mod.get_start_time = lambda pid: None
        try:
            self.assertTrue(mod.pid_unverifiable_but_alive(os.getpid(), "bogus"))
        finally:
            mod.get_start_time = orig
        # Verifiable mismatch (pid reuse) is safe to leave alone: not refused.
        self.assertFalse(mod.pid_unverifiable_but_alive(
            os.getpid(), "definitely-not-the-start-time"))

    def test_resume_refuses_when_start_time_unverifiable(self):
        import io
        import types as _t
        from contextlib import redirect_stderr
        b = self.write_brief("b1.md", "unverifiable work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60",
                                             "MUSE_LANE_STALL_SEC": "60"})
        mus = None
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                st = self.read_state(lid)
            except (FileNotFoundError, OSError, ValueError):
                time.sleep(0.15)
                continue
            mus = st.get("muse_pid")
            if mus:
                try:
                    os.kill(int(mus), 0)
                    break
                except OSError:
                    mus = None
            time.sleep(0.15)
        self.assertTrue(mus, "no live muse child recorded")
        st = self.read_state(lid)
        os.kill(int(st["supervisor_pid"]), signal.SIGKILL)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(int(st["supervisor_pid"]), 0)
                time.sleep(0.1)
            except OSError:
                break
        time.sleep(0.5)
        try:
            os.kill(int(mus), 0)
        except OSError:
            self.fail("orphaned muse died on its own; test not deterministic")
        mod = _load_lane_module()
        old_root = os.environ.get("MUSE_LANES_ROOT")
        os.environ["MUSE_LANES_ROOT"] = self.lanes
        try:
            orig = mod.get_start_time
            mod.get_start_time = lambda pid: None
            try:
                buf = io.StringIO()
                with redirect_stderr(buf):
                    rc = mod.cmd_resume(_t.SimpleNamespace(id=lid))
            finally:
                mod.get_start_time = orig
        finally:
            if old_root is None:
                del os.environ["MUSE_LANES_ROOT"]
            else:
                os.environ["MUSE_LANES_ROOT"] = old_root
        self.assertNotEqual(rc, 0)
        self.assertIn("cannot be verified", buf.getvalue())
        # No second supervisor started.
        r = self.run_lane("status", lid, "--json")
        self.assertEqual(json.loads(r.stdout)[0]["status"], "orphaned")
        # The lane is still resumable once verification works.
        r2 = self.run_lane("resume", lid, env_extra={"FAKE_MODE": "complete",
                                                    "FAKE_TEXT": "AFTER-REFUSE"})
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.wait_status(lid, "done", timeout=25)


class TestRunLockRetry(LaneBase):
    def _start_and_orphan(self, lid_extra=""):
        b = self.write_brief("b%s.md" % lid_extra, "lock retry work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60",
                                             "MUSE_LANE_STALL_SEC": "60"})
        st = self.wait_status(lid, {"running", "retry_wait"}, timeout=15)
        try:
            os.kill(int(st["supervisor_pid"]), signal.SIGKILL)
        except OSError:
            pass
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(int(st["supervisor_pid"]), 0)
                time.sleep(0.1)
            except OSError:
                break
        try:
            os.kill(int(st["muse_pid"]), signal.SIGKILL)
        except (OSError, TypeError):
            pass
        time.sleep(0.5)
        return lid

    def test_run_retries_flock_briefly(self):
        import fcntl
        lid = self._start_and_orphan("1")
        ldir = os.path.join(self.lanes, lid)
        fd = os.open(os.path.join(ldir, "supervisor.lock"), os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            env = dict(self.base_env)
            env.update({"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60"})
            p = subprocess.Popen(
                [sys.executable, LANE, "_run", lid], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            try:
                time.sleep(0.6)
                fcntl.flock(fd, fcntl.LOCK_UN)
                held = False
                deadline = time.time() + 8
                while time.time() < deadline:
                    if p.poll() is not None:
                        break
                    fd2 = os.open(os.path.join(ldir, "supervisor.lock"), os.O_RDWR)
                    try:
                        try:
                            fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            fcntl.flock(fd2, fcntl.LOCK_UN)
                        except (BlockingIOError, OSError):
                            held = True
                            break
                    finally:
                        os.close(fd2)
                    time.sleep(0.1)
                self.assertTrue(held, "_run gave up instead of retrying the flock")
                self.assertIsNone(p.poll(), "_run exited early")
            finally:
                r = self.run_lane("stop", lid)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.wait_status(lid, "stopped", timeout=20)
                deadline = time.time() + 10
                while time.time() < deadline and p.poll() is None:
                    time.sleep(0.1)
                self.assertIsNotNone(p.poll())
        finally:
            os.close(fd)

    def test_run_gives_up_when_lock_held(self):
        import fcntl
        lid = self._start_and_orphan("2")
        ldir = os.path.join(self.lanes, lid)
        fd = os.open(os.path.join(ldir, "supervisor.lock"), os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            t0 = time.monotonic()
            r = self.run_lane("_run", lid, timeout=30)
            dt = time.monotonic() - t0
        finally:
            os.close(fd)
        self.assertNotEqual(r.returncode, 0)
        self.assertGreaterEqual(dt, 1.5)
        self.assertLess(dt, 15.0)


class TestQueuedOrphan(LaneBase):
    def _kill_sup_and_muse(self, st):
        for k in ("supervisor_pid", "muse_pid"):
            try:
                os.kill(int(st[k]), signal.SIGKILL)
            except (OSError, TypeError):
                pass
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(int(st["supervisor_pid"]), 0)
                time.sleep(0.1)
            except (OSError, TypeError):
                break
        time.sleep(0.5)

    def test_old_queued_lane_reports_orphaned_and_resumes(self):
        import datetime
        b = self.write_brief("b1.md", "queued orphan work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60"})
        st = self.wait_status(lid, {"running", "retry_wait"}, timeout=15)
        self._kill_sup_and_muse(st)
        sp = self.lane_path(lid, "state.json")
        with open(sp) as f:
            cur = json.load(f)
        old = (datetime.datetime.now(datetime.timezone.utc) -
               datetime.timedelta(seconds=60)).isoformat()
        cur["status"] = "queued"
        cur["started_at"] = old
        cur["updated_at"] = old
        cur["supervisor_pid"] = None
        cur["supervisor_started"] = None
        cur["muse_pid"] = None
        cur["muse_started"] = None
        with open(sp, "w") as f:
            json.dump(cur, f)
        r = self.run_lane("status", lid, "--json")
        self.assertEqual(json.loads(r.stdout)[0]["status"], "orphaned")
        r2 = self.run_lane("resume", lid, env_extra={"FAKE_MODE": "complete",
                                                    "FAKE_TEXT": "QUEUED-RESUMED"})
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.wait_status(lid, "done", timeout=25)
        with open(self.lane_path(lid, "step1-final.md")) as f:
            self.assertIn("QUEUED-RESUMED", f.read())

    def test_fresh_queued_lane_stays_queued(self):
        import datetime
        b = self.write_brief("b1.md", "fresh queued work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60"})
        st = self.wait_status(lid, {"running", "retry_wait"}, timeout=15)
        self._kill_sup_and_muse(st)
        sp = self.lane_path(lid, "state.json")
        with open(sp) as f:
            cur = json.load(f)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cur["status"] = "queued"
        cur["started_at"] = now
        cur["updated_at"] = now
        cur["supervisor_pid"] = None
        cur["supervisor_started"] = None
        cur["muse_pid"] = None
        cur["muse_started"] = None
        with open(sp, "w") as f:
            json.dump(cur, f)
        r = self.run_lane("status", lid, "--json")
        self.assertEqual(json.loads(r.stdout)[0]["status"], "queued")
        r2 = self.run_lane("stop", lid)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.wait_status(lid, "stopped", timeout=20)


class TestStopImmediately(LaneBase):
    def _assert_stopped_and_stays(self, lid):
        st = self.wait_status(lid, "stopped", timeout=25)
        self.assertTrue(os.path.exists(self.lane_path(lid, "stop.requested")))
        self.assertTrue(os.path.exists(self.lane_path(lid, "summary.md")))
        time.sleep(2.5)
        st2 = self.read_state(lid)
        self.assertEqual(st2["status"], "stopped")
        for k in ("supervisor_pid", "muse_pid", "accept_pid"):
            pid = st2.get(k)
            if pid:
                with self.assertRaises(OSError):
                    os.kill(int(pid), 0)

    def test_stop_right_after_start_stays_stopped(self):
        b = self.write_brief("b1.md", "immediate stop work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60"})
        r = self.run_lane("stop", lid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self._assert_stopped_and_stays(lid)

    def test_stop_right_after_resume_stays_stopped(self):
        b = self.write_brief("b1.md", "resume then stop work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60",
                                             "MUSE_LANE_STALL_SEC": "60"})
        st = self.wait_status(lid, {"running", "retry_wait"}, timeout=15)
        os.kill(int(st["supervisor_pid"]), signal.SIGKILL)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(int(st["supervisor_pid"]), 0)
                time.sleep(0.1)
            except OSError:
                break
        time.sleep(0.5)
        r = self.run_lane("resume", lid, env_extra={"FAKE_MODE": "sleeper",
                                                   "FAKE_SLEEP": "60"})
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = self.run_lane("stop", lid)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self._assert_stopped_and_stays(lid)


class TestCompletedThenHung(LaneBase):
    def test_completed_then_hung_counts_as_done(self):
        b = self.write_brief("b1.md", "hanging work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete_then_hang",
                                             "FAKE_TEXT": "HUNG-FINAL-3",
                                             "FAKE_SLEEP": "60",
                                             "MUSE_LANE_STALL_SEC": "1"})
        st = self.wait_status(lid, "done", timeout=25)
        st = self.read_state(lid)
        self.assertEqual(st["attempt"], 1)
        with open(self.lane_path(lid, "step1-final.md")) as f:
            self.assertIn("HUNG-FINAL-3", f.read())
        with open(self.lane_path(lid, "history.json")) as f:
            hist = json.load(f)
        self.assertTrue(hist["1"][0].get("ok"))


class TestStopRedactionSweep(LaneBase):
    def test_stop_of_orphaned_lane_sweeps_secrets(self):
        secret = "STOP-SWEEP-SECRET-fake-13579"
        envf = os.path.join(self.root, "sweep.env")
        with open(envf, "w") as f:
            f.write("MY_SECRET=%s\n" % secret)
        b = self.write_brief("b1.md", "sweep work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60",
                                             "MUSE_LANE_STALL_SEC": "60"},
                              env_file=envf)
        st = self.wait_status(lid, {"running", "retry_wait"}, timeout=15)
        mus = st.get("muse_pid")
        os.kill(int(st["supervisor_pid"]), signal.SIGKILL)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(int(st["supervisor_pid"]), 0)
                time.sleep(0.1)
            except OSError:
                break
        time.sleep(0.5)
        with open(self.lane_path(lid, "step1-attempt1.err"), "a") as f:
            f.write("leaked value: %s\n" % secret)
        r = self.run_lane("stop", lid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.wait_status(lid, "stopped", timeout=20)
        with open(self.lane_path(lid, "step1-attempt1.err")) as f:
            self.assertNotIn(secret, f.read())
        self.assert_no_secret_in_lane(lid, secret)
        if mus:
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    os.kill(int(mus), 0)
                    time.sleep(0.1)
                except OSError:
                    break
            with self.assertRaises(OSError):
                os.kill(int(mus), 0)


class TestSecretSnapshotUnion(LaneBase):
    def test_write_summary_uses_union_of_snapshot_and_current(self):
        mod = _load_lane_module()
        old_secret = "OLD-SNAPSHOT-SECRET-fake-24680"
        new_secret = "NEW-CURRENT-SECRET-fake-13579"
        envf = os.path.join(self.root, "rot.env")
        with open(envf, "w") as f:
            f.write("MY_SECRET=%s\n" % new_secret)
        ldir = os.path.join(self.lanes, "snaptest")
        os.makedirs(ldir, exist_ok=True)
        now = mod.now_iso()
        with open(os.path.join(ldir, "lane.json"), "w") as f:
            json.dump({"id": "snaptest", "label": "snap", "cwd": self.cwd,
                       "briefs": ["b1"], "accept": None, "created_at": now,
                       "env_file": envf}, f)
        with open(os.path.join(ldir, "state.json"), "w") as f:
            json.dump({"status": "done", "started_at": now, "head_start": None,
                       "head": None, "commits": 0}, f)
        with open(os.path.join(ldir, "history.json"), "w") as f:
            json.dump({}, f)
        with open(os.path.join(ldir, "step1-final.md"), "w") as f:
            f.write("old=%s new=%s\n" % (old_secret, new_secret))
        mod.write_summary_file(ldir, "done")
        with open(os.path.join(ldir, "summary.md")) as f:
            plain = f.read()
        self.assertNotIn(new_secret, plain)
        self.assertIn(old_secret, plain)
        mod.write_summary_file(ldir, "done", extra_secrets=[old_secret])
        with open(os.path.join(ldir, "summary.md")) as f:
            with_snap = f.read()
        self.assertNotIn(old_secret, with_snap)
        self.assertNotIn(new_secret, with_snap)
        self.assertIn("***", with_snap)


class TestTreeCpu(LaneBase):
    def test_counts_group_and_setsid_descendant(self):
        from unittest import mock
        mod = _load_lane_module()
        ps_out = (
            "    1       0       1   0:01.00\n"
            "  100       1     100   0:02.00\n"
            "  101     100     100   0:03.00\n"
            "  102     101     102   0:04.00\n"
            "  200       1     200   9:59.99\n"
        )
        fake = mock.Mock(returncode=0, stdout=ps_out)
        with mock.patch.object(mod.subprocess, "run", return_value=fake) as m:
            total = mod.get_tree_cpu_total(100)
        self.assertAlmostEqual(total, 2.0 + 3.0 + 4.0)
        _a, kwargs = m.call_args
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")
        self.assertEqual(kwargs["env"]["LANG"], "C")


class TestStatusAnnounceFields(LaneBase):
    def test_status_json_carries_owner_and_announce_fields(self):
        b = self.write_brief("b1.md", "announce fields work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              owner_session="sess-abc-123")
        self.wait_status(lid, "done", timeout=20)
        r = self.run_lane("status", lid, "--json")
        o = json.loads(r.stdout)[0]
        self.assertEqual(o["owner_session"], "sess-abc-123")
        self.assertIs(o["announced"], False)
        self.assertIs(o["orphan_announced"], False)
        ra = self.run_lane("ack", lid)
        self.assertEqual(ra.returncode, 0, ra.stderr)
        r2 = self.run_lane("status", lid, "--json")
        self.assertIs(json.loads(r2.stdout)[0]["announced"], True)


class TestAckExclusive(LaneBase):
    def test_two_concurrent_callers_one_wins(self):
        b = self.write_brief("b1.md", "ack race work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"})
        self.wait_status(lid, "done", timeout=20)
        env = dict(self.base_env)
        p1 = subprocess.Popen([sys.executable, LANE, "ack", lid], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p2 = subprocess.Popen([sys.executable, LANE, "ack", lid], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p1.communicate(timeout=15)
        p2.communicate(timeout=15)
        self.assertEqual(sorted([p1.returncode, p2.returncode]), [0, 3])
        r3 = self.run_lane("ack", lid)
        self.assertEqual(r3.returncode, 3)

    def test_ack_on_live_lane_refuses(self):
        b = self.write_brief("b1.md", "live ack work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60"})
        r = self.run_lane("ack", lid)
        self.assertEqual(r.returncode, 2)


class TestOrphanAckPerIncarnation(LaneBase):
    def _orphan(self, lid, timeout=15):
        st = self.wait_status(lid, {"running", "retry_wait"}, timeout=timeout)
        os.kill(int(st["supervisor_pid"]), signal.SIGKILL)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(int(st["supervisor_pid"]), 0)
                time.sleep(0.1)
            except OSError:
                break
        time.sleep(0.5)
        return st

    def test_orphan_ack_is_per_incarnation(self):
        b = self.write_brief("b1.md", "orphan incarnation work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60",
                                             "MUSE_LANE_STALL_SEC": "60"})
        st1 = self._orphan(lid)
        try:
            os.kill(int(st1["muse_pid"]), signal.SIGKILL)
        except (OSError, TypeError):
            pass
        r = self.run_lane("status", lid, "--json")
        o = json.loads(r.stdout)[0]
        self.assertEqual(o["status"], "orphaned")
        self.assertIs(o["orphan_announced"], False)
        a1 = self.run_lane("ack", lid, "--orphan")
        self.assertEqual(a1.returncode, 0, a1.stderr)
        r = self.run_lane("status", lid, "--json")
        self.assertIs(json.loads(r.stdout)[0]["orphan_announced"], True)
        a2 = self.run_lane("ack", lid, "--orphan")
        self.assertEqual(a2.returncode, 3)
        r3 = self.run_lane("resume", lid, env_extra={"FAKE_MODE": "sleeper",
                                                    "FAKE_SLEEP": "60"})
        self.assertEqual(r3.returncode, 0, r3.stderr)
        self._orphan(lid)
        r = self.run_lane("status", lid, "--json")
        o = json.loads(r.stdout)[0]
        self.assertEqual(o["status"], "orphaned")
        self.assertIs(o["orphan_announced"], False)
        a3 = self.run_lane("ack", lid, "--orphan")
        self.assertEqual(a3.returncode, 0, a3.stderr)
        r = self.run_lane("status", lid, "--json")
        self.assertIs(json.loads(r.stdout)[0]["orphan_announced"], True)
        r4 = self.run_lane("resume", lid, env_extra={"FAKE_MODE": "complete",
                                                    "FAKE_TEXT": "ORPHAN-ACK-DONE"})
        self.assertEqual(r4.returncode, 0, r4.stderr)
        self.wait_status(lid, "done", timeout=25)
        a4 = self.run_lane("ack", lid, "--orphan")
        self.assertEqual(a4.returncode, 2)


class TestReviewPass(LaneBase):
    def test_review_pass_ends_done_with_section(self):
        b = self.write_brief("b1.md", "review pass work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "FAKE_TEXT": "work done",
                                              "FAKE_REVIEW_VERDICT": "PASS"},
                              accept="exit 0", review=True)
        self.wait_status(lid, "done", timeout=25)
        st = self.read_state(lid)
        self.assertEqual(st["status"], "done")
        rounds = st.get("review_rounds") or []
        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0].get("verdict"), "PASS")
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("Muse pre-review (not the independent review)", summ)
        self.assertIn("Round 1: PASS", summ)
        self.assertTrue(os.path.exists(self.lane_path(lid, "REVIEW-1.md")))
        self.assertTrue(os.path.exists(os.path.join(self.cwd, ".lane", "REVIEW-1.md")))
        with open(self.lane_path(lid, "review-brief1.md")) as f:
            rb = f.read()
        self.assertIn("review pass work", rb)
        self.assertIn("REVIEW-1.md", rb)
        self.assertIn("round 1 of 2", rb)


class TestReviewFailNoRoundsLeft(LaneBase):
    def test_review_fail_ends_review_failed(self):
        b = self.write_brief("b1.md", "review fail work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "FAKE_REVIEW_VERDICT": "FAIL",
                                              "FAKE_REVIEW_FINDINGS": "1. app.py:42 missing test\n2. app.py:50 toothless control"},
                              accept="exit 0", review=True, review_rounds=0)
        self.wait_status(lid, "review_failed", timeout=25)
        st = self.read_state(lid)
        self.assertEqual(st["status"], "review_failed")
        rounds = st.get("review_rounds") or []
        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0].get("verdict"), "FAIL")
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("Muse pre-review (not the independent review)", summ)
        self.assertIn("Round 1: FAIL", summ)
        self.assertIn("app.py:42", summ)
        r = self.run_lane("ack", lid)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestReviewFailThenPass(LaneBase):
    def test_review_fail_reruns_last_step_then_done(self):
        count = os.path.join(self.state_dir, "review-count")
        b1 = self.write_brief("b1.md", "first work")
        b2 = self.write_brief("b2.md", "last work RERUN-MARKER")
        lid = self.start_lane([b1, b2], env_extra={"FAKE_MODE": "complete",
                                                   "FAKE_REVIEW_FAILS": "1",
                                                   "FAKE_REVIEW_COUNT_FILE": count,
                                                   "FAKE_REVIEW_FINDINGS": "1. last.py:7 fix this"},
                              accept="exit 0", review=True, review_rounds=2)
        self.wait_status(lid, "done", timeout=40)
        st = self.read_state(lid)
        self.assertEqual(st["status"], "done")
        rounds = st.get("review_rounds") or []
        self.assertEqual([e.get("verdict") for e in rounds], ["FAIL", "PASS"])
        with open(self.lane_path(lid, "brief2.md")) as f:
            aug = f.read()
        self.assertIn("RERUN-MARKER", aug)
        self.assertIn("last.py:7", aug)
        with open(self.lane_path(lid, "brief2-orig.md")) as f:
            orig = f.read()
        self.assertIn("RERUN-MARKER", orig)
        self.assertNotIn("last.py:7", orig)
        with open(self.lane_path(lid, "history.json")) as f:
            hist = json.load(f)
        self.assertIn("2-pre-r1", hist)
        self.assertIn("2", hist)
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("Round 1: FAIL", summ)
        self.assertIn("Round 2: PASS", summ)

    def test_review_default_round_fixes_once(self):
        count = os.path.join(self.state_dir, "review-count-default")
        b = self.write_brief("b1.md", "default fix work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "FAKE_REVIEW_FAILS": "1",
                                              "FAKE_REVIEW_COUNT_FILE": count,
                                              "FAKE_REVIEW_FINDINGS": "1. app.py:9 fix me"},
                              accept="exit 0", review=True)
        self.wait_status(lid, "done", timeout=40)
        st = self.read_state(lid)
        self.assertEqual(st["status"], "done")
        rounds = st.get("review_rounds") or []
        self.assertEqual([e.get("verdict") for e in rounds], ["FAIL", "PASS"])
        with open(self.lane_path(lid, "history.json")) as f:
            hist = json.load(f)
        self.assertIn("1-pre-r1", hist)
        self.assertEqual(len(hist["1-pre-r1"]), 1)
        self.assertEqual(len(hist["1"]), 1)
        with open(self.lane_path(lid, "brief1.md")) as f:
            self.assertIn("app.py:9", f.read())


class TestReviewPassOverride(LaneBase):
    def test_pass_with_should_fix_triggers_fix_round(self):
        b = self.write_brief("b1.md", "override work OVERRIDE-MARKER")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "FAKE_REVIEW_VERDICT": "PASS",
                                              "FAKE_REVIEW_FINDINGS_1": "1. [should-fix] app.py:9 fix me",
                                              "FAKE_REVIEW_FINDINGS_2": "1. [nit] app.py:3 typo"},
                              accept="exit 0", review=True)
        self.wait_status(lid, "done", timeout=40)
        st = self.read_state(lid)
        self.assertEqual(st["status"], "done")
        rounds = st.get("review_rounds") or []
        self.assertEqual([e.get("verdict") for e in rounds], ["FAIL", "PASS"])
        self.assertEqual(rounds[0].get("overridden"), "PASS overridden: should-fix findings")
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("Round 1: FAIL (PASS overridden: should-fix findings)", summ)
        self.assertIn("Round 2: PASS", summ)
        # The fix round ran as for FAIL: brief augmented, history archived.
        with open(self.lane_path(lid, "brief1.md")) as f:
            self.assertIn("app.py:9", f.read())
        with open(self.lane_path(lid, "history.json")) as f:
            self.assertIn("1-pre-r1", json.load(f))
        # The verdict file keeps the reviewer's verbatim PASS text.
        with open(self.lane_path(lid, "REVIEW-1.md")) as f:
            self.assertTrue(f.read().startswith("PASS"))

    def test_pass_with_only_nits_skips_fix_round(self):
        b = self.write_brief("b1.md", "nits work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "FAKE_REVIEW_VERDICT": "PASS",
                                              "FAKE_REVIEW_FINDINGS": "1. [nit] app.py:3 typo\n2. [nit] app.py:4 spacing"},
                              accept="exit 0", review=True)
        self.wait_status(lid, "done", timeout=25)
        st = self.read_state(lid)
        rounds = st.get("review_rounds") or []
        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0].get("verdict"), "PASS")
        with open(self.lane_path(lid, "summary.md")) as f:
            self.assertNotIn("overridden", f.read())
        with open(self.lane_path(lid, "history.json")) as f:
            self.assertNotIn("1-pre-r1", json.load(f))


class TestReviewError(LaneBase):
    def test_review_crash_does_not_block_done(self):
        b = self.write_brief("b1.md", "review crash work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "FAKE_REVIEW_MODE": "crash"},
                              accept="exit 0", review=True)
        self.wait_status(lid, "done", timeout=25)
        st = self.read_state(lid)
        self.assertEqual(st["status"], "done")
        self.assertTrue(st.get("review_error"))
        rounds = st.get("review_rounds") or []
        self.assertEqual(rounds[0].get("verdict"), "ERROR")
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("review_error", summ)

    def test_review_timeout_records_error(self):
        b = self.write_brief("b1.md", "review timeout work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "FAKE_REVIEW_MODE": "sleep",
                                              "FAKE_REVIEW_SLEEP": "30",
                                              "MUSE_LANE_REVIEW_TIMEOUT_SEC": "1"},
                              accept="exit 0", review=True)
        self.wait_status(lid, "done", timeout=30)
        st = self.read_state(lid)
        self.assertIn("timed out", st.get("review_error") or "")


class TestReviewBrief(LaneBase):
    def test_review_brief_caps_large_diff_and_parses_verdict(self):
        mod = _load_lane_module()
        subprocess.run(["git", "init"], cwd=self.cwd, capture_output=True, timeout=15, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=self.cwd, capture_output=True, timeout=15)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.cwd, capture_output=True, timeout=15)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.cwd, capture_output=True, timeout=15)
        with open(os.path.join(self.cwd, "init.txt"), "w") as f:
            f.write("init\n")
        subprocess.run(["git", "add", "."], cwd=self.cwd, capture_output=True, timeout=15, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.cwd, capture_output=True, timeout=15, check=True)
        head_start = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.cwd, capture_output=True,
                                    text=True, timeout=15).stdout.strip()
        big = "x" * (mod.REVIEW_DIFF_CAP + 1000)
        with open(os.path.join(self.cwd, "big.txt"), "w") as f:
            f.write(big + "\n")
        subprocess.run(["git", "add", "."], cwd=self.cwd, capture_output=True, timeout=15, check=True)
        subprocess.run(["git", "commit", "-m", "big"], cwd=self.cwd, capture_output=True, timeout=15, check=True)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.cwd, capture_output=True,
                              text=True, timeout=15).stdout.strip()
        stat, full, files = mod.get_review_diff(self.cwd, head_start, head)
        self.assertIsNone(full)
        self.assertIn("big.txt", files)
        self.assertIn("big.txt", stat)
        txt = mod.build_review_brief("lbl", "lid", ["brief one"], head_start, head,
                                     stat, full, files, "exit 0", 0, "tail", [], 1, 2, None)
        self.assertIn("round 1 of 2", txt)
        self.assertIn("read them yourself", txt)
        self.assertIn("brief one", txt)
        self.assertIn("allowlist", txt)
        self.assertIn("toothless", txt)
        self.assertNotIn(big[:100], txt)
        v, f = mod.parse_review_verdict("FAIL\n1. a.py:1 bad\n")
        self.assertEqual(v, "FAIL")
        self.assertIn("a.py:1", f)
        v2, _ = mod.parse_review_verdict("pass\n")
        self.assertEqual(v2, "PASS")
        v3, _ = mod.parse_review_verdict("maybe\n")
        self.assertIsNone(v3)

    def test_pass_override_predicate_and_brief_rule(self):
        mod = _load_lane_module()
        self.assertTrue(mod.pass_has_severe_findings("1. [should-fix] a.py:1 x"))
        self.assertTrue(mod.pass_has_severe_findings("2. BLOCKER: b.py:2 y"))
        self.assertTrue(mod.pass_has_severe_findings("1) Should-Fix c.py:3 z"))
        self.assertFalse(mod.pass_has_severe_findings("1. [nit] a.py:1 typo"))
        self.assertFalse(mod.pass_has_severe_findings("1. a.py:1 fix this"))
        self.assertFalse(mod.pass_has_severe_findings(
            "overall should-fix sentiment but no numbered finding"))
        self.assertFalse(mod.pass_has_severe_findings(""))
        txt = mod.build_review_brief("lbl", "lid", ["b"], None, None, "stat",
                                     "diff", [], "exit 0", 0, "tail", [], 1, 2,
                                     None)
        self.assertIn("Any blocker or should-fix finding", txt)
        self.assertIn("means FAIL", txt)
        self.assertIn("PASS only when the findings are nits or none", txt)

    def test_review_flags_validated(self):
        b = self.write_brief("b1.md", "x")
        r = self.run_lane("start", "--cwd", self.cwd, "--brief", b, "--review", "--review-rounds", "-1")
        self.assertNotEqual(r.returncode, 0)
        r2 = self.run_lane("start", "--cwd", self.cwd, "--brief", b, "--review-brief", "extra")
        self.assertNotEqual(r2.returncode, 0)
        # rounds 0 is valid: review once with no fix re-run.
        b0 = self.write_brief("b0.md", "rounds zero work")
        lid = self.start_lane([b0], env_extra={"FAKE_MODE": "complete",
                                               "FAKE_REVIEW_VERDICT": "PASS"},
                              accept="exit 0", review=True, review_rounds=0)
        self.wait_status(lid, "done", timeout=25)
        st = self.read_state(lid)
        self.assertEqual(len(st.get("review_rounds") or []), 1)


class TestConsultAnswers(LaneBase):
    def test_consult_helper_answers_and_step_reads_it(self):
        b = self.write_brief("b1.md", "consult work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "ask",
                                              "FAKE_ASK_COUNT": "1",
                                              "FAKE_CONSULT_ANSWER": "CONSULT-ANSWER-77"})
        self.wait_status(lid, "done", timeout=30)
        with open(self.lane_path(lid, "step1-final.md")) as f:
            final = f.read()
        self.assertIn("CONSULT-ANSWER-77", final)
        st = self.read_state(lid)
        consults = st.get("consults") or []
        self.assertEqual(len(consults), 1)
        self.assertTrue(consults[0].get("answered"))
        self.assertEqual(consults[0].get("helper"), "ok")
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("## Consult", summ)
        self.assertIn("Question 1", summ)
        with open(self.lane_path(lid, "brief1.md")) as f:
            brief = f.read()
        self.assertIn("ASK.md", "\n".join(brief.splitlines()[:3]))
        self.assertIn("ANSWER.md", "\n".join(brief.splitlines()[:3]))
        self.assertTrue(os.path.exists(os.path.join(self.cwd, ".lane", "ASK-1.md")))
        self.assertTrue(os.path.exists(os.path.join(self.cwd, ".lane", "ANSWER-1.md")))

    def test_consult_limit_reached_past_max(self):
        b = self.write_brief("b1.md", "consult limit work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "ask",
                                              "FAKE_ASK_COUNT": "4",
                                              "FAKE_CONSULT_ANSWER": "A"},
                              consult_max=3)
        self.wait_status(lid, "done", timeout=40)
        with open(self.lane_path(lid, "step1-final.md")) as f:
            final = f.read()
        self.assertIn("limit", final.lower())
        st = self.read_state(lid)
        consults = st.get("consults") or []
        self.assertEqual(len(consults), 4)
        self.assertEqual(consults[-1].get("helper"), "limited")
        self.assertFalse(consults[-1].get("answered"))

    def test_consult_helper_timeout_still_completes(self):
        b = self.write_brief("b1.md", "consult timeout work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "ask",
                                              "FAKE_ASK_COUNT": "1",
                                              "FAKE_CONSULT_SLEEP": "30",
                                              "MUSE_LANE_CONSULT_TIMEOUT_SEC": "1"})
        self.wait_status(lid, "done", timeout=30)
        with open(self.lane_path(lid, "step1-final.md")) as f:
            final = f.read()
        self.assertIn("timed out", final.lower())
        st = self.read_state(lid)
        consults = st.get("consults") or []
        self.assertEqual(consults[0].get("helper"), "timeout")
        self.assertFalse(consults[0].get("answered"))

    def test_consult_empty_terminal_text_uses_delta_answer(self):
        b = self.write_brief("b1.md", "consult delta work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "ask",
                                              "FAKE_ASK_COUNT": "1",
                                              "FAKE_CONSULT_EMPTY_TERMINAL": "1",
                                              "FAKE_CONSULT_ANSWER": "DELTA-ANSWER-53"})
        self.wait_status(lid, "done", timeout=30)
        with open(os.path.join(self.cwd, ".lane", "ANSWER.md")) as f:
            self.assertIn("DELTA-ANSWER-53", f.read())
        with open(self.lane_path(lid, "supervisor.log")) as f:
            log = f.read()
        self.assertIn("consult step 1 #1 ok", log)
        st = self.read_state(lid)
        consults = st.get("consults") or []
        self.assertEqual(len(consults), 1)
        self.assertTrue(consults[0].get("answered"))
        self.assertEqual(consults[0].get("helper"), "ok")

    def test_consult_no_answer_logs_failed_not_ok(self):
        b = self.write_brief("b1.md", "consult no-answer work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "ask",
                                              "FAKE_ASK_COUNT": "1",
                                              "FAKE_CONSULT_NO_ANSWER": "1"})
        self.wait_status(lid, "done", timeout=30)
        with open(os.path.join(self.cwd, ".lane", "ANSWER.md")) as f:
            self.assertIn("helper failed", f.read())
        with open(self.lane_path(lid, "supervisor.log")) as f:
            log = f.read()
        self.assertIn("consult step 1 #1 failed", log)
        self.assertNotIn("consult step 1 #1 ok", log)
        st = self.read_state(lid)
        consults = st.get("consults") or []
        self.assertEqual(len(consults), 1)
        self.assertFalse(consults[0].get("answered"))
        self.assertEqual(consults[0].get("helper"), "failed")


class TestReadOnlySessions(LaneBase):
    def test_consult_and_review_run_without_write(self):
        argv_file = os.path.join(self.state_dir, "argv-ro.log")
        b = self.write_brief("b1.md", "readonly work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "ask",
                                              "FAKE_ASK_COUNT": "1",
                                              "FAKE_CONSULT_ANSWER": "CONSULT-RO-9",
                                              "FAKE_REVIEW_VERDICT": "PASS",
                                              "FAKE_REVIEW_FINDINGS": "1. ok.py:1 fine",
                                              "FAKE_ARGV_FILE": argv_file},
                              accept="exit 0", review=True)
        self.wait_status(lid, "done", timeout=40)
        with open(argv_file) as f:
            argvs = [json.loads(line) for line in f.read().splitlines()
                     if line.strip()]
        by_prompt = {}
        for argv in argvs:
            if "--prompt-file" in argv:
                pf = argv[argv.index("--prompt-file") + 1]
                by_prompt[os.path.basename(pf)] = argv
        step_argv = by_prompt.get("brief1.md")
        consult_argv = by_prompt.get("consult-brief-1.md")
        review_argv = by_prompt.get("review-brief1.md")
        self.assertTrue(step_argv and consult_argv and review_argv,
                        "missing sessions: %s" % sorted(by_prompt))
        self.assertNotIn("--disable-write", step_argv)
        self.assertIn("--disable-write", consult_argv)
        self.assertIn("--disable-write", review_argv)
        # The supervisor wrote both answer files from the helper's final text.
        with open(os.path.join(self.cwd, ".lane", "ANSWER-1.md")) as f:
            self.assertIn("CONSULT-RO-9", f.read())
        with open(os.path.join(self.cwd, ".lane", "ANSWER.md")) as f:
            self.assertIn("CONSULT-RO-9", f.read())
        # The supervisor wrote both verdict files from the reviewer's final text.
        for p in (os.path.join(self.cwd, ".lane", "REVIEW-1.md"),
                  self.lane_path(lid, "REVIEW-1.md")):
            with open(p) as f:
                content = f.read()
            self.assertTrue(content.startswith("PASS"),
                            "verdict file %s: %r" % (p, content[:40]))
            self.assertIn("ok.py:1", content)

    def test_review_session_changing_tracked_files_fails_lane(self):
        subprocess.run(["git", "init"], cwd=self.cwd, capture_output=True, timeout=15, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=self.cwd, capture_output=True, timeout=15)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.cwd, capture_output=True, timeout=15)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.cwd, capture_output=True, timeout=15)
        with open(os.path.join(self.cwd, "tracked.txt"), "w") as f:
            f.write("v1\n")
        subprocess.run(["git", "add", "."], cwd=self.cwd, capture_output=True, timeout=15, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.cwd, capture_output=True, timeout=15, check=True)
        b = self.write_brief("b1.md", "dirty review work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "FAKE_REVIEW_VERDICT": "PASS",
                                              "FAKE_REVIEW_DIRTY": "1",
                                              "FAKE_REVIEW_DIRTY_FILE": "tracked.txt"},
                              accept="exit 0", review=True)
        self.wait_status(lid, "failed", timeout=30)
        st = self.read_state(lid)
        self.assertEqual(st["status"], "failed")
        self.assertEqual(st.get("reason"), "review session changed tracked files")
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("tracked.txt", summ)
        # Nothing is reverted: the reviewer's edit is still there.
        with open(os.path.join(self.cwd, "tracked.txt")) as f:
            self.assertIn("reviewer was here", f.read())


class TestAcceptPhases(LaneBase):
    def test_phase_from_accept_lines(self):
        b = self.write_brief("b1.md", "phase work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              accept="echo LANE-PHASE: gate1; sleep 2; echo LANE-PHASE: gate2; exit 0")
        deadline = time.time() + 20
        st = None
        seen_gate1 = False
        while time.time() < deadline:
            try:
                st = self.read_state(lid)
            except (FileNotFoundError, OSError, ValueError):
                time.sleep(0.15)
                continue
            if st.get("phase") == "gate1":
                seen_gate1 = True
                break
            if st.get("status") in ("done", "failed"):
                break
            time.sleep(0.15)
        self.assertTrue(seen_gate1, "never saw gate1 phase: %s" % (st,))
        self.wait_status(lid, "done", timeout=20)
        st = self.read_state(lid)
        self.assertEqual(st.get("phase"), "gate2")
        self.assertTrue(st.get("phase_started"))

    def test_phase_step_and_review(self):
        b = self.write_brief("b1.md", "step phase work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60"})
        self.wait_status(lid, {"running", "retry_wait"}, timeout=15)
        st = self.read_state(lid)
        self.assertEqual(st.get("phase"), "step:1")
        self.assertTrue(st.get("phase_started"))
        r = self.run_lane("stop", lid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.wait_status(lid, "stopped", timeout=20)
        b2 = self.write_brief("b2.md", "review phase work")
        lid2 = self.start_lane([b2], env_extra={"FAKE_MODE": "complete",
                                                "FAKE_REVIEW_VERDICT": "FAIL"},
                               accept="exit 0", review=True, review_rounds=0)
        self.wait_status(lid2, "review_failed", timeout=25)
        st2 = self.read_state(lid2)
        self.assertEqual(st2.get("phase"), "review:1")


class TestStatusActive(LaneBase):
    def test_phase_status_active_and_limit(self):
        b1 = self.write_brief("b1.md", "active work")
        lid1 = self.start_lane([b1], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60"})
        self.wait_status(lid1, {"running", "retry_wait"}, timeout=15)
        b2 = self.write_brief("b2.md", "old work")
        lid2 = self.start_lane([b2], env_extra={"FAKE_MODE": "complete"})
        self.wait_status(lid2, "done", timeout=20)
        import datetime as _dt
        old = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=2)).isoformat()
        sp = self.lane_path(lid2, "state.json")
        with open(sp) as f:
            cur = json.load(f)
        cur["updated_at"] = old
        with open(sp, "w") as f:
            json.dump(cur, f)
        r = self.run_lane("status", "--json")
        objs = json.loads(r.stdout)
        self.assertEqual(len(objs), 2)
        ra = self.run_lane("status", "--json", "--active")
        obja = json.loads(ra.stdout)
        self.assertEqual([o["id"] for o in obja], [lid1])
        rl = self.run_lane("status", "--json", "--limit", "1")
        objl = json.loads(rl.stdout)
        self.assertEqual(len(objl), 1)
        rh = self.run_lane("status", "--active")
        self.assertIn("older lanes", rh.stdout)
        self.assertIn(lid1, rh.stdout)
        self.assertIn("phase", obja[0])
        self.assertIn("stall_sec", obja[0])
        self.assertIn("accept_tail", obja[0])
        self.assertIn("last_subject", obja[0])

    def test_phase_old_state_without_new_keys_reads(self):
        b = self.write_brief("b1.md", "old state work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"})
        self.wait_status(lid, "done", timeout=20)
        sp = self.lane_path(lid, "state.json")
        with open(sp) as f:
            cur = json.load(f)
        for k in ("phase", "phase_started", "review_rounds", "review_error", "consults"):
            cur.pop(k, None)
        with open(sp, "w") as f:
            json.dump(cur, f)
        r = self.run_lane("status", lid, "--json")
        o = json.loads(r.stdout)[0]
        self.assertEqual(o["status"], "done")
        self.assertIsNone(o["phase"])
        self.assertEqual(o["review_rounds"], [])
        r2 = self.run_lane("summary", lid)
        self.assertEqual(r2.returncode, 0)


class TestStatusActiveCost(LaneBase):
    def test_status_active_never_runs_git_for_ended_lanes(self):
        import datetime as _dt
        import fcntl
        # git shim that counts invocations instead of touching repos.
        shimdir = os.path.join(self.root, "shimbin")
        os.makedirs(shimdir, exist_ok=True)
        count_file = os.path.join(self.root, "git-calls.log")
        with open(os.path.join(shimdir, "git"), "w") as f:
            f.write('#!/bin/sh\n'
                    'echo "$PWD :: $*" >> "%s"\n'
                    'echo "shim-subject-line"\n'
                    'exit 0\n' % count_file)
        os.chmod(os.path.join(shimdir, "git"), 0o755)
        env_extra = {"PATH": shimdir + os.pathsep + self.base_env.get("PATH", "")}
        now = _dt.datetime.now(_dt.timezone.utc)
        recent = now.isoformat()
        old = (now - _dt.timedelta(days=2)).isoformat()
        live_cwd = os.path.join(self.root, "live-cwd")
        ended_cwd = os.path.join(self.root, "ended-cwd")
        os.makedirs(live_cwd, exist_ok=True)
        os.makedirs(ended_cwd, exist_ok=True)

        def mk(lid, status, updated, created, cwd):
            ldir = os.path.join(self.lanes, lid)
            os.makedirs(ldir, exist_ok=True)
            lane = {"id": lid, "label": "L-" + lid, "cwd": cwd,
                    "created_at": created, "owner_session": "sess-1",
                    "stall_sec": 2400, "env_file": None, "briefs": ["b.md"]}
            state = {"status": status, "step": 1, "steps": 1, "attempt": 1,
                     "supervisor_pid": None, "supervisor_started": None,
                     "muse_pid": None, "muse_started": None,
                     "started_at": created, "updated_at": updated,
                     "last_activity_at": updated, "commits": 0,
                     "reason": None, "phase": "step:1",
                     "phase_started": created, "review_rounds": [],
                     "review_error": None, "consults": []}
            with open(os.path.join(ldir, "lane.json"), "w") as f:
                json.dump(lane, f)
            with open(os.path.join(ldir, "state.json"), "w") as f:
                json.dump(state, f)

        base = now - _dt.timedelta(hours=3)
        terms = ["done", "failed", "gave_up", "stopped", "review_failed"]
        recent_ids = []
        old_ids = []
        for i in range(12):
            rid = "lane-ended-recent-%02d" % i
            oid = "lane-ended-old-%02d" % i
            mk(rid, terms[i % len(terms)], recent,
               (base + _dt.timedelta(seconds=i)).isoformat(), ended_cwd)
            mk(oid, terms[(i + 1) % len(terms)], old,
               (base + _dt.timedelta(seconds=100 + i)).isoformat(), ended_cwd)
            recent_ids.append(rid)
            old_ids.append(oid)
        live_id = "lane-live-1"
        mk(live_id, "running", recent,
           (base + _dt.timedelta(seconds=1000)).isoformat(), live_cwd)
        # Hold the live lane's supervisor lock so it displays running.
        lock_fd = os.open(self.lane_path(live_id, "supervisor.lock"),
                          os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = self.run_lane("status", "--json", "--active",
                              env_extra=env_extra)
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(lock_fd)
        self.assertEqual(r.returncode, 0, r.stderr)
        objs = json.loads(r.stdout)
        by_id = {o["id"]: o for o in objs}
        self.assertIn(live_id, by_id)
        self.assertEqual(by_id[live_id]["status"], "running")
        self.assertEqual(by_id[live_id]["last_subject"], "shim-subject-line")
        self.assertEqual(by_id[live_id]["branch"], "shim-subject-line")
        self.assertEqual(by_id[live_id]["head"], "shim-subject-line")
        for rid in recent_ids:
            self.assertIn(rid, by_id)
            self.assertIsNone(by_id[rid]["last_subject"], rid)
            self.assertIsNone(by_id[rid]["branch"], rid)
            self.assertIsNone(by_id[rid]["head"], rid)
            self.assertIsNone(by_id[rid]["needs_lead"], rid)
            self.assertIs(by_id[rid]["needs_lead_announced"], False, rid)
            self.assertIsNone(by_id[rid]["box"], rid)
            self.assertIsNone(by_id[rid]["box_state"], rid)
            self.assertIsNone(by_id[rid]["box_queued_at"], rid)
            self.assertIsNone(by_id[rid]["evidence"], rid)
            self.assertEqual(by_id[rid]["advisor_calls"], 0, rid)
        for oid in old_ids:
            self.assertNotIn(oid, by_id)
        try:
            with open(count_file) as f:
                calls = [l for l in f.read().splitlines() if l.strip()]
        except FileNotFoundError:
            calls = []
        # Live lane: branch + head + subject. Ended lanes: no git at all.
        self.assertEqual(len(calls), 3,
                         "status --active ran git %d times, want 3 live-only: %s"
                         % (len(calls), calls[:5]))
        for c in calls:
            got_pwd = c.split(" :: ")[0]
            self.assertEqual(os.path.realpath(got_pwd), os.path.realpath(live_cwd), c)
        joined = " ".join(calls)
        self.assertIn("branch", joined)
        self.assertIn("rev-parse", joined)
        self.assertIn(" log ", " " + joined + " ")


class TestSandboxNetworkArgv(LaneBase):
    def test_step_argv_carries_sandbox_network_restricted(self):
        argv_file = os.path.join(self.state_dir, "argv.log")
        b = self.write_brief("b1.md", "argv work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "FAKE_ARGV_FILE": argv_file})
        self.wait_status(lid, "done", timeout=20)
        self.wait_file(argv_file, timeout=10)
        with open(argv_file) as f:
            lines = [l.strip() for l in f.read().splitlines() if l.strip()]
        self.assertTrue(lines, "fake muse never recorded argv")
        argv = json.loads(lines[-1])
        self.assertIn("--sandbox-network", argv)
        self.assertIn("restricted", argv)
        self.assertLess(argv.index("--json"), argv.index("--sandbox-network"))
        i = argv.index("--sandbox-network")
        self.assertEqual(argv[i + 1], "restricted")


class TestConfigLoading(LaneBase):
    def test_defaults_copied_when_no_config(self):
        b = self.write_brief("b1.md", "config defaults work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"})
        lane = self.read_lane(lid)
        cfg = lane.get("config")
        self.assertIsInstance(cfg, dict)
        self.assertEqual(cfg.get("accept_exit_kinds"), {})
        self.assertEqual(cfg.get("box_wait_max_min"), 30)
        self.assertIsNone(lane.get("box"))
        self.assertEqual(lane.get("scope"), [])
        self.wait_status(lid, "done", timeout=20)

    def test_env_config_copied_and_unknown_keys_ignored(self):
        cfg_path = os.path.join(self.root, "lanes-config.json")
        with open(cfg_path, "w") as f:
            json.dump({"accept_exit_kinds": {"5": "accept_failed_harness"},
                       "box_wait_max_min": 7,
                       "nope_unknown_key": 123}, f)
        b = self.write_brief("b1.md", "env config work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "MUSE_LANES_CONFIG": cfg_path})
        cfg = self.read_lane(lid).get("config")
        self.assertEqual(cfg.get("accept_exit_kinds"), {"5": "accept_failed_harness"})
        self.assertEqual(cfg.get("box_wait_max_min"), 7)
        self.assertNotIn("nope_unknown_key", cfg)
        self.wait_status(lid, "done", timeout=20)

    def test_root_config_used_and_env_wins(self):
        root_cfg = os.path.join(self.lanes, "config.json")
        with open(root_cfg, "w") as f:
            json.dump({"box_wait_max_min": 11}, f)
        b = self.write_brief("b1.md", "root config work")
        lid1 = self.start_lane([b], env_extra={"FAKE_MODE": "complete"})
        self.assertEqual(self.read_lane(lid1)["config"]["box_wait_max_min"], 11)
        self.wait_status(lid1, "done", timeout=20)
        env_cfg = os.path.join(self.root, "env-config.json")
        with open(env_cfg, "w") as f:
            json.dump({"box_wait_max_min": 22}, f)
        lid2 = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                               "MUSE_LANES_CONFIG": env_cfg})
        self.assertEqual(self.read_lane(lid2)["config"]["box_wait_max_min"], 22)
        self.wait_status(lid2, "done", timeout=20)

    def test_malformed_key_is_start_error_naming_key(self):
        cfg_path = os.path.join(self.root, "bad-config.json")
        with open(cfg_path, "w") as f:
            json.dump({"box_wait_max_min": "soon"}, f)
        b = self.write_brief("b1.md", "bad config work")
        r = self.run_lane("start", "--cwd", self.cwd, "--brief", b,
                          env_extra={"MUSE_LANES_CONFIG": cfg_path})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("box_wait_max_min", r.stderr)
        cfg2 = os.path.join(self.root, "bad-config2.json")
        with open(cfg2, "w") as f:
            json.dump({"accept_exit_kinds": {"1": "frobnicate"}}, f)
        r2 = self.run_lane("start", "--cwd", self.cwd, "--brief", b,
                           env_extra={"MUSE_LANES_CONFIG": cfg2})
        self.assertNotEqual(r2.returncode, 0)
        self.assertIn("accept_exit_kinds", r2.stderr)

    def test_malformed_json_is_start_error(self):
        cfg_path = os.path.join(self.root, "broken.json")
        with open(cfg_path, "w") as f:
            f.write("{not json")
        b = self.write_brief("b1.md", "broken config work")
        r = self.run_lane("start", "--cwd", self.cwd, "--brief", b,
                          env_extra={"MUSE_LANES_CONFIG": cfg_path})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("config", r.stderr.lower())

    def test_running_lane_keeps_config_snapshot(self):
        cfg_path = os.path.join(self.root, "snap-config.json")
        with open(cfg_path, "w") as f:
            json.dump({"box_wait_max_min": 9}, f)
        b = self.write_brief("b1.md", "snapshot work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "MUSE_LANES_CONFIG": cfg_path})
        with open(cfg_path, "w") as f:
            json.dump({"box_wait_max_min": 99}, f)
        self.assertEqual(self.read_lane(lid)["config"]["box_wait_max_min"], 9)
        self.wait_status(lid, "done", timeout=20)


class TestAcceptExitMapping(LaneBase):
    def _cfg(self, mapping):
        p = os.path.join(self.root, "cfg-%d.json" % time.time_ns())
        with open(p, "w") as f:
            json.dump({"accept_exit_kinds": mapping}, f)
        return p

    def test_exit_5_maps_to_harness(self):
        cfg = self._cfg({"5": "accept_failed_harness"})
        b = self.write_brief("b1.md", "harness map work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "MUSE_LANES_CONFIG": cfg},
                              accept="exit 5")
        st = self.wait_status(lid, "failed", timeout=20)
        nl = st.get("needs_lead")
        self.assertIsNotNone(nl)
        self.assertEqual(nl.get("kind"), "accept_failed_harness")
        self.assertEqual(nl.get("seq"), 1)
        self.assertIn("accept exit 5", nl.get("detail") or "")
        o = self.status_obj(lid)
        self.assertEqual(o["needs_lead"]["kind"], "accept_failed_harness")
        self.assertIs(o["needs_lead_announced"], False)
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("NEEDS LEAD", summ)
        self.assertIn("accept_failed_harness", summ)

    def test_exit_6_maps_to_box_wait_timeout_failed(self):
        cfg = self._cfg({"6": "box_wait_timeout"})
        b = self.write_brief("b1.md", "box timeout map work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "MUSE_LANES_CONFIG": cfg},
                              accept="exit 6")
        st = self.wait_status(lid, "failed", timeout=20)
        self.assertEqual(st["needs_lead"]["kind"], "box_wait_timeout")
        self.assertEqual(st["needs_lead"]["seq"], 1)

    def test_unmapped_exit_is_code(self):
        b = self.write_brief("b1.md", "code default work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              accept="exit 1")
        st = self.wait_status(lid, "failed", timeout=20)
        self.assertEqual(st["needs_lead"]["kind"], "accept_failed_code")
        self.assertIn("accept exit 1", st["needs_lead"]["detail"])


class TestNeedsLeadLine(LaneBase):
    def test_line_wins_over_exit_code(self):
        b = self.write_brief("b1.md", "line wins work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "complete"},
            accept="echo 'LANE-NEEDS-LEAD: accept_failed_harness gate exploded'; exit 1")
        st = self.wait_status(lid, "failed", timeout=20)
        self.assertEqual(st["needs_lead"]["kind"], "accept_failed_harness")
        self.assertIn("gate exploded", st["needs_lead"]["detail"])
        self.assertNotIn("accept exit 1", st["needs_lead"]["detail"])

    def test_last_line_wins(self):
        b = self.write_brief("b1.md", "last wins work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "complete"},
            accept="echo 'LANE-NEEDS-LEAD: accept_failed_harness first'; "
                   "echo 'LANE-NEEDS-LEAD: box_wait_timeout still queued'; exit 1")
        st = self.wait_status(lid, "failed", timeout=20)
        self.assertEqual(st["needs_lead"]["kind"], "box_wait_timeout")
        self.assertIn("still queued", st["needs_lead"]["detail"])

    def test_unknown_kind_becomes_code_with_raw_line(self):
        b = self.write_brief("b1.md", "unknown kind work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "complete"},
            accept="echo 'LANE-NEEDS-LEAD: frobnicate oops'; exit 1")
        st = self.wait_status(lid, "failed", timeout=20)
        self.assertEqual(st["needs_lead"]["kind"], "accept_failed_code")
        self.assertIn("LANE-NEEDS-LEAD: frobnicate oops", st["needs_lead"]["detail"])


class TestScopeViolation(LaneBase):
    def test_violation_ends_failed_with_paths(self):
        self.init_git_repo()
        with open(os.path.join(self.cwd, "evil.txt"), "w") as f:
            f.write("outside\n")
        b = self.write_brief("b1.md", "scope violation work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              scope=["allowed/*"])
        self.assertEqual(self.read_lane(lid).get("scope"), ["allowed/*"])
        st = self.wait_status(lid, "failed", timeout=20)
        self.assertEqual(st["needs_lead"]["kind"], "scope_violation")
        self.assertEqual(st["needs_lead"]["seq"], 1)
        self.assertIn("evil.txt", st["needs_lead"]["detail"])
        self.assertIn("scope violation", (st.get("reason") or "").lower())
        with open(self.lane_path(lid, "summary.md")) as f:
            self.assertIn("scope_violation", f.read())

    def test_allowed_paths_pass(self):
        self.init_git_repo()
        os.makedirs(os.path.join(self.cwd, "allowed"), exist_ok=True)
        with open(os.path.join(self.cwd, "allowed", "ok.txt"), "w") as f:
            f.write("inside\n")
        b = self.write_brief("b1.md", "scope pass work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              scope=["allowed/*", "seed.txt"])
        self.wait_status(lid, "done", timeout=20)
        self.assertIsNone(self.read_state(lid).get("needs_lead"))

    def test_no_scope_no_check(self):
        self.init_git_repo()
        with open(os.path.join(self.cwd, "evil.txt"), "w") as f:
            f.write("outside but unchecked\n")
        b = self.write_brief("b1.md", "no scope work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"})
        self.wait_status(lid, "done", timeout=20)
        self.assertIsNone(self.read_state(lid).get("needs_lead"))

    def test_committed_change_is_checked(self):
        self.init_git_repo()
        b = self.write_brief("b1.md", "committed scope work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "gitcommit"},
                              scope=["allowed/*"])
        st = self.wait_status(lid, "failed", timeout=25)
        self.assertEqual(st["needs_lead"]["kind"], "scope_violation")
        self.assertIn("lane-made.txt", st["needs_lead"]["detail"])

    def test_double_star_matches_nested(self):
        self.init_git_repo()
        os.makedirs(os.path.join(self.cwd, "src", "sub"), exist_ok=True)
        with open(os.path.join(self.cwd, "src", "sub", "b.py"), "w") as f:
            f.write("x=1\n")
        b = self.write_brief("b1.md", "globstar work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              scope=["src/**", "seed.txt"])
        self.wait_status(lid, "done", timeout=20)
        self.assertIsNone(self.read_state(lid).get("needs_lead"))


class TestAckLead(LaneBase):
    def test_ack_lead_exactly_once(self):
        b = self.write_brief("b1.md", "ack lead work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              accept="exit 1")
        self.wait_status(lid, "failed", timeout=20)
        o = self.status_obj(lid)
        self.assertEqual(o["needs_lead"]["seq"], 1)
        self.assertIs(o["needs_lead_announced"], False)
        a1 = self.run_lane("ack", lid, "--lead", "1")
        self.assertEqual(a1.returncode, 0, a1.stderr)
        self.assertTrue(os.path.exists(self.lane_path(lid, "announced-lead-1")))
        self.assertIs(self.status_obj(lid)["needs_lead_announced"], True)
        a2 = self.run_lane("ack", lid, "--lead", "1")
        self.assertEqual(a2.returncode, 3)
        a3 = self.run_lane("ack", lid, "--lead", "2")
        self.assertEqual(a3.returncode, 2)

    def test_ack_lead_without_needs_lead_refuses(self):
        b = self.write_brief("b1.md", "ack lead none work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"})
        self.wait_status(lid, "done", timeout=20)
        r = self.run_lane("ack", lid, "--lead", "1")
        self.assertEqual(r.returncode, 2)


class TestAnswerLead(LaneBase):
    def _mk_live_lane(self, lid, needs_lead):
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        ldir = os.path.join(self.lanes, lid)
        os.makedirs(ldir, exist_ok=True)
        lane = {"id": lid, "label": "L", "cwd": self.cwd, "briefs": ["b.md"],
                "created_at": now, "owner_session": None, "stall_sec": 2400,
                "env_file": None, "scope": [], "box": None,
                "config": {"accept_exit_kinds": {}}}
        state = {"status": "running", "step": 1, "steps": 1, "attempt": 1,
                 "supervisor_pid": None, "supervisor_started": None,
                 "muse_pid": None, "muse_started": None,
                 "started_at": now, "updated_at": now,
                 "last_activity_at": now, "last_event": None,
                 "head_start": None, "head": None, "commits": 0,
                 "stderr_tail": "", "accept_exit": None, "retry_at": None,
                 "reason": None, "phase": "step:1", "phase_started": now,
                 "review_rounds": [], "review_error": None, "consults": [],
                 "needs_lead": needs_lead, "needs_lead_seq": 1,
                 "box_state": None, "box_queued_at": None,
                 "evidence": None, "advisor_calls": 0}
        with open(os.path.join(ldir, "lane.json"), "w") as f:
            json.dump(lane, f)
        with open(os.path.join(ldir, "state.json"), "w") as f:
            json.dump(state, f)
        return ldir

    def test_answer_clears_question_and_logs(self):
        import datetime as _dt
        nl = {"seq": 1, "kind": "question", "Detail": "ESCALATE: pick one",
              "at": _dt.datetime.now(_dt.timezone.utc).isoformat(), "step": 1}
        lid = "lane-answer-q1"
        self._mk_live_lane(lid, nl)
        r = self.run_lane("answer", lid, "--text", "do the second thing")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.cwd, ".lane", "ANSWER.md")) as f:
            self.assertIn("do the second thing", f.read())
        with open(os.path.join(self.cwd, ".lane", "ANSWER-lead-1.md")) as f:
            self.assertIn("do the second thing", f.read())
        st = self.read_state(lid)
        self.assertIsNone(st.get("needs_lead"))
        self.assertEqual(st.get("needs_lead_seq"), 1)
        last = (st.get("consults") or [])[-1]
        self.assertEqual(last.get("by"), "lead")
        self.assertIn("do the second thing", last.get("answer_preview") or "")
        # Orphaned lane: state updated directly, no sidecars written.
        self.assertEqual([fn for fn in os.listdir(self.lane_path(lid))
                          if fn.startswith("lead-")], [])

    def test_answer_text_file(self):
        import datetime as _dt
        nl = {"seq": 4, "kind": "question", "Detail": "ESCALATE: which box",
              "at": _dt.datetime.now(_dt.timezone.utc).isoformat(), "step": 1}
        lid = "lane-answer-file"
        self._mk_live_lane(lid, nl)
        with open(os.path.join(self.root, "reply.txt"), "w") as f:
            f.write("use box seven")
        r = self.run_lane("answer", lid, "--text-file",
                          os.path.join(self.root, "reply.txt"))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.cwd, ".lane", "ANSWER-lead-4.md")) as f:
            self.assertIn("use box seven", f.read())
        self.assertIsNone(self.read_state(lid).get("needs_lead"))

    def test_answer_preserves_non_question(self):
        import datetime as _dt
        nl = {"seq": 2, "kind": "accept_failed_code", "Detail": "accept exit 1",
              "at": _dt.datetime.now(_dt.timezone.utc).isoformat(), "step": 1}
        lid = "lane-answer-keep"
        self._mk_live_lane(lid, nl)
        r = self.run_lane("answer", lid, "--text", "noted")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.read_state(lid)
        self.assertIsNotNone(st.get("needs_lead"))
        self.assertEqual(st["needs_lead"]["kind"], "accept_failed_code")

    def test_answer_refuses_ended_lane(self):
        b = self.write_brief("b1.md", "answer ended work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"})
        self.wait_status(lid, "done", timeout=20)
        r = self.run_lane("answer", lid, "--text", "too late")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ended", r.stderr.lower())


class TestOldStateV03(LaneBase):
    def test_old_state_without_v03_fields_lists(self):
        b = self.write_brief("b1.md", "old v03 state work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              box="box-1")
        self.wait_status(lid, "done", timeout=20)
        sp = self.lane_path(lid, "state.json")
        with open(sp) as f:
            cur = json.load(f)
        for k in ("needs_lead", "needs_lead_seq", "box_state", "box_queued_at",
                  "evidence", "advisor_calls"):
            cur.pop(k, None)
        with open(sp, "w") as f:
            json.dump(cur, f)
        lp = self.lane_path(lid, "lane.json")
        with open(lp) as f:
            lane = json.load(f)
        for k in ("config", "scope", "box"):
            lane.pop(k, None)
        with open(lp, "w") as f:
            json.dump(lane, f)
        o = self.status_obj(lid)
        self.assertEqual(o["status"], "done")
        self.assertIsNone(o["needs_lead"])
        self.assertIs(o["needs_lead_announced"], False)
        self.assertIsNone(o["box"])
        self.assertIsNone(o["evidence"])
        self.assertEqual(o["advisor_calls"], 0)
        self.assertIsNone(o["branch"])
        self.assertIsNone(o["head"])
        r2 = self.run_lane("summary", lid)
        self.assertEqual(r2.returncode, 0)


class TestReviewFailedNeedsLead(LaneBase):
    def test_review_fail_raises_needs_lead(self):
        b = self.write_brief("b1.md", "review needs lead work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "FAKE_REVIEW_VERDICT": "FAIL",
                                              "FAKE_REVIEW_FINDINGS": "1. bad.py:1 must fix"},
                              accept="exit 0", review=True, review_rounds=0)
        st = self.wait_status(lid, "review_failed", timeout=25)
        self.assertEqual(st["needs_lead"]["kind"], "review_failed")
        self.assertEqual(st["needs_lead"]["seq"], 1)
        self.assertIn("bad.py", st["needs_lead"]["detail"])
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("NEEDS LEAD", summ)
        self.assertIn("review_failed", summ)


class TestSummaryEvidence(LaneBase):
    def test_ready_to_merge_and_evidence(self):
        b = self.write_brief("b1.md", "ready merge work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              accept="exit 0")
        self.wait_status(lid, "done", timeout=20)
        o = self.status_obj(lid)
        ev = o.get("evidence")
        self.assertIsNotNone(ev)
        for k in ("branch", "head", "head_start", "commits", "accept_log",
                  "review_files", "summary_path"):
            self.assertIn(k, ev)
        self.assertIsInstance(ev["review_files"], list)
        self.assertTrue(ev["summary_path"].endswith("summary.md"))
        self.assertEqual(o["advisor_calls"], 0)
        self.assertIsNone(o["needs_lead"])
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("READY TO MERGE", summ)
        self.assertNotIn("NEEDS LEAD", summ)


class TestStatusV03Fields(LaneBase):
    def test_box_stored_and_shown(self):
        b = self.write_brief("b1.md", "box field work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              box="lab-box-2")
        self.assertEqual(self.read_lane(lid).get("box"), "lab-box-2")
        o = self.status_obj(lid)
        self.assertEqual(o["box"], "lab-box-2")
        self.assertIsNone(o["box_state"])
        self.assertIsNone(o["box_queued_at"])
        self.wait_status(lid, "done", timeout=20)

    def test_branch_head_live_only(self):
        self.init_git_repo()
        b = self.write_brief("b1.md", "live branch work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "sleeper",
                                              "FAKE_SLEEP": "60"})
        self.wait_status(lid, {"running", "retry_wait"}, timeout=15)
        o = self.status_obj(lid)
        self.assertIsNotNone(o["head"])
        self.assertIsNotNone(o["branch"])
        r = self.run_lane("stop", lid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.wait_status(lid, "stopped", timeout=20)
        o2 = self.status_obj(lid)
        self.assertIsNone(o2["branch"])
        # Ended lanes report the stored head (no git), as 0.2.3 did.
        self.assertEqual(o2["head"], self.read_state(lid).get("head"))
        self.assertIsNotNone(o2["head"])


class TestAdvisorStart(LaneBase):
    def test_no_flags_no_advisor(self):
        b = self.write_brief("b1.md", "no advisor work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"})
        self.assertIsNone(self.read_lane(lid).get("advisor"))
        self.wait_status(lid, "done", timeout=20)

    def test_model_only_defaults_max(self):
        b = self.write_brief("b1.md", "advisor model work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              advisor_model="opus")
        self.assertEqual(self.read_lane(lid).get("advisor"),
                         {"model": "opus", "max": 3})
        self.wait_status(lid, "done", timeout=20)

    def test_max_only_defaults_model(self):
        b = self.write_brief("b1.md", "advisor max work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              advisor_max=5)
        self.assertEqual(self.read_lane(lid).get("advisor"),
                         {"model": "sonnet", "max": 5})
        self.wait_status(lid, "done", timeout=20)

    def test_both_stored(self):
        b = self.write_brief("b1.md", "advisor both work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              advisor_model="opus", advisor_max=1)
        self.assertEqual(self.read_lane(lid).get("advisor"),
                         {"model": "opus", "max": 1})
        self.wait_status(lid, "done", timeout=20)

    def test_invalid_max_rejected(self):
        b = self.write_brief("b1.md", "bad advisor work")
        r = self.run_lane("start", "--cwd", self.cwd, "--brief", b,
                          "--advisor-max", "-1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("advisor-max", r.stderr)


class TestAdvisorUnits(LaneBase):
    def test_parse_escalate(self):
        mod = _load_lane_module()
        p = mod.parse_escalate_reason
        self.assertEqual(p("ESCALATE: pick one"), "pick one")
        self.assertEqual(p("\n\n  ESCALATE: spaced\nmore"), "spaced")
        self.assertIsNone(p("hello\nESCALATE: not first"))
        self.assertIsNone(p("Just a note about ESCALATE: x"))
        self.assertEqual(p("ESCALATE:"), "")
        self.assertIsNone(p(""))
        self.assertIsNone(p("   \n  \n"))
        self.assertIsNone(p("escalate: lower"))
        self.assertEqual(p("`ESCALATE: quoted`"), "quoted`")
        self.assertEqual(p("**ESCALATE: bold**"), "bold**")
        self.assertEqual(p("> ESCALATE: reply"), "reply")
        self.assertEqual(p("__ESCALATE: under__"), "under__")
        self.assertEqual(p("> `ESCALATE: combo`"), "combo`")
        self.assertIsNone(p("`escalate: lower quoted`"))
        self.assertIsNone(p("```\nESCALATE: fenced\n```"))

    def test_build_cmd_model_fill_and_override(self):
        mod = _load_lane_module()
        cmd = mod.build_advisor_cmd(None, "sonnet", None)
        self.assertEqual(cmd[0], "claude")
        self.assertIn("sonnet", cmd)
        self.assertNotIn("{model}", " ".join(cmd))
        custom = ["/usr/bin/claude", "-p", "--model", "{model}", "--extra"]
        out = mod.build_advisor_cmd(custom, "opus", "")
        self.assertEqual(out[0], "/usr/bin/claude")
        self.assertIn("opus", out)
        over = mod.build_advisor_cmd(custom, "opus", "/tmp/fake-claude")
        self.assertEqual(over[0], "/tmp/fake-claude")
        self.assertIn("opus", over)

    def test_build_prompt_has_accept_scope_rule(self):
        mod = _load_lane_module()
        txt = mod.build_advisor_prompt("How to test?\nPaths: foo.py",
                                       "ASK-1.md", "make check", ["src/**"], 1, 1)
        self.assertIn("How to test?", txt)
        self.assertIn("ASK-1.md", txt)
        self.assertIn("make check", txt)
        self.assertIn("src/**", txt)
        self.assertIn("may not change", txt)
        self.assertIn("ESCALATE:", txt)
        self.assertNotIn("`ESCALATE:", txt)


class TestAdvisorRouting(LaneBase):
    def test_routes_to_advisor(self):
        argv_file = os.path.join(self.state_dir, "argv-advisor.log")
        prompt_file = os.path.join(self.state_dir, "advisor-prompt.txt")
        b = self.write_brief("b1.md", "advisor route work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "ask", "FAKE_ASK_COUNT": "1",
                            "FAKE_CLAUDE_ANSWER": "ADVISOR-ANSWER-1",
                            "CLAUDE_BIN": self.fake_claude,
                            "FAKE_ARGV_FILE": argv_file,
                            "FAKE_CLAUDE_PROMPT_FILE": prompt_file},
            advisor_model="sonnet", advisor_max=3)
        self.wait_status(lid, "done", timeout=30)
        st = self.read_state(lid)
        consults = st.get("consults") or []
        self.assertEqual(len(consults), 1)
        self.assertEqual(consults[0].get("by"), "claude-sonnet")
        self.assertIs(consults[0].get("escalated"), False)
        self.assertTrue(consults[0].get("answered"))
        self.assertEqual(consults[0].get("helper"), "ok")
        self.assertEqual(st.get("advisor_calls"), 1)
        self.assertEqual(self.status_obj(lid).get("advisor_calls"), 1)
        with open(os.path.join(self.cwd, ".lane", "ANSWER.md")) as f:
            self.assertIn("ADVISOR-ANSWER-1", f.read())
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("by=claude-sonnet", summ)
        self.assertIn("escalated=False", summ)
        with open(argv_file) as f:
            argvs = [json.loads(ln) for ln in f.read().splitlines() if ln.strip()]
        claude_argvs = [a for a in argvs if a and a[0] == self.fake_claude]
        self.assertTrue(claude_argvs, "fake claude was never invoked")
        self.assertIn("sonnet", claude_argvs[0])
        with open(prompt_file) as f:
            prompt = f.read()
        self.assertIn("Question 1", prompt)
        self.assertIn("ESCALATE:", prompt)

    def test_budget_fallback_to_muse(self):
        b = self.write_brief("b1.md", "advisor fallback work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "ask", "FAKE_ASK_COUNT": "2",
                            "FAKE_CLAUDE_ANSWER": "ADVISOR-FIRST",
                            "FAKE_CONSULT_ANSWER": "MUSE-SECOND",
                            "CLAUDE_BIN": self.fake_claude},
            advisor_model="sonnet", advisor_max=1)
        self.wait_status(lid, "done", timeout=40)
        st = self.read_state(lid)
        consults = st.get("consults") or []
        self.assertEqual(len(consults), 2)
        self.assertEqual(consults[0].get("by"), "claude-sonnet")
        self.assertEqual(consults[1].get("by"), "muse")
        self.assertEqual(st.get("advisor_calls"), 1)
        with open(self.lane_path(lid, "step1-final.md")) as f:
            final = f.read()
        self.assertIn("ADVISOR-FIRST", final)
        self.assertIn("MUSE-SECOND", final)

    def test_model_fill_opus(self):
        argv_file = os.path.join(self.state_dir, "argv-opus.log")
        b = self.write_brief("b1.md", "opus fill work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "ask", "FAKE_ASK_COUNT": "1",
                            "FAKE_CLAUDE_ANSWER": "OPUS-ANS",
                            "CLAUDE_BIN": self.fake_claude,
                            "FAKE_ARGV_FILE": argv_file},
            advisor_model="opus", advisor_max=2)
        self.wait_status(lid, "done", timeout=30)
        st = self.read_state(lid)
        self.assertEqual((st.get("consults") or [])[0].get("by"), "claude-opus")
        with open(argv_file) as f:
            argvs = [json.loads(ln) for ln in f.read().splitlines() if ln.strip()]
        claude_argvs = [a for a in argvs if a and a[0] == self.fake_claude]
        self.assertTrue(claude_argvs)
        self.assertIn("opus", claude_argvs[0])
        self.assertNotIn("sonnet", claude_argvs[0])

    def test_claude_bin_override(self):
        cfg_path = os.path.join(self.root, "advisor-cfg.json")
        with open(cfg_path, "w") as f:
            json.dump({"advisor_cmd": ["/nonexistent-claude-xyz", "-p",
                                       "--model", "{model}"]}, f)
        argv_file = os.path.join(self.state_dir, "argv-override.log")
        b = self.write_brief("b1.md", "override work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "ask", "FAKE_ASK_COUNT": "1",
                            "MUSE_LANES_CONFIG": cfg_path,
                            "FAKE_CLAUDE_ANSWER": "OVERRIDE-OK",
                            "CLAUDE_BIN": self.fake_claude,
                            "FAKE_ARGV_FILE": argv_file},
            advisor_model="sonnet", advisor_max=1)
        self.wait_status(lid, "done", timeout=30)
        with open(os.path.join(self.cwd, ".lane", "ANSWER.md")) as f:
            self.assertIn("OVERRIDE-OK", f.read())
        with open(argv_file) as f:
            argvs = [json.loads(ln) for ln in f.read().splitlines() if ln.strip()]
        claude_argvs = [a for a in argvs if a and a[0] == self.fake_claude]
        self.assertTrue(claude_argvs, "override binary was not used")
        self.assertIn("sonnet", claude_argvs[0])

    def test_prompt_contains_accept_and_scope(self):
        prompt_file = os.path.join(self.state_dir, "advisor-prompt2.txt")
        b = self.write_brief("b1.md", "prompt content work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "ask", "FAKE_ASK_COUNT": "1",
                            "FAKE_CLAUDE_ANSWER": "PROMPT-OK",
                            "CLAUDE_BIN": self.fake_claude,
                            "FAKE_CLAUDE_PROMPT_FILE": prompt_file},
            advisor_max=1, accept="echo accept-marker-456; exit 0",
            scope=["src/**"])
        self.wait_status(lid, "done", timeout=30)
        with open(prompt_file) as f:
            prompt = f.read()
        self.assertIn("accept-marker-456", prompt)
        self.assertIn("src/**", prompt)
        self.assertIn("may not change", prompt)
        self.assertIn("ESCALATE:", prompt)
        self.assertIn("Question 1", prompt)


class TestAdvisorTimeoutCapWrites(LaneBase):
    def test_timeout(self):
        b = self.write_brief("b1.md", "advisor timeout work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "ask", "FAKE_ASK_COUNT": "1",
                            "FAKE_CLAUDE_SLEEP": "30",
                            "FAKE_CONSULT_ANSWER": "MUSE-TIMEOUT-FALLBACK",
                            "MUSE_LANE_ADVISOR_TIMEOUT_SEC": "1",
                            "CLAUDE_BIN": self.fake_claude},
            advisor_max=2)
        self.wait_status(lid, "done", timeout=30)
        st = self.read_state(lid)
        consults = st.get("consults") or []
        self.assertEqual(len(consults), 1)
        c = consults[0]
        # Non-dirty advisor failure falls back to the Muse helper, same n.
        self.assertEqual(c.get("by"), "muse")
        self.assertEqual(c.get("helper"), "ok")
        self.assertTrue(c.get("answered"))
        self.assertEqual(c.get("n"), 1)
        self.assertIn("exit ", c.get("advisor_error") or "")
        self.assertEqual(st.get("advisor_calls"), 1)
        with open(os.path.join(self.cwd, ".lane", "ANSWER.md")) as f:
            self.assertIn("MUSE-TIMEOUT-FALLBACK", f.read())
        with open(self.lane_path(lid, "summary.md")) as f:
            self.assertIn("advisor_error=exit ", f.read())

    def test_answer_cap_8000(self):
        b = self.write_brief("b1.md", "advisor cap work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "ask", "FAKE_ASK_COUNT": "1",
                            "FAKE_CLAUDE_ANSWER_LEN": "9000",
                            "CLAUDE_BIN": self.fake_claude},
            advisor_max=1)
        self.wait_status(lid, "done", timeout=30)
        with open(os.path.join(self.cwd, ".lane", "ANSWER.md")) as f:
            body = f.read().strip()
        self.assertEqual(len(body), 8000)
        self.assertEqual(body, "A" * 8000)
        with open(os.path.join(self.cwd, ".lane", "ANSWER-1.md")) as f:
            self.assertEqual(len(f.read().strip()), 8000)

    def test_advisor_edits_do_not_fail_lane(self):
        # No git before/after guard on the advisor call: Muse keeps
        # working while a consult runs, so its own edits would trip it.
        self.init_git_repo()
        tracked = os.path.join(self.cwd, "tracked.txt")
        with open(tracked, "w") as f:
            f.write("v1\n")
        subprocess.run(["git", "add", "."], cwd=self.cwd, capture_output=True,
                       timeout=15, check=True)
        subprocess.run(["git", "commit", "-m", "add tracked"], cwd=self.cwd,
                       capture_output=True, timeout=15, check=True)
        b = self.write_brief("b1.md", "advisor writes work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "ask", "FAKE_ASK_COUNT": "1",
                            "FAKE_CLAUDE_DIRTY": "1",
                            "FAKE_CLAUDE_DIRTY_FILE": "tracked.txt",
                            "FAKE_CLAUDE_ANSWER": "ADVISOR-WROTE-ANYWAY",
                            "CLAUDE_BIN": self.fake_claude},
            advisor_max=3)
        self.wait_status(lid, "done", timeout=30)
        st = self.read_state(lid)
        self.assertEqual(st.get("advisor_calls"), 1)
        consults = st.get("consults") or []
        self.assertEqual(len(consults), 1)
        self.assertTrue(consults[0].get("answered"))
        self.assertEqual(consults[0].get("by"), "claude-sonnet")
        with open(os.path.join(self.cwd, ".lane", "ANSWER.md")) as f:
            self.assertIn("ADVISOR-WROTE-ANYWAY", f.read())
        with open(tracked) as f:
            self.assertIn("advisor was here", f.read())


class TestEscalateQuestion(LaneBase):
    def test_advisor_escalate_raises_question(self):
        b = self.write_brief("b1.md", "advisor escalate work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "ask", "FAKE_ASK_COUNT": "1",
                            "FAKE_CLAUDE_ANSWER": "ESCALATE: pick the red box",
                            "CLAUDE_BIN": self.fake_claude},
            advisor_max=3)
        st = self.wait_status(lid, "done", timeout=30)
        nl = st.get("needs_lead")
        self.assertIsNotNone(nl)
        self.assertEqual(nl.get("kind"), "question")
        self.assertEqual(nl.get("seq"), 1)
        self.assertIn("pick the red box", nl.get("detail") or "")
        consults = st.get("consults") or []
        self.assertTrue(consults[0].get("escalated"))
        self.assertEqual(consults[0].get("by"), "claude-sonnet")
        self.assertTrue(consults[0].get("answered"))
        with open(os.path.join(self.cwd, ".lane", "ANSWER.md")) as f:
            body = f.read()
        self.assertIn("lead was asked", body.lower())
        self.assertIn("Keep working", body)
        self.assertIn("wait", body.lower())
        self.assertIn("ANSWER.md", body)
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("NEEDS LEAD", summ)
        self.assertIn("question", summ)
        self.assertIn("escalated=True", summ)

    def test_helper_escalate_raises_question(self):
        b = self.write_brief("b1.md", "helper escalate work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "ask",
                                              "FAKE_ASK_COUNT": "1",
                                              "FAKE_CONSULT_ANSWER": "ESCALATE: choose wisely"})
        st = self.wait_status(lid, "done", timeout=30)
        nl = st.get("needs_lead")
        self.assertIsNotNone(nl)
        self.assertEqual(nl.get("kind"), "question")
        self.assertEqual(nl.get("seq"), 1)
        self.assertIn("choose wisely", nl.get("detail") or "")
        consults = st.get("consults") or []
        self.assertTrue(consults[0].get("escalated"))
        self.assertEqual(consults[0].get("by"), "muse")
        with open(os.path.join(self.cwd, ".lane", "ANSWER.md")) as f:
            self.assertIn("lead was asked", f.read().lower())
        with open(self.lane_path(lid, "consult-brief-1.md")) as f:
            self.assertIn("ESCALATE:", f.read())

    def test_non_first_line_does_not_escalate(self):
        b = self.write_brief("b1.md", "no escalate work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "ask",
                                              "FAKE_ASK_COUNT": "1",
                                              "FAKE_CONSULT_ANSWER": "Just a note\nESCALATE: not first"})
        st = self.wait_status(lid, "done", timeout=30)
        self.assertIsNone(st.get("needs_lead"))
        consults = st.get("consults") or []
        self.assertIs(consults[0].get("escalated"), False)

    def test_seq_increments_two_escalates(self):
        b = self.write_brief("b1.md", "two escalates work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "ask", "FAKE_ASK_COUNT": "2",
                            "FAKE_CLAUDE_ANSWER": "ESCALATE: decide now",
                            "CLAUDE_BIN": self.fake_claude},
            advisor_max=3)
        st = self.wait_status(lid, "done", timeout=40)
        self.assertEqual(st.get("needs_lead", {}).get("seq"), 2)
        self.assertEqual(st.get("needs_lead", {}).get("kind"), "question")
        consults = st.get("consults") or []
        self.assertEqual(len(consults), 2)
        self.assertTrue(all(c.get("escalated") for c in consults))

    def test_answer_clears_escalated_question(self):
        b = self.write_brief("b1.md", "answer clears work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "sleeper", "FAKE_SLEEP": "60",
                            "FAKE_CLAUDE_ANSWER": "ESCALATE: which way",
                            "CLAUDE_BIN": self.fake_claude},
            advisor_max=3)
        self.wait_status(lid, {"running", "retry_wait"}, timeout=15)
        lane_dot = os.path.join(self.cwd, ".lane")
        os.makedirs(lane_dot, exist_ok=True)
        with open(os.path.join(lane_dot, "ASK.md"), "w") as f:
            f.write("Which way?\nPaths: foo.py\n")
        deadline = time.time() + 25
        nl = None
        while time.time() < deadline:
            try:
                nl = self.read_state(lid).get("needs_lead")
            except (FileNotFoundError, OSError, ValueError):
                nl = None
            if isinstance(nl, dict) and nl.get("kind") == "question":
                break
            time.sleep(0.2)
        self.assertIsNotNone(nl, "escalated question never raised")
        self.assertEqual(nl.get("seq"), 1)
        r = self.run_lane("answer", lid, "--text", "go left")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(lane_dot, "ANSWER.md")) as f:
            self.assertIn("go left", f.read())
        # Live supervisor: answer wrote sidecars, the supervisor merges
        # them on its next poll (state.json is never rewritten under it).
        deadline = time.time() + 15
        st = None
        while time.time() < deadline:
            try:
                st = self.read_state(lid)
            except (FileNotFoundError, OSError, ValueError):
                st = None
            if st is not None and st.get("needs_lead") is None:
                break
            time.sleep(0.2)
        self.assertIsNotNone(st)
        self.assertIsNone(st.get("needs_lead"))
        last = (st.get("consults") or [])[-1]
        self.assertEqual(last.get("by"), "lead")
        self.assertIn("go left", last.get("answer_preview") or "")
        merged = [fn for fn in os.listdir(self.lane_path(lid))
                  if fn.startswith("lead-") and fn.endswith(".merged")]
        self.assertTrue(merged, "no merged lead sidecar found")
        unmerged = [fn for fn in os.listdir(self.lane_path(lid))
                    if fn.startswith("lead-") and fn.endswith(".json")]
        self.assertEqual(unmerged, [])
        r2 = self.run_lane("stop", lid)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.wait_status(lid, "stopped", timeout=20)
        with open(self.lane_path(lid, "summary.md")) as f:
            self.assertIn("by=lead", f.read())


class TestBoxTicketUnits(LaneBase):
    def test_parse_ticket_name(self):
        mod = _load_lane_module()
        p = mod.parse_box_ticket_name
        self.assertEqual(p("20261106T120000.123456-lane-1"),
                         ("20261106T120000.123456", "lane-1"))
        self.assertEqual(p("0-dead"), ("0", "dead"))
        self.assertIsNone(p("nodash"))
        self.assertIsNone(p(""))
        self.assertIsNone(p("-lane"))
        self.assertIsNone(p("stamp-"))
        self.assertIsNone(p("a/b-lane"))

    def test_ticket_stamp_sorts(self):
        import datetime as _dt
        mod = _load_lane_module()
        a = mod.box_ticket_stamp(_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc))
        b = mod.box_ticket_stamp(_dt.datetime(2026, 6, 1, tzinfo=_dt.timezone.utc))
        self.assertLess(a, b)
        self.assertNotIn("-", a)

    def test_parse_leases(self):
        mod = _load_lane_module()
        claim = r"^(?P<at>\S+) CLAIM (?P<box>\S+) by (?P<who>[^:]+): (?P<what>.*)$"
        release = r"^(?P<at>\S+) RELEASE (?P<box>\S+) by "
        text = "\n".join([
            "2026-11-06T10:00:00 CLAIM box-a by alice: build 1",
            "2026-11-06T10:05:00 RELEASE box-a by alice",
            "2026-11-06T10:06:00 CLAIM box-b by bob: build 2",
        ])
        held, seen = mod.parse_box_leases(text, claim, release)
        self.assertEqual(seen, {"box-a", "box-b"})
        self.assertNotIn("box-a", held)
        self.assertEqual(held["box-b"], {"who": "bob", "what": "build 2",
                                         "since": "2026-11-06T10:06:00"})
        held2, _ = mod.parse_box_leases(
            text + "\n2026-11-06T10:07:00 CLAIM box-a by cara: build 3",
            claim, release)
        self.assertEqual(held2["box-a"]["who"], "cara")
        self.assertEqual(mod.parse_box_leases(text, None, release), ({}, set()))
        self.assertEqual(mod.parse_box_leases("", claim, release), ({}, set()))

    def test_format_advisor_error(self):
        mod = _load_lane_module()
        f = mod.format_advisor_error
        self.assertEqual(f(1, "boom\nlast err\n", "out"), "exit 1: last err")
        self.assertEqual(f(1, "", "only out\n"), "exit 1: only out")
        self.assertEqual(f(1, "  \n", "  "), "exit 1")
        self.assertEqual(f(None, "", ""), "exit ?")
        self.assertEqual(f(-15, "", ""), "exit -15")
        self.assertEqual(len(f(1, "x" * 500, "")), 300)
        self.assertIn("***", f(1, "leak SECRETVALUE12 here", "", ["SECRETVALUE12"]))
        self.assertNotIn("SECRETVALUE12",
                         f(1, "leak SECRETVALUE12 here", "", ["SECRETVALUE12"]))

    def test_lane_internal_paths(self):
        mod = _load_lane_module()
        self.assertTrue(mod._is_lane_internal_path(".lane/ASK.md"))
        self.assertTrue(mod._is_lane_internal_path(".lane"))
        self.assertFalse(mod._is_lane_internal_path(".lanefoo/x"))
        self.assertFalse(mod._is_lane_internal_path("allowed/x"))


class TestBoxQueueOrder(LaneBase):
    def test_two_lanes_strict_order_no_overlap(self):
        ts = os.path.join(self.state_dir, "accept-times.log")
        now = "$(python3 -c 'import time; print(time.time())')"
        b = self.write_brief("b1.md", "box order work")
        lid1 = self.start_lane(
            [b], env_extra={"FAKE_MODE": "complete"},
            accept="echo \"L1 START %s box=$LANE_BOX\" >> %s; sleep 4; "
                   "echo \"L1 END %s\" >> %s" % (now, ts, now, ts),
            box="box-q1")
        self.wait_state_field(lid1, "box_state", "held", timeout=15)
        lid2 = self.start_lane(
            [b], env_extra={"FAKE_MODE": "complete"},
            accept="echo \"L2 START %s box=$LANE_BOX\" >> %s; sleep 1; "
                   "echo \"L2 END %s\" >> %s" % (now, ts, now, ts),
            box="box-q1")
        self.wait_state_field(lid2, "box_state", "queued", timeout=15)
        self.assertEqual(self.read_state(lid2).get("phase"), "box_wait")
        self.assertTrue(self.read_state(lid2).get("box_queued_at"))
        r = self.run_lane("boxes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        by_box = {o["box"]: o for o in json.loads(r.stdout)}
        self.assertIn("box-q1", by_box)
        self.assertEqual(by_box["box-q1"]["holder_lane"], lid1)
        self.assertEqual(by_box["box-q1"]["queue"], [lid2])
        self.assertIsNone(by_box["box-q1"]["lease"])
        self.wait_status(lid1, "done", timeout=20)
        self.wait_status(lid2, "done", timeout=20)
        with open(ts) as f:
            lines = [ln.split() for ln in f.read().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 4)
        times = {}
        for parts in lines:
            self.assertEqual(len(parts), 4 if parts[1] == "START" else 3)
            times[(parts[0], parts[1])] = float(parts[2])
            if parts[1] == "START":
                self.assertEqual(parts[3], "box=box-q1")
        self.assertLess(times[("L1", "START")], times[("L1", "END")])
        self.assertLessEqual(times[("L1", "END")], times[("L2", "START")])
        self.assertLess(times[("L2", "START")], times[("L2", "END")])
        self.assertEqual(
            os.listdir(os.path.join(self.lanes, "_boxes", "box-q1")), [])


class TestBoxDeadTicket(LaneBase):
    def test_dead_ticket_does_not_block(self):
        box = "box-dead1"
        bdir = os.path.join(self.lanes, "_boxes", box)
        os.makedirs(bdir, exist_ok=True)
        dead = os.path.join(bdir, "20000101T000000.000000-gone-lane-xyz")
        with open(dead, "w") as f:
            f.write("{}\n")
        b = self.write_brief("b1.md", "dead ticket work")
        marker = os.path.join(self.state_dir, "accept-ran")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              accept="echo ran > %s" % marker, box=box)
        self.wait_status(lid, "done", timeout=20)
        self.assertTrue(os.path.exists(marker))
        self.assertTrue(os.path.exists(dead))
        self.assertEqual(os.listdir(bdir), [os.path.basename(dead)])


class TestBoxWaitTimeout(LaneBase):
    def test_timeout_raises_once_and_continues(self):
        ts = os.path.join(self.state_dir, "accept-times2.log")
        b = self.write_brief("b1.md", "box timeout work")
        lid1 = self.start_lane(
            [b], env_extra={"FAKE_MODE": "complete"},
            accept="echo H1START >> %s; sleep 6; echo H1END >> %s" % (ts, ts),
            box="box-t1")
        self.wait_state_field(lid1, "box_state", "held", timeout=15)
        lid2 = self.start_lane(
            [b], env_extra={"FAKE_MODE": "complete",
                            "MUSE_LANE_BOX_WAIT_MAX_SEC": "1"},
            accept="echo H2START >> %s; echo H2END >> %s" % (ts, ts),
            box="box-t1")
        deadline = time.time() + 15
        nl = None
        while time.time() < deadline:
            try:
                nl = self.read_state(lid2).get("needs_lead")
            except (FileNotFoundError, OSError, ValueError):
                nl = None
            if isinstance(nl, dict) and nl.get("kind") == "box_wait_timeout":
                break
            time.sleep(0.1)
        self.assertIsNotNone(nl, "box_wait_timeout never raised")
        self.assertEqual(nl.get("seq"), 1)
        self.assertIn("box-t1", nl.get("detail") or "")
        self.wait_status(lid2, "done", timeout=25)
        st2 = self.read_state(lid2)
        # Raised once, then cleared when the lane got its box: a done
        # lane never ends with a stale box_wait_timeout.
        self.assertIsNone(st2.get("needs_lead"))
        self.assertEqual(st2.get("needs_lead_seq"), 1)
        self.wait_status(lid1, "done", timeout=20)
        self.assertIsNone(self.read_state(lid1).get("needs_lead"))
        with open(ts) as f:
            order = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
        self.assertEqual(order, ["H1START", "H1END", "H2START", "H2END"])


class TestBoxStopAndFail(LaneBase):
    def test_stop_during_box_wait_removes_ticket(self):
        box = "box-s1"
        bdir = os.path.join(self.lanes, "_boxes", box)
        b = self.write_brief("b1.md", "box stop work")
        lid1 = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                               accept="sleep 30", box=box)
        self.wait_state_field(lid1, "box_state", "held", timeout=15)
        lid2 = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                               accept="exit 0", box=box)
        self.wait_state_field(lid2, "box_state", "queued", timeout=15)
        self.assertEqual(len(os.listdir(bdir)), 2)
        r = self.run_lane("stop", lid2)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.wait_status(lid2, "stopped", timeout=20)
        remaining = os.listdir(bdir)
        self.assertEqual(len(remaining), 1)
        self.assertIn(lid1, remaining[0])
        r = self.run_lane("stop", lid1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.wait_status(lid1, "stopped", timeout=20)
        self.assertEqual(os.listdir(bdir), [])

    def test_failed_accept_removes_ticket(self):
        box = "box-f1"
        b = self.write_brief("b1.md", "box fail work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              accept="exit 1", box=box)
        st = self.wait_status(lid, "failed", timeout=20)
        self.assertEqual(st["needs_lead"]["kind"], "accept_failed_code")
        self.assertEqual(os.listdir(os.path.join(self.lanes, "_boxes", box)), [])


class TestAnswerBox(LaneBase):
    def _mk_lane(self, lid, box, needs_lead, status="running"):
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        ldir = os.path.join(self.lanes, lid)
        os.makedirs(ldir, exist_ok=True)
        lane = {"id": lid, "label": "L", "cwd": self.cwd, "briefs": ["b.md"],
                "created_at": now, "owner_session": None, "stall_sec": 2400,
                "env_file": None, "scope": [], "box": box,
                "config": {"accept_exit_kinds": {}}}
        state = {"status": status, "step": 1, "steps": 1, "attempt": 1,
                 "supervisor_pid": None, "supervisor_started": None,
                 "muse_pid": None, "muse_started": None,
                 "started_at": now, "updated_at": now,
                 "last_activity_at": now, "last_event": None,
                 "head_start": None, "head": None, "commits": 0,
                 "stderr_tail": "", "accept_exit": None, "retry_at": None,
                 "reason": None, "phase": "box_wait", "phase_started": now,
                 "review_rounds": [], "review_error": None, "consults": [],
                 "needs_lead": needs_lead, "needs_lead_seq": 1,
                 "box_state": "queued", "box_queued_at": now,
                 "evidence": None, "advisor_calls": 0}
        with open(os.path.join(ldir, "lane.json"), "w") as f:
            json.dump(lane, f)
        with open(os.path.join(ldir, "state.json"), "w") as f:
            json.dump(state, f)
        return ldir

    def _mk_ticket(self, box, name):
        bdir = os.path.join(self.lanes, "_boxes", box)
        os.makedirs(bdir, exist_ok=True)
        with open(os.path.join(bdir, name), "w") as f:
            f.write("{}\n")

    def test_box_moves_ticket_and_clears_timeout(self):
        import datetime as _dt
        lid = "lane-box-move"
        nl = {"seq": 3, "kind": "box_wait_timeout", "detail": "box box-a: queued",
              "at": _dt.datetime.now(_dt.timezone.utc).isoformat(), "step": 1}
        self._mk_lane(lid, "box-a", nl)
        ticket = "20260101T000000.000000-%s" % lid
        self._mk_ticket("box-a", ticket)
        r = self.run_lane("answer", lid, "--box", "box-b")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(
            os.path.join(self.lanes, "_boxes", "box-a", ticket)))
        # Fresh stamp (now): the moved ticket joins the BACK of box-b.
        names = os.listdir(os.path.join(self.lanes, "_boxes", "box-b"))
        self.assertEqual(len(names), 1)
        self.assertNotEqual(names[0], ticket)
        self.assertTrue(names[0].endswith("-" + lid))
        self.assertGreater(names[0].split("-", 1)[0],
                           ticket.split("-", 1)[0])
        self.assertEqual(self.read_lane(lid).get("box"), "box-b")
        st = self.read_state(lid)
        self.assertIsNone(st.get("needs_lead"))
        self.assertEqual(st.get("needs_lead_seq"), 1)
        self.assertEqual(st.get("consults"), [])
        self.assertFalse(os.path.exists(os.path.join(self.cwd, ".lane", "ANSWER.md")))

    def test_box_without_ticket_sets_box(self):
        import datetime as _dt
        lid = "lane-box-naked"
        nl = {"seq": 1, "kind": "box_wait_timeout", "detail": "queued",
              "at": _dt.datetime.now(_dt.timezone.utc).isoformat(), "step": 1}
        self._mk_lane(lid, "box-a", nl)
        r = self.run_lane("answer", lid, "--box", "box-c")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_lane(lid).get("box"), "box-c")
        self.assertIsNone(self.read_state(lid).get("needs_lead"))
        self.assertEqual([fn for fn in os.listdir(self.lane_path(lid))
                          if fn.startswith("lead-")], [])

    def test_box_combined_with_text(self):
        import datetime as _dt
        lid = "lane-box-both"
        nl = {"seq": 2, "kind": "question", "detail": "ESCALATE: pick",
              "at": _dt.datetime.now(_dt.timezone.utc).isoformat(), "step": 1}
        self._mk_lane(lid, "box-a", nl)
        ticket = "20260101T000000.000000-%s" % lid
        self._mk_ticket("box-a", ticket)
        r = self.run_lane("answer", lid, "--text", "go left", "--box", "box-b")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.cwd, ".lane", "ANSWER.md")) as f:
            self.assertIn("go left", f.read())
        names = os.listdir(os.path.join(self.lanes, "_boxes", "box-b"))
        self.assertEqual(len(names), 1)
        self.assertNotEqual(names[0], ticket)
        self.assertTrue(names[0].endswith("-" + lid))
        self.assertEqual(self.read_lane(lid).get("box"), "box-b")
        st = self.read_state(lid)
        self.assertIsNone(st.get("needs_lead"))
        self.assertEqual((st.get("consults") or [])[-1].get("by"), "lead")

    def test_box_refuses_ended_lane(self):
        lid = "lane-box-ended"
        self._mk_lane(lid, "box-a", None, status="done")
        r = self.run_lane("answer", lid, "--box", "box-b")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ended", r.stderr.lower())

    def test_box_move_unblocks_waiter_live(self):
        ts = os.path.join(self.state_dir, "accept-times3.log")
        b = self.write_brief("b1.md", "box move live work")
        lid1 = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                               accept="sleep 10", box="box-m1")
        self.wait_state_field(lid1, "box_state", "held", timeout=15)
        lid2 = self.start_lane(
            [b], env_extra={"FAKE_MODE": "complete",
                            "MUSE_LANE_BOX_WAIT_MAX_SEC": "1"},
            accept="echo MOVED-RAN >> %s" % ts, box="box-m1")
        deadline = time.time() + 15
        nl = None
        while time.time() < deadline:
            try:
                nl = self.read_state(lid2).get("needs_lead")
            except (FileNotFoundError, OSError, ValueError):
                nl = None
            if isinstance(nl, dict) and nl.get("kind") == "box_wait_timeout":
                break
            time.sleep(0.1)
        self.assertIsNotNone(nl, "box_wait_timeout never raised")
        r = self.run_lane("answer", lid2, "--box", "box-m2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_lane(lid2).get("box"), "box-m2")
        self.wait_status(lid2, "done", timeout=20)
        st2 = self.read_state(lid2)
        self.assertIsNone(st2.get("needs_lead"))
        self.assertTrue(os.path.exists(ts))
        st1 = self.read_state(lid1)
        self.assertNotIn(st1.get("status"), ("done", "failed", "gave_up", "stopped"))
        r = self.run_lane("stop", lid1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.wait_status(lid1, "stopped", timeout=20)
        self.assertEqual(
            os.listdir(os.path.join(self.lanes, "_boxes", "box-m2")), [])


class TestBoxesJson(LaneBase):
    def _lease_cfg(self, lease_path):
        p = os.path.join(self.root, "lease-cfg.json")
        with open(p, "w") as f:
            json.dump({
                "lease_file": lease_path,
                "lease_claim_re": r"^(?P<at>\S+) CLAIM (?P<box>\S+) by (?P<who>[^:]+): (?P<what>.*)$",
                "lease_release_re": r"^(?P<at>\S+) RELEASE (?P<box>\S+) by ",
            }, f)
        return p

    def test_leases_and_dead_tickets(self):
        leases = os.path.join(self.root, "LEASES.md")
        with open(leases, "w") as f:
            f.write("\n".join([
                "2026-11-06T10:00:00 CLAIM lab-1 by alice: build 9",
                "2026-11-06T10:05:00 RELEASE lab-1 by alice",
                "2026-11-06T10:06:00 CLAIM lab-2 by bob: build 10",
                "",
            ]))
        cfg = self._lease_cfg(leases)
        bdir = os.path.join(self.lanes, "_boxes", "lab-3")
        os.makedirs(bdir, exist_ok=True)
        with open(os.path.join(bdir, "0-gone-lane"), "w") as f:
            f.write("{}\n")
        r = self.run_lane("boxes", "--json", env_extra={"MUSE_LANES_CONFIG": cfg})
        self.assertEqual(r.returncode, 0, r.stderr)
        by_box = {o["box"]: o for o in json.loads(r.stdout)}
        self.assertEqual(set(by_box), {"lab-1", "lab-2", "lab-3"})
        self.assertIsNone(by_box["lab-1"]["lease"])
        self.assertEqual(by_box["lab-2"]["lease"],
                         {"who": "bob", "what": "build 10",
                          "since": "2026-11-06T10:06:00"})
        self.assertIsNone(by_box["lab-3"]["lease"])
        self.assertIsNone(by_box["lab-3"]["holder_lane"])
        self.assertEqual(by_box["lab-3"]["queue"], [])
        self.assertIsNone(by_box["lab-1"]["holder_lane"])

    def test_missing_lease_file_is_null(self):
        cfg = self._lease_cfg(os.path.join(self.root, "no-such-leases.md"))
        bdir = os.path.join(self.lanes, "_boxes", "lab-9")
        os.makedirs(bdir, exist_ok=True)
        with open(os.path.join(bdir, "0-gone-lane"), "w") as f:
            f.write("{}\n")
        r = self.run_lane("boxes", "--json", env_extra={"MUSE_LANES_CONFIG": cfg})
        self.assertEqual(r.returncode, 0, r.stderr)
        by_box = {o["box"]: o for o in json.loads(r.stdout)}
        self.assertEqual(set(by_box), {"lab-9"})
        self.assertIsNone(by_box["lab-9"]["lease"])


class TestNoPgrep(LaneBase):
    def test_runner_never_matches_process_names(self):
        with open(LANE) as f:
            src = f.read()
        for banned in ("pgrep", "ps -f", "ps aux", "ps -ef"):
            self.assertNotIn(banned, src)


class TestScopeLaneDir(LaneBase):
    def test_lane_dir_files_are_not_violations(self):
        self.init_git_repo()
        b = self.write_brief("b1.md", "lane dir scope work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "writescope"},
                              scope=["allowed/*"])
        st = self.wait_status(lid, "done", timeout=25)
        self.assertIsNone(st.get("needs_lead"))
        self.assertTrue(os.path.isdir(os.path.join(self.cwd, ".lane")))
        r = subprocess.run(["git", "status", "--porcelain"], cwd=self.cwd,
                           capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0)
        self.assertIn(".lane/", r.stdout)


class TestAdvisorFallback(LaneBase):
    def test_exit_1_falls_back_to_muse(self):
        b = self.write_brief("b1.md", "advisor fallback work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "ask", "FAKE_ASK_COUNT": "1",
                            "FAKE_CLAUDE_EXIT": "1",
                            "FAKE_CLAUDE_ANSWER": "You've hit your weekly limit",
                            "FAKE_CONSULT_ANSWER": "MUSE-FALLBACK-77",
                            "CLAUDE_BIN": self.fake_claude},
            advisor_max=3)
        st = self.wait_status(lid, "done", timeout=30)
        consults = st.get("consults") or []
        self.assertEqual(len(consults), 1)
        c = consults[0]
        self.assertEqual(c.get("by"), "muse")
        self.assertEqual(c.get("helper"), "ok")
        self.assertTrue(c.get("answered"))
        self.assertEqual(c.get("n"), 1)
        self.assertIn("exit 1", c.get("advisor_error") or "")
        self.assertIn("weekly limit", c.get("advisor_error") or "")
        self.assertEqual(st.get("advisor_calls"), 1)
        with open(os.path.join(self.cwd, ".lane", "ANSWER.md")) as f:
            self.assertIn("MUSE-FALLBACK-77", f.read())
        with open(self.lane_path(lid, "step1-final.md")) as f:
            self.assertIn("MUSE-FALLBACK-77", f.read())
        with open(self.lane_path(lid, "summary.md")) as f:
            summ = f.read()
        self.assertIn("advisor_error=exit 1", summ)
        self.assertIn("weekly limit", summ)


class TestBoxMoveFreshStampLive(LaneBase):
    def test_waiter_adopts_fresh_stamp(self):
        ts = os.path.join(self.state_dir, "accept-fs.log")
        b = self.write_brief("b1.md", "fresh stamp live work")
        lid1 = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                               accept="sleep 8", box="box-fs1")
        self.wait_state_field(lid1, "box_state", "held", timeout=15)
        lid2 = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                               accept="echo FS-RAN >> %s" % ts, box="box-fs1")
        self.wait_state_field(lid2, "box_state", "queued", timeout=15)
        olds = [fn for fn in os.listdir(os.path.join(self.lanes, "_boxes", "box-fs1"))
                if fn.endswith("-" + lid2)]
        self.assertEqual(len(olds), 1)
        r = self.run_lane("answer", lid2, "--box", "box-fs2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_lane(lid2).get("box"), "box-fs2")
        news = os.listdir(os.path.join(self.lanes, "_boxes", "box-fs2"))
        self.assertEqual(len(news), 1)
        self.assertNotEqual(news[0], olds[0])
        self.assertGreater(news[0].split("-", 1)[0], olds[0].split("-", 1)[0])
        self.wait_status(lid2, "done", timeout=20)
        self.assertTrue(os.path.exists(ts))
        self.assertEqual(os.listdir(os.path.join(self.lanes, "_boxes", "box-fs2")), [])
        r = self.run_lane("stop", lid1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.wait_status(lid1, "stopped", timeout=20)


class TestAnswerBoxHeld(LaneBase):
    def _mk_lane(self, lid, box_state):
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        ldir = os.path.join(self.lanes, lid)
        os.makedirs(ldir, exist_ok=True)
        lane = {"id": lid, "label": "L", "cwd": self.cwd, "briefs": ["b.md"],
                "created_at": now, "owner_session": None, "stall_sec": 2400,
                "env_file": None, "scope": [], "box": "box-h1",
                "config": {"accept_exit_kinds": {}}}
        state = {"status": "running", "step": 1, "steps": 1, "attempt": 1,
                 "supervisor_pid": None, "supervisor_started": None,
                 "muse_pid": None, "muse_started": None,
                 "started_at": now, "updated_at": now,
                 "last_activity_at": now, "last_event": None,
                 "head_start": None, "head": None, "commits": 0,
                 "stderr_tail": "", "accept_exit": None, "retry_at": None,
                 "reason": None, "phase": "accept", "phase_started": now,
                 "review_rounds": [], "review_error": None, "consults": [],
                 "needs_lead": None, "needs_lead_seq": 0,
                 "box_state": box_state, "box_queued_at": now,
                 "evidence": None, "advisor_calls": 0}
        with open(os.path.join(ldir, "lane.json"), "w") as f:
            json.dump(lane, f)
        with open(os.path.join(ldir, "state.json"), "w") as f:
            json.dump(state, f)
        return ldir

    def test_box_refused_while_held(self):
        lid = "lane-held-refuse"
        self._mk_lane(lid, "held")
        bdir = os.path.join(self.lanes, "_boxes", "box-h1")
        os.makedirs(bdir, exist_ok=True)
        ticket = "20260101T000000.000000-%s" % lid
        with open(os.path.join(bdir, ticket), "w") as f:
            f.write("{}\n")
        r = self.run_lane("answer", lid, "--box", "box-h2")
        self.assertEqual(r.returncode, 2)
        self.assertIn("held", r.stderr.lower())
        self.assertEqual(self.read_lane(lid).get("box"), "box-h1")
        self.assertTrue(os.path.exists(os.path.join(bdir, ticket)))
        self.assertFalse(os.path.exists(os.path.join(self.lanes, "_boxes", "box-h2")))

    def test_box_refused_while_held_with_text(self):
        lid = "lane-held-both"
        self._mk_lane(lid, "held")
        r = self.run_lane("answer", lid, "--text", "go left", "--box", "box-h2")
        self.assertEqual(r.returncode, 2)
        self.assertIn("held", r.stderr.lower())
        self.assertFalse(os.path.exists(os.path.join(self.cwd, ".lane", "ANSWER.md")))
        self.assertEqual(self.read_lane(lid).get("box"), "box-h1")

    def test_held_clears_open_timeout_live(self):
        ts = os.path.join(self.state_dir, "accept-held.log")
        b = self.write_brief("b1.md", "held clears work")
        lid1 = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                               accept="sleep 5", box="box-hc1")
        self.wait_state_field(lid1, "box_state", "held", timeout=15)
        lid2 = self.start_lane(
            [b], env_extra={"FAKE_MODE": "complete",
                            "MUSE_LANE_BOX_WAIT_MAX_SEC": "1"},
            accept="echo HC-RAN >> %s; sleep 3" % ts, box="box-hc1")
        deadline = time.time() + 15
        nl = None
        while time.time() < deadline:
            try:
                nl = self.read_state(lid2).get("needs_lead")
            except (FileNotFoundError, OSError, ValueError):
                nl = None
            if isinstance(nl, dict) and nl.get("kind") == "box_wait_timeout":
                break
            time.sleep(0.1)
        self.assertIsNotNone(nl, "box_wait_timeout never raised")
        # When the waiting lane gets its box, the open timeout clears at
        # once: held and cleared land in the same state write.
        self.wait_state_field(lid2, "box_state", "held", timeout=20)
        st = self.read_state(lid2)
        self.assertEqual(st.get("box_state"), "held")
        self.assertIsNone(st.get("needs_lead"))
        self.assertEqual(st.get("needs_lead_seq"), 1)
        self.wait_status(lid2, "done", timeout=20)
        self.assertIsNone(self.read_state(lid2).get("needs_lead"))
        self.assertTrue(os.path.exists(ts))
        self.wait_status(lid1, "done", timeout=20)


class TestAdvisorToolsRefusal(LaneBase):
    def test_forbidden_tool_units(self):
        mod = _load_lane_module()
        f = mod.advisor_cmd_forbidden_tool
        self.assertIsNone(f(None))
        self.assertIsNone(f([]))
        self.assertIsNone(f(list(mod.DEFAULT_ADVISOR_CMD)))
        self.assertIsNone(f(["claude", "-p", "--model", "x"]))
        self.assertIsNone(f(["claude", "--tools"]))
        self.assertIsNone(f(["claude", "--tools", "Read,Grep,Glob"]))
        self.assertIsNone(f(["claude", "--tools", "Read,Editx"]))
        self.assertEqual(f(["claude", "--tools", "Read,Bash"]), "Bash")
        self.assertEqual(f(["claude", "--tools=Bash"]), "Bash")
        self.assertEqual(f(["claude", "--tools", "Edit"]), "Edit")
        self.assertEqual(f(["claude", "--tools", "Read, Write"]), "Write")
        self.assertEqual(f(["claude", "--tools", "Read,NotebookEdit"]), "NotebookEdit")

    def test_start_refuses_each_tool(self):
        b = self.write_brief("b1.md", "bad tools work")
        for tool in ("Bash", "Edit", "Write", "NotebookEdit"):
            cfg_path = os.path.join(self.root, "tools-%s.json" % tool)
            with open(cfg_path, "w") as f:
                json.dump({"advisor_cmd": ["claude", "-p", "--model", "{model}",
                                           "--tools", "Read,%s" % tool]}, f)
            r = self.run_lane("start", "--cwd", self.cwd, "--brief", b,
                              env_extra={"MUSE_LANES_CONFIG": cfg_path})
            self.assertNotEqual(r.returncode, 0, tool)
            self.assertIn(tool, r.stderr)
        cfg_eq = os.path.join(self.root, "tools-eq.json")
        with open(cfg_eq, "w") as f:
            json.dump({"advisor_cmd": ["claude", "--tools=Write"]}, f)
        r = self.run_lane("start", "--cwd", self.cwd, "--brief", b,
                          env_extra={"MUSE_LANES_CONFIG": cfg_eq})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Write", r.stderr)

    def test_start_allows_readonly_tools(self):
        cfg_path = os.path.join(self.root, "tools-ok.json")
        with open(cfg_path, "w") as f:
            json.dump({"advisor_cmd": ["claude", "-p", "--model", "{model}",
                                       "--tools", "Read,Grep,Glob"]}, f)
        b = self.write_brief("b1.md", "good tools work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete",
                                              "MUSE_LANES_CONFIG": cfg_path})
        self.assertIn("Read,Grep,Glob",
                      self.read_lane(lid)["config"]["advisor_cmd"])
        self.wait_status(lid, "done", timeout=20)


class TestStaleTicketCleanup(LaneBase):
    def _mk_ticket(self, box, name):
        bdir = os.path.join(self.lanes, "_boxes", box)
        os.makedirs(bdir, exist_ok=True)
        p = os.path.join(bdir, name)
        with open(p, "w") as f:
            f.write("{}\n")
        return p

    def test_start_removes_own_stale_tickets(self):
        lid = "lane-s1-start"
        stale = [self._mk_ticket(box, "20200101T000000.000000-%s" % lid)
                 for box in ("box-s1a", "box-s1b")]
        b = self.write_brief("b1.md", "stale start work")
        lid2 = self.start_lane([b], env_extra={"FAKE_MODE": "complete"}, id=lid)
        self.assertEqual(lid2, lid)
        deadline = time.time() + 10
        while time.time() < deadline:
            if not any(os.path.exists(p) for p in stale):
                break
            time.sleep(0.1)
        self.assertFalse(any(os.path.exists(p) for p in stale),
                         "stale tickets survived start")
        self.wait_status(lid, "done", timeout=20)

    def test_resume_removes_own_stale_tickets(self):
        import datetime as _dt
        lid = "lane-s1-resume"
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        ldir = os.path.join(self.lanes, lid)
        os.makedirs(ldir, exist_ok=True)
        lane = {"id": lid, "label": "L", "cwd": self.cwd, "briefs": ["b.md"],
                "created_at": now, "owner_session": None, "stall_sec": 2400,
                "env_file": None, "scope": [], "box": None,
                "config": {"accept_exit_kinds": {}}}
        state = {"status": "running", "step": 1, "steps": 1, "attempt": 1,
                 "supervisor_pid": None, "supervisor_started": None,
                 "muse_pid": None, "muse_started": None,
                 "started_at": now, "updated_at": now,
                 "last_activity_at": now, "last_event": None,
                 "head_start": None, "head": None, "commits": 0,
                 "stderr_tail": "", "accept_exit": None, "retry_at": None,
                 "reason": None, "phase": "step:1", "phase_started": now,
                 "review_rounds": [], "review_error": None, "consults": [],
                 "needs_lead": None, "needs_lead_seq": 0,
                 "box_state": None, "box_queued_at": None,
                 "evidence": None, "advisor_calls": 0}
        with open(os.path.join(ldir, "lane.json"), "w") as f:
            json.dump(lane, f)
        with open(os.path.join(ldir, "state.json"), "w") as f:
            json.dump(state, f)
        stale = self._mk_ticket("box-s1r", "20200101T000000.000000-%s" % lid)
        r = self.run_lane("resume", lid, env_extra={"FAKE_MODE": "complete"})
        self.assertEqual(r.returncode, 0, r.stderr)
        deadline = time.time() + 10
        while time.time() < deadline:
            if not os.path.exists(stale):
                break
            time.sleep(0.1)
        self.assertFalse(os.path.exists(stale), "stale ticket survived resume")
        self.wait_status(lid, "done", timeout=20)


class TestLeadSidecarUnits(LaneBase):
    def test_should_apply_lead_clear(self):
        mod = _load_lane_module()
        f = mod.should_apply_lead_clear
        cur = {"seq": 2, "kind": "question"}
        self.assertTrue(f(cur, "question", 2))
        self.assertTrue(f(cur, None, 2))
        self.assertFalse(f(cur, "question", 3))
        self.assertFalse(f(cur, "box_wait_timeout", 2))
        self.assertFalse(f(None, "question", 2))
        self.assertFalse(f({"seq": 2}, "question", "x"))
        self.assertFalse(f("question", "question", 2))

    def test_write_lead_sidecar_names(self):
        mod = _load_lane_module()
        ldir = os.path.join(self.root, "sidedir")
        os.makedirs(ldir, exist_ok=True)
        p1 = mod.write_lead_sidecar(ldir, "clear", {"kind": "question", "seq": 1})
        p2 = mod.write_lead_sidecar(ldir, "consult", {"entry": {"n": 1}})
        self.assertTrue(os.path.basename(p1).startswith("lead-"))
        self.assertTrue(p1.endswith("-1.json"))
        self.assertTrue(p2.endswith("-2.json"))
        with open(p1) as f:
            sc = json.load(f)
        self.assertEqual(sc["kind"], "clear")
        self.assertEqual(sc["payload"], {"kind": "question", "seq": 1})


class TestEscalateStrippedE2E(LaneBase):
    def test_backticked_escalate_raises_question(self):
        b = self.write_brief("b1.md", "quoted escalate work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "ask",
                                              "FAKE_ASK_COUNT": "1",
                                              "FAKE_CONSULT_ANSWER": "`ESCALATE: quoted pick`"})
        st = self.wait_status(lid, "done", timeout=30)
        nl = st.get("needs_lead")
        self.assertIsNotNone(nl)
        self.assertEqual(nl.get("kind"), "question")
        self.assertIn("quoted pick", nl.get("detail") or "")
        consults = st.get("consults") or []
        self.assertTrue(consults[0].get("escalated"))
        with open(self.lane_path(lid, "consult-brief-1.md")) as f:
            brief = f.read()
        self.assertIn("ESCALATE:", brief)
        self.assertNotIn("`ESCALATE:", brief)


class TestScopeNulSeparated(LaneBase):
    def test_parse_porcelain_z_fields(self):
        mod = _load_lane_module()
        f = mod._parse_porcelain_z_fields
        self.assertEqual(f(["R  new.txt", "old.txt"]), ["new.txt", "old.txt"])
        self.assertEqual(f(["M  a.py", "?? b.py"]), ["a.py", "b.py"])
        self.assertEqual(f(["R  n", "o", "M  m"]), ["n", "o", "m"])
        self.assertEqual(f([]), [])
        self.assertEqual(f(["short"]), [])

    def test_non_ascii_in_scope_passes(self):
        self.init_git_repo()
        os.makedirs(os.path.join(self.cwd, "src"), exist_ok=True)
        with open(os.path.join(self.cwd, "src", "caf\u00e9.py"), "w") as f:
            f.write("x = 1\n")
        b = self.write_brief("b1.md", "nonascii scope work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              scope=["src/*.py"])
        self.wait_status(lid, "done", timeout=20)
        self.assertIsNone(self.read_state(lid).get("needs_lead"))

    def test_untracked_dir_files_match_passes(self):
        self.init_git_repo()
        os.makedirs(os.path.join(self.cwd, "src"), exist_ok=True)
        with open(os.path.join(self.cwd, "src", "a.py"), "w") as f:
            f.write("x = 1\n")
        b = self.write_brief("b1.md", "untracked dir work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              scope=["src/*.py"])
        self.wait_status(lid, "done", timeout=20)
        self.assertIsNone(self.read_state(lid).get("needs_lead"))

    def test_rename_from_outside_scope_violates(self):
        self.init_git_repo()
        with open(os.path.join(self.cwd, "outside.txt"), "w") as f:
            f.write("v1\n")
        subprocess.run(["git", "add", "."], cwd=self.cwd, capture_output=True,
                       timeout=15, check=True)
        subprocess.run(["git", "commit", "-m", "add outside"], cwd=self.cwd,
                       capture_output=True, timeout=15, check=True)
        os.makedirs(os.path.join(self.cwd, "src"), exist_ok=True)
        subprocess.run(["git", "mv", "outside.txt", "src/inside.py"], cwd=self.cwd,
                       capture_output=True, timeout=15, check=True)
        b = self.write_brief("b1.md", "rename scope work")
        lid = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                              scope=["src/*.py"])
        st = self.wait_status(lid, "failed", timeout=20)
        self.assertEqual(st["needs_lead"]["kind"], "scope_violation")
        self.assertIn("outside.txt", st["needs_lead"]["detail"])


class TestBoxMoveResetsTimer(LaneBase):
    def test_move_resets_wait_timer(self):
        b = self.write_brief("b1.md", "timer reset work")
        lidA = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                               accept="sleep 10", box="box-s7a")
        self.wait_state_field(lidA, "box_state", "held", timeout=15)
        lidC = self.start_lane([b], env_extra={"FAKE_MODE": "complete"},
                               accept="sleep 15", box="box-s7c")
        self.wait_state_field(lidC, "box_state", "held", timeout=15)
        lidB = self.start_lane(
            [b], env_extra={"FAKE_MODE": "complete",
                            "MUSE_LANE_BOX_WAIT_MAX_SEC": "1"},
            accept="exit 0", box="box-s7a")
        deadline = time.time() + 15
        nl = None
        while time.time() < deadline:
            try:
                nl = self.read_state(lidB).get("needs_lead")
            except (FileNotFoundError, OSError, ValueError):
                nl = None
            if isinstance(nl, dict) and nl.get("kind") == "box_wait_timeout":
                break
            time.sleep(0.1)
        self.assertIsNotNone(nl, "first box_wait_timeout never raised")
        self.assertEqual(nl.get("seq"), 1)
        r = self.run_lane("answer", lidB, "--box", "box-s7c")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_lane(lidB).get("box"), "box-s7c")
        # The merged clear lands while the lane is still queued behind
        # the box-s7c holder.
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                st = self.read_state(lidB)
            except (FileNotFoundError, OSError, ValueError):
                st = None
            if st is not None and st.get("needs_lead") is None:
                break
            time.sleep(0.1)
        st = self.read_state(lidB)
        self.assertIsNone(st.get("needs_lead"))
        self.assertEqual(st.get("box_state"), "queued")
        merged = [fn for fn in os.listdir(self.lane_path(lidB))
                  if fn.startswith("lead-") and fn.endswith(".merged")]
        self.assertTrue(merged, "no merged lead sidecar found")
        # Still queued past the budget again: the reset timer raises a
        # second timeout naming the new box.
        deadline = time.time() + 15
        nl2 = None
        while time.time() < deadline:
            try:
                nl2 = self.read_state(lidB).get("needs_lead")
            except (FileNotFoundError, OSError, ValueError):
                nl2 = None
            if isinstance(nl2, dict) and nl2.get("seq") == 2:
                break
            time.sleep(0.1)
        self.assertIsNotNone(nl2, "second box_wait_timeout never raised")
        self.assertEqual(nl2.get("kind"), "box_wait_timeout")
        self.assertIn("box-s7c", nl2.get("detail") or "")
        for lid in (lidB, lidA, lidC):
            r = self.run_lane("stop", lid)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.wait_status(lid, "stopped", timeout=20)
        self.assertEqual(os.listdir(os.path.join(self.lanes, "_boxes", "box-s7a")), [])
        self.assertEqual(os.listdir(os.path.join(self.lanes, "_boxes", "box-s7c")), [])


class TestBoxNameValidation(LaneBase):
    def _mk_lane(self, lid):
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        ldir = os.path.join(self.lanes, lid)
        os.makedirs(ldir, exist_ok=True)
        lane = {"id": lid, "label": "L", "cwd": self.cwd, "briefs": ["b.md"],
                "created_at": now, "owner_session": None, "stall_sec": 2400,
                "env_file": None, "scope": [], "box": "box-a",
                "config": {"accept_exit_kinds": {}}}
        state = {"status": "running", "step": 1, "steps": 1, "attempt": 1,
                 "supervisor_pid": None, "supervisor_started": None,
                 "muse_pid": None, "muse_started": None,
                 "started_at": now, "updated_at": now,
                 "last_activity_at": now, "last_event": None,
                 "head_start": None, "head": None, "commits": 0,
                 "stderr_tail": "", "accept_exit": None, "retry_at": None,
                 "reason": None, "phase": "box_wait", "phase_started": now,
                 "review_rounds": [], "review_error": None, "consults": [],
                 "needs_lead": None, "needs_lead_seq": 0,
                 "box_state": "queued", "box_queued_at": now,
                 "evidence": None, "advisor_calls": 0}
        with open(os.path.join(ldir, "lane.json"), "w") as f:
            json.dump(lane, f)
        with open(os.path.join(ldir, "state.json"), "w") as f:
            json.dump(state, f)
        return ldir

    def test_units(self):
        mod = _load_lane_module()
        f = mod.box_name_error
        self.assertIsNone(f("box-1"))
        self.assertIsNone(f("lab_box.2"))
        self.assertTrue(f(""))
        self.assertTrue(f("."))
        self.assertTrue(f(".."))
        self.assertTrue(f("a/b"))
        self.assertTrue(f("a\x00b"))

    def test_start_rejects_bad_names(self):
        b = self.write_brief("b1.md", "bad box work")
        for bad in (".", "..", "a/b", ""):
            r = self.run_lane("start", "--cwd", self.cwd, "--brief", b,
                              "--box", bad)
            self.assertNotEqual(r.returncode, 0, repr(bad))
            self.assertIn("invalid", r.stderr.lower())

    def test_answer_rejects_bad_names(self):
        lid = "lane-badbox"
        self._mk_lane(lid)
        for bad in (".", "..", "a/b"):
            r = self.run_lane("answer", lid, "--box", bad)
            self.assertNotEqual(r.returncode, 0, repr(bad))
            self.assertIn("invalid", r.stderr.lower())
        self.assertEqual(self.read_lane(lid).get("box"), "box-a")


class TestStallRestartsAfterConsult(LaneBase):
    def test_long_consult_does_not_stall(self):
        # Each consult blocks the poll loop 5s with a 2s stall budget; the
        # gap forces idle iterations right after a consult, when a stale
        # clock would read 5s. consult_max 10 keeps retries on real
        # consults (no silent pass through "limited").
        b = self.write_brief("b1.md", "stall consult work")
        lid = self.start_lane(
            [b], env_extra={"FAKE_MODE": "ask", "FAKE_ASK_COUNT": "2",
                            "FAKE_ASK_GAP": "0.5",
                            "FAKE_CONSULT_SLEEP": "5",
                            "MUSE_LANE_STALL_SEC": "2"},
            consult_max=10)
        st = self.wait_status(lid, "done", timeout=40)
        consults = st.get("consults") or []
        self.assertEqual(len(consults), 2)
        self.assertTrue(all(c.get("answered") for c in consults))


class TestBoxesMalformedConfig(LaneBase):
    def test_malformed_config_lists_tickets(self):
        cfg_path = os.path.join(self.root, "boxes-bad.json")
        with open(cfg_path, "w") as f:
            json.dump({"box_wait_max_min": "soon"}, f)
        bdir = os.path.join(self.lanes, "_boxes", "box-n3")
        os.makedirs(bdir, exist_ok=True)
        with open(os.path.join(bdir, "0-gone-lane"), "w") as f:
            f.write("{}\n")
        r = self.run_lane("boxes", "--json",
                          env_extra={"MUSE_LANES_CONFIG": cfg_path})
        self.assertEqual(r.returncode, 0, r.stderr)
        by_box = {o["box"]: o for o in json.loads(r.stdout)}
        self.assertIn("box-n3", by_box)
        self.assertIsNone(by_box["box-n3"]["lease"])
        self.assertEqual(by_box["box-n3"]["queue"], [])
        self.assertIn("box_wait_max_min", r.stderr)
        self.assertIn("leases unavailable", r.stderr)


if __name__ == "__main__":
    unittest.main()
