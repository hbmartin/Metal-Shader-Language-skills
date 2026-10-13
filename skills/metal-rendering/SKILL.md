---
name: metal-rendering
description: "Connect native MSL shaders to classic Metal render passes, fullscreen effects, attachments, blending, and resource lifetimes. Use when a visual effect needs renderer integration or a render-pass correctness fix."
---

# Metal Rendering

Make the requested shader visible through the project's existing native Metal renderer. Adapt its current render loop and bindings before introducing a new framework or pass graph. Use classic `MTLCommandQueue`, `MTLCommandBuffer`, and encoders; this skill does not introduce SwiftUI integration or Metal 4 APIs.

## Inspect the actual pipeline

Locate shader entry points, library ownership, pipeline descriptors, drawable/offscreen targets, pass ordering, uniform layout, and texture/sampler bindings. Confirm target OS, SDK, and device capabilities where they affect the change. Distinguish a shader defect from mismatched bindings, formats, load/store actions, or stale CPU/GPU data.

## Read only the needed detail

- For a fullscreen effect, pass attachments, blending, or MSAA, read [Passes and fullscreen drawing](references/passes-fullscreen.md).
- For library compilation, per-frame ownership, CPU/GPU synchronization, or multipass hazards, read [Lifecycle and resources](references/lifecycle-resources.md).
- If the project already uses Satin, MiniMetal, or Raster, read [Optional framework integration](references/frameworks.md). None is a required dependency.

Keep the host/shader contract explicit: entry-point names, resource indices, shared layouts, texture dimensions, coordinate origin, linear/color-encoded output, and alpha convention. Add only inputs and passes required by the effect. Cache immutable pipeline state; update uniforms for animation instead of compiling source every frame.

## Verify rendering behavior

Compile shaders and construct the actual pipeline; compilation alone cannot verify attachment or stage compatibility. Render at the target resolution, then resize and exercise unavailable drawables and effect extremes. For multipass work, verify a known producer pattern reaches the consumer in the same intended frame. Run API validation when available and inspect command-buffer errors. A successful build or validation run does not prove resource races absent.

Report the visible result, host changes made for it, and the evidence actually obtained. Keep setup instructions proportional to the task; missing capture/profiling tools do not prevent source inspection or a shader-only fix.
