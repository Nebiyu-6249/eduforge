"""Run code against tests in a sandbox (plan 2.19; reused for student code in 4.7).

Backends (SANDBOX_MODE):

* docker     - `docker run --network none`, memory/CPU/pid limits, read-only
               mount, no privileges. The real isolation; required in production
               and for any student code (Phase 4).
* subprocess - a time-limited Python subprocess in an empty temp dir with an
               empty environment (and CPU/memory limits on POSIX). NOT isolated:
               it can reach the network and the file system. Development only,
               for model-written reference solutions.
* auto       - docker if a daemon answers, else subprocess.
* off        - don't run code; the check reports "skipped".

Tests are plain functions named test_* that use assert, written against
`from solution import *`. No pytest is needed inside the sandbox.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

RUNNER = r'''
import json, sys, traceback, importlib
results = {"passed": [], "failed": [], "error": None}
try:
    tests = importlib.import_module("test_solution")
except Exception as e:
    results["error"] = "Tests failed to load: " + "".join(traceback.format_exception_only(type(e), e)).strip()
    print(json.dumps(results)); sys.exit(0)
for name in sorted(n for n in dir(tests) if n.startswith("test_") and callable(getattr(tests, n))):
    try:
        getattr(tests, name)()
        results["passed"].append(name)
    except AssertionError as e:
        results["failed"].append({"name": name, "error": ("AssertionError: " + str(e))[:300]})
    except Exception as e:
        results["failed"].append({"name": name, "error": "".join(traceback.format_exception_only(type(e), e)).strip()[:300]})
print(json.dumps(results))
'''

DOCKER_IMAGE = "python:3.12-slim"


@dataclass
class RunResult:
    backend: str
    passed: list[str] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    error: str | None = None
    isolated: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and not self.failed and bool(self.passed)


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=5, check=False).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def backend() -> str:
    from app.config import get_settings

    mode = get_settings().sandbox_mode
    if mode == "auto":
        return "docker" if _docker_ok() else "subprocess"
    return mode


def run_tests(solution_code: str, tests_code: str, timeout: int = 10) -> RunResult:
    which = backend()
    if which == "off":
        return RunResult("off", error="Code execution is turned off (SANDBOX_MODE=off).")
    with tempfile.TemporaryDirectory(prefix="eduforge-sbx-") as d:
        work = Path(d)
        (work / "solution.py").write_text(solution_code, encoding="utf-8")
        (work / "test_solution.py").write_text("from solution import *\n" + tests_code, encoding="utf-8")
        (work / "runner.py").write_text(RUNNER, encoding="utf-8")
        if which == "docker":
            cmd = ["docker", "run", "--rm", "--network", "none", "--memory", "256m", "--cpus", "1",
                   "--pids-limit", "64", "--read-only", "--tmpfs", "/tmp", "--security-opt", "no-new-privileges",
                   "-v", f"{work}:/work:ro", "-w", "/work", "-e", "PYTHONDONTWRITEBYTECODE=1",
                   DOCKER_IMAGE, "python", "-I", "-c", "import sys; sys.path.insert(0, '/work'); exec(open('/work/runner.py').read())"]
            isolated = True
        else:
            cmd = [sys.executable, "-I", "-c",
                   "import sys; sys.path.insert(0, '.'); sys.dont_write_bytecode = True; exec(open('runner.py').read())"]
            isolated = False
        try:
            p = subprocess.run(cmd, cwd=work, capture_output=True, check=False, timeout=timeout + (20 if which == "docker" else 0),
                               env={"PATH": "/usr/bin:/bin", "SYSTEMROOT": _sysroot(), "PYTHONIOENCODING": "utf-8"},
                               preexec_fn=_limits if sys.platform != "win32" and which == "subprocess" else None)
        except subprocess.TimeoutExpired:
            return RunResult(which, error=f"Timed out after {timeout}s.", isolated=isolated)
        out = p.stdout.decode(errors="replace").strip().splitlines()
        try:
            data = json.loads(out[-1]) if out else None
        except json.JSONDecodeError:
            data = None
        if data is None:
            err = p.stderr.decode(errors="replace").strip().splitlines()
            return RunResult(which, error=(err[-1] if err else "The sandbox produced no result.")[:300], isolated=isolated)
        return RunResult(which, passed=data["passed"], failed=data["failed"], error=data["error"], isolated=isolated)


def _sysroot() -> str:
    import os

    return os.environ.get("SYSTEMROOT", "")


def _limits() -> None:  # POSIX only
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
