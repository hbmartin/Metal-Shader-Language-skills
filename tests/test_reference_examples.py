"""Execute the documented examples with temporary fixtures and bounded signal probes."""

import sys

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import unittest


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


def snapshot(directory):
    result = {}
    for entry in sorted(directory.iterdir()):
        if entry.is_symlink():
            result[entry.name] = ("symlink", os.readlink(entry))
        elif entry.is_dir():
            result[entry.name] = ("directory", snapshot(entry))
        else:
            result[entry.name] = ("file", entry.read_bytes())
    return result


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


@unittest.skipUnless(os.name == "posix" and CALLERS, "requires POSIX shells")
class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="metal-reference-tests-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.project = self.base / "project with spaces"
        self.project.mkdir()
        (self.project / "Shaders.metal").write_text(SHADER)
        (self.project / "Shaders.diagnostic.metallib").write_bytes(b"project sentinel")
        self.original_project = snapshot(self.project)
        self.outputs = self.base / "temporary outputs"
        self.outputs.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for name in ("xcrun", "mktemp", "metal-test-gate"):
            executable = self.bin / name
            executable.write_text("#!" + sys.executable + "\n" + STUB)
            executable.chmod(0o700)
        self.env = os.environ.copy()
        self.env.update(
            TMPDIR=str(self.outputs),
            PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", os.defpath),
            METAL_TEST_REAL_MKTEMP=shutil.which("mktemp") or "/usr/bin/mktemp",
            METAL_TEST_ALLOCATIONS=str(self.base / "allocations"),
            METAL_TEST_CALLS=str(self.base / "compiler calls"),
            METAL_TEST_READY=str(self.base / "ready"),
            METAL_TEST_RELEASE=str(self.base / "release"),
        )

    def run_example(self, example, caller=None, env=None, cwd=None):
        return subprocess.run(
            [caller or CALLERS[0], "-c", example], cwd=cwd or self.project,
            env=env or self.env, capture_output=True, text=True, timeout=12,
        )

    def start_example(self, example, caller, env):
        process = subprocess.Popen(
            [caller, "-c", example], cwd=self.project, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
        self.addCleanup(self.stop_process, process)
        return process

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=3)

    def finish(self, process):
        try:
            return process.communicate(timeout=8)
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

    def reset_probe(self):
        for key in ("METAL_TEST_READY", "METAL_TEST_RELEASE"):
            Path(self.env[key]).unlink(missing_ok=True)

    def retained_library(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        library = Path(lines[0])
        self.assertTrue(library.is_absolute())
        self.assertTrue(library.is_file())
        self.assertEqual(library.parent.parent, self.outputs)
        self.assertEqual(snapshot(library.parent), {
            ".metal-diagnostic-run": ("file", MARKER),
            "Shaders.diagnostic.metallib": ("file", b"library"),
        })
        self.assertEqual(stat.S_IMODE(library.parent.stat().st_mode) & 0o077, 0)
        return library

    def test_success_repeated_builds_and_cleanup(self):
        libraries = set()
        for caller in CALLERS:
            for path in DIAGNOSTIC_REFERENCES:
                with self.subTest(caller=caller, reference=path.name):
                    result = self.run_example(build_example(path), caller)
                    library = self.retained_library(result)
                    self.assertNotIn(library, libraries)
                    libraries.add(library)
                    self.assertIn(str(library.parent), result.stderr)
                    cleanup = cleanup_example(str(library.parent) + "///", path)
                    self.assertEqual(self.run_example(cleanup, caller).returncode, 0)
                    self.assertEqual(self.run_example(cleanup, caller).returncode, 0)
                    self.assertFalse(library.parent.exists())
        self.assertEqual(snapshot(self.project), self.original_project)

    def test_compile_and_link_failures_preserve_status(self):
        for caller in CALLERS:
            for stage, status in (("metal", 42), ("metallib", 43)):
                with self.subTest(caller=caller, stage=stage):
                    env = dict(self.env, METAL_TEST_FAIL=stage,
                               METAL_TEST_FAILURE_STATUS=str(status))
                    result = self.run_example(build_example(), caller, env)
                    self.assertEqual(result.returncode, status, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(list(self.outputs.iterdir()), [])
                    self.assertEqual(snapshot(self.project), self.original_project)

    def test_concurrent_builds_use_separate_directories(self):
        for caller in CALLERS:
            with self.subTest(caller=caller):
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
        self.assertEqual(snapshot(self.project), self.original_project)

    def test_invalid_temporary_roots_allocate_nothing(self):
        nested = self.project / "temporary"
        nested.mkdir()
        alias = self.base / "project alias"
        alias.symlink_to(self.project, target_is_directory=True)
        for root in ("relative", "-temporary", str(self.project), str(nested), str(alias)):
            with self.subTest(root=root):
                result = self.run_example(build_example(), env=dict(self.env, TMPDIR=root))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertFalse(Path(self.env["METAL_TEST_ALLOCATIONS"]).exists())
        self.assertEqual(list(self.outputs.iterdir()), [])
        self.assertEqual((self.project / "Shaders.diagnostic.metallib").read_bytes(),
                         b"project sentinel")

    def test_git_project_root_is_used_from_subdirectory(self):
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
        self.assertIn("outside the project", result.stderr)
        self.assertFalse(Path(self.env["METAL_TEST_ALLOCATIONS"]).exists())

    def test_temporary_root_symlink_resolves_to_physical_path(self):
        alias = self.base / "temporary alias"
        alias.symlink_to(self.outputs, target_is_directory=True)
        result = self.run_example(build_example(), env=dict(self.env, TMPDIR=str(alias)))
        library = self.retained_library(result)
        self.assertEqual(self.run_example(cleanup_example(library.parent)).returncode, 0)

    def test_unset_temporary_root_falls_back_outside_project(self):
        env = dict(self.env, METAL_TEST_FAIL="metal")
        env.pop("TMPDIR", None)
        result = self.run_example(build_example(), env=env)
        self.assertEqual(result.returncode, 42, result.stderr)
        directory = Path(Path(self.env["METAL_TEST_ALLOCATIONS"]).read_text().strip())
        self.assertEqual(directory.parent, Path("/tmp").resolve())
        self.assertFalse(directory.exists())
        self.assertEqual(snapshot(self.project), self.original_project)

    def test_stderr_errors_do_not_invalidate_success(self):
        example = build_example().replace("sh <<", "sh 2>&- <<", 1)
        for caller in CALLERS:
            with self.subTest(caller=caller):
                library = self.retained_library(self.run_example(example, caller))
                self.assertEqual(self.run_example(
                    cleanup_example(library.parent), caller).returncode, 0)

    def test_stdout_error_retains_completed_outputs(self):
        example = build_example().replace("sh <<", "sh 1>&- <<", 1)
        result = self.run_example(example)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        directories = list(self.outputs.iterdir())
        self.assertEqual(len(directories), 1)
        self.assertEqual(snapshot(directories[0]), {
            ".metal-diagnostic-run": ("file", MARKER),
            "Shaders.diagnostic.metallib": ("file", b"library"),
        })
        self.assertEqual(self.run_example(cleanup_example(directories[0])).returncode, 0)

    def test_signals_during_allocation_and_compilation_stop_loops(self):
        for caller in CALLERS:
            for phase in ("allocation", "metal", "metallib"):
                for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                    with self.subTest(caller=caller, phase=phase, signal=sig.name):
                        self.reset_probe()
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
                        self.assertEqual(list(self.outputs.iterdir()), [])
        self.assertEqual(snapshot(self.project), self.original_project)

    def test_diagnostic_process_really_terminates_by_signal(self):
        # Execute the extracted here-document body directly to inspect wait status.
        body = build_example().split("\n", 1)[1].rsplit("METAL_DIAGNOSTIC\n", 1)[0]
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=sig.name):
                self.reset_probe()
                process = self.start_example(body, shutil.which("sh"),
                                             dict(self.env, METAL_TEST_GATE="metal"))
                self.wait_ready(process)
                os.killpg(process.pid, sig)
                self.release_probe()
                self.finish(process)
                self.assertEqual(process.returncode, -sig)
                self.assertEqual(list(self.outputs.iterdir()), [])

    def test_signals_during_final_cleanup_preserve_signal_status(self):
        boundary = "    trap - INT TERM HUP\n"
        self.assertEqual(build_example().count(boundary), 1)
        # Cleanup runs in a conditional context: its failure must not trigger
        # errexit before the EXIT handler can honor a recorded signal.
        example = build_example().replace(
            boundary, "    metal-test-gate exit-cleanup || :\n" + boundary)
        body = example.split("\n", 1)[1].rsplit("METAL_DIAGNOSTIC\n", 1)[0]
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=sig.name):
                self.reset_probe()
                process = self.start_example(
                    body, shutil.which("sh"),
                    dict(self.env, METAL_TEST_FAIL="metal",
                         METAL_TEST_GATE="exit-cleanup"))
                self.wait_ready(process)
                os.killpg(process.pid, sig)
                self.release_probe()
                self.finish(process)
                self.assertEqual(process.returncode, -sig)
                self.assertEqual(list(self.outputs.iterdir()), [])

    def test_publication_interrupts_retain_completed_library(self):
        publication = "printf '%s\\n' \"$metal_library\"\n"
        self.assertEqual(build_example().count(publication), 1)
        for caller in CALLERS:
            for position in ("before", "after"):
                for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                    with self.subTest(caller=caller, position=position, signal=sig.name):
                        self.reset_probe()
                        probe = "metal-test-gate publication\n"
                        replacement = (probe + publication if position == "before"
                                       else publication + probe)
                        example = build_example().replace(publication, replacement)
                        process = self.start_example(
                            example, caller, dict(self.env, METAL_TEST_GATE="publication"))
                        self.wait_ready(process)
                        os.killpg(process.pid, sig)
                        self.release_probe()
                        stdout, _ = self.finish(process)
                        self.assertNotEqual(process.returncode, 0)
                        directories = list(self.outputs.iterdir())
                        self.assertEqual(len(directories), 1)
                        library = directories[0] / "Shaders.diagnostic.metallib"
                        self.assertEqual(library.read_bytes(), b"library")
                        self.assertEqual((directories[0] / ".metal-diagnostic-run").read_bytes(),
                                         MARKER)
                        self.assertEqual(stdout.splitlines(),
                                         [str(library)] if position == "after" else [])
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
                with self.subTest(caller=caller, variant=variant):
                    directory = self.make_run(name="metal-diagnostic.backup")
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
                    shutil.rmtree(directory)

    def test_cleanup_refuses_symlinks_without_changing_targets(self):
        for caller in CALLERS:
            for variant in ("directory", "marker", "library", "dangling-air"):
                with self.subTest(caller=caller, variant=variant):
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
                        }[variant]
                        entry.unlink(missing_ok=True)
                        entry.symlink_to(victim if variant != "dangling-air"
                                         else self.base / "missing victim")
                    before = snapshot(directory)
                    result = self.run_example(cleanup_example(str(path) + "/"), caller)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(snapshot(directory), before)
                    self.assertEqual(victim.read_bytes(), MARKER)
                    if path.is_symlink():
                        path.unlink()
                    shutil.rmtree(directory)
                    victim.unlink()

    def test_cleanup_rejects_malformed_paths(self):
        directory = self.make_run()
        inputs = ("", "/", ".", "relative/metal-diagnostic.abc123",
                  str(self.outputs / "metal-diagnostic.too-long"),
                  str(self.outputs) + "/./" + directory.name,
                  str(self.outputs) + "/../temporary outputs/" + directory.name,
                  str(directory) + "/.")
        before = snapshot(directory)
        for path in inputs:
            with self.subTest(path=path):
                self.assertEqual(self.run_example(cleanup_example(path)).returncode, 1)
                self.assertEqual(snapshot(directory), before)

    def test_cleanup_accepts_known_intermediate(self):
        directory = self.make_run()
        (directory / "Shaders.air").write_bytes(b"air")
        self.assertEqual(self.run_example(cleanup_example(directory)).returncode, 0)
        self.assertFalse(directory.exists())

    def test_automatic_cleanup_refuses_unexpected_entries_and_symlinks(self):
        victim = self.base / "victim"
        victim.write_bytes(b"unrelated")
        for variant in ("unexpected", "symlink", "directory"):
            with self.subTest(variant=variant):
                result = self.run_example(build_example(), env=dict(
                    self.env, METAL_TEST_FAIL="metal", METAL_TEST_INJECT=variant,
                    METAL_TEST_VICTIM=str(victim)))
                self.assertEqual(result.returncode, 42)
                self.assertIn("Refusing or unable to clean", result.stderr)
                directories = list(self.outputs.iterdir())
                self.assertEqual(len(directories), 1)
                directory = directories[0]
                self.assertEqual((directory / ".metal-diagnostic-run").read_bytes(), MARKER)
                self.assertTrue((directory / "Shaders.air").exists())
                self.assertEqual(victim.read_bytes(), b"unrelated")
                shutil.rmtree(directory)


