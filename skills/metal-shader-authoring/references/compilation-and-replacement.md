# Compilation and runtime replacement

## Build-time compilation

Use the project's existing shader build path first. For a standalone diagnostic, choose an installed SDK and the project's pre-4 language version explicitly. This example selects MSL 3.0 without setting a collection-wide minimum:

```sh
(
set -eu
metal_sdk="macosx"
metal_language="metal3.0"
metal_keep_output=0
metal_build_dir="$(mktemp -d "${TMPDIR:-/tmp}/metal-diagnostic.XXXXXX")"
trap 'if [ "$metal_keep_output" -eq 0 ]; then rm -rf -- "$metal_build_dir"; fi' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
metal_run_dir="$(CDPATH= cd -P -- "$metal_build_dir" >/dev/null && pwd -P)"
metal_library="$metal_run_dir/Shaders.diagnostic.metallib"
xcrun --sdk "$metal_sdk" metal -std="$metal_language" \
    -c Shaders.metal -o "$metal_build_dir/Shaders.air"
xcrun --sdk "$metal_sdk" metallib \
    "$metal_build_dir/Shaders.air" -o "$metal_library"
rm "$metal_build_dir/Shaders.air"
printf '%s\n' "$metal_library"
printf 'Retained run directory: %s\n' "$metal_run_dir" >&2
metal_keep_output=1
)
```

Each run creates a private, unique directory under `${TMPDIR:-/tmp}`; keep that temporary root outside project source/resource trees. Command failures and handled INT, TERM, or HUP interruptions remove the run directory. Successful runs remove the intermediate `.air`, print one absolute library path on stdout and the labeled absolute run-directory path on stderr, and retain only `Shaders.diagnostic.metallib` for loading and inspection. Repeated or concurrent runs use separate directories and leave libraries in the current directory untouched.

After inspection, copy the printed run-directory path into `metal_run_dir` below. The guard requires an absolute path whose final component is `metal-diagnostic.` followed by six characters, an existing directory, and no symlink at that path. It refuses an empty, parent, or unrelated target.

```sh
(
set -eu
metal_run_dir="/absolute/path/to/metal-diagnostic.XXXXXX"
metal_cleanup_ok=0
case "$metal_run_dir" in
    /*)
        case "${metal_run_dir##*/}" in
            metal-diagnostic.??????) metal_cleanup_ok=1 ;;
        esac
        ;;
esac
if [ "$metal_cleanup_ok" -ne 1 ] || [ ! -d "$metal_run_dir" ] || [ -L "$metal_run_dir" ]; then
    printf 'Refusing cleanup of run directory: %s\n' "$metal_run_dir" >&2
    exit 1
fi
rm -rf -- "$metal_run_dir"
)
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
