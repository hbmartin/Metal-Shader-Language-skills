---
name: metal-procedural-effects
description: "Create and refine native Metal Shading Language procedural textures, animated noise, patterns, and postprocessing effects. Use for fBm, domain warping, analytic antialiasing, blur, bloom, or color treatments in Metal shaders."
---

# Metal Procedural Effects

Create the requested visual treatment while keeping its coordinate, color, and cost assumptions explicit. Work within the existing Apple-platform Metal pipeline; use only the host code needed to bind parameters or resources. These instructions concern native MSL, not SwiftUI shader modifiers, shader-language porting, or Metal 4 APIs.

## Shape the effect

- Establish the visual target, input image or geometry, coordinate units, animation controls, transparency, and frame budget from the request and project. Preserve its art direction; physically plausible output is optional unless requested.
- Distinguish a generated field from an image treatment. A fragment shader can generate a pattern without a texture; a neighborhood filter needs an input texture and a separate output resource.
- Keep positions, noise coordinates, time, and derivatives in `float`. Consider `half` for bounded colors after checking range and visible precision; do not reduce a hash or high-frequency coordinate calculation blindly.
- Use local elapsed time for animation and define whether motion translates a pattern or evolves it. A loop or seamless tile requires an explicit construction, not merely wrapping arbitrary time or coordinates.
- Filter detail smaller than the pixel footprint. Compute fragment derivatives in coherent control flow; compute kernels need an explicit footprint or a prefiltered texture.

## Read only the relevant reference

- [Noise and fractals](references/noise-and-fractals.md): choose value/gradient/cellular noise, promise periodicity precisely, compose fBm and domain warps, and budget octaves.
- [Coordinates, animation, and antialiasing](references/coordinates-and-antialiasing.md): resolution-independent patterns, stable motion, derivatives, and analytic edge/stripe coverage.
- [Image treatments](references/image-treatments.md): separable filtering, bloom ordering, HDR/color-space boundaries, and alpha-safe treatments.

## Verify the visual contract

Compile the complete MSL unit with the project's target language version and inspect fixed-time frames at more than one resolution or zoom. Check negative coordinates, transparent pixels, black/grayscale inputs, maximum sampling offsets, and finite values at parameter endpoints. For promised periodicity, compare the field and its continuity across the actual period. Report measured cost on the target GPU when performance is part of the request; texture lookup, branching, and computed noise have workload-dependent tradeoffs.
