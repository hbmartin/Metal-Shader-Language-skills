# Surface tracing

March within the camera's ray interval and budget actual field evaluations. A hit means the field satisfies the chosen convergence criterion; reaching the maximum iteration count is a separate result. Choose epsilon relative to scene scale and projected pixel footprint, rather than assuming one tolerance works for every camera distance. Small epsilon can cause stagnation when a large `float` ray distance can no longer represent that increment.

For an exact signed distance, stepping by its absolute value also handles an inside origin approaching an exit. Do not silently apply this to arbitrary fields with unknown bounds. If the effect should exclude inside-camera surfaces or select entry faces only, make that an explicit camera/material choice.

## Complete sphere tracer and fragment

This unit intentionally traces an exact sphere to make the contract testable against an analytic intersection. Results use physical distance along the internally normalized direction. Parameters must be finite, with `radius > 0`, `0 <= nearDistance <= farDistance`, and `epsilon > 0`. A zero evaluation budget returns exhaustion. A finite step that cannot advance returns `RMTraceStalled`; neither stagnation nor exhaustion establishes a hit. Checks for invalid inputs/arithmetic require compiler math settings that preserve nonfinite behavior.

The fragment binds a 16-byte `RMSphereViewParams` at buffer 0 and needs only a vertex-produced `[[position]]`. Its camera is at `(0, 0, 3)`, looks toward negative Z with focal scale 1.5, and uses positive Y as up. The ray flips Metal's downward-increasing pixel Y; texture-coordinate orientation remains a separate host/asset contract. With resolution `(1920, 1080)`, radius `1`, epsilon `1e-4`, and a 512-evaluation budget, the reference setup renders an opaque lit sphere without diagnostic pixels on the verified Apple M2 Pro. This is a demonstration setting, not a universal tolerance or budget. Blue exposes precision stagnation, amber budget exhaustion, and magenta invalid input/arithmetic; tighter tolerances can still show diagnostics.

```metal
#include <metal_stdlib>
using namespace metal;

enum RMTraceStatus : uint {
    RMTraceMiss = 0,
    RMTraceHit = 1,
    RMTraceExhausted = 2,
    RMTraceInvalid = 3,
    RMTraceStalled = 4
};

struct RMTraceResult {
    float distance;
    uint status;
    uint evaluations;
};

float rm_sphere_field(float3 p, float3 center, float radius) {
    return length(p - center) - radius;
}

RMTraceResult rm_trace_sphere(float3 origin, float3 direction,
                              float3 center, float radius,
                              float nearDistance, float farDistance,
                              float epsilon, uint maxEvaluations) {
    float rayLength = length(direction);
    if (!all(isfinite(origin)) || !all(isfinite(direction)) ||
        !all(isfinite(center)) || !isfinite(rayLength) || rayLength <= 0.0f ||
        !isfinite(radius) || radius <= 0.0f ||
        !isfinite(nearDistance) || !isfinite(farDistance) ||
        nearDistance < 0.0f || farDistance < nearDistance ||
        !isfinite(epsilon) || epsilon <= 0.0f) {
        return {0.0f, RMTraceInvalid, 0};
    }
    direction /= rayLength;
    float t = nearDistance;
    for (uint i = 0; i < maxEvaluations; ++i) {
        if (t > farDistance) return {t, RMTraceMiss, i};
        float d = rm_sphere_field(origin + direction * t, center, radius);
        if (!isfinite(d)) return {t, RMTraceInvalid, i + 1};
        if (abs(d) <= epsilon) return {t, RMTraceHit, i + 1};
        float next = t + abs(d);
        if (!isfinite(next)) return {t, RMTraceInvalid, i + 1};
        if (next <= t) return {t, RMTraceStalled, i + 1};
        t = next;
    }
    return {t, t > farDistance ? RMTraceMiss : RMTraceExhausted,
            maxEvaluations};
}

float3 rm_sphere_normal(float3 p, float3 center) {
    float3 radial = p - center;
    float radialLength = length(radial);
    return isfinite(radialLength) && radialLength > 0.0f
        ? radial / radialLength : float3(0, 0, 1);
}

struct RMSphereViewParams {
    float2 resolution;
    float radius;
    float epsilon;
};

fragment half4 rm_sphere_fragment(
    float4 pixelPosition [[position]],
    constant RMSphereViewParams& params [[buffer(0)]]
) {
    float2 uv = (2.0f * pixelPosition.xy - params.resolution) /
                max(params.resolution.y, 1.0f);
    uv.y = -uv.y;
    float3 origin = float3(0, 0, 3);
    float3 direction = normalize(float3(uv, -1.5f));
    float3 center = float3(0);
    RMTraceResult result = rm_trace_sphere(origin, direction, center,
        params.radius, 0.0f, 20.0f, params.epsilon, 512);
    if (result.status == RMTraceInvalid) return half4(1, 0, 1, 1);
    if (result.status == RMTraceExhausted) return half4(1, 0.5h, 0, 1);
    if (result.status == RMTraceStalled) return half4(0, 0.4h, 1, 1);
    if (result.status == RMTraceMiss) return half4(0.02h, 0.03h, 0.05h, 1);
    float3 normal = rm_sphere_normal(origin + direction * result.distance,
                                     center);
    float light = 0.1f + 0.9f * max(dot(normal, normalize(float3(1, 1, 2))), 0.0f);
    return half4(half3(0.3h, 0.6h, 0.9h) * half(light), 1);
}
```

When adapting the algorithm to a scene, use the same final scene field in the primary tracer, normal probes, and shadow rays. Return material identity with the selected field if composition changes the material; do not infer identity from an unrelated nearest primitive after marching. Handle degenerate normals explicitly when the field has corners or an ill-defined gradient.

Keep shadow bias in scene units and check it at contact edges. Soft-shadow/AO probes are approximations with extra field cost, not free consequences of an SDF. Use iteration-count and normal views to find convergence errors before increasing the budget. Bound the scene, skip empty intervals when justified, and profile before selecting lower resolution, reprojection, or a larger tolerance.

For composition with rasterized geometry, convert the sampled depth to the renderer's ray-distance convention before limiting the interval. A fragment's raster `[[position]]` is not the original vertex clip position; dividing its z by w is not a general linear-depth reconstruction. Preserve reversed-Z and projection conventions from the host renderer.

## Sources

- [Hart's sphere-tracing paper](https://graphics.stanford.edu/courses/cs348b-20-spring-content/uploads/hart.pdf): safe stepping with distance/derivative bounds and termination context.
- [Metal Shading Language specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf): stage-position semantics, types, and shader entry interfaces.

Sources reviewed 2026-10-13.
