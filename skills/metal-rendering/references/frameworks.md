# Optional framework integration

Read this only when the project already uses one of these frameworks or the user requests it. Do not add or migrate a dependency merely because it illustrates a good practice. Inspect the resolved package version and its source before using APIs from mutable upstream documentation.

## Satin

The intended repository is [Fabric-Project/Satin](https://github.com/Fabric-Project/Satin), a maintained fork of the original Satin framework. It provides scene/material abstractions, compute, PBR, shader caches, and live source editing. Reuse its material uniforms, binding conventions, and render context instead of bypassing them with a second pipeline.

For source-based materials, inspect [`SourceMaterial`](https://github.com/Fabric-Project/Satin/blob/main/Sources/Satin/Materials/SourceMaterial.swift) and the project's example for that exact revision: current APIs accept a `pipelineURL` and `live` option. Its file compiler assembles source includes before runtime compilation; this does not establish an include search path in Metal itself. Its uniform buffer's 256-byte slots are a framework convention, not a universal alignment rule for every buffer operation. Follow the project's existing lifecycle and supported platform baseline.

## MiniMetal

The intended repository is [apardee/MiniMetal](https://github.com/apardee/MiniMetal), a small macOS AppKit/MetalKit demo package. Its classic `Window.show` overload with an explicitly typed `Frame` uses a conventional command queue. The separately available `Frame4` overload is outside this skill's scope. Exposed `view` and `device` permit ordinary native Metal configuration.

`MiniMetalMacros` is optional and introduces a SwiftSyntax build cost; `MiniMetal` alone has no macro requirement. `@MetalLayout` can generate/check supported uniform layouts, while `#shader` scans inline source and prepends those declarations. Treat the scanner as a convenience, not a full shader compiler. Explicitly select the classic frame overload in examples to avoid ambiguous closures or adoption of a different API family.

## Raster / MetalPetal

[aldealabs/raster](https://github.com/aldealabs/raster) is an independently maintained continuation of MetalPetal. Raster 2.x changes the module/product to `Raster` and retains the `MTI*` type names; the 1.26 compatibility line still uses `MetalPetal`. Respect the dependency already selected by the project. See the [migration boundary](https://raster.aldealabs.com/docs/start/migrating-from-metalpetal/).

Use `MTIFunctionDescriptor` and the framework's render/compute kernel contracts for custom filters. Contexts own device-specific cached pipeline state, including function constants and render configuration. Input texture order and the name-based buffer parameter dictionary are different contracts: inspect both before changing a shader signature. The [pipeline and argument-encoding guide](https://raster.aldealabs.com/docs/internals/pipelines-argument-encoding/) describes those boundaries. Make alpha, color space, and lazy image resolution explicit instead of assuming an `MTIImage` is an eagerly rendered bitmap.

## Provenance

These frameworks' core repositories report MIT licensing; preserve relevant notices if copying their code. This skill vendors none. Raster's [`RasterExamples` license](https://github.com/aldealabs/raster/blob/master/RasterExamples/LICENSE.md) restricts that directory to non-commercial testing/evaluation, so do not copy its assets/code into distributable templates under the core license.

ShaderKit (`jamesrochabrun/ShaderKit`) and Inferno (`twostraws/Inferno`) are SwiftUI integrations, while current MetalSprockets centers on Metal 4. They are outside this skill's integration scope. General ideas such as immutable pipeline cache keys, bounded sampling, and explicit alpha contracts can be applied directly without adopting their APIs.
