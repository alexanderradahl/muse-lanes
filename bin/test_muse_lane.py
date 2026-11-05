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
    emit("ask final; answers=%s" % ("|".join(_got)))
    sys.exit(0)
else:
    emit("default final")
    sys.exit(0)
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
        for rid in recent_ids:
            self.assertIn(rid, by_id)
            self.assertIsNone(by_id[rid]["last_subject"], rid)
        for oid in old_ids:
            self.assertNotIn(oid, by_id)
        try:
            with open(count_file) as f:
                calls = [l for l in f.read().splitlines() if l.strip()]
        except FileNotFoundError:
            calls = []
        self.assertEqual(len(calls), 1,
                         "status --active ran git %d times, want at most 1: %s"
                         % (len(calls), calls[:5]))
        self.assertIn(" log ", " " + calls[0] + " ")
        got_pwd = calls[0].split(" :: ")[0]
        self.assertEqual(os.path.realpath(got_pwd), os.path.realpath(live_cwd))


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


if __name__ == "__main__":
    unittest.main()
