# Coordinates, animation, and antialiasing

Name the coordinate space and unit for each control: pixels, normalized UVs, object space, or world space. Screen patterns commonly use `(pixelPosition - 0.5 * resolution) / resolution.y` to preserve equal scale on both axes. Use render-target pixel dimensions, not host-view points. Texture UV orientation and camera conventions come from the existing renderer.

Use elapsed seconds relative to a nearby origin. Casting an epoch-sized timestamp to `float` loses frame-scale changes. A scroll `p + velocity * time` translates the same field; changing a noise dimension or gradient rotates/evolves it. Make an exact looping trajectory continuous, for example a circular phase with matching endpoints. Resetting time alone does not make the field continuous.

## Filter the quantity that defines the edge

For an implicit edge, soften coverage using the screen-space footprint of its distance value. For repeated stripes, low-pass the oscillation when its phase changes substantially across a pixel. Do not call fragment derivatives in nonuniform control flow and assume useful results; measure the footprint beforehand. `dfdx`, `dfdy`, and `fwidth` are fragment-stage tools; a compute kernel needs passed-in scale/Jacobian information.

This complete translation unit contains a distance-coverage helper and a runnable fragment example. The stripe filter integrates a locally linear phase over a square pixel; it is an approximation when the phase curves strongly within that pixel. The host binds the `PEPatternParams` struct at fragment buffer 0 with its MSL layout and a positive pixel resolution. The vertex stage only needs to provide `[[position]]`.

```metal
#include <metal_stdlib>
using namespace metal;

float pe_edge_coverage(float signedDistance, float distanceFootprint) {
    float width = max(0.5f * abs(distanceFootprint), 1.0e-5f);
    return 1.0f - smoothstep(-width, width, signedDistance);
}

float pe_sinc(float x) {
    return abs(x) < 1.0e-3f ? 1.0f - x * x / 6.0f : sin(x) / x;
}

float pe_filtered_stripe(float phase, float2 phaseGradient) {
    float attenuation = pe_sinc(0.5f * phaseGradient.x) *
                        pe_sinc(0.5f * phaseGradient.y);
    return 0.5f + 0.5f * sin(phase) * attenuation;
}

struct PEPatternParams {
    float2 resolution;
    float elapsedSeconds;
    float cyclesPerUnit;
};

fragment half4 pe_stripe_fragment(
    float4 pixelPosition [[position]],
    constant PEPatternParams& params [[buffer(0)]]
) {
    float2 p = (pixelPosition.xy - 0.5f * params.resolution) /
               max(params.resolution.y, 1.0f);
    float phase = 6.28318530718f *
                  (p.x * params.cyclesPerUnit - params.elapsedSeconds * 0.1f);
    float2 gradient = float2(dfdx(phase), dfdy(phase));
    float value = pe_filtered_stripe(phase, gradient);
    return half4(half3(value), 1.0h);
}
```

For thresholded noise or SDF masks, call `pe_edge_coverage(d, fwidth(d))` before converting to a bounded color. Avoid reversed `smoothstep` edges; invert an ordered result instead. A smaller half-precision epsilon can round to zero, so keep coverage/normalization safeguards in `float`.

Inspect a fixed-time frame while changing scale/resolution, then animate at that same scale. Look for moiré, crawling boundaries, and intensity changes as detail disappears. A prefiltered noise texture is another option, but initialize or generate its mip levels before sampling them.

## Sources

- [Metal Shading Language specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf): fragment derivatives, scalar/vector types, and sampling rules; use the revision matching the target compiler.
- [Gustavson and McEwan's noise paper](https://jcgt.org/published/0011/01/02/paper.pdf): analytic derivatives and rotating-gradient flow animation.
