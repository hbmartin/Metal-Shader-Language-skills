# Compilation and runtime replacement

## Build-time compilation

Use the project's existing shader build path first. For a standalone diagnostic, choose an installed SDK and the project's pre-4 language version explicitly. This example selects MSL 3.0 without setting a collection-wide minimum:

```sh
sh <<'METAL_DIAGNOSTIC'
set -eu
metal_sdk="macosx"
metal_language="metal3.0"

metal_temp_root="${TMPDIR:-/tmp}"
case "$metal_temp_root" in
    /*) ;;
    *) printf 'Temporary root must be absolute: %s\n' "$metal_temp_root" >&2; exit 1 ;;
esac
metal_temp_root="$(CDPATH= cd -P -- "$metal_temp_root" && pwd -P)"
metal_project_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd -P)"
metal_project_root="$(CDPATH= cd -P -- "$metal_project_root" && pwd -P)"
case "$metal_temp_root/" in
    "${metal_project_root%/}/"*)
        printf 'Temporary root must be outside the project: %s\n' "$metal_temp_root" >&2
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
            Shaders.air|Shaders.diagnostic.metallib|.metal-diagnostic-run)
                [ -f "$metal_entry" ] && [ ! -L "$metal_entry" ] || return 1
                ;;
            *) return 1 ;;
        esac
    done
    rm -f -- "$metal_build_dir/Shaders.air" "$metal_build_dir/Shaders.diagnostic.metallib" \
        "$metal_build_dir/.metal-diagnostic-run" || return 1
    rmdir -- "$metal_build_dir"
}
metal_on_exit() {
    metal_status=$?
    metal_abort_if_signalled
    trap - EXIT
    metal_cleanup || {
        printf 'Refusing or unable to clean run directory: %s\n' "$metal_build_dir" >&2 || :
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
        printf 'Refusing or unable to clean run directory: %s\n' "$metal_build_dir" >&2 || :
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
metal_run_dir="$(CDPATH= cd -P -- "$metal_build_dir" && pwd -P)"
metal_abort_if_signalled
metal_library="$metal_run_dir/Shaders.diagnostic.metallib"
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
printf 'Retained run directory: %s\n' "$metal_run_dir" >&2 || :
METAL_DIAGNOSTIC
```

Each run launches a separate `sh` process and creates a private, unique directory under the physical path of `${TMPDIR:-/tmp}`. Relative temporary roots and roots inside the project are refused; Git identifies the project root when available, otherwise the working directory is used. Keep diagnostic outputs temporary and outside source/resource trees; never commit them. The marker `.metal-diagnostic-run` identifies this recipe's directories. Signal traps record INT, TERM, and HUP requests; cleanup and re-raising happen at command boundaries after the recording trap returns. The allocating child ignores those signals until it returns its directory path, so pending cancellation can remove the allocated directory. The diagnostic process then terminates by the original signal so a surrounding bash loop stops.

Before retention, command failures and handled interruptions remove only known outputs and the empty run directory. Unexpected entries or symlinks cause cleanup to refuse the directory. Successful runs remove `Shaders.air`, commit retention, then print one absolute library path on stdout and the labeled absolute run-directory path on stderr. The stderr annotation is best-effort. After retention, output errors or signals leave `Shaders.diagnostic.metallib` and the marker available for loading and inspection, including when a path has already been printed. Repeated or concurrent runs use separate directories and leave libraries in the current directory untouched.

After inspection, copy the printed run-directory path into `metal_run_dir` below. Cleanup accepts trailing slashes and succeeds when a valid target is already absent. Existing targets must be nonsymlink directories with this recipe's exact marker and only regular, nonsymlink known outputs; all entries are checked before anything is deleted. A matching folder name alone does not establish ownership. Cleanup removes only the known files and uses `rmdir` to remove the empty directory; it never recursively deletes other contents.

