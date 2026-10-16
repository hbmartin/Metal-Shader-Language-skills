"""Execute the documented examples with temporary fixtures and bounded signal probes."""

from contextlib import ExitStack, contextmanager
import codecs
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
from unittest.mock import patch


if sys.version_info < (3, 13):
    raise RuntimeError(
        "Reference example tests require Python 3.13 or newer; "
        "run python3.13 -m unittest discover -s tests (or use a newer interpreter).")


ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT_REFERENCES = (
    ROOT / "skills/metal-compute/references/dispatch-and-reductions.md",
    ROOT / "skills/metal-shader-authoring/references/interfaces-and-layout.md",
)
DIAGNOSTIC_REFERENCES = (
    ROOT / "skills/metal-debugging/references/compilation-and-validation.md",
    ROOT / "skills/metal-shader-authoring/references/compilation-and-replacement.md",
)
CALLERS = tuple(path for name in ("bash", "dash", "zsh") if (path := shutil.which(name)))
NONREAPING_WAIT = all(hasattr(os, name) for name in
                     ("waitid", "P_PID", "WEXITED", "WNOHANG", "WNOWAIT"))
CANCELLATION_SIGNALS = tuple(getattr(signal, name) for name in
                             ("SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT")
                             if hasattr(signal, name))
MARKER = b"metal-diagnostic-v1\n"
SHADER = """#include <metal_stdlib>
using namespace metal;
kernel void diagnostic(device float* values [[buffer(0)]],
                       uint index [[thread_position_in_grid]]) {
    values[index] *= 2.0f;
}
"""


def block(path, language, identifier):
    fence = chr(96) * 3
    blocks = re.findall(r"^" + re.escape(fence + language) + r"\n(.*?)^" + fence + r"$",
                        path.read_text(), re.MULTILINE | re.DOTALL)
    matches = [value for value in blocks if identifier in value]
    if len(matches) != 1:
        raise AssertionError(f"Expected one {identifier} block in {path}, got {len(matches)}")
    return matches[0]


def build_example(path=DIAGNOSTIC_REFERENCES[0]):
    return block(path, "sh", "sh <<'METAL_DIAGNOSTIC'")


def cleanup_example(directory, path=DIAGNOSTIC_REFERENCES[0]):
    example = block(path, "sh", "sh <<'METAL_CLEANUP'")
    assignment = 'metal_run_dir="/absolute/path/to/metal-diagnostic.XXXXXX"'
    if example.count(assignment) != 1:
        raise AssertionError("Cleanup input assignment is missing or ambiguous")
    return example.replace(assignment, "metal_run_dir=" + shlex.quote(str(directory)))


def inspection_example(directory, path=DIAGNOSTIC_REFERENCES[0]):
    example = block(path, "sh", "sh <<'METAL_INSPECT'")
    assignment = 'metal_inspect_dir="/absolute/path/to/metal-diagnostic.XXXXXX"'
    if example.count(assignment) != 1:
        raise AssertionError("Inspection input assignment is missing or ambiguous")
    replacement = ("unset metal_inspect_dir" if directory is None
                   else "metal_inspect_dir=" + shlex.quote(str(directory)))
    return example.replace(assignment, replacement)


def ordinary_finder_metadata(entry):
    return entry.name == ".DS_Store" and entry.is_file() and not entry.is_symlink()


def snapshot(directory, ignore_metadata=False):
    result = {}
    for entry in sorted(directory.iterdir()):
        if ignore_metadata and ordinary_finder_metadata(entry):
            continue
        if entry.is_symlink():
            result[entry.name] = ("symlink", os.readlink(entry))
        elif entry.is_dir():
            result[entry.name] = ("directory", snapshot(entry, ignore_metadata=ignore_metadata))
        else:
            result[entry.name] = ("file", entry.read_bytes())
    return result


def allocation_records(log):
    return [Path(line) for line in log.read_text().splitlines()] if log.exists() else []


def note_cleanup_failure(primary, cleanup_error):
    if cleanup_error is not primary:
        primary.add_note("Additional teardown failure:\n" + "".join(
            traceback.format_exception(cleanup_error, chain=False)))


class ProcessOwnershipError(RuntimeError):
    pass


class OwnedProcess:
    """Own capture and reaping; expose no competing Popen operations or pipe handles."""

    def __init__(self, args, *, cwd, env, stderr=subprocess.PIPE):
        if not NONREAPING_WAIT:
            raise unittest.SkipTest("Process tests require POSIX waitid(WNOWAIT)")
        self._process = subprocess.Popen(
            args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=stderr,
            text=True, start_new_session=True)
        self._streams = (self._process.stdout, self._process.stderr)
        self._chunks = [[], []]
        self._read_errors = []
        self._capture_lock = threading.Lock()
        self._reader_stop = threading.Event()
        self._readers = []
        self._returncode = None
        self._ownership_error = None
        self._stopped = False
        for index, stream in enumerate(self._streams):
            if stream is not None:
                decoder = codecs.getincrementaldecoder(stream.encoding)(errors=stream.errors)
                os.set_blocking(stream.fileno(), False)
                reader = threading.Thread(target=self._read_pipe, args=(index, stream, decoder),
                                          daemon=True)
                self._readers.append(reader)
                reader.start()

    @property
    def args(self):
        return tuple(self._process.args)

    @property
    def pid(self):
        return self._process.pid

    @property
    def returncode(self):
        return self._returncode

    @property
    def pipes_closed(self):
        return all(stream is None or stream.closed for stream in self._streams)

    def _read_pipe(self, index, stream, decoder):
        try:
            while not self._reader_stop.is_set():
                if not select.select([stream], [], [], 0.05)[0]:
                    continue
                try:
                    chunk = os.read(stream.fileno(), 65536)
                except BlockingIOError:
                    continue
                text = decoder.decode(chunk, final=not chunk)
                with self._capture_lock:
                    self._chunks[index].append(text)
                if not chunk:
                    return
        except Exception as error:
            with self._capture_lock:
                self._read_errors.append(error)

    def output(self):
        with self._capture_lock:
            captured = ["".join(chunks) for chunks in self._chunks]
        return tuple(text.replace("\r\n", "\n").replace("\r", "\n")
                     if stream is not None else None
                     for text, stream in zip(captured, self._streams))

    def exited(self):
        if self._ownership_error is not None:
            raise self._ownership_error
        if self._stopped:
            return True
        try:
            if self._process.returncode is not None:
                raise ChildProcessError("Child was reaped outside its owner")
            return os.waitid(os.P_PID, self.pid,
                             os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
        except ChildProcessError as error:
            self._ownership_error = ProcessOwnershipError(
                "Process ownership lost: child was reaped outside its owner")
            raise self._ownership_error from error

    def wait_for_exit(self, timeout):
        deadline = time.monotonic() + timeout
        while not self.exited():
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.args, timeout)
            time.sleep(0.005)

    def _join_readers(self, deadline):
        for reader in self._readers:
            reader.join(timeout=max(0, deadline - time.monotonic()))
        return all(not reader.is_alive() for reader in self._readers)

    def stop(self):
        if self._stopped:
            return
        try:
            self.exited()  # Prove this is still our unreaped child before signaling its group.
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass  # macOS can return EPERM for a group containing only a zombie.
            self._returncode = self._process.wait(timeout=3)
            if not self._join_readers(time.monotonic() + 3):
                raise AssertionError("Process pipes remained open after group teardown")
            if self._read_errors:
                raise AssertionError(f"Process pipe reader failed: {self._read_errors!r}")
        finally:
            self._reader_stop.set()
            self._join_readers(time.monotonic() + 0.25)
            try:
                with ExitStack() as closing:
                    for stream in self._streams:
                        if stream is not None:
                            closing.callback(stream.close)
                    if self._ownership_error is not None and self._process.returncode is None:
                        # Acknowledge ECHILD to Popen's resource tracking. Its fallback status
                        # stays private: this owner still reports None and the ownership error.
                        self._process.wait(timeout=0)
            finally:
                self._stopped = True

    def collect(self, timeout):
        deadline = time.monotonic() + timeout
        primary_error = None
        try:
            self.wait_for_exit(timeout)
            # A caller can exit while its diagnostic is still honoring cancellation.
            if not self._join_readers(deadline):
                raise subprocess.TimeoutExpired(self.args, timeout)
        except BaseException as error:
            primary_error = error
            raise
        finally:
            try:
                self.stop()
            except Exception as cleanup_error:
                if primary_error is None:
                    raise
                note_cleanup_failure(primary_error, cleanup_error)
            if isinstance(primary_error, subprocess.TimeoutExpired):
                primary_error.output, primary_error.stderr = self.output()
        return self.output()


