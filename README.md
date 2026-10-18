# Metal and Metal Shading Language Skills

Seven independent Codex skills for creative native MSL work and the GPU engineering that supports it. They cover macOS, iOS/iPadOS, and tvOS using pre-Metal-4 language features and classic Metal APIs. Host guidance adapts to your existing project; SwiftUI and shader-language porting are outside this collection.

| Skill | Use it for |
| --- | --- |
| [metal-shader-authoring](skills/metal-shader-authoring/SKILL.md) | Stage interfaces, bindings, layout, precision, specialization, compilation, and runtime replacement |
| [metal-procedural-effects](skills/metal-procedural-effects/SKILL.md) | Noise, patterns, animation, antialiasing, and image effects |
| [metal-ray-marching](skills/metal-ray-marching/SKILL.md) | Distance fields, conservative marching, normals, and volumetrics |
| [metal-materials-lighting](skills/metal-materials-lighting/SKILL.md) | Materials, GGX lighting, normals, linear color, and HDR |
| [metal-rendering](skills/metal-rendering/SKILL.md) | Pipelines, passes, blending, resources, synchronization, and optional frameworks |
| [metal-compute](skills/metal-compute/SKILL.md) | Dispatch, barriers, race-free algorithms, simulations, and image processing |
| [metal-debugging](skills/metal-debugging/SKILL.md) | Validation, visual diagnosis, GPU capture, inspection, and profiling |

## Usage

Each folder is a complete skill with its own `SKILL.md`, UI metadata, and optional references. Install only the folders you need into your Codex skills directory, or reference a folder's `SKILL.md` directly in a request. Automatic discovery uses the skill descriptions; explicit invocation uses its name, such as `$metal-ray-marching`.

For example: “Use $metal-procedural-effects to make an animated, seamless noise material in this existing Metal renderer.” Include the relevant shader and its host bindings, deployment target, and output/color requirements when available.

The entrypoints route to deeper references as needed. No third-party framework, companion skill, custom MCP server, or application template is required. Optional framework notes apply only when that framework is relevant to the project. Reference examples declare their resource and algorithm assumptions; they are building blocks rather than drop-in renderer replacements.

## Sources and compatibility

Guidance is checked against Apple's MSL specification, classic Metal documentation, feature tables, and primary algorithm sources linked in the references. Each reference records a `Sources reviewed YYYY-MM-DD` date for the latest check of its cited guidance. This is the collection's research snapshot, not a source publication date or a guarantee of compatibility with every target. Check target-specific availability when using an advanced feature. Compilation on a recent SDK alone does not establish older-device compatibility.

Background notes remain research inputs and are not redistributed as skill references. The collection does not bundle downloaded applications, archives, copied manuals, or third-party tooling. Original examples use this repository's Apache-2.0 license; any future adapted third-party implementations must retain their applicable notices.

## Verify reference examples

Run the standard-library regression suite with Python 3.13 or newer, disabling bytecode output to keep the checkout clean:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

The suite extracts the documented examples, checks paired copies for consistency, and exercises temporary builds, guarded cleanup, read-only inspection, output publication, and cancellation from available bash, dash, and zsh callers. Compiler stubs make shell failures and signal timing reproducible; Xcode and SDKs are not required. Older Python versions fail discovery with a version requirement. Process creation requires POSIX `waitid(WNOWAIT)` and reports an explicit skip where it is unavailable; bookkeeping tests still run.

Process-group tests simulate INT, TERM, and HUP terminal cancellation, while separate diagnostic-process tests check termination by the original signal. Controlled QUIT tests target only the diagnostic PID after its handlers are installed and require numeric status 131. QUIT-dependent subcases explicitly skip when the runner inherits QUIT as ignored; other signals and bookkeeping checks still run. Terminal handoff probes verify that recorded QUIT is honored and later QUIT is ignored through exit.

A constrained process wrapper owns pipe reading and reaping; teardown stops its owned group before releasing the leader PID. Capture drains raw bytes and displays undecodable bytes as escapes. The fixture registers ownership before launching, so failed capture setup and a failed immediate rollback still leave a teardown callback available. After confirmed external reaping, the wrapper closes capture and disables automatic reaping by its private `Popen`; it never waits on or signals that released PID or invents an exit status. Secondary teardown exception chains are reported as notes without repeating the primary traceback or replacing its cause.

Each shell subcase owns its cleanup resources and removes its recorded allocations, including fallback allocations outside the fixture directory. Leak checks combine allocation records with an independent output-directory inventory.

Real group-wide QUIT probes are opt-in: run the same command with `METAL_TEST_GROUP_QUIT=1` to include them. These probes can generate OS crash reports from unhandled processes. The fixture disables core dumps and restores the prior resource limit afterward, but that limit does not suppress macOS crash reporting or every system crash-reporting service. OS-generated reports are outside fixture cleanup and are not removed by the suite.

When changing compiler flags, also perform a manual compile/link check with the available Metal toolchain; include `-MD` when validating dependency output and cleanup. Report unavailable tooling explicitly. All generated fixtures and diagnostic outputs stay in temporary directories outside the checkout and are never committed.
