# Normals and surface detail

Keep positions, normals, tangents, view directions, and light directions in one agreed space. Transform normals with the inverse transpose of the model's linear transform under nonuniform scaling, then normalize after interpolation. Compute the normal matrix on the host when already available. A singular transform needs an explicit fallback, not an undefined inverse.

## Tangent-space detail

Normal maps store direction data, so sample them through a linear texture format. Decode `[0,1]` to `[-1,1]`; match the asset's tangent basis and green-channel convention. Reorthogonalize the interpolated tangent against the normal. Preserve the tangent sign across mirrored UVs and orientation-reversing transforms; choose how back faces orient their basis for a two-sided material.

This original helper accepts a tangent and normal already transformed to the shading space. `handedness` is `+1` or `-1` from the mesh's tangent convention, adjusted for a reflected object transform when needed. Inputs are finite. The fallback axis is for degenerate tangents; correct seams still require the asset's intended tangent basis.

```metal
#include <metal_stdlib>
using namespace metal;

float3 normalUnitOr(float3 value, float3 fallback) {
    float length2 = dot(value, value);
    return isfinite(length2) && length2 > 1e-12f
        ? value * rsqrt(length2) : fallback;
}

float3 tangentNormal(float3 encodedNormal, float3 normal,
                     float3 tangent, float handedness) {
    float3 N = normalUnitOr(normal, float3(0.0f, 0.0f, 1.0f));
    float3 axis = abs(N.z) < 0.999f
        ? float3(0.0f, 0.0f, 1.0f) : float3(0.0f, 1.0f, 0.0f);
    float3 fallbackT = normalUnitOr(cross(axis, N), float3(1.0f, 0.0f, 0.0f));
    float3 T = normalUnitOr(tangent - N * dot(N, tangent), fallbackT);
    float sign = handedness < 0.0f ? -1.0f : 1.0f;
    float3 B = sign * cross(N, T);
    float3 mapped = encodedNormal * 2.0f - 1.0f;
    return normalUnitOr(T * mapped.x + B * mapped.y + N * mapped.z, N);
}
```

`(0.5, 0.5, 1)` must reproduce the surface normal, and a degenerate map `(0.5, 0.5, 0.5)` takes the fallback. Test a rotated/nonuniformly scaled object and mirrored UV islands before tuning light intensity around apparent errors.

For procedural bump detail, perturb a normalized normal from a height gradient in a known surface basis. Choose derivative spacing from the effect's scale and target resolution; shrinking it indefinitely loses precision. Adding unrelated XYZ noise directly to a normal changes its direction unpredictably and does not represent a height-field gradient. For screen derivatives, keep evaluation valid across the fragment quad and avoid divergent derivative-dependent code.

Use the [MSL specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf) for matrix/vector and derivative rules. For an asset workflow that uses MikkTSpace, use its [reference tangent-space implementation](https://github.com/mmikk/MikkTSpace) to match baking and rendering rather than substituting a different tangent generator.
