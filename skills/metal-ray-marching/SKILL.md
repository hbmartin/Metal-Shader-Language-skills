---
name: metal-ray-marching
description: "Build and debug native MSL signed-distance surface renderers and ray-marched fog, clouds, or other volumes. Use for SDF composition, sphere tracing, distance bounds, surface normals, shadows, or volumetric integration; hardware acceleration-structure ray tracing is a different workflow."
---

# Metal Ray Marching

Create the requested surface or volume effect in the existing Apple-platform Metal pipeline. Keep host integration minimal and match the project's camera, depth, and output conventions. This skill concerns native MSL before Metal 4; it does not prescribe SwiftUI effects, a framework, or a shader-language port.

## Choose the march deliberately

- For implicit surfaces, distinguish an exact signed distance, a conservative distance bound, and a general scalar field. Distance-driven sphere tracing is safe only when the proposed step cannot skip the surface; arbitrary displacement or domain warping can invalidate that bound.
- For volumes, integrate density/extinction over a bounded ray interval. A density value is not a surface distance, and a surface marcher is not a volume integrator.
- Use normalized ray directions and consistent scene units. Keep ray distances, fields, transmittance, and accumulated radiance in `float`; choose output precision separately.
- Give the ray an interval, convergence tolerance, and finite evaluation budget. Distinguish a hit, an interval miss, budget exhaustion, precision stagnation, and invalid arithmetic. Exhausted and stalled rays do not establish a hit.
- Reuse the marched field for normals and secondary surface rays. Budget normal probes, shadows, AO, and nested lighting separately from the primary march.

Choose the tolerance policy for the effect. A strict epsilon preserves the requested field-residual criterion and can report stagnation when `float` cannot advance; it is useful for numerical comparisons and explicit diagnostics. A documented effective tolerance floor can improve practical convergence, but accepts larger residuals and can expand silhouettes or erase fine features. When choosing a floor, account for scene scale, representable increments at the current ray distance, and the projected pixel footprint; a residual bound is not the same as ray-distance accuracy near a grazing surface. Keep exhaustion distinct even with a floor. The reference tracer uses strict epsilon without silently increasing it.

## Read the relevant reference

- [Distance fields and transforms](references/distance-fields.md): primitive contracts, composition, scaling, negative-coordinate repetition, and deformations.
- [Surface tracing](references/surface-tracing.md): explicit results, inside origins, convergence, consistent normals, and a complete sphere fragment.
- [Volumes](references/volumes.md): bounding intervals, Beer–Lambert integration, opacity, quality changes, and early termination.

## Verify geometry and appearance

Compile the complete MSL unit for the target language version. Compare a simple field against analytic intersections before adding deformations. Test negative coordinates, zero deformation, grazing/inside rays, and a deliberately exhausted budget. Inspect normals and iteration counts at fixed time and more than one resolution. For volumes, compare a homogeneous path with analytic transmittance and vary step count; fixed-path opacity should converge rather than change with an accidental missing step-length factor. Profile the actual target GPU when quality/cost tradeoffs are requested.
