---
name: metal-materials-lighting
description: "Create and tune native Metal material and lighting shaders, including metallic or dielectric surfaces, normal detail, and linear color or HDR output. Use for surface appearance and illumination work in MSL."
---

# Metal Materials and Lighting

Build the requested surface appearance in native MSL, preserving the project's renderer, material model, and artistic intent. A stylized material can use deliberate approximations; introduce physically based shading when it serves the requested result.

## Establish the contract

Inspect the material entry point, coordinate space, light directions, normal transforms, textures, attachment formats, and output transfer function. Reuse existing bindings and uniforms; make only the host changes required to supply the shader's inputs. Match the project's deployment target and GPU capabilities. This skill does not introduce SwiftUI integration or Metal 4 APIs.

## Choose the relevant guidance

- For metallic/dielectric response, roughness, Fresnel, or grazing highlights, read [Direct lighting](references/direct-lighting.md).
- For normals, tangent frames, or bump detail, read [Normals and surface detail](references/normals.md).
- For texture color spaces, emission, transparency, exposure, or HDR, read [Color and output](references/color-output.md).

## Work toward an observable appearance

- Separate material parameters from light and camera parameters. Expose useful artistic controls with units or ranges; reuse the existing roughness convention.
- Keep BRDF, coordinate, and denominator calculations in `float` until precision is demonstrated sufficient. Very sharp highlights can exceed `half` range.
- Document the chosen model and approximations. Keep distribution and masking terms matched; distinguish geometric attenuation from visibility that already includes the BRDF denominator.
- Add only required lighting infrastructure. An environment lookup is an artistic approximation unless the project supplies matching diffuse convolution, specular prefiltering, and BRDF integration.

Compile against the target SDK, then inspect an image or real render. For a physical material, exercise metallic 0/1, roughness endpoints, grazing and back-facing directions, nonuniform scale, and dark/bright illumination. For stylized work, verify the intended silhouette, highlights, motion, and parameter extremes. Check finite output before tone mapping so clamping cannot conceal a broken BRDF. Report what was visually and numerically verified and any hardware-dependent checks left open.
