---
name: metal-compute
description: "Build or fix native Metal compute kernels for image effects, reductions, particles, and simulations on Apple platforms. Use for dispatch sizing, parallel ownership, GPU resources, and compute-to-render handoffs with the pre-Metal-4 API."
---

# Metal Compute

Turn the requested operation into a kernel with an explicit input/output contract, then connect it to the project's existing Metal pipeline. Preserve its host language, framework, deployment targets, and resource conventions. This skill covers native MSL and the `MTLCommandQueue` / `MTLComputeCommandEncoder` API; SwiftUI shaders and Metal 4 workflows are outside its scope.

## Make parallel behavior explicit

- Establish dimensions or active counts, buffer capacities, element strides, texture formats, and each thread's output ownership before dispatch. Host and shader layouts must agree; a normal `float3` occupies and aligns to 16 bytes.
- Query `threadExecutionWidth`, `maxTotalThreadsPerThreadgroup`, and threadgroup-memory limits for the actual pipeline and device. Pick a legal group shape, then measure it. Neither 32-wide execution nor the largest group is a universal optimum.
- Use a bounds guard for a rounded grid. For cooperative kernels, keep every participating thread through the barriers and load an identity value for inactive elements. A shader barrier cannot synchronize separate threadgroups or dispatches.
- Distinguish algorithmic races, command-order hazards, and CPU/GPU ownership. Shared storage does not make concurrent CPU writes safe. Preserve inputs until every consumer has finished.
- Validate against a small CPU reference, including empty and uneven sizes, before optimizing precision, SIMD operations, or memory access.

## Read the relevant reference

- [Dispatch and reductions](references/dispatch-and-reductions.md): independent maps, full-group reductions, and their executable MSL examples.
- [Simulation and ownership](references/simulation-and-ownership.md): neighborhood updates, feedback, particle capacity, and bounded appends.
- [Resources and library choices](references/resources-and-libraries.md): storage, residency, synchronization, and when an MPS operation is useful.

Deliver the kernel together with its binding indices, dispatch dimensions, scratch/output capacities, and required ordering. Report compilation, numerical comparison, and device execution separately; a successful compile does not establish race freedom.
