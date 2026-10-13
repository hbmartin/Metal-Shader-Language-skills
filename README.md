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

Guidance is checked against Apple's MSL specification, classic Metal documentation, feature tables, and primary algorithm sources linked in the references. Source review dates identify the research snapshot; check target-specific availability when using an advanced feature. Compilation on a recent SDK alone does not establish older-device compatibility.

Background notes remain research inputs and are not redistributed as skill references. The collection does not bundle downloaded applications, archives, copied manuals, or third-party tooling. Original examples use this repository's Apache-2.0 license; any future adapted third-party implementations must retain their applicable notices.
