---
name: metal-debugging
description: "Diagnose native Metal/MSL compiler errors, incorrect images, GPU faults, and performance regressions on Apple platforms. Use for shader validation, GPU capture, resource inspection, and measured optimization of pre-Metal-4 pipelines."
---

# Metal Debugging

Find the earliest incorrect value or resource use, make a focused correction, and verify it under the same workload. Preserve the project's host language, rendering framework, deployment targets, and normal build settings. This skill covers native MSL and the classic Metal API; SwiftUI shaders and Metal 4 workflows are outside its scope.

## Choose the diagnostic path

- For compilation failures, reproduce with the actual SDK, language standard, macros, includes, and entry-point names. Separate source compilation from library loading and pipeline creation.
- For blank or incorrect images, first check drawable/pass setup, pipeline formats, bindings, counts, and resource contents. Then isolate the shader math with a known constant output or a temporary diagnostic view.
- For crashes or intermittent artifacts, inspect command-buffer errors and ownership, enable API/Shader Validation for a diagnostic run, and capture the failing work. A clean validation run does not prove race freedom.
- For slowness, reproduce and measure first. Separate compilation, CPU encoding, waits, GPU execution, and presentation before optimizing shader code. Validation instrumentation changes the workload, so measure the normal configuration separately.

## Focused references

- [Compilation and validation](references/compilation-and-validation.md): selectable pre-4 compiler recipes, diagnostics, and capture setup.
- [Visual and resource diagnosis](references/visual-diagnosis.md): finite-value, UV, normal, depth, and producer/consumer checks with executable MSL helpers.
- [Measured profiling](references/measured-profiling.md): GPU capture, Instruments, per-line inspection, and comparison criteria.

Report the reproduction, evidence, correction, and verification performed. Distinguish a compiled shader, a completed GPU dispatch, a numerically checked result, and a visually reviewed image. If a needed device or tool is unavailable, state the missing verification precisely.
