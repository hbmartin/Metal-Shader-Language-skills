# Precision and specialization

## Choose precision from error and range

Use `float` when positions, accumulated results, small differences, divisions, derivatives, or long-running time exceed an acceptable half-precision error budget. Use `half` for colors and local calculations when range and measured output quality allow it. Smaller types can reduce memory/register demand; neither speedup nor free conversion is guaranteed.

Half's smallest positive normal is about 6.1e-5. Subnormal preservation varies with execution/compile behavior; `1e-10h` is zero and cannot protect a denominator. Choose a numerically meaningful float bound, fix the singularity, or use a representable half bound appropriate to the model. A tiny epsilon is not a substitute for defining zero-length vectors, zero roughness, or coincident points.

For animation, keep time in sufficient precision or derive a bounded phase on the host only when the animation is actually periodic. Arbitrary wrapping makes nonperiodic effects jump.

`fast::` math and compiler math options trade guarantees for throughput. Compare images and finite outputs across the required parameter range before changing those options. Do not solve correctness failures by loosening math guarantees.

## Branches and derivatives

Uniform branches can avoid work. A divergent branch can cost more, while replacing it with `mix` or `select` may evaluate both expensive alternatives. Choose based on the generated work and measurements, not a rule that all branching is bad.

`dfdx`, `dfdy`, and `fwidth` apply to fragment functions; their results are undefined in nonuniform control flow. Compute the footprint before a pixel-dependent branch, or use an explicit footprint for compute-generated images. Evaluate expensive noise only at frequencies the output can represent.

## Function constants

Use function constants for a small number of structural alternatives, such as presence of a normal map or a bounded octave count. Use uniforms for rapidly changing values such as time and tint. Specialization creates a new function/pipeline variant; it does not mutate an existing pipeline without compilation work.

This complete unit requires the host to set Boolean constant index 0 before creating its compute pipeline:

```metal
#include <metal_stdlib>
using namespace metal;
constant bool apply_tint [[function_constant(0)]];

kernel void specialized_tint(device float4* samples [[buffer(0)]],
                             constant float4& tint [[buffer(1)]],
                             constant uint& count [[buffer(2)]],
                             uint i [[thread_position_in_grid]]) {
    if (i >= count) return;
    if (apply_tint) samples[i] *= tint;
}
```

Cache variants by all settings that affect compiled behavior and pipeline compatibility. Bound variant count; an unbounded combination of material options can create a compilation/cache problem larger than the branch it replaces.

## Availability

Determine the deployment OS, selected `MTLLanguageVersion`, and GPU capabilities separately. Compiling against a newer SDK is not proof of support on an older device. Use feature-specific properties or `supportsFamily` where appropriate and consult the dated feature tables. Prefer portable constructs for basic effects; label requirements for optional SIMD, tile, mesh, or ray-tracing features rather than prescribing a GPU family from memory.

This collection uses pre-4 language features and classic Metal APIs. Existing older language targets should remain valid unless the requested technique requires a deliberate compatibility change.

## Sources

- [Apple MSL specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf): numeric types, function constants, math namespaces, derivatives, and version annotations.
- [Learn performance best practices for Metal shaders](https://developer.apple.com/videos/play/tech-talks/111373/): precision and specialization tradeoffs.
- [Detecting GPU features and Metal software versions](https://developer.apple.com/documentation/metal/detecting-gpu-features-and-metal-software-versions) and [feature tables PDF](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf): capability checks.

Sources reviewed 2026-10-13; feature-table PDF dated 2026-05-21.