```sh
sh <<'METAL_CLEANUP'
set -eu
metal_run_dir="/absolute/path/to/metal-diagnostic.XXXXXX"
metal_refuse_cleanup() {
    printf 'Refusing cleanup of run directory: %s\n' "$metal_run_dir" >&2
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
        Shaders.air|Shaders.diagnostic.metallib|.metal-diagnostic-run)
            [ -f "$metal_entry" ] && [ ! -L "$metal_entry" ] || metal_refuse_cleanup
            ;;
        *) metal_refuse_cleanup ;;
    esac
done
rm -f -- "$metal_run_dir/Shaders.air" "$metal_run_dir/Shaders.diagnostic.metallib" \
    "$metal_marker"
rmdir -- "$metal_run_dir"
METAL_CLEANUP
```

`metal -c` checks source compilation; `metallib` links the compiled source into a library. Neither creates or executes the app's render/compute pipeline. Load or inspect the retained diagnostic library before removing it.

For device compilation use `iphoneos` or `appletvos` with an appropriate language version/deployment target. These checks compile for those platforms; they do not execute on a device. Check `xcrun ... metal -help` for flags supported by the installed toolchain. Add embedded sources/debug information when shader inspection is needed; avoid blanket warnings-as-errors or changing global Xcode selection to make a single recipe work.

A compiled library is not a valid pipeline by itself. Resolve the actual entry-point names, specialize any function constants, and create the render/compute pipeline. Render creation must agree with attachments, sample count, vertex descriptor, and the vertex/fragment interface. Read compiler and pipeline diagnostics separately.

## Source-string compilation

Classic `MTLDevice.makeLibrary(source:options:)` compiles MSL text, not host application code. It provides no ordinary filesystem include search path. Assemble required helper declarations into the source explicitly, use the standard Metal library, or use a separately supported linking mechanism already designed into the project. Build-time header inclusion does not establish equivalent runtime behavior.

Set the intended `MTLCompileOptions.languageVersion` and preserve relevant math options. Synchronous compilation blocks its caller; use a suitable asynchronous API or worker execution for interactive editing. Pipeline creation is another potentially expensive stage. Source edits cannot allocate textures, change pass scheduling, or bind a newly declared argument automatically.

## Transactional replacement for an editor

The following is a recommended application design, not an API guarantee:

1. Keep a stable shader contract: entry points, argument types/indices, output formats, and required resources. If the editor changes that contract, validate and construct the matching host changes before activation.
2. Compile the candidate library and create all required pipeline variants off the draw path. Keep diagnostics associated with the source revision that produced them.
3. Activate a complete candidate at a frame boundary only if it is still the newest requested revision. A slow old compile must not overwrite a newer successful edit.
4. On library or pipeline failure, retain the last successful pipeline and display the relevant diagnostic. Keep resources/pipelines used by submitted work alive until completion.

Cache by source/helper content, entry points, language/math options, function constants, device context, and relevant pipeline configuration. Device-specific pipeline objects are not portable across devices. Binary archives can reduce suitable pipeline compilation costs, but do not bypass source/interface validity or all compilation work.

For arbitrary user-edited shader execution, use an application-appropriate bounded work/resource policy. A successful compile does not prove safe indexing, finite results, convergence, or acceptable GPU cost. Keep any checks proportional to the editor's actual trust model; ordinary project authoring does not need a new sandbox architecture.

## Sources

- [POSIX: Shell command language, trap](https://pubs.opengroup.org/onlinepubs/9799919799/utilities/V3_chap02.html#trap) — explicit signal handling and EXIT cleanup.
- [makeLibrary(source:options:)](https://developer.apple.com/documentation/metal/mtldevice/makelibrary(source:options:)): runtime compilation and include limitation.
- [MTLCompileOptions](https://developer.apple.com/documentation/metal/mtlcompileoptions): compilation settings and language version.
- [Metal binary archives](https://developer.apple.com/documentation/metal/metal-binary-archives): pipeline compilation caches.
- [Building with embedded shader sources](https://developer.apple.com/documentation/xcode/building-your-project-with-embedded-shader-sources): shader inspection builds.

Sources reviewed 2026-10-13. Use the classic `MTLDevice`/pipeline path; newer Metal compiler/submission APIs are outside this collection.
