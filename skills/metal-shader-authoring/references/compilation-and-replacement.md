# Compilation and runtime replacement

## Build-time compilation

Use the project's existing shader build path first. For a standalone diagnostic, choose an installed SDK and the project's pre-4 language version explicitly. This example selects MSL 3.0 without setting a collection-wide minimum:

```sh
(
set -eu
metal_sdk="macosx"
metal_language="metal3.0"
metal_library="$PWD/Shaders.diagnostic.metallib"
if [ -e "$metal_library" ] || [ -L "$metal_library" ]; then
    printf 'Diagnostic output already exists: %s\n' "$metal_library" >&2
    exit 1
fi
metal_build_dir="$(mktemp -d)"
trap 'rm -rf "$metal_build_dir"' EXIT
xcrun --sdk "$metal_sdk" metal -std="$metal_language" \
    -c Shaders.metal -o "$metal_build_dir/Shaders.air"
xcrun --sdk "$metal_sdk" metallib \
    "$metal_build_dir/Shaders.air" -o "$metal_build_dir/Shaders.metallib"
if [ -e "$metal_library" ] || [ -L "$metal_library" ]; then
    printf 'Diagnostic output already exists: %s\n' "$metal_library" >&2
    exit 1
fi
if ! cp -n "$metal_build_dir/Shaders.metallib" "$metal_library"; then
    printf 'Could not publish diagnostic output: %s\n' "$metal_library" >&2
    exit 1
fi
)
```

The subshell removes scratch files on success or failure. It retains `Shaders.diagnostic.metallib` in the current directory after a successful link and copy. It rejects an existing output file, directory, or symlink before compilation and checks again before publication; `cp -n` also prevents replacing an output file created between the final check and copy. Choose a fresh diagnostic output path for another run. The recipe leaves an existing `Shaders.metallib` untouched.

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

- [makeLibrary(source:options:)](https://developer.apple.com/documentation/metal/mtldevice/makelibrary(source:options:)): runtime compilation and include limitation.
- [MTLCompileOptions](https://developer.apple.com/documentation/metal/mtlcompileoptions): compilation settings and language version.
- [Metal binary archives](https://developer.apple.com/documentation/metal/metal-binary-archives): pipeline compilation caches.
- [Building with embedded shader sources](https://developer.apple.com/documentation/xcode/building-your-project-with-embedded-shader-sources): shader inspection builds.

Sources reviewed 2026-10-13. Use the classic `MTLDevice`/pipeline path; newer Metal compiler/submission APIs are outside this collection.
