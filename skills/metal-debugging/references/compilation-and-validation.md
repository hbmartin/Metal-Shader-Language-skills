# Compilation and validation

## Reproduce the compiler context

Inspect the project's actual Metal build or runtime compile options. Carry over its SDK, deployment target, language standard, macros, includes, and math options. Pre-4 standards include platform-specific 2.x names and unified `metal3.0`, `metal3.1`, and `metal3.2`; language features still require matching OS and GPU support. Select a standard supported by the project's installed compiler and targets, rather than updating the project to make one snippet compile.

Read the toolchain without changing global configuration:

```sh
xcode-select -p
xcrun --sdk macosx --find metal
xcrun --sdk macosx --show-sdk-version
```

Here is a **macOS / MSL 3.1 example**, not a default for an arbitrary project. Change the SDK (`macosx`, `iphoneos`, `appletvos`, or the project's other target SDK) and standard to match its build. Also use its deployment-target flags when validating compatibility; a language selection alone does not set every host build constraint.

```sh
sh <<'METAL_DIAGNOSTIC'
set -eu
metal_stderr() {
    (trap '' PIPE; printf "$@") >&2 || :
}
metal_sdk="macosx"
metal_language="metal3.1"

metal_temp_root="${TMPDIR:-/tmp}"
case "$metal_temp_root" in
    /*) ;;
    *) metal_stderr 'Temporary root must be absolute: %s\n' "$metal_temp_root"; exit 1 ;;
esac
metal_temp_root="$(CDPATH= cd -P -- "$metal_temp_root" && pwd -P)"
if metal_project_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    metal_boundary_name="Git project"
else
    metal_project_root="$(pwd -P)"
    metal_boundary_name="working directory"
fi
metal_project_root="$(CDPATH= cd -P -- "$metal_project_root" && pwd -P)"
case "$metal_temp_root/" in
    "${metal_project_root%/}/"*)
        metal_stderr 'Temporary root must be outside the %s (%s): %s\n' \
            "$metal_boundary_name" "$metal_project_root" "$metal_temp_root"
        exit 1
        ;;
esac

metal_build_dir=
metal_keep_output=0
metal_pending_signal=
metal_signal_keep_output=0
metal_cleanup() {
    [ "$metal_keep_output" -eq 0 ] && [ -n "$metal_build_dir" ] || return 0
    [ -e "$metal_build_dir" ] || [ -L "$metal_build_dir" ] || return 0
    [ -d "$metal_build_dir" ] && [ ! -L "$metal_build_dir" ] || return 1
    # Validate every entry before deleting any known output.
    for metal_entry in "$metal_build_dir"/* "$metal_build_dir"/.[!.]* "$metal_build_dir"/..?*; do
        [ -e "$metal_entry" ] || [ -L "$metal_entry" ] || continue
        case "${metal_entry##*/}" in
            Shaders.air|Shaders.d|Shaders.diagnostic.metallib|.DS_Store|.metal-diagnostic-run)
                [ -f "$metal_entry" ] && [ ! -L "$metal_entry" ] || return 1
                ;;
            *) return 1 ;;
        esac
    done
    rm -f -- "$metal_build_dir/Shaders.air" "$metal_build_dir/Shaders.diagnostic.metallib" \
        "$metal_build_dir/Shaders.d" "$metal_build_dir/.DS_Store" \
        "$metal_build_dir/.metal-diagnostic-run" || return 1
    rmdir -- "$metal_build_dir"
}
metal_on_exit() {
    metal_status=$?
    metal_abort_if_signalled
    trap - EXIT
    metal_cleanup || {
        metal_stderr 'Refusing or unable to clean run directory: %s\n' "$metal_build_dir"
    }
    trap - INT TERM HUP
    metal_abort_if_signalled
    exit "$metal_status"
}
metal_record_signal() {
    if [ -z "$metal_pending_signal" ]; then
        metal_pending_signal="$1"
        metal_signal_keep_output="$metal_keep_output"
    fi
}
metal_abort_if_signalled() {
    case "$metal_pending_signal" in
        INT) metal_signal_status=130 ;;
        TERM) metal_signal_status=143 ;;
        HUP) metal_signal_status=129 ;;
        *) return 0 ;;
    esac
    metal_keep_output="$metal_signal_keep_output"
    metal_cleanup || {
        metal_stderr 'Refusing or unable to clean run directory: %s\n' "$metal_build_dir"
    }
    trap - EXIT INT TERM HUP
    # Re-raise after the recording trap has returned, including on macOS sh.
    kill -s "$metal_pending_signal" "$$"
    exit "$metal_signal_status"
}
trap 'metal_on_exit' EXIT
trap 'metal_record_signal INT' INT
trap 'metal_record_signal TERM' TERM
trap 'metal_record_signal HUP' HUP
# The allocating child finishes even if the parent records a pending signal.
metal_build_dir="$(trap '' INT TERM HUP; mktemp -d -- "$metal_temp_root/metal-diagnostic.XXXXXX")"
metal_abort_if_signalled
printf 'metal-diagnostic-v1\n' > "$metal_build_dir/.metal-diagnostic-run"
metal_abort_if_signalled
metal_stderr 'Diagnostic run directory: %s\n' "$metal_build_dir"
metal_abort_if_signalled
metal_library="$metal_build_dir/Shaders.diagnostic.metallib"
xcrun --sdk "$metal_sdk" metal -std="$metal_language" \
    -c Shaders.metal -o "$metal_build_dir/Shaders.air"
metal_abort_if_signalled
xcrun --sdk "$metal_sdk" metallib \
    "$metal_build_dir/Shaders.air" -o "$metal_library"
metal_abort_if_signalled
rm -f -- "$metal_build_dir/Shaders.air"
metal_abort_if_signalled
# Once retained, output errors or signals must not invalidate a published path.
metal_keep_output=1
metal_abort_if_signalled
printf '%s\n' "$metal_library"
metal_abort_if_signalled
METAL_DIAGNOSTIC
```

Keep the closing `METAL_DIAGNOSTIC`, `METAL_CLEANUP`, and `METAL_INSPECT` delimiters unindented when inserting these blocks into a function or conditional; leading spaces prevent the shell from recognizing a heredoc delimiter.

Each run launches a separate `sh` process and creates a private, unique directory under the physical path of `${TMPDIR:-/tmp}`. Relative temporary roots are refused. The boundary is the Git project root when available, otherwise the working directory; roots equal to or inside that boundary are refused. Without a discoverable Git root, run from the project root: the recipe cannot identify a non-Git project's ancestor root from a subdirectory. Running from the temporary root itself also fails this check because it equals the working-directory boundary. Keep diagnostic outputs temporary and outside source/resource trees; never commit them.

The marker `.metal-diagnostic-run` identifies this recipe's directories. Signal traps record INT, TERM, and HUP requests; cleanup and re-raising happen at command boundaries after the recording trap returns. The allocating child ignores those signals until it returns its directory path, so pending cancellation can remove the allocated directory. The diagnostic process then terminates by the original signal. This preserves bash's Ctrl-C behavior when a terminal interrupt reaches both the caller and diagnostic process.

After allocation and marker creation, stderr announces `Diagnostic run directory: <absolute path>` before compilation. This annotation is best-effort: a closed descriptor or broken pipe does not fail the build or add text to stdout. Before retention, command failures and handled interruptions remove only known outputs and the empty run directory. Automatic cleanup uses the allocation returned by this process's own `mktemp` call, including cancellation before the marker is created. Known files include regular, nonsymlink `.DS_Store` metadata and `Shaders.d` dependency output produced by an added `-MD` flag. Other entries or symlinks cause cleanup to refuse the directory.

Successful runs remove `Shaders.air`, commit retention, then print one absolute library path on stdout. After retention, output errors or signals leave the library, marker, and any known side files available for inspection, including if cancellation precedes stdout publication. The early stderr announcement identifies that directory when stderr was available. Repeated or concurrent runs use separate directories and leave libraries in the current directory untouched.

After inspection, copy the announced run-directory path into `metal_run_dir` below. Cleanup accepts trailing slashes and succeeds when a valid target is already absent. Every existing target, including an empty directory, requires this recipe's exact regular, nonsymlink marker and only regular, nonsymlink known files; all entries are checked before anything is deleted. A matching folder name alone does not establish ownership. Cleanup removes only the named files and uses `rmdir` to remove the empty directory; it never recurses.

```sh
sh <<'METAL_CLEANUP'
set -eu
metal_stderr() {
    (trap '' PIPE; printf "$@") >&2 || :
}
metal_run_dir="/absolute/path/to/metal-diagnostic.XXXXXX"
metal_refuse_cleanup() {
    metal_stderr 'Refusing cleanup of run directory: %s\n' "$metal_run_dir"
    exit 1
}
while [ "${metal_run_dir%/}" != "$metal_run_dir" ]; do
    metal_run_dir="${metal_run_dir%/}"
done
case "$metal_run_dir" in
    /*) ;;
    *) metal_refuse_cleanup ;;
esac
case "$metal_run_dir" in
    */./*|*/../*) metal_refuse_cleanup ;;
esac
case "${metal_run_dir##*/}" in
    metal-diagnostic.[A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9]) ;;
    *) metal_refuse_cleanup ;;
esac
[ ! -L "$metal_run_dir" ] || metal_refuse_cleanup
# Repeating cleanup of an already-absent valid target is harmless.
[ -e "$metal_run_dir" ] || exit 0
[ -d "$metal_run_dir" ] || metal_refuse_cleanup
metal_run_dir="$(CDPATH= cd -P -- "$metal_run_dir" && pwd -P)"
metal_marker="$metal_run_dir/.metal-diagnostic-run"
[ -f "$metal_marker" ] && [ ! -L "$metal_marker" ] || metal_refuse_cleanup
printf 'metal-diagnostic-v1\n' | cmp -s -- - "$metal_marker" || metal_refuse_cleanup
for metal_entry in "$metal_run_dir"/* "$metal_run_dir"/.[!.]* "$metal_run_dir"/..?*; do
    [ -e "$metal_entry" ] || [ -L "$metal_entry" ] || continue
    case "${metal_entry##*/}" in
        Shaders.air|Shaders.d|Shaders.diagnostic.metallib|.DS_Store|.metal-diagnostic-run)
            [ -f "$metal_entry" ] && [ ! -L "$metal_entry" ] || metal_refuse_cleanup
            ;;
        *) metal_refuse_cleanup ;;
    esac
done
rm -f -- "$metal_run_dir/Shaders.air" "$metal_run_dir/Shaders.diagnostic.metallib" \
    "$metal_run_dir/Shaders.d" "$metal_run_dir/.DS_Store" "$metal_marker"
rmdir -- "$metal_run_dir"
METAL_CLEANUP
```

Legacy runs created without a marker and interrupted cleanup can leave markerless directories, including empty ones. Normal cleanup refuses every existing markerless target. Recovery is operator-managed: select the path explicitly, inspect its directory metadata and entries, and compare them with your own run history before deciding how to handle it. This separate example only lists the selected path; it does not delete anything or establish ownership.

```sh
sh <<'METAL_INSPECT'
set -eu
metal_stderr() {
    (trap '' PIPE; printf "$@") >&2 || :
}
metal_inspect_dir="/absolute/path/to/metal-diagnostic.XXXXXX"
case "${metal_inspect_dir:-}" in
    /*) ;;
    *) metal_stderr 'Inspection path must be absolute and nonempty\n'; exit 1 ;;
esac
ls -ld -- "$metal_inspect_dir"
ls -la -- "$metal_inspect_dir"
METAL_INSPECT
```

An interruption or concurrent file creation between removing the marker and `rmdir` can leave a target that normal cleanup will refuse. Repeating cleanup succeeds for an already-absent valid target; existing markerless leftovers need the inspection above and operator-managed recovery.

`metal -c` checks source compilation; `metallib` links the compiled source into a library. Neither creates or executes the app's render/compute pipeline. For an isolated diagnostic involving NaN/Inf or sensitivity to optimizations, compare with `-fno-fast-math` without changing the shipping configuration. Do not silently add `-Werror` or switch the system-wide Xcode selection.

For runtime source compilation, retain the compiler's full error and the source/options that produced it. Add a useful `#line` filename when generated source needs stable diagnostic locations. Check that the expected entry point exists in the loaded library and that pipeline creation succeeds with the actual attachment formats or compute settings.

## Validate runtime use

In Xcode, use the scheme's Run > Diagnostics options for Metal API Validation and Shader Validation. For a command-line macOS diagnostic run, set the variables before the app creates a Metal device:

```sh
MTL_DEBUG_LAYER=1 MTL_SHADER_VALIDATION=1 \
    MTL_SHADER_VALIDATION_REPORT_TO_STDERR=1 /path/to/app-executable
```

Inspect the original error and implicated allocation/binding before changing instrumentation. Consult the installed `man MetalValidation` for supported options. Validation can affect runtime, compilation, and queried pipeline limits, so re-query dispatch limits and measure performance without instrumentation afterward.

Label resources, pipelines, and encoders so reports identify the actual work. On supported targets, `MTLCommandBufferDescriptor.errorOptions` with `encoderExecutionStatus` gives encoder-level failure information. Inspect status/error after completion; source compilation success and a submitted command buffer do not imply successful GPU execution.

## Capture the failing work

For Xcode capture, enable GPU Frame Capture in the scheme and use the Metal Capture control while reproducing the issue. Include relevant shader source/debug information or companion library symbols so shader inspection has useful source locations.

For an existing programmatic capture path, use `MTLCaptureManager` with an `MTLCaptureDescriptor` identifying the device or queue. Enable capture with the app's diagnostic `MetalCaptureEnabled` setting, or `MTL_CAPTURE_ENABLED=1` for a supported macOS 14+ run. Select a supported destination, start before the commands of interest, and stop on every exit path. Follow the selected SDK's capture API and include the producing passes as well as the broken consumer. Add temporary diagnostics within the authorized project work; avoid introducing a separate custom capture server or trace parser.

## Sources

- [POSIX: Shell command language, trap](https://pubs.opengroup.org/onlinepubs/9799919799/utilities/V3_chap02.html#trap) — explicit signal handling and EXIT cleanup.
- [Apple: Building a shader library by precompiling source files](https://developer.apple.com/documentation/metal/building-a-shader-library-by-precompiling-source-files) — compiler and library stages; SDK selection.
- [Apple: MSL specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf), compiler-options section — language targets and math modes. Filter newer content to the project's pre-4 standard.
- [Apple: Validating Metal API usage](https://developer.apple.com/documentation/xcode/validating-your-apps-metal-api-usage) and [Shader Validation](https://developer.apple.com/documentation/xcode/validating-your-apps-metal-shader-usage) — diagnostics and environment settings.
- [Apple: Debug GPU-side errors in Metal, WWDC20](https://developer.apple.com/videos/play/wwdc2020/10616/) — command-buffer encoder status and generated-source diagnostics.
- [Apple: Capturing a Metal workload in Xcode](https://developer.apple.com/documentation/xcode/capturing-a-metal-workload-in-xcode) and [programmatically](https://developer.apple.com/documentation/xcode/capturing-a-metal-workload-programmatically) — target-scoped capture and its enablement.

Sources reviewed 2026-10-14.
