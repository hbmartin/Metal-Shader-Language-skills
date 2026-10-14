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
(
set -eu
metal_sdk="macosx"
metal_language="metal3.1"
metal_keep_output=0
metal_build_dir="$(mktemp -d "${TMPDIR:-/tmp}/metal-diagnostic.XXXXXX")"
trap 'if [ "$metal_keep_output" -eq 0 ]; then rm -rf "$metal_build_dir"; fi' EXIT
metal_library="$(cd "$metal_build_dir" && pwd -P)/Shaders.diagnostic.metallib"
xcrun --sdk "$metal_sdk" metal -std="$metal_language" \
    -c Shaders.metal -o "$metal_build_dir/Shaders.air"
xcrun --sdk "$metal_sdk" metallib \
    "$metal_build_dir/Shaders.air" -o "$metal_library"
rm "$metal_build_dir/Shaders.air"
printf '%s\n' "$metal_library"
metal_keep_output=1
)
```

Each run creates a private, unique directory under `${TMPDIR:-/tmp}`; keep that temporary root outside project source/resource trees. Failed runs remove their directory. Successful runs remove the intermediate `.air`, print the library's absolute path, and retain only `Shaders.diagnostic.metallib` in the run directory for loading and inspection. Repeated or concurrent runs use separate directories and leave libraries in the current directory untouched. After inspection, remove the retained run directory with `rm -rf "/absolute/path/to/metal-diagnostic.XXXXXX"`, replacing the example path with the parent directory of the printed library path.

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

- [Apple: Building a shader library by precompiling source files](https://developer.apple.com/documentation/metal/building-a-shader-library-by-precompiling-source-files) — compiler and library stages; SDK selection.
- [Apple: MSL specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf), compiler-options section — language targets and math modes. Filter newer content to the project's pre-4 standard.
- [Apple: Validating Metal API usage](https://developer.apple.com/documentation/xcode/validating-your-apps-metal-api-usage) and [Shader Validation](https://developer.apple.com/documentation/xcode/validating-your-apps-metal-shader-usage) — diagnostics and environment settings.
- [Apple: Debug GPU-side errors in Metal, WWDC20](https://developer.apple.com/videos/play/wwdc2020/10616/) — command-buffer encoder status and generated-source diagnostics.
- [Apple: Capturing a Metal workload in Xcode](https://developer.apple.com/documentation/xcode/capturing-a-metal-workload-in-xcode) and [programmatically](https://developer.apple.com/documentation/xcode/capturing-a-metal-workload-programmatically) — target-scoped capture and its enablement.

Sources reviewed 2026-10-13.
