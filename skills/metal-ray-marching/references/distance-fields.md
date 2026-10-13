# Distance fields and transforms

Use negative-inside, positive-outside distances unless the project states another convention. An exact SDF returns geometric distance. A conservative distance bound can be smaller in magnitude and still support safe stepping; a generic implicit value does not carry either guarantee. Preserve that distinction after every composition and transform.

## Complete primitive helper unit

These helpers use positive radii/half-extents and scene-space units. For the rounded box, `halfExtent` is the outer half-extent, with `0 <= radius <= min(halfExtent)`. Translation queries `p - center`. Smooth union falls back to hard union when its blend width is nonpositive.

```metal
#include <metal_stdlib>
using namespace metal;

float rm_sd_sphere(float3 p, float radius) {
    return length(p) - radius;
}

float rm_sd_box(float3 p, float3 halfExtent) {
    float3 q = abs(p) - halfExtent;
    return length(max(q, 0.0f)) + min(max(q.x, max(q.y, q.z)), 0.0f);
}

float rm_sd_round_box(float3 p, float3 halfExtent, float radius) {
    float3 q = abs(p) - (halfExtent - radius);
    return length(max(q, 0.0f)) +
           min(max(q.x, max(q.y, q.z)), 0.0f) - radius;
}

float rm_union(float a, float b) { return min(a, b); }
float rm_intersection(float a, float b) { return max(a, b); }
float rm_subtract(float base, float cut) { return max(base, -cut); }

float rm_smooth_union(float a, float b, float width) {
    if (width <= 0.0f) return min(a, b);
    float h = saturate(0.5f + 0.5f * (b - a) / width);
    return mix(b, a, h) - width * h * (1.0f - h);
}

// Centered cell folding, correct on either side of zero.
// Positive spacing on every axis is required.
float3 rm_repeat_centered(float3 p, float3 spacing) {
    return p - spacing * floor(p / spacing + 0.5f);
}

// Coordinate deformation only: not an automatic distance correction.
float3 rm_twist_y(float3 p, float radiansPerUnit) {
    float angle = radiansPerUnit * p.y;
    float c = cos(angle);
    float s = sin(angle);
    return float3(c * p.x - s * p.z, p.y, s * p.x + c * p.z);
}

// Conservative world-space bound for a nonuniformly scaled sphere.
// Every scale component must be finite and nonzero.
float rm_scaled_sphere_bound(float3 p, float3 scale, float radius) {
    float minimumScale = min(abs(scale.x), min(abs(scale.y), abs(scale.z)));
    return rm_sd_sphere(p / scale, radius) * minimumScale;
}
```

## Keep the distance contract after transforms

- Query a rigid transform through its inverse; rotations/reflections preserve geometric distance. MSL matrices use columns, so verify a known basis-vector transform instead of guessing constructor ordering.
- Uniform positive scaling queries `p / scale` and multiplies the distance by `scale`. A nonuniform scale needs a conservative correction, such as the minimum absolute component for a diagonal transform, and is generally a bound rather than an exact distance.
- Hard Boolean combinations preserve the zero-set operation, but do not always preserve exact Euclidean distance. A smooth operator changes the geometry; do not substitute it while claiming the same silhouette.
- Cell folding is a coordinate map, not a universal distance guarantee. For centered symmetric primitives it is useful; asymmetric shapes or shapes spanning cell boundaries may require checking neighboring copies. Establish continuity and a conservative bound before marching the folded field.
- Twist, bend, noise displacement, and arbitrary domain warps can stretch space. Bound the transform's derivative over the rendered region and reduce the step accordingly, or use a suitable robust root-finding/marching method. An unexplained factor such as `distance * 0.5` does not prove safety for arbitrary deformation.

Normals are gradients of the final field, including its transforms. Check that a zero twist returns the original point and that a repeated field behaves consistently for matching positive and negative cells. The rounded box's interior term matters for signed distances and inside-origin rays.

## Sources

- [Hart, Sphere Tracing](https://graphics.stanford.edu/courses/cs348b-20-spring-content/uploads/hart.pdf): geometric distance, conservative derivative bounds, and transformed implicit surfaces.
- [Quilez's distance-functions reference](https://iquilezles.org/articles/distfunctions/): author reference for primitive/deformation families. The supplied helpers are concise formulas written for this skill, not a copied primitive catalog.
