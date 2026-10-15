"""Execute the documented examples with temporary fixtures and bounded signal probes."""

from contextlib import ExitStack, contextmanager
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
import time
import unittest
from unittest.mock import patch


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

for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
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
        with ExitStack() as resources:
            self.resources = resources
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

    @staticmethod
    def remove_external_allocations(log, base):
        for directory in allocation_records(log):
            if base in directory.parents:
                continue  # TemporaryDirectory owns these, including unlogged entries.
            # Only the real fallback /tmp allocations can be outside this fixture.
            if (directory.parent != Path("/tmp").resolve()
                    or not re.fullmatch(r"metal-diagnostic\.[A-Za-z0-9]{6}", directory.name)):
                raise AssertionError(f"Unexpected external test allocation: {directory}")
            if directory.is_symlink():
                directory.unlink()
            elif directory.exists():
                shutil.rmtree(directory)

    def run_example(self, example, caller=None, env=None, cwd=None):
        process = self.start_example(example, caller or CALLERS[0], env or self.env, cwd=cwd)
        stdout, stderr = self.finish(process, timeout=12)
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)

    def start_example(self, example, caller, env, stderr=subprocess.PIPE, cwd=None):
        process = subprocess.Popen(
            [caller, "-c", example], cwd=cwd or self.project, env=env,
            stdout=subprocess.PIPE, stderr=stderr, text=True,
            start_new_session=True,
        )
        self.resources.callback(self.stop_process, process)
        return process

    @staticmethod
    def stop_process(process):
        # Descendants can hold pipes open after the session leader has exited.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=3)
        finally:
            for stream in (process.stdout, process.stderr):
                if stream:
                    stream.close()

    def allocations(self):
        return allocation_records(Path(self.env["METAL_TEST_ALLOCATIONS"]))

    def remaining_outputs(self):
        remaining = {path for path in self.allocations() if path.exists() or path.is_symlink()}
        remaining.update(entry for entry in self.outputs.iterdir()
                         if not ordinary_finder_metadata(entry))
        return sorted(remaining)

    def finish(self, process, timeout=8):
        try:
            return process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output = process.communicate(timeout=3)
            self.fail(f"Diagnostic exceeded bounded wait: {output!r}")

    def wait_ready(self, process):
        ready = Path(self.env["METAL_TEST_READY"])
        deadline = time.monotonic() + 4
        while not ready.exists():
            if process.poll() is not None:
                self.fail(f"Diagnostic exited before probe: {process.communicate()!r}")
            if time.monotonic() > deadline:
                self.fail("Diagnostic never reached the signal probe")
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
                self.assertEqual(process.stderr.readline(),
                                 "Diagnostic run directory: " + str(directory) + "\n")
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
                for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                    with self.subTest(caller=caller, phase=phase, signal=sig.name), self.fixture():
                        env = dict(self.env, METAL_TEST_GATE=phase)
                        loop = ('for metal_test_run in 1 2 3; do\n'
                                'printf "RUN %s\\n" "$metal_test_run"\n'
                                + build_example() + "done\n")
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
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
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
        boundary = "    trap - INT TERM HUP\n"
        self.assertEqual(build_example().count(boundary), 1)
        # Cleanup runs in a conditional context: its failure must not trigger
        # errexit before the EXIT handler can honor a recorded signal.
        example = build_example().replace(
            boundary, "    metal-test-gate exit-cleanup || :\n" + boundary)
        body = example.split("\n", 1)[1].rsplit("METAL_DIAGNOSTIC\n", 1)[0]
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
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
                for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
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

    def test_interrupted_cleanup_refuses_empty_markerless_target(self):
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=sig.name), self.fixture(rmdir_probe=True):
                directory = self.make_run()
                process = self.start_example(cleanup_example(directory), CALLERS[0],
                                             dict(self.env, METAL_TEST_GATE="rmdir"))
                self.wait_ready(process)
                self.assertFalse((directory / ".metal-diagnostic-run").exists())
                os.killpg(process.pid, sig)
                self.release_probe()
                self.finish(process)
                self.assertNotEqual(process.returncode, 0)
                self.assertTrue(directory.is_dir())
                self.assertEqual(snapshot(directory), {})
                self.assertEqual(self.run_example(cleanup_example(directory)).returncode, 1)
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
                env = dict(self.env)
                env.pop("metal_run_dir", None)
                result = self.run_example(inspection_example(directory, reference), env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(str(directory), result.stdout)
                self.assertIn("notes", result.stdout)
                self.assertIn(".DS_Store", result.stdout)
                self.assertEqual(snapshot(directory), before)
                self.assertEqual(self.run_example(cleanup_example(directory)).returncode, 1)

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
        with tempfile.TemporaryDirectory(prefix="metal-diagnostic.", dir="/tmp") as unrelated:
            sentinel = Path(unrelated) / "keep"
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

    def test_fixture_preserves_test_level_cleanup_scope(self):
        events = []
        self.addCleanup(events.append, "test cleanup")
        with self.fixture():
            events.append("fixture body")
        self.assertEqual(events, ["fixture body"])

    def test_exited_leader_descendants_are_stopped_before_draining_pipes(self):
        with self.fixture():
            code = ('import os,time\nfrom pathlib import Path\n'
                    'if os.fork(): os._exit(0)\n'
                    'Path(os.environ["METAL_TEST_READY"]).write_text(str(os.getpid()))\n'
                    'time.sleep(30)\n')
            process = self.start_example(code, sys.executable, self.env)
            ready = Path(self.env["METAL_TEST_READY"])
            deadline = time.monotonic() + 4
            while not ready.exists():
                if time.monotonic() > deadline:
                    self.fail("Descendant did not reach the probe")
                time.sleep(0.005)
            self.assertEqual(process.wait(timeout=3), 0)
            communicate = process.communicate

            def drain_after_descendant_exit(*args, **kwargs):
                # This child writes nothing. Readability therefore means EOF,
                # proving it no longer holds stdout open before draining begins.
                readable, _, _ = select.select([process.stdout], [], [], 2)
                self.assertEqual(readable, [process.stdout], "Descendant still holds stdout open")
                return communicate(*args, **kwargs)

            with patch.object(process, "communicate", side_effect=drain_after_descendant_exit):
                self.stop_process(process)
            self.assertTrue(process.stdout.closed)

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
                        self.assertIsNotNone(processes[0].poll())
                        self.assertTrue(processes[0].stdout.closed)

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
