# Direct lighting

Use one stated convention: `N` is the surface normal, and `V` and `L` point from the surface toward the viewer and light, all in the same space. Incident radiance is linear and already includes distance attenuation and shadow visibility. Multiply the BRDF by `N·L` exactly once.

For an opaque metallic workflow, base color represents diffuse reflectance at metallic 0 and specular reflectance at metallic 1. A dielectric `F0 = 0.04` is a useful artistic default, corresponding to an index of refraction near 1.5; retain a project's IOR-derived `F0` when present. Pure metal has no diffuse lobe. Intermediate metallic values can represent mixed coverage rather than a new homogeneous substance.

## A matched, finite reference

This original example uses isotropic GGX, height-correlated Smith visibility, Schlick Fresnel, and Fresnel-weighted Lambert diffuse. It is a compact single-scattering baseline, without rough-surface multiple-scattering compensation, clearcoat, transmission, or IBL. Inputs are finite; colors are linear reflectances in `[0,1]`, and radiance is finite and nonnegative at ordinary scene scales. Zero-length light/view directions return black. The roughness floor is an example policy to avoid a delta-like lobe, not a Metal requirement.

```metal
#include <metal_stdlib>
using namespace metal;

float3 brdfUnitOr(float3 value, float3 fallback) {
    float length2 = dot(value, value);
    return isfinite(length2) && length2 > 1e-12f
        ? value * rsqrt(length2) : fallback;
}

float ggxDistribution(float NoH, float alpha) {
    float a2 = alpha * alpha;
    float d = (1.0f - NoH * NoH) + a2 * NoH * NoH;
    return a2 / (3.14159265359f * d * d);
}

// Returns G2 / (4 * NoV * NoL), not G2 alone.
float smithGGXVisibility(float NoV, float NoL, float alpha) {
    float a2 = alpha * alpha;
    float v = NoL * sqrt(a2 + (1.0f - a2) * NoV * NoV);
    float l = NoV * sqrt(a2 + (1.0f - a2) * NoL * NoL);
    return 0.5f / max(v + l, 1e-7f);
}

float3 metallicDirectLight(float3 normal, float3 view, float3 light,
                           float3 baseColor, float metallic,
                           float perceptualRoughness, float3 radiance) {
    if (dot(view, view) <= 1e-12f || dot(light, light) <= 1e-12f)
        return float3(0.0f);
    float3 N = brdfUnitOr(normal, float3(0.0f, 0.0f, 1.0f));
    float3 V = brdfUnitOr(view, float3(0.0f));
    float3 L = brdfUnitOr(light, float3(0.0f));
    float NoV = saturate(dot(N, V));
    float NoL = saturate(dot(N, L));
    if (NoV <= 0.0f || NoL <= 0.0f) return float3(0.0f);

    float3 H = brdfUnitOr(V + L, N);
    float NoH = saturate(dot(N, H));
    float VoH = saturate(dot(V, H));
    float r = clamp(perceptualRoughness, 0.045f, 1.0f);
    float alpha = r * r; // Same alpha for D and Smith visibility.
    float m = saturate(metallic);
    float3 albedo = saturate(baseColor);
    float3 F0 = mix(float3(0.04f), albedo, m);
    float q = 1.0f - VoH;
    float q2 = q * q;
    float3 F = F0 + (1.0f - F0) * (q2 * q2 * q);

    float D = ggxDistribution(NoH, alpha);
    float visibility = smithGGXVisibility(NoV, NoL, alpha);
    float3 specular = D * visibility * F;
    float3 diffuse = (1.0f - F) * (1.0f - m) * albedo
        / 3.14159265359f;
    return (diffuse + specular) * max(radiance, float3(0.0f)) * NoL;
}
```

Helpers assume dot products in `[0,1]` and positive `alpha`, as established by the wrapper. Do not divide `D * visibility * F` by `4 * NoV * NoL` again. If replacing visibility with a geometric `G` term, restore that denominator. Do not mix a Beckmann masking approximation with GGX by accident, or square perceptual roughness again in only one term.

Check metallic 1 with black base color at normal incidence (`V = L = N`): the result is zero. Its diffuse term is zero at every angle, while Schlick's white grazing limit can still produce specular away from normal incidence. Check metallic 0 with black base color: dielectric specular remains. Roughness zero deliberately maps to the floor, and a bright narrow highlight may exceed 1 before output mapping. A lobe's peak above 1 does not by itself imply energy gain.

For point lights, guard distance near zero according to the light's physical or artistic size instead of allowing inverse-square singularities. Use geometry/shadow visibility for occlusion; do not multiply ambient occlusion into every direct light by default. When adding IBL or layered lobes, keep their roughness and energy conventions aligned with the existing renderer.

Theory: [Heitz's masking-shadowing analysis](https://jcgt.org/published/0003/02/03/) establishes model consistency; [Filament's material equations](https://google.github.io/filament/main/filament.html#materialsystem/specularbrdf) give a practical GGX/Smith formulation. The code here is original MSL illustrating those equations, not vendored framework source.

Sources reviewed 2026-10-13.