@contextmanager
def external_run():
    """An unrecorded, valid-looking sibling of real fallback allocations."""
    directory = Path(subprocess.check_output(
        [shutil.which("mktemp") or "/usr/bin/mktemp", "-d", "--",
         "/tmp/metal-diagnostic.XXXXXX"], text=True).strip()).resolve()
    try:
        yield directory
    finally:
        if directory.is_symlink():
            directory.unlink()
        elif directory.exists():
            shutil.rmtree(directory)


# This executable doubles as mktemp, xcrun, and an injected publication probe.
# Allocation preserves ignored signals inherited from the allocating shell.
STUB = r"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
    if signal.getsignal(sig) != signal.SIG_IGN:
        signal.signal(sig, signal.SIG_DFL)

def gate(phase):
    if os.environ.get("METAL_TEST_GATE") != phase:
        return
    Path(os.environ["METAL_TEST_READY"]).write_text(str(os.getpid()))
    deadline = time.monotonic() + 6
    while not Path(os.environ["METAL_TEST_RELEASE"]).exists():
        if time.monotonic() > deadline:
            sys.exit(97)
        time.sleep(0.005)

name = Path(sys.argv[0]).name
args = sys.argv[1:]
if name == "mktemp":
    directory = subprocess.check_output([os.environ["METAL_TEST_REAL_MKTEMP"], *args],
                                        text=True).strip()
    with open(os.environ["METAL_TEST_ALLOCATIONS"], "a") as log:
        log.write(directory + "\n")
    gate("allocation")
    print(directory, flush=True)
elif name == "rmdir":
    directory = Path(args[-1])
    if directory.is_dir() and not (directory / ".metal-diagnostic-run").exists():
        if os.environ.get("METAL_TEST_LATE_METADATA"):
            (directory / ".DS_Store").write_bytes(b"late metadata")
        gate("rmdir")
    sys.exit(subprocess.call([os.environ["METAL_TEST_REAL_RMDIR"], *args]))
elif name == "metal-test-gate":
    gate(args[0])
else:
    stage = "metal" if "metal" in args else "metallib"
    output = Path(args[args.index("-o") + 1])
    with open(os.environ["METAL_TEST_CALLS"], "a") as log:
        log.write(json.dumps(args) + "\n")
    injection = os.environ.get("METAL_TEST_INJECT")
    if injection == "symlink":
        output.symlink_to(os.environ["METAL_TEST_VICTIM"])
    elif injection == "directory":
        output.mkdir()
    else:
        output.write_bytes(b"air" if stage == "metal" else b"library")
    if stage == "metal" and "-MD" in args:
        (output.parent / "Shaders.d").write_bytes(b"dependency")
    if os.environ.get("METAL_TEST_METADATA"):
        (output.parent / ".DS_Store").write_bytes(b"metadata")
    if injection == "unexpected":
        (output.parent / ".unrelated").write_bytes(b"keep me")
    gate(stage)
    if os.environ.get("METAL_TEST_FAIL") == stage:
        sys.exit(int(os.environ.get("METAL_TEST_FAILURE_STATUS", "42")))
