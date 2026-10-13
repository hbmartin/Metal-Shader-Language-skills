# Visual and resource diagnosis

## Isolate the first wrong stage

Check the actual bound resource and shader entry point in a capture. Verify dimensions, formats, load/store actions, viewport, depth state, blend state, and the host/shader layout. Inspect intermediate outputs before diagnosing the final composite. A constant opaque color can separate missing drawing from broken material math; a known UV or checker pattern can separate coordinates from sampling.

Keep diagnostic changes local and temporary. To compare images, hold camera, input data, resolution, time, seed, and exposure constant. Also test a resize or aspect-ratio change if coordinates matter.

## Executable diagnostic helpers

These original functions can be compiled together or inserted into an existing fragment shader. They deliberately do not prescribe a vertex-output type or an app framework. Their shared legend is magenta for NaN, cyan for Inf, and yellow for a near-zero normal; NaN takes precedence when both nonfinite kinds occur. Cyan also exposes an infinite squared normal length. This value-diagnostic legend is separate from a tracer's result-status legend. `debug_uv` displays the supplied coordinate without wrapping it; inspect an unclipped floating-point output or the values in the shader debugger when values outside `[0,1]` matter.

```metal
#include <metal_stdlib>
using namespace metal;

float4 debug_finite_color(float4 color)
{
    if (any(isnan(color))) return float4(1.0f, 0.0f, 1.0f, 1.0f);
    if (any(isinf(color))) return float4(0.0f, 1.0f, 1.0f, 1.0f);
    return color;
}

float4 debug_uv(float2 uv)
{
    if (any(isnan(uv))) return float4(1.0f, 0.0f, 1.0f, 1.0f);
    if (any(isinf(uv))) return float4(0.0f, 1.0f, 1.0f, 1.0f);
    return float4(uv.x, uv.y, 0.0f, 1.0f);
}

float4 debug_normal(float3 normal)
{
    if (any(isnan(normal))) return float4(1.0f, 0.0f, 1.0f, 1.0f);
    if (any(isinf(normal))) return float4(0.0f, 1.0f, 1.0f, 1.0f);
    float lengthSquared = dot(normal, normal);
    if (isinf(lengthSquared)) return float4(0.0f, 1.0f, 1.0f, 1.0f);
    if (lengthSquared <= 1.0e-12f) return float4(1.0f, 1.0f, 0.0f, 1.0f);
    return float4(normal * rsqrt(lengthSquared) * 0.5f + 0.5f, 1.0f);
}
```

Finite-value tests need compiler math settings that preserve NaN/Inf behavior; fast-math assumptions can remove or invalidate the intended diagnostic. For normals, display their raw length separately if normalization might hide the bug. Extremely large components can overflow the squared length; inspect those values at the source.

## Common interpretation traps

| Symptom | Check |
|---|---|
| Effect stretched after resize | Pixel versus normalized coordinates, aspect correction, drawable size versus view size |
| Black or clamped procedural output | Finite math, actual pixel format/range, alpha, blend factors, color-space conversion |
| Seams or blur near edges | Addressing policy, filter footprint, selected mip, texture dimensions, UV convention |
| Incorrect normal lighting | Normal space, transform, length, tangent handedness, degenerate input |
| Flicker or one-frame-old data | Initialization, producer/consumer ordering, aliased storage, resource reuse while in flight |
| Only certain counts fail | Capacities, strides, bounds, incomplete groups, reduction identity and barriers |

A fragment's `[[position]]` is raster-space data. Dividing its `z` by `w` is not a general linear-depth reconstruction. Distinguish depth-buffer values from clip/view/world coordinates; reconstruct using the actual projection and depth convention, including reverse-Z when present.

For mip diagnostics, scale UV derivatives by both bound texture dimensions before estimating a footprint. Compute derivatives before divergent flow; guard a zero footprint before `log2`. Such estimates are diagnostic approximations, not the sampler's authoritative chosen mip.

Counting one compute invocation per pixel measures the dispatch grid, not raster overdraw. Raster overdraw involves multiple fragments for the same pixel; ordinary texture read-modify-write increments race under overlap. Use supported capture counters or a supported atomic accumulation with a clearly defined measurement instead.

Function constants specialize shader functions; changing them requires a newly specialized function/pipeline. Use a uniform parameter for a diagnostic switch that must change without rebuilding pipeline variants.

## Sources

- [Apple: Inspecting the bound resources for a command](https://developer.apple.com/documentation/xcode/inspecting-the-bound-resources-for-a-command) — verify the input that a captured command actually receives.
- [Apple: Inspecting shaders](https://developer.apple.com/documentation/xcode/inspecting-shaders) — source inspection and captured-work shader iteration.
- [Apple: MSL specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf) — raster coordinates, derivatives, function constants, and numerical/math-mode behavior; select the applicable pre-4 features.

Sources reviewed 2026-10-13.
