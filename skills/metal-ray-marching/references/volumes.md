# Volume integration

Intersect a bounded density region before integrating it. Use the visible interval after camera near/far and opaque-scene clipping, with a normalized ray and consistent physical or artistic scene units. Empty-space skipping needs an occupancy bound; evaluating one empty sample does not prove that the next large interval is empty.

For each segment of length `ds`, evaluate extinction `sigma_t` and its radiance source. Beer–Lambert transmittance is `exp(-sigma_t * ds)`. With a locally constant source function `S`, accumulate `C += T * (1 - segmentTransmittance) * S`, then update `T *= segmentTransmittance`. Here `S` is a radiance source function, not raw emission per unit distance; raw emission/scattering coefficients require the corresponding normalization/integration. A vacuum with emission needs its own zero-extinction limit.

## Complete bounded and homogeneous helpers

The interval helper assumes a unit direction, finite values, and positive radius. The integration example returns premultiplied RGB and opacity for a homogeneous segment. It requires nonnegative finite extinction/path length and a positive step count; zero steps returns an empty contribution and must not be reported as a completed integration. Keeping the ray length fixed while varying `steps` should agree with the analytic result up to floating-point error.

```metal
#include <metal_stdlib>
using namespace metal;

bool rm_sphere_interval(float3 origin, float3 unitDirection,
                        float3 center, float radius,
                        thread float2& interval) {
    float3 offset = origin - center;
    float b = dot(offset, unitDirection);
    float c = dot(offset, offset) - radius * radius;
    float discriminant = b * b - c;
    if (discriminant < 0.0f) return false;
    float root = sqrt(max(discriminant, 0.0f));
    interval = float2(max(-b - root, 0.0f), -b + root);
    return interval.y >= interval.x;
}

float rm_segment_opacity(float opticalDepth) {
    float tau = max(opticalDepth, 0.0f);
    // Avoid cancellation in 1 - exp(-tau) for very small segments.
    return tau < 1.0e-3f
        ? tau * (1.0f - 0.5f * tau + tau * tau / 6.0f)
        : 1.0f - exp(-tau);
}

void rm_accumulate_segment(float3 sourceRadiance, float extinction,
                           float segmentLength,
                           thread float3& radiance,
                           thread float& opacity) {
    float alpha = rm_segment_opacity(max(extinction, 0.0f) *
                                     max(segmentLength, 0.0f));
    float transmittance = 1.0f - opacity;
    radiance += transmittance * alpha * sourceRadiance;
    opacity += transmittance * alpha;
}

float4 rm_integrate_constant_volume(float3 sourceRadiance, float extinction,
                                    float pathLength, uint steps) {
    float3 radiance = float3(0);
    float opacity = 0.0f;
    if (steps == 0) return float4(0);
    float ds = max(pathLength, 0.0f) / float(steps);
    for (uint i = 0; i < steps; ++i) {
        rm_accumulate_segment(sourceRadiance, extinction, ds,
                               radiance, opacity);
    }
    return float4(radiance, opacity);
}
```

The example accumulates opacity directly. Repeatedly multiplying a near-one transmittance and then returning `1 - T` can lose the entire opacity of a thin volume as the number of segments grows. Direct opacity accumulation preserves the small contribution; use `T = 1 - opacity` for ordinary compositing. Very small surviving transmittance in an optically thick HDR volume may need a separate transmittance or log-transmittance representation for the required error budget.

## Heterogeneous fields and quality

Sample density within each segment and convert it to extinction in the chosen units. Clip the last segment to the interval end; changing the step length requires changing the optical-depth factor too. Use enough samples for spatial density variation, including noise frequency and light visibility. Record exhaustion separately if a sample budget leaves the interval unfinished.

Jitter a sample's location within its segment without changing that segment's total optical depth convention. Temporal reuse needs reprojection and history rejection; it can ghost when cameras, density, or lights change. Reduced resolution saves work but needs an appropriate reconstruction at opaque boundaries.

Early termination at small remaining `T` is an error/cost choice. In HDR, even a small remaining transmittance can matter when the remaining source/background is bright; use the requested radiance error or a useful source bound rather than claiming a universal invisible threshold. For premultiplied compositing, a volume result combines as `C + T * background` in the working linear space.

Lighting may require a secondary density integral toward the light. Budget it separately. If a physically based phase function is requested, use its actual normalization and direction convention; an artistic cosine/power lobe is not automatically a Henyey–Greenstein phase function. Purely artistic fog can choose a simpler lobe explicitly.

## Sources

- [Physically Based Rendering, transmittance](https://pbr-book.org/4ed/Volume_Scattering/Transmittance): author textbook on Beer’s law, optical thickness, and multiplicative segment transmittance.
- [Gustavson and McEwan's noise paper](https://jcgt.org/published/0011/01/02/paper.pdf): animated/periodic density building blocks and derivatives; it does not prescribe a universal march step count.

Sources reviewed 2026-10-13.