"""


class ConsistencyTests(unittest.TestCase):
    def test_alignment_copies(self):
        for language in ("swift", "c"):
            self.assertEqual(
                block(ALIGNMENT_REFERENCES[0], language, "constantBufferOffsetAlignment"),
                block(ALIGNMENT_REFERENCES[1], language, "constantBufferOffsetAlignment"),
            )

    def test_diagnostic_copies(self):
        build_a, build_b = (build_example(path) for path in DIAGNOSTIC_REFERENCES)
        self.assertIn('metal_language="metal3.1"', build_a)
        self.assertIn('metal_language="metal3.0"', build_b)
        self.assertEqual(build_a.replace('metal_language="metal3.1"',
                                         'metal_language="metal3.0"'), build_b)
        self.assertEqual(
            block(DIAGNOSTIC_REFERENCES[0], "sh", "sh <<'METAL_CLEANUP'"),
            block(DIAGNOSTIC_REFERENCES[1], "sh", "sh <<'METAL_CLEANUP'"),
        )
        self.assertEqual(
            block(DIAGNOSTIC_REFERENCES[0], "sh", "sh <<'METAL_INSPECT'"),
            block(DIAGNOSTIC_REFERENCES[1], "sh", "sh <<'METAL_INSPECT'"),
        )


@unittest.skipUnless(os.name == "posix" and CALLERS, "requires POSIX shells")
class DiagnosticTests(unittest.TestCase):
    @contextmanager
    def fixture(self, rmdir_probe=False):
        resources = ExitStack()
        self.resources = resources
        primary_error = None
        try:
            import resource
            core_limit = resource.getrlimit(resource.RLIMIT_CORE)
            resource.setrlimit(resource.RLIMIT_CORE, (0, core_limit[1]))
            resources.callback(resource.setrlimit, resource.RLIMIT_CORE, core_limit)
            fixture_dir = resources.enter_context(
                tempfile.TemporaryDirectory(prefix="metal-reference-tests-", dir="/tmp"))
            self.base = Path(fixture_dir).resolve()
            self.project = self.base / "project with spaces"
            self.project.mkdir()
            (self.project / "Shaders.metal").write_text(SHADER)
            (self.project / "Shaders.diagnostic.metallib").write_bytes(b"project sentinel")
            self.original_project = snapshot(self.project, ignore_metadata=True)
            self.outputs = self.base / "temporary outputs"
            self.outputs.mkdir()
            (self.outputs / ".DS_Store").write_bytes(b"fixture metadata")
            self.bin = self.base / "bin"
            self.bin.mkdir()
            names = ("xcrun", "mktemp", "metal-test-gate")
            if rmdir_probe:
                names += ("rmdir",)
            for name in names:
                executable = self.bin / name
                executable.write_text("#!" + sys.executable + "\n" + STUB)
                executable.chmod(0o700)
            self.env = os.environ.copy()
            self.env.update(
                TMPDIR=str(self.outputs),
                PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", os.defpath),
                METAL_TEST_REAL_MKTEMP=shutil.which("mktemp") or "/usr/bin/mktemp",
                METAL_TEST_REAL_RMDIR=shutil.which("rmdir") or "/bin/rmdir",
                METAL_TEST_ALLOCATIONS=str(self.base / "allocations"),
                METAL_TEST_CALLS=str(self.base / "compiler calls"),
                METAL_TEST_READY=str(self.base / "ready"),
                METAL_TEST_RELEASE=str(self.base / "release"),
            )
            # Process callbacks are registered later and therefore run first.
            resources.callback(self.remove_external_allocations,
                               Path(self.env["METAL_TEST_ALLOCATIONS"]), self.base)
            yield
        except BaseException as error:
            primary_error = error
            raise
        finally:
            self.resources = None
            try:
                resources.close()
            except Exception as cleanup_error:
                if primary_error is None:
                    raise
                note_cleanup_failure(primary_error, cleanup_error)

    @staticmethod
    def remove_external_allocations(log, base):
        errors = []
        for directory in allocation_records(log):
            if base in directory.parents:
                continue  # TemporaryDirectory owns these, including unlogged entries.
            # Only the real fallback /tmp allocations can be outside this fixture.
            if (directory.parent != Path("/tmp").resolve()
                    or not re.fullmatch(r"metal-diagnostic\.[A-Za-z0-9]{6}", directory.name)):
                errors.append(f"Unexpected external test allocation: {directory}")
                continue
            try:
                if directory.is_symlink():
                    directory.unlink()
                elif directory.exists():
                    shutil.rmtree(directory)
            except OSError as error:
                errors.append(f"Unable to remove test allocation {directory}: {error}")
        if errors:
            raise AssertionError("\n".join(errors))

    def run_example(self, example, caller=None, env=None, cwd=None):
        process = self.start_example(example, caller or CALLERS[0], env or self.env, cwd=cwd)
        stdout, stderr = self.finish(process, timeout=12)
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)

    def start_example(self, example, caller, env, stderr=subprocess.PIPE, cwd=None):
        resources = getattr(self, "resources", None)
        if resources is None:
            raise RuntimeError("Starting a process requires an active fixture")
        process = OwnedProcess(
            [caller, "-c", example], cwd=cwd or self.project, env=env,
            stderr=stderr,
        )
        resources.callback(process.stop)
        return process

    def allocations(self):
        return allocation_records(Path(self.env["METAL_TEST_ALLOCATIONS"]))

    def remaining_outputs(self):
        remaining = {path for path in self.allocations() if path.exists() or path.is_symlink()}
        remaining.update(entry for entry in self.outputs.iterdir()
                         if not ordinary_finder_metadata(entry))
        return sorted(remaining)

    def finish(self, process, timeout=8):
        try:
            return process.collect(timeout)
        except subprocess.TimeoutExpired as error:
            raise AssertionError(
                f"Diagnostic exceeded bounded wait: {(error.output, error.stderr)!r}") from error

    def wait_ready(self, process):
        self.wait_for_file(process, Path(self.env["METAL_TEST_READY"]))

    def wait_for_file(self, process, path, timeout=4):
        deadline = time.monotonic() + timeout
        while not path.exists():
            if process.exited():
                process.stop()
                self.fail(f"Diagnostic exited before probe: {process.output()!r}")
            if time.monotonic() > deadline:
                self.fail(f"Diagnostic never reached the probe: {path.name}")
            time.sleep(0.005)

    def release_probe(self):
        Path(self.env["METAL_TEST_RELEASE"]).touch()

    def retained_library(self, result, dependencies=False):
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        library = Path(lines[0])
        self.assertTrue(library.is_absolute())
        self.assertTrue(library.is_file())
        self.assertEqual(library.parent.parent, self.outputs)
        self.assertIn(library.parent, self.allocations())
        expected = {
            ".metal-diagnostic-run": ("file", MARKER),
            "Shaders.diagnostic.metallib": ("file", b"library"),
        }
        if dependencies:
            expected["Shaders.d"] = ("file", b"dependency")
        self.assertEqual(snapshot(library.parent, ignore_metadata=True), expected)
        self.assertEqual(stat.S_IMODE(library.parent.stat().st_mode) & 0o077, 0)
        return library

    def test_success_repeated_builds_and_cleanup(self):
        for caller in CALLERS:
            for path in DIAGNOSTIC_REFERENCES:
                with self.subTest(caller=caller, reference=path.name), self.fixture():
                    libraries = []
                    for _ in range(2):
                        result = self.run_example(build_example(path), caller)
                        library = self.retained_library(result)
                        libraries.append(library)
                        self.assertIn("Diagnostic run directory: " + str(library.parent),
                                      result.stderr)
                    self.assertNotEqual(libraries[0], libraries[1])
                    for library in libraries:
                        cleanup = cleanup_example(str(library.parent) + "///", path)
                        self.assertEqual(self.run_example(cleanup, caller).returncode, 0)
                        self.assertEqual(self.run_example(cleanup, caller).returncode, 0)
                        self.assertFalse(library.parent.exists())
                    self.assertEqual(snapshot(self.project, ignore_metadata=True), self.original_project)

    def test_compile_and_link_failures_preserve_status(self):
        for caller in CALLERS:
            for stage, status in (("metal", 42), ("metallib", 43)):
                with self.subTest(caller=caller, stage=stage), self.fixture():
                    env = dict(self.env, METAL_TEST_FAIL=stage,
                               METAL_TEST_FAILURE_STATUS=str(status))
                    result = self.run_example(build_example(), caller, env)
                    self.assertEqual(result.returncode, status, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(self.remaining_outputs(), [])
                    self.assertEqual(snapshot(self.project, ignore_metadata=True), self.original_project)

    def test_concurrent_builds_use_separate_directories(self):
        for caller in CALLERS:
            with self.subTest(caller=caller), self.fixture():
                processes = [self.start_example(build_example(), caller, self.env)
                             for _ in range(2)]
                libraries = []
                for process in processes:
                    stdout, stderr = self.finish(process)
                    libraries.append(self.retained_library(
                        subprocess.CompletedProcess([], process.returncode, stdout, stderr)))
                self.assertNotEqual(libraries[0], libraries[1])
                for library in libraries:
                    self.assertEqual(self.run_example(
                        cleanup_example(library.parent), caller).returncode, 0)
                self.assertEqual(snapshot(self.project, ignore_metadata=True), self.original_project)

    def test_invalid_temporary_roots_allocate_nothing(self):
        for variant in ("relative", "leading-dash", "project", "nested", "alias"):
            with self.subTest(root=variant), self.fixture():
                nested = self.project / "temporary"
                nested.mkdir()
                alias = self.base / "project alias"
                alias.symlink_to(self.project, target_is_directory=True)
                root = {"relative": "relative", "leading-dash": "-temporary",
                        "project": str(self.project), "nested": str(nested),
                        "alias": str(alias)}[variant]
                result = self.run_example(build_example(), env=dict(self.env, TMPDIR=root))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertEqual(self.allocations(), [])
                self.assertEqual((self.project / "Shaders.diagnostic.metallib").read_bytes(),
                                 b"project sentinel")

    def test_git_project_root_is_used_from_subdirectory(self):
        with self.fixture():
            if not shutil.which("git"):
                self.skipTest("git unavailable")
            subprocess.run(["git", "init", "-q", str(self.project)], check=True,
                           capture_output=True)
            subdirectory = self.project / "source"
            subdirectory.mkdir()
            root = self.project / "temporary"
            root.mkdir()
            result = self.run_example(build_example(), env=dict(self.env, TMPDIR=str(root)),
                                      cwd=subdirectory)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside the Git project", result.stderr)
            self.assertFalse(Path(self.env["METAL_TEST_ALLOCATIONS"]).exists())

    def test_temporary_root_symlink_resolves_to_physical_path(self):
        with self.fixture():
            alias = self.base / "temporary alias"
            alias.symlink_to(self.outputs, target_is_directory=True)
            result = self.run_example(build_example(), env=dict(self.env, TMPDIR=str(alias)))
            library = self.retained_library(result)
            self.assertEqual(self.run_example(cleanup_example(library.parent)).returncode, 0)

    def test_unset_temporary_root_falls_back_outside_project(self):
        with self.fixture():
            env = dict(self.env, METAL_TEST_FAIL="metal")
            env.pop("TMPDIR", None)
            result = self.run_example(build_example(), env=env)
            self.assertEqual(result.returncode, 42, result.stderr)
            directory, = self.allocations()
            self.assertEqual(directory.parent, Path("/tmp").resolve())
            self.assertFalse(directory.exists())
            self.assertEqual(snapshot(self.project, ignore_metadata=True), self.original_project)

    def test_stderr_errors_do_not_invalidate_success(self):
        example = build_example().replace("sh <<", "sh 2>&- <<", 1)
        for caller in CALLERS:
            with self.subTest(caller=caller), self.fixture():
                library = self.retained_library(self.run_example(example, caller))
                self.assertEqual(self.run_example(
                    cleanup_example(library.parent), caller).returncode, 0)

    def test_broken_stderr_pipe_preserves_success_and_failure_status(self):
        for caller in CALLERS:
            for outcome in ("success", "failure", "refused-cleanup"):
                with self.subTest(caller=caller, outcome=outcome), self.fixture():
                    env = dict(self.env)
                    if outcome != "success":
                        env["METAL_TEST_FAIL"] = "metal"
                    if outcome == "refused-cleanup":
                        env["METAL_TEST_INJECT"] = "unexpected"
                    reader, writer = os.pipe()
                    os.close(reader)
                    try:
                        process = self.start_example(build_example(), caller, env, stderr=writer)
                    finally:
                        os.close(writer)
                    stdout, _ = self.finish(process)
                    if outcome == "success":
                        result = subprocess.CompletedProcess([], process.returncode, stdout, "")
                        library = self.retained_library(result)
                        self.assertEqual(self.run_example(
                            cleanup_example(library.parent), caller).returncode, 0)
                    else:
                        self.assertEqual(process.returncode, 42)
                        self.assertEqual(stdout, "")
                        self.assertEqual(len(self.remaining_outputs()),
                                         1 if outcome == "refused-cleanup" else 0)

    def test_directory_is_announced_before_compilation_completes(self):
        for caller in CALLERS:
            with self.subTest(caller=caller), self.fixture():
                process = self.start_example(build_example(), caller, dict(
                    self.env, METAL_TEST_GATE="metal", METAL_TEST_FAIL="metal"))
                self.wait_ready(process)
                directory, = self.allocations()
                announcement = "Diagnostic run directory: " + str(directory) + "\n"
                deadline = time.monotonic() + 3
                while announcement not in process.output()[1]:
                    if time.monotonic() >= deadline:
                        self.fail("Run directory was not announced before compilation")
                    time.sleep(0.005)
                self.assertEqual(process.output()[1], announcement)
                self.release_probe()
                stdout, _ = self.finish(process)
                self.assertEqual(process.returncode, 42)
                self.assertEqual(stdout, "")
                self.assertEqual(self.remaining_outputs(), [])

    def test_stdout_error_retains_completed_outputs(self):
        with self.fixture():
            example = build_example().replace("sh <<", "sh 1>&- <<", 1)
            result = self.run_example(example)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            directories = self.remaining_outputs()
            self.assertEqual(len(directories), 1)
            self.assertEqual(snapshot(directories[0], ignore_metadata=True), {
                ".metal-diagnostic-run": ("file", MARKER),
                "Shaders.diagnostic.metallib": ("file", b"library"),
            })
            self.assertEqual(self.run_example(cleanup_example(directories[0])).returncode, 0)

    def test_signals_during_allocation_and_compilation_stop_loops(self):
        # Simulate terminal cancellation of the whole foreground process group.
        # Bash SIGINT specifically detects a child that exits numerically instead.
        for caller in CALLERS:
            for phase in ("allocation", "metal", "metallib"):
                for sig in CANCELLATION_SIGNALS:
                    with self.subTest(caller=caller, phase=phase, signal=sig.name), self.fixture():
                        env = dict(self.env, METAL_TEST_GATE=phase)
                        # zsh ignores QUIT itself; automation must check the child's status.
                        checked_status = ('metal_test_status=$?\n'
                                          '[ "$metal_test_status" -eq 0 ] || exit "$metal_test_status"\n'
                                          if sig == signal.SIGQUIT else "")
                        loop = ('for metal_test_run in 1 2 3; do\n'
                                'printf "RUN %s\\n" "$metal_test_run"\n'
                                + build_example() + checked_status + "done\n")
                        process = self.start_example(loop, caller, env)
                        self.wait_ready(process)
                        os.killpg(process.pid, sig)
                        self.release_probe()
                        stdout, stderr = self.finish(process)
                        self.assertNotEqual(process.returncode, 0, stderr)
                        self.assertEqual(stdout.splitlines(), ["RUN 1"])
                        self.assertEqual(self.remaining_outputs(), [])
                        self.assertEqual(snapshot(self.project, ignore_metadata=True), self.original_project)

    def test_diagnostic_process_really_terminates_by_signal(self):
        # These direct-process assertions independently prove signal re-raising;
        # outer loops can terminate from the group signal without proving that.
        # Execute the extracted here-document body directly to inspect wait status.
        body = build_example().split("\n", 1)[1].rsplit("METAL_DIAGNOSTIC\n", 1)[0]
        for sig in CANCELLATION_SIGNALS:
            with self.subTest(signal=sig.name), self.fixture():
                process = self.start_example(body, shutil.which("sh"),
                                             dict(self.env, METAL_TEST_GATE="metal"))
                self.wait_ready(process)
                os.killpg(process.pid, sig)
                self.release_probe()
                self.finish(process)
                self.assertEqual(process.returncode, -sig)
                self.assertEqual(self.remaining_outputs(), [])

    def test_signals_during_final_cleanup_preserve_signal_status(self):
        boundary = "    trap - INT TERM HUP QUIT\n"
        self.assertEqual(build_example().count(boundary), 1)
        # Cleanup runs in a conditional context: its failure must not trigger
        # errexit before the EXIT handler can honor a recorded signal.
        example = build_example().replace(
            boundary, "    metal-test-gate exit-cleanup || :\n" + boundary)
        body = example.split("\n", 1)[1].rsplit("METAL_DIAGNOSTIC\n", 1)[0]
        for sig in CANCELLATION_SIGNALS:
            with self.subTest(signal=sig.name), self.fixture():
                process = self.start_example(
                    body, shutil.which("sh"),
                    dict(self.env, METAL_TEST_FAIL="metal",
                         METAL_TEST_GATE="exit-cleanup"))
                self.wait_ready(process)
                os.killpg(process.pid, sig)
                self.release_probe()
                self.finish(process)
                self.assertEqual(process.returncode, -sig)
                self.assertEqual(self.remaining_outputs(), [])

    def test_publication_interrupts_retain_completed_library(self):
        publication = "printf '%s\\n' \"$metal_library\"\n"
        self.assertEqual(build_example().count(publication), 1)
        for caller in CALLERS:
            for position in ("before", "after"):
                for sig in CANCELLATION_SIGNALS:
                    with self.subTest(caller=caller, position=position, signal=sig.name), self.fixture():
                        probe = "metal-test-gate publication\n"
                        replacement = (probe + publication if position == "before"
                                       else publication + probe)
                        example = build_example().replace(publication, replacement)
                        process = self.start_example(
                            example, caller, dict(self.env, METAL_TEST_GATE="publication"))
                        self.wait_ready(process)
                        os.killpg(process.pid, sig)
                        self.release_probe()
                        stdout, stderr = self.finish(process)
                        self.assertNotEqual(process.returncode, 0)
                        directories = self.remaining_outputs()
                        self.assertEqual(len(directories), 1)
                        library = directories[0] / "Shaders.diagnostic.metallib"
                        self.assertEqual(library.read_bytes(), b"library")
                        self.assertEqual((directories[0] / ".metal-diagnostic-run").read_bytes(),
                                         MARKER)
                        self.assertEqual(stdout.splitlines(),
                                         [str(library)] if position == "after" else [])
                        self.assertIn("Diagnostic run directory: " + str(library.parent), stderr)
                        self.assertEqual(self.run_example(
                            cleanup_example(directories[0]), caller).returncode, 0)

    def make_run(self, name="metal-diagnostic.abc123", marker=MARKER):
        directory = self.outputs / name
        directory.mkdir()
        (directory / "Shaders.diagnostic.metallib").write_bytes(b"unrelated library")
        if marker is not None:
            (directory / ".metal-diagnostic-run").write_bytes(marker)
        return directory

    def test_cleanup_refuses_unrelated_invalid_and_unexpected_contents(self):
        variants = ("missing-marker", "invalid-marker", "missing-newline", "extra-line",
                    "visible-file", "hidden-file", "nested-directory")
        for caller in CALLERS:
            for variant in variants:
                with self.subTest(caller=caller, variant=variant), self.fixture():
                    directory = self.make_run(name="metal-diagnostic.backup")
                    (directory / ".DS_Store").write_bytes(b"metadata")
                    (directory / "Shaders.d").write_bytes(b"dependency")
                    marker = directory / ".metal-diagnostic-run"
                    if variant == "missing-marker":
                        marker.unlink()
                    elif variant == "invalid-marker":
                        marker.write_bytes(b"another project\n")
                    elif variant == "missing-newline":
                        marker.write_bytes(MARKER.rstrip(b"\n"))
                    elif variant == "extra-line":
                        marker.write_bytes(MARKER + b"extra\n")
                    elif variant == "visible-file":
                        (directory / "notes").write_bytes(b"unrelated")
                    elif variant == "hidden-file":
                        (directory / ".notes").write_bytes(b"unrelated")
                    elif variant == "nested-directory":
                        (directory / "project").mkdir()
                        (directory / "project" / "notes").write_bytes(b"unrelated")
                    before = snapshot(directory)
                    result = self.run_example(cleanup_example(str(directory) + "/"), caller)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("Refusing cleanup", result.stderr)
                    self.assertEqual(snapshot(directory), before)
                    self.assertEqual((directory / ".DS_Store").read_bytes(), b"metadata")

    def test_cleanup_refuses_symlinks_without_changing_targets(self):
        for caller in CALLERS:
            for variant in ("directory", "marker", "library", "dangling-air",
                            "metadata", "dependency"):
                with self.subTest(caller=caller, variant=variant), self.fixture():
                    directory = self.make_run()
                    victim = self.base / "victim"
                    victim.write_bytes(MARKER)
                    if variant == "directory":
                        path = self.outputs / "metal-diagnostic.def456"
                        path.symlink_to(directory, target_is_directory=True)
                    else:
                        path = directory
                        entry = directory / {
                            "marker": ".metal-diagnostic-run",
                            "library": "Shaders.diagnostic.metallib",
                            "dangling-air": "Shaders.air",
                            "metadata": ".DS_Store",
                            "dependency": "Shaders.d",
                        }[variant]
                        entry.unlink(missing_ok=True)
                        entry.symlink_to(victim if variant != "dangling-air"
                                         else self.base / "missing victim")
                    before = snapshot(directory)
                    result = self.run_example(cleanup_example(str(path) + "/"), caller)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(snapshot(directory), before)
                    self.assertEqual(victim.read_bytes(), MARKER)

    def test_cleanup_rejects_malformed_paths(self):
        for variant in ("empty", "root", "dot", "relative", "long", "dot-component",
                        "parent-component", "trailing-dot"):
            with self.subTest(path=variant), self.fixture():
                directory = self.make_run()
                path = {"empty": "", "root": "/", "dot": ".",
                        "relative": "relative/metal-diagnostic.abc123",
                        "long": str(self.outputs / "metal-diagnostic.too-long"),
                        "dot-component": str(self.outputs) + "/./" + directory.name,
                        "parent-component": str(self.outputs) + "/../temporary outputs/" + directory.name,
                        "trailing-dot": str(directory) + "/."}[variant]
                before = snapshot(directory)
                self.assertEqual(self.run_example(cleanup_example(path)).returncode, 1)
                self.assertEqual(snapshot(directory), before)

    def test_cleanup_accepts_known_intermediate(self):
        with self.fixture():
            directory = self.make_run()
            (directory / "Shaders.air").write_bytes(b"air")
            self.assertEqual(self.run_example(cleanup_example(directory)).returncode, 0)
            self.assertFalse(directory.exists())

    def test_metadata_and_dependencies_are_known_outputs(self):
        example = build_example().replace("-c Shaders.metal", "-MD -c Shaders.metal")
        for caller in CALLERS:
            for outcome in ("success", "failure"):
                with self.subTest(caller=caller, outcome=outcome), self.fixture():
                    env = dict(self.env, METAL_TEST_METADATA="1")
                    if outcome == "failure":
                        env["METAL_TEST_FAIL"] = "metal"
                    result = self.run_example(example, caller, env)
                    if outcome == "success":
                        library = self.retained_library(result, dependencies=True)
                        self.assertEqual((library.parent / ".DS_Store").read_bytes(), b"metadata")
                        self.assertEqual(self.run_example(
                            cleanup_example(library.parent), caller).returncode, 0)
                    else:
                        self.assertEqual(result.returncode, 42)
                        self.assertEqual(result.stdout, "")
                    self.assertEqual(self.remaining_outputs(), [])

    def test_known_side_files_must_be_regular(self):
        for name in (".DS_Store", "Shaders.d"):
            with self.subTest(name=name), self.fixture():
                directory = self.make_run()
                (directory / name).mkdir()
                (directory / name / "notes").write_bytes(b"unrelated")
                before = snapshot(directory)
                self.assertEqual(self.run_example(cleanup_example(directory)).returncode, 1)
                self.assertEqual(snapshot(directory), before)

    def test_empty_unrelated_targets_are_preserved(self):
        for caller in CALLERS:
            with self.subTest(caller=caller), self.fixture():
                directory = self.base / "outside temporary root" / "metal-diagnostic.backup"
                directory.mkdir(parents=True, mode=0o750)
                mode = stat.S_IMODE(directory.stat().st_mode)
                for _ in range(2):
                    self.assertEqual(self.run_example(
                        cleanup_example(str(directory) + "///"), caller).returncode, 1)
                    self.assertTrue(directory.is_dir())
                    self.assertEqual(stat.S_IMODE(directory.stat().st_mode), mode)
                    self.assertEqual(snapshot(directory), {})

    def test_marked_directory_without_library_and_absent_target_cleanup(self):
        with self.fixture():
            directory = self.outputs / "metal-diagnostic.abc123"
            directory.mkdir()
            (directory / ".metal-diagnostic-run").write_bytes(MARKER)
            for _ in range(2):
                self.assertEqual(self.run_example(cleanup_example(directory)).returncode, 0)
                self.assertFalse(directory.exists())

    def test_cleanup_defers_signals_until_directory_removed(self):
        for caller in CALLERS:
            for suffix in ("", "///"):
                for sig in CANCELLATION_SIGNALS:
                    with self.subTest(caller=caller, suffix=suffix, signal=sig.name), \
                            self.fixture(rmdir_probe=True):
                        directory = self.make_run()
                        checked_status = ('metal_test_status=$?\n'
                                          '[ "$metal_test_status" -eq 0 ] || exit "$metal_test_status"\n'
                                          if sig == signal.SIGQUIT else "")
                        loop = ('for metal_test_run in 1 2 3; do\n'
                                'printf "RUN %s\\n" "$metal_test_run"\n'
                                + cleanup_example(str(directory) + suffix)
                                + checked_status + "done\n")
                        process = self.start_example(
                            loop, caller, dict(self.env, METAL_TEST_GATE="rmdir"))
                        self.wait_ready(process)
                        self.assertFalse((directory / ".metal-diagnostic-run").exists())
                        os.killpg(process.pid, sig)
                        self.release_probe()
                        stdout, _ = self.finish(process)
                        self.assertNotEqual(process.returncode, 0)
                        self.assertEqual(stdout.splitlines(), ["RUN 1"])
                        self.assertFalse(directory.exists())
                        self.assertEqual(self.run_example(
                            cleanup_example(str(directory) + suffix), caller).returncode, 0)

    def test_manual_cleanup_really_terminates_by_signal_after_removal(self):
        for sig in CANCELLATION_SIGNALS:
            with self.subTest(signal=sig.name), self.fixture(rmdir_probe=True):
                directory = self.make_run()
                body = cleanup_example(directory).split("\n", 1)[1].rsplit(
                    "METAL_CLEANUP\n", 1)[0]
                process = self.start_example(body, shutil.which("sh"),
                                             dict(self.env, METAL_TEST_GATE="rmdir"))
                self.wait_ready(process)
                os.killpg(process.pid, sig)
                self.release_probe()
                self.finish(process)
                self.assertEqual(process.returncode, -sig)
                self.assertFalse(directory.exists())

    def test_stalled_manual_deletion_defers_cancellation_until_released(self):
        for sig in CANCELLATION_SIGNALS:
            with self.subTest(signal=sig.name), self.fixture(rmdir_probe=True):
                directory = self.make_run()
                body = cleanup_example(directory).split("\n", 1)[1].rsplit(
                    "METAL_CLEANUP\n", 1)[0]
                process = self.start_example(body, shutil.which("sh"),
                                             dict(self.env, METAL_TEST_GATE="rmdir"))
                self.wait_ready(process)
                os.killpg(process.pid, sig)
                # The controlled deletion stays blocked until this test releases it.
                time.sleep(0.05)
                self.assertFalse(process.exited())
                self.assertTrue(directory.is_dir())
                self.release_probe()
                self.finish(process)
                self.assertEqual(process.returncode, -sig)
                self.assertFalse(directory.exists())

    def test_uncatchable_cleanup_interrupt_refuses_empty_markerless_target(self):
        for caller in CALLERS:
            for suffix in ("", "///"):
                with self.subTest(caller=caller, suffix=suffix), self.fixture(rmdir_probe=True):
                    directory = self.make_run()
                    process = self.start_example(cleanup_example(str(directory) + suffix),
                                                 caller, dict(self.env, METAL_TEST_GATE="rmdir"))
                    self.wait_ready(process)
                    self.assertFalse((directory / ".metal-diagnostic-run").exists())
                    os.killpg(process.pid, signal.SIGKILL)
                    self.finish(process)
                    self.assertNotEqual(process.returncode, 0)
                    self.assertTrue(directory.is_dir())
                    self.assertEqual(snapshot(directory), {})
                    self.assertEqual(self.run_example(
                        cleanup_example(str(directory) + suffix), caller).returncode, 1)
                    self.assertTrue(directory.is_dir())
                    self.assertEqual(snapshot(directory), {})

    def test_late_metadata_after_marker_removal_requires_inspected_recovery(self):
        with self.fixture(rmdir_probe=True):
            directory = self.make_run()
            first = self.run_example(cleanup_example(directory),
                                     env=dict(self.env, METAL_TEST_LATE_METADATA="1"))
            self.assertNotEqual(first.returncode, 0)
            self.assertFalse((directory / ".metal-diagnostic-run").exists())
            self.assertFalse((directory / "Shaders.diagnostic.metallib").exists())
            metadata = directory / ".DS_Store"
            self.assertEqual(metadata.read_bytes(), b"late metadata")
            self.assertEqual(self.run_example(cleanup_example(directory)).returncode, 1)
            self.assertEqual(metadata.read_bytes(), b"late metadata")

    def test_inspection_is_self_contained_and_read_only(self):
        for reference in DIAGNOSTIC_REFERENCES:
            with self.subTest(reference=reference.name), self.fixture():
                directory = self.make_run(marker=None)
                (directory / ".DS_Store").write_bytes(b"metadata")
                (directory / "notes").write_bytes(b"operator must inspect this")
                before = snapshot(directory)
                inherited = str(self.base / "conflicting inherited inspection path")
                env = dict(self.env, metal_inspect_dir=inherited)
                for suffix in ("", "///"):
                    result = self.run_example(
                        inspection_example(str(directory) + suffix, reference), env=env)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(str(directory), result.stdout)
                    self.assertNotIn(inherited, result.stdout)
                    self.assertIn("notes", result.stdout)
                    self.assertIn(".DS_Store", result.stdout)
                    self.assertEqual(snapshot(directory), before)
                self.assertEqual(self.run_example(cleanup_example(directory)).returncode, 1)

    def test_inspection_refuses_symlinks_and_invalid_targets_with_stderr_errors(self):
        variants = ("symlink", "symlink-slash", "symlink-dot", "dot", "parent",
                    "trailing-parent", "file", "missing")
        for reference in DIAGNOSTIC_REFERENCES:
            for variant in variants:
                for stream in ("normal", "closed", "broken-pipe"):
                    with self.subTest(reference=reference.name, variant=variant, stream=stream), \
                            self.fixture():
                        directory = self.make_run(marker=None)
                        (directory / "notes").write_bytes(b"operator must inspect this")
                        alias = self.outputs / "directory alias"
                        alias.symlink_to(directory, target_is_directory=True)
                        target = {
                            "symlink": str(alias), "symlink-slash": str(alias) + "///",
                            "symlink-dot": str(alias) + "/./",
                            "dot": str(directory) + "/.",
                            "parent": str(directory) + "/../" + directory.name,
                            "trailing-parent": str(directory) + "/..",
                            "file": str(directory / "notes"),
                            "missing": str(self.outputs / "missing directory"),
                        }[variant]
                        before = snapshot(self.outputs)
                        example = inspection_example(target, reference)
                        if stream == "closed":
                            example = example.replace("sh <<", "sh 2>&- <<", 1)
                        if stream == "broken-pipe":
                            reader, writer = os.pipe()
                            os.close(reader)
                            try:
                                process = self.start_example(example, CALLERS[0], self.env,
                                                             stderr=writer)
                            finally:
                                os.close(writer)
                            stdout, _ = self.finish(process)
                            status = process.returncode
                        else:
                            result = self.run_example(example)
                            stdout, status = result.stdout, result.returncode
                            if stream == "normal":
                                category = ("dot or parent components" if variant in
                                            ("symlink-dot", "dot", "parent", "trailing-parent")
                                            else "existing nonsymlink directory")
                                self.assertIn(category, result.stderr)
                                self.assertIn(target.rstrip("/"), result.stderr)
                        self.assertEqual(status, 1)
                        self.assertEqual(stdout, "")
                        self.assertEqual(snapshot(self.outputs), before)

    def test_refusal_status_survives_stderr_errors(self):
        cases = ("relative-root", "boundary-root", "manual-refusal",
                 "inspection-unset", "inspection-empty", "inspection-relative")
        for caller in CALLERS:
            for stream in ("closed", "broken-pipe"):
                for case in cases:
                    with self.subTest(caller=caller, stream=stream, case=case), self.fixture():
                        env = dict(self.env)
                        if case == "relative-root":
                            example = build_example()
                            env["TMPDIR"] = "relative"
                        elif case == "boundary-root":
                            example = build_example()
                            env["TMPDIR"] = str(self.project)
                        elif case == "manual-refusal":
                            directory = self.make_run(marker=None)
                            example = cleanup_example(directory)
                        else:
                            value = {"inspection-unset": None, "inspection-empty": "",
                                     "inspection-relative": "relative"}[case]
                            example = inspection_example(value)
                        if stream == "closed":
                            example = example.replace("sh <<", "sh 2>&- <<", 1)
                            result = self.run_example(example, caller, env)
                        else:
                            reader, writer = os.pipe()
                            os.close(reader)
                            try:
                                process = self.start_example(example, caller, env, stderr=writer)
                            finally:
                                os.close(writer)
                            stdout, _ = self.finish(process)
                            result = subprocess.CompletedProcess([], process.returncode, stdout, "")
                        self.assertEqual(result.returncode, 1, result.stderr)
                        self.assertEqual(result.stdout, "")

    def test_native_cleanup_errors_remain_visible(self):
        if os.geteuid() == 0:
            self.skipTest("root can bypass directory permissions")
        with self.fixture():
            directory = self.make_run()
            self.outputs.chmod(0o500)
            try:
                result = self.run_example(cleanup_example(directory))
            finally:
                self.outputs.chmod(0o700)
            self.assertEqual(result.returncode, 1)
            self.assertIn(str(directory), result.stderr)
            self.assertNotIn("Refusing cleanup", result.stderr)
            self.assertFalse((directory / ".metal-diagnostic-run").exists())

    def test_leak_inventory_sees_unlogged_entries(self):
        with self.fixture():
            stray = self.outputs / "stray file"
            stray.write_bytes(b"unlogged output")
            directory = self.outputs / "unlogged directory"
            directory.mkdir()
            self.assertEqual(self.allocations(), [])
            self.assertEqual(set(self.remaining_outputs()), {stray, directory})
            metadata = self.outputs / ".DS_Store"
            metadata.unlink()
            metadata.symlink_to(stray)
            self.assertIn(metadata, self.remaining_outputs())

    def test_snapshot_metadata_filter_is_explicit(self):
        with self.fixture():
            directory = self.make_run()
            metadata = directory / ".DS_Store"
            metadata.write_bytes(b"before")
            exact_before = snapshot(directory)
            incidental_before = snapshot(directory, ignore_metadata=True)
            metadata.write_bytes(b"after")
            self.assertNotEqual(snapshot(directory), exact_before)
            self.assertEqual(snapshot(directory, ignore_metadata=True), incidental_before)
            metadata.unlink()
            metadata.symlink_to(directory / "Shaders.diagnostic.metallib")
            self.assertEqual(snapshot(directory, ignore_metadata=True)[".DS_Store"][0], "symlink")

    def test_fallback_allocations_are_removed_after_fixture_failure(self):
        # A separate, unrecorded temporary directory is outside the fixture's ownership.
        with external_run() as unrelated:
            self.assertRegex(unrelated.name, r"^metal-diagnostic\.[A-Za-z0-9]{6}$")
            sentinel = unrelated / "keep"
            sentinel.write_bytes(b"unrelated")
            with self.assertRaisesRegex(RuntimeError, "injected failure"):
                with self.fixture():
                    env = dict(self.env, METAL_TEST_FAIL="metal", METAL_TEST_INJECT="unexpected")
                    env.pop("TMPDIR", None)
                    result = self.run_example(build_example(), env=env)
                    self.assertEqual(result.returncode, 42)
                    directory, = self.allocations()
                    self.assertEqual(directory.parent, Path("/tmp").resolve())
                    self.assertTrue(directory.exists())
                    raise RuntimeError("injected failure")
            self.assertFalse(directory.exists())
            self.assertEqual(sentinel.read_bytes(), b"unrelated")

    def test_external_allocation_errors_do_not_skip_later_owned_directories(self):
        with tempfile.TemporaryDirectory(prefix="metal-unrelated-", dir="/tmp") as unrelated, \
                external_run() as owned:
            unrelated = Path(unrelated).resolve()
            sentinel = unrelated / "keep"
            sentinel.write_bytes(b"unrelated")
            log = unrelated / "allocations"
            log.write_text(str(unrelated) + "\n" + str(owned) + "\n")
            with self.assertRaisesRegex(AssertionError, "Unexpected external test allocation"):
                self.remove_external_allocations(log, unrelated / "fixture")
            self.assertFalse(owned.exists())
            self.assertEqual(sentinel.read_bytes(), b"unrelated")

    def test_fixture_preserves_primary_failure_and_reports_teardown_error(self):
        original_cause = KeyError("original fixture cause")
        with external_run() as owned:
            with self.assertRaisesRegex(RuntimeError, "primary fixture failure") as raised:
                with self.fixture():
                    base = self.base
                    log = Path(self.env["METAL_TEST_ALLOCATIONS"])
                    log.write_text("/unexpected-unowned-allocation\n" + str(owned) + "\n")
                    raise RuntimeError("primary fixture failure") from original_cause
            self.assertIs(raised.exception.__cause__, original_cause)
            self.assertIn("Unexpected external test allocation", "\n".join(raised.exception.__notes__))
            rendered = "".join(traceback.format_exception(raised.exception))
            self.assertIn("original fixture cause", rendered)
            self.assertIn("Unexpected external test allocation", rendered)
            self.assertFalse(owned.exists())
            self.assertFalse(base.exists())
            self.assertIsNone(self.resources)

    def test_process_start_requires_an_active_fixture(self):
        case = DiagnosticTests("runTest")
        with patch.object(OwnedProcess, "__init__") as start:
            with self.assertRaisesRegex(RuntimeError, "active fixture"):
                case.start_example("exit 0", CALLERS[0], os.environ.copy(), cwd="/tmp")
            start.assert_not_called()
        with case.fixture():
            pass
        self.assertIsNone(case.resources)
        with patch.object(OwnedProcess, "__init__") as start:
            with self.assertRaisesRegex(RuntimeError, "active fixture"):
                case.start_example("exit 0", CALLERS[0], os.environ.copy(), cwd="/tmp")
            start.assert_not_called()

    def test_waitid_capability_only_gates_process_creation(self):
        with patch(__name__ + ".NONREAPING_WAIT", False):
            result = unittest.TestResult()
            DiagnosticTests("test_snapshot_metadata_filter_is_explicit").run(result)
            self.assertEqual(result.testsRun, 1)
            self.assertEqual(result.skipped, [])
            self.assertTrue(result.wasSuccessful(), (result.errors, result.failures))
            with self.fixture(), patch.object(subprocess, "Popen") as spawn:
                with self.assertRaisesRegex(unittest.SkipTest, "waitid"):
                    self.start_example("exit 0", CALLERS[0], self.env)
                spawn.assert_not_called()

    def test_fixture_disables_core_dumps_and_restores_its_limit(self):
        import resource
        before = resource.getrlimit(resource.RLIMIT_CORE)
        with self.fixture():
            self.assertEqual(resource.getrlimit(resource.RLIMIT_CORE)[0], 0)
            result = self.run_example(
                'import resource; print(resource.getrlimit(resource.RLIMIT_CORE)[0])',
                caller=sys.executable)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "0\n")
        self.assertEqual(resource.getrlimit(resource.RLIMIT_CORE), before)

    def test_fixture_preserves_test_level_cleanup_scope(self):
        events = []
        self.addCleanup(events.append, "test cleanup")
        with self.fixture():
            events.append("fixture body")
        self.assertEqual(events, ["fixture body"])

    def test_exited_leader_descendants_are_stopped_before_draining_pipes(self):
        with self.fixture():
            code = ('import os,time\nfrom pathlib import Path\n'
                    'if os.fork(): os._exit(7)\n'
                    'Path(os.environ["METAL_TEST_READY"]).write_text(str(os.getpid()))\n'
                    'time.sleep(30)\n')
            process = self.start_example(code, sys.executable, self.env)
            self.wait_for_file(process, Path(self.env["METAL_TEST_READY"]))
            process.wait_for_exit(timeout=3)
            self.assertIsNone(process.returncode)  # Keep the leader's PID reserved.
            self.assertTrue(any(reader.is_alive() for reader in process._readers))
            process.stop()
            self.assertEqual(process.returncode, 7)
            self.assertTrue(all(not reader.is_alive() for reader in process._readers))
            self.assertTrue(process.pipes_closed)

    def test_unreaped_process_teardown_closes_pipes_and_is_idempotent(self):
        for error in (None, PermissionError("macOS zombie group"), ProcessLookupError()):
            with self.subTest(group_error=type(error).__name__), self.fixture():
                process = self.start_example("import os; os._exit(7)", sys.executable, self.env)
                process.wait_for_exit(timeout=3)
                self.assertIsNone(process.returncode)
                real_killpg = os.killpg
                # Exercise the native macOS zombie behavior as well as deterministic errors.
                with patch.object(os, "killpg", side_effect=error or real_killpg) as kill:
                    process.stop()
                    process.stop()
                    kill.assert_called_once_with(process.pid, signal.SIGKILL)
                self.assertEqual(process.returncode, 7)
                self.assertTrue(process.pipes_closed)

    def test_completed_collection_never_signals_a_reaped_group(self):
        with self.fixture():
            process = self.start_example("exit 0", CALLERS[0], self.env)
            self.assertEqual(self.finish(process), ("", ""))
            self.assertEqual(process.returncode, 0)
            with patch.object(os, "killpg") as kill:
                process.stop()
                kill.assert_not_called()

    def test_process_wrapper_excludes_competing_operations_and_pipe_handles(self):
        with self.fixture():
            process = self.start_example("import time; time.sleep(30)", sys.executable, self.env)
            for operation in ("poll", "wait", "communicate", "stdout", "stderr"):
                with self.subTest(operation=operation), self.assertRaises(AttributeError):
                    getattr(process, operation)
            with self.assertRaises(TypeError):
                with process:
                    self.fail("Unsupported context management was accepted")
            for attribute in ("pid", "returncode", "args"):
                with self.subTest(attribute=attribute), self.assertRaises(AttributeError):
                    setattr(process, attribute, 0)
            self.assertFalse(process.exited())
            process.stop()
            self.assertEqual(process.returncode, -signal.SIGKILL)
            self.assertTrue(process.pipes_closed)

    def test_external_reaping_reports_ownership_loss_without_group_signals(self):
        for mode in ("raw-waitpid", "private-popen-wait"):
            with self.subTest(mode=mode), self.fixture():
                process = self.start_example("exit 7", CALLERS[0], self.env)
                process.wait_for_exit(timeout=3)
                if mode == "raw-waitpid":
                    _, status = os.waitpid(process.pid, 0)
                    self.assertEqual(os.waitstatus_to_exitcode(status), 7)
                else:
                    self.assertEqual(process._process.wait(timeout=3), 7)
                with patch.object(os, "killpg") as kill:
                    with self.assertRaisesRegex(ProcessOwnershipError, "ownership lost") as seen:
                        process.exited()
                    with self.assertRaises(ProcessOwnershipError) as stopped:
                        process.stop()
                    self.assertIs(stopped.exception, seen.exception)
                    process.stop()  # Teardown remains idempotent after reporting the failure.
                    kill.assert_not_called()
                self.assertIsNone(process.returncode)
                self.assertTrue(process.pipes_closed)

    def test_collection_timeout_retains_output_and_secondary_teardown_error(self):
        with self.fixture():
            code = ('import os,time\nfrom pathlib import Path\n'
                    'os.write(1,b"stdout sentinel\\n");os.write(2,b"stderr sentinel\\n")\n'
                    'Path(os.environ["METAL_TEST_READY"]).touch()\ntime.sleep(30)\n')
            process = self.start_example(code, sys.executable, self.env)
            self.wait_ready(process)
            stop = process.stop

            def failing_stop():
                stop()  # Really stop the owned child before injecting the secondary failure.
                raise RuntimeError("secondary teardown sentinel")

            original_cause = KeyError("original timeout cause")
            timeout = subprocess.TimeoutExpired(process.args, 0.01)

            def fail_wait(_):
                raise timeout from original_cause

            with patch.object(process, "wait_for_exit", side_effect=fail_wait), \
                    patch.object(process, "stop", side_effect=failing_stop):
                with self.assertRaisesRegex(AssertionError, "Diagnostic exceeded bounded wait") as raised:
                    self.finish(process, timeout=0.01)
            self.assertIs(raised.exception.__cause__, timeout)
            self.assertIs(timeout.__cause__, original_cause)
            self.assertEqual(timeout.output, "stdout sentinel\n")
            self.assertEqual(timeout.stderr, "stderr sentinel\n")
            rendered = "".join(traceback.format_exception(raised.exception))
            for expected in ("original timeout cause", "secondary teardown sentinel",
                             "stdout sentinel", "stderr sentinel"):
                self.assertIn(expected, rendered)
            self.assertTrue(process.pipes_closed)

    def test_standalone_teardown_failure_remains_a_failure(self):
        with self.fixture():
            process = self.start_example("exit 0", CALLERS[0], self.env)
            stop = process.stop

            def failing_stop():
                stop()
                raise RuntimeError("standalone teardown sentinel")

            with patch.object(process, "stop", side_effect=failing_stop):
                with self.assertRaisesRegex(RuntimeError, "standalone teardown sentinel"):
                    self.finish(process)

    def test_large_output_is_drained_without_reaping_the_live_leader(self):
        with self.fixture():
            code = ('import os\nfrom pathlib import Path\n'
                    'os.write(1,b"x"*131072)\nos.write(2,b"y"*131072)\n'
                    'Path(os.environ["METAL_TEST_READY"]).write_text("flushed")\n')
            process = self.start_example(code, sys.executable, self.env)
            self.wait_for_file(process, Path(self.env["METAL_TEST_READY"]), timeout=3)
            process.wait_for_exit(timeout=3)
            self.assertIsNone(process.returncode)
            self.assertEqual(self.finish(process), ("x" * 131072, "y" * 131072))
            self.assertEqual(process.returncode, 0)

    def test_working_directory_boundary_without_git(self):
        for location in ("temporary-root", "project-root", "project-subdirectory"):
            with self.subTest(location=location), self.fixture():
                git = self.bin / "git"
                git.write_text("#!/bin/sh\nexit 1\n")
                git.chmod(0o700)
                if location == "temporary-root":
                    cwd, root = self.outputs, self.outputs
                else:
                    root = self.project / "temporary"
                    root.mkdir()
                    cwd = self.project
                    if location == "project-subdirectory":
                        cwd = self.project / "source"
                        cwd.mkdir()
                        (cwd / "Shaders.metal").write_text(SHADER)
                result = self.run_example(build_example(), cwd=cwd,
                                          env=dict(self.env, TMPDIR=str(root)))
                if location == "project-subdirectory":
                    # This is the documented limit of the working-directory fallback.
                    self.assertEqual(result.returncode, 0, result.stderr)
                    library = Path(result.stdout.strip())
                    self.assertEqual(library.parent.parent, root)
                    self.assertEqual(self.run_example(cleanup_example(library.parent)).returncode, 0)
                else:
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("outside the working directory (" + str(cwd) + ")", result.stderr)
                    self.assertEqual(self.allocations(), [])

    def test_failed_subcase_cannot_contaminate_next_fixture(self):
        bases, processes = [], []

        class FailingSubcases(DiagnosticTests):
            def exercise(self):
                for index in range(2):
                    with self.subTest(index=index), self.fixture():
                        bases.append(self.base)
                        self.make_run()  # Reuse a fixed name in independently owned fixtures.
                        if index == 0:
                            process = self.start_example(build_example(), CALLERS[0],
                                                         dict(self.env, METAL_TEST_GATE="allocation"))
                            processes.append(process)
                            self.wait_ready(process)
                            self.fail("injected first-subcase failure")
                        self.assertFalse(bases[0].exists())
                        self.assertIsNotNone(processes[0].returncode)
                        self.assertTrue(processes[0].pipes_closed)

        result = unittest.TestResult()
        FailingSubcases("exercise").run(result)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(len(bases), 2)
        self.assertNotEqual(bases[0], bases[1])
        self.assertTrue(all(not base.exists() for base in bases))

    def test_automatic_cleanup_refuses_unexpected_entries_and_symlinks(self):
        for variant in ("unexpected", "symlink", "directory"):
            with self.subTest(variant=variant), self.fixture():
                victim = self.base / "victim"
                victim.write_bytes(b"unrelated")
                result = self.run_example(build_example(), env=dict(
                    self.env, METAL_TEST_FAIL="metal", METAL_TEST_INJECT=variant,
                    METAL_TEST_VICTIM=str(victim)))
                self.assertEqual(result.returncode, 42)
                self.assertIn("Refusing or unable to clean", result.stderr)
                directories = self.remaining_outputs()
                self.assertEqual(len(directories), 1)
                directory = directories[0]
                self.assertEqual((directory / ".metal-diagnostic-run").read_bytes(), MARKER)
                self.assertTrue((directory / "Shaders.air").exists())
                self.assertEqual(victim.read_bytes(), b"unrelated")


if __name__ == "__main__":
    unittest.main()
