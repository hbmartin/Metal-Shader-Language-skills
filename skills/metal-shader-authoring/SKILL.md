---
name: metal-shader-authoring
description: "Write, compile, and correct native Metal Shading Language functions and their host interfaces. Use for stage signatures, resource bindings, buffer layout, precision, specialization, and runtime shader compilation; technique design and GPU profiling have separate workflows."
---

# Metal Shader Authoring

Produce MSL that fits the caller's rendering or compute pipeline. Work within the project's deployment targets, shader language version, entry points, and resource conventions. This skill covers native MSL and classic Metal APIs through the pre-Metal-4 programming model; SwiftUI and shader-language porting are outside its scope.

## Establish the interface

Inspect the actual `.metal` files, library loading, pipeline descriptors, and binding code before changing a signature. Record the stage, input/output types, buffer/texture/sampler indices, matrix convention, coordinate spaces, texture formats, and color/alpha contract relevant to the change. Request missing host information only when it prevents a correct interface.

Preserve the existing host language and architecture. Shared headers or generated declarations can help, but introduce them only when they fit the project. For buffer structs, verify field offsets, alignment, and array stride on both sides; total size alone does not establish compatibility.

## Choose the relevant reference

- Read [interfaces and layout](references/interfaces-and-layout.md) for signatures, address spaces, bindings, vector/matrix layout, and coordinate contracts.
- Read [precision and specialization](references/precision-and-specialization.md) for type choices, derivatives, function constants, and feature availability.
- Read [compilation and replacement](references/compilation-and-replacement.md) for build-time libraries, compiler recipes, source-string compilation, caching, and live editing.

Keep examples small and specify their dependencies. Use declared binding indices and the host's actual texture access modes. Fix diagnostics at the interface or algorithm that causes them; avoid casting away address-space or layout mismatches.

Compile the changed entry points for the chosen language/SDK, then create the relevant pipeline. For changes to layout, precision, or output semantics, check an observable result in the existing renderer or a small isolated probe. Distinguish compilation, pipeline creation, and execution evidence.
