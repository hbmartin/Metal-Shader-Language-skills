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
- Give the ray an interval, convergence tolerance, and finite evaluation budget. Distinguish a hit, an interval miss, budget exhaustion, and invalid arithmetic. Exhausting the loop is not a hit.
- Reuse the marched field for normals and secondary surface rays. Budget normal probes, shadows, AO, and nested lighting separately from the primary march.

## Read the relevant reference

- [Distance fields and transforms](references/distance-fields.md): primitive contracts, composition, scaling, negative-coordinate repetition, and deformations.
- [Surface tracing](references/surface-tracing.md): explicit results, inside origins, convergence, consistent normals, and a complete sphere fragment.
- [Volumes](references/volumes.md): bounding intervals, Beer–Lambert integration, opacity, quality changes, and early termination.

## Verify geometry and appearance

Compile the complete MSL unit for the target language version. Compare a simple field against analytic intersections before adding deformations. Test negative coordinates, zero deformation, grazing/inside rays, and a deliberately exhausted budget. Inspect normals and iteration counts at fixed time and more than one resolution. For volumes, compare a homogeneous path with analytic transmittance and vary step count; fixed-path opacity should converge rather than change with an accidental missing step-length factor. Profile the actual target GPU when quality/cost tradeoffs are requested.