class ToolchainTests(unittest.TestCase):
    def sdk(self, name):
        if not shutil.which("xcrun"):
            self.skipTest("Xcode SDKs unavailable: xcrun not installed")
        result = subprocess.run(["xcrun", "--sdk", name, "--show-sdk-path"],
                                capture_output=True, text=True, timeout=20)
        if result.returncode:
            self.skipTest(f"{name} SDK unavailable: {result.stderr.strip()}")
        return result.stdout.strip()

    def targets(self):
        return (
            ("macosx", "arm64-apple-macosx14.0"),
            ("macosx", "x86_64-apple-macosx14.0"),
            ("macosx", "arm64-apple-ios17.0-macabi"),
            ("macosx", "x86_64-apple-ios17.0-macabi"),
            ("iphonesimulator", "arm64-apple-ios17.0-simulator"),
            ("iphonesimulator", "x86_64-apple-ios17.0-simulator"),
        )

    def test_swift_alignment_typechecks_for_every_target(self):
        compiler = shutil.which("swiftc")
        if not compiler:
            self.skipTest("swiftc unavailable")
        with tempfile.TemporaryDirectory(prefix="metal-swift-tests-", dir="/tmp") as temp:
            source = Path(temp) / "Alignment.swift"
            source.write_text(block(ALIGNMENT_REFERENCES[0], "swift",
                                    "constantBufferOffsetAlignment"))
            for sdk_name, target in self.targets():
                with self.subTest(target=target):
                    result = subprocess.run(
                        [compiler, "-typecheck", "-target", target, "-sdk",
                         self.sdk(sdk_name), str(source)],
                        capture_output=True, text=True, timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_swift_alignment_policy_value(self):
        compiler = shutil.which("swiftc")
        if not compiler:
            self.skipTest("swiftc unavailable")
        with tempfile.TemporaryDirectory(prefix="metal-swift-value-", dir="/tmp") as temp:
            source = Path(temp) / "Alignment.swift"
            binary = Path(temp) / "alignment"
            source.write_text(block(ALIGNMENT_REFERENCES[0], "swift",
                                    "constantBufferOffsetAlignment")
                              + "print(constantBufferOffsetAlignment)\n")
            result = subprocess.run([compiler, str(source), "-o", str(binary)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "256\n")

    def test_c_and_objective_c_alignment_for_every_target(self):
        compiler = shutil.which("clang")
        if not compiler:
            self.skipTest("clang unavailable")
        source = (block(ALIGNMENT_REFERENCES[0], "c", "constantBufferOffsetAlignment")
                  + '_Static_assert(constantBufferOffsetAlignment == 256, "alignment policy");\n')
        for sdk_name, target in self.targets():
            for language in ("c", "objective-c"):
                with self.subTest(target=target, language=language):
                    result = subprocess.run(
                        [compiler, "-fsyntax-only", "-target", target, "-isysroot",
                         self.sdk(sdk_name), "-x", language, "-"],
                        input=source, capture_output=True, text=True, timeout=20,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_metal_compile_and_link(self):
        self.sdk("macosx")
        for tool in ("metal", "metallib"):
            available = subprocess.run(["xcrun", "--sdk", "macosx", "--find", tool],
                                       capture_output=True, text=True, timeout=20)
            if available.returncode:
                self.skipTest(f"{tool} unavailable: {available.stderr.strip()}")
        with tempfile.TemporaryDirectory(prefix="metal-real-build-", dir="/tmp") as temp:
            base = Path(temp).resolve()
            project = base / "source"
            project.mkdir()
            (project / "Shaders.metal").write_text(SHADER)
            outputs = base / "outputs"
            outputs.mkdir()
            env = dict(os.environ, TMPDIR=str(outputs))
            result = subprocess.run(
                [shutil.which("sh"), "-c", build_example()], cwd=project, env=env,
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode and "missing Metal Toolchain" in result.stderr:
                self.skipTest(result.stderr.strip())
            self.assertEqual(result.returncode, 0, result.stderr)
            library = Path(result.stdout.strip())
            self.assertTrue(library.is_file())
            self.assertGreater(library.stat().st_size, 0)
            self.assertEqual({entry.name for entry in library.parent.iterdir()},
                             {"Shaders.diagnostic.metallib", ".metal-diagnostic-run"})
            cleanup = subprocess.run(
                [shutil.which("sh"), "-c", cleanup_example(library.parent)],
                cwd=project, env=env, capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(cleanup.returncode, 0, cleanup.stderr)
            self.assertFalse(library.parent.exists())


if __name__ == "__main__":
    unittest.main()
