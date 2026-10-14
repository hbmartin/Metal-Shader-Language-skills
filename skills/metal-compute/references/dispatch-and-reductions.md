# Dispatch and reductions

## Independent map

This original example doubles a buffer. Binding 0 is a read-only `count`-element float buffer; binding 1 is a separate writable buffer with at least `count` floats; binding 2 is one unsigned 32-bit count. The device-buffer offsets must retain the float type's 4-byte alignment. The count's constant-buffer offset must satisfy both uint alignment and the target GPU/environment's constant-buffer binding requirement. These are separate constraints: consult `setBuffer(_:offset:index:)` and the applicable feature tables rather than assuming type alignment is always sufficient. Skip dispatch for zero count.

This alignment guidance covers physical Apple-family GPUs, including Apple silicon Macs, and Simulator. Apple-family GPUs currently list a 4-byte minimum constant-buffer offset alignment. Simulator requires 256-byte constant-buffer offsets even though its reported capabilities resemble Apple family 2. Check the Simulator environment before applying GPU-family rules; `supportsFamily(.apple2)` alone cannot select the alignment. In Swift, use `targetEnvironment(simulator)` as below; C/Objective-C uses `TARGET_OS_SIMULATOR` from `<TargetConditionals.h>`.

```swift
#if targetEnvironment(simulator)
let minimumConstantBufferOffsetAlignment = 256
#else
// Physical Apple-family GPU; retain the bound type's alignment as well.
let minimumConstantBufferOffsetAlignment = 4
#endif
```

```metal
#include <metal_stdlib>
using namespace metal;

kernel void map_double(
    device const float* input [[buffer(0)]],
    device float* output [[buffer(1)]],
    constant uint& count [[buffer(2)]],
    uint gid [[thread_position_in_grid]])
{
    if (gid >= count) return;
    output[gid] = input[gid] * 2.0f;
}
```

For a legal one-dimensional group size `T`, either dispatch exactly `(count, 1, 1)` threads on a device supporting nonuniform groups, or dispatch `ceil(count / T)` complete groups of `(T, 1, 1)`. The guard supports either. Choose `T` from the pipeline's limits; multiples of its `threadExecutionWidth` are candidates for efficient execution. Keep unused dimensions equal to one.

For image maps, bind the intended mip level and use `uint2` indexing with guards against the bound texture's width and height. Sampling uses a sampler and its coordinate convention; integer `read` does not provide the same filtering. Compute kernels cannot use fragment derivatives such as `fwidth`; supply a pixel footprint when antialiasing procedural content.

## One partial sum per complete group

This original example deliberately uses complete, uniform threadgroups. Select a power-of-two `T >= 2`, legal for this pipeline. Dispatch `(ceil(count / T), 1, 1)` groups with `(T, 1, 1)` threads using `dispatchThreadgroups`. Do **not** substitute a nonuniform edge dispatch without changing the algorithm.

Bind input at 0, a separate partial-output buffer at 1, and `count` at 2. Reserve `roundUp(T * sizeof(float), 16)` dynamic threadgroup bytes at index 0: the encoder's memory length must be a multiple of 16 bytes even when the kernel needs fewer bytes. For example, `T = 2` needs an allocation length of 16, not 8. The output needs `ceil(count / T)` floats. Check static plus rounded dynamic threadgroup memory against the device limit. Every lane initializes a scratch slot and reaches every barrier, including lanes outside the input range.

```metal
#include <metal_stdlib>
using namespace metal;

kernel void reduce_sum_partials(
    device const float* input [[buffer(0)]],
    device float* partials [[buffer(1)]],
    constant uint& count [[buffer(2)]],
    threadgroup float* scratch [[threadgroup(0)]],
    uint gid [[thread_position_in_grid]],
    uint lid [[thread_position_in_threadgroup]],
    uint group [[threadgroup_position_in_grid]],
    uint groupSize [[threads_per_threadgroup]])
{
    scratch[lid] = gid < count ? input[gid] : 0.0f;
    threadgroup_barrier(mem_flags::mem_threadgroup);

    for (uint stride = groupSize / 2; stride > 0; stride >>= 1) {
        if (lid < stride) scratch[lid] += scratch[lid + stride];
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }

    if (lid == 0) partials[group] = scratch[0];
}
```

Reduce the partials with subsequent ordered dispatches until one remains, alternating distinct input/output buffers. The host controls these global stages. For zero inputs, return the sum identity on the host or initialize a dedicated result without executing this kernel. For one input, use it directly or launch one full group. Ensure rounded grid indices fit the kernel's `uint` representation; use chunking or a suitable wider indexing design for larger data.

Changing the reduction tree changes floating-point addition order. Test finite inputs against a CPU reference with an error tolerance appropriate to magnitude and length; define NaN/Inf behavior if the application needs it. Useful sizes include `0`, `1`, `T-1`, `T`, `T+1`, and multiple groups plus a tail. Include mixed signs and values of different magnitudes.

## Correctness before tuning

A normal memory load followed by a store is not an atomic append or accumulation. For this pre-4 scope, ordinary atomic operations use `memory_order_relaxed`; atomicity alone does not publish unrelated payload data. Prefer a separate consumer dispatch with command-level ordering when publishing multi-field results.

The reduction index is the **group ID**, not the group size or SIMD width. Group size controls the scratch capacity and reduction tree. SIMD width describes a different execution scope; do not interchange them.

The dimensional thread built-ins in this one-dimensional signature all use scalar `uint`. If changing to vector coordinates, use matching vector dimensions for these built-ins rather than mixing scalar indices with a `uint3` group size.

## Sources

- [Apple: setBuffer(_:offset:index:)](https://developer.apple.com/documentation/metal/mtlcomputecommandencoder/setbuffer(_:offset:index:)) and [Metal feature tables](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf) — distinguish device type alignment from hardware-dependent constant-buffer offset alignment.
- [Apple: Developing Metal apps that run in Simulator](https://developer.apple.com/documentation/metal/developing-metal-apps-that-run-in-simulator) — Simulator-specific constant-buffer offset restrictions.
- [Apple: Calculating threadgroup and grid sizes](https://developer.apple.com/documentation/metal/calculating-threadgroup-and-grid-sizes) — pipeline-dependent limits and uniform versus nonuniform dispatch.
- [Apple: threadExecutionWidth](https://developer.apple.com/documentation/metal/mtlcomputepipelinestate/threadexecutionwidth) — query the execution width instead of hardcoding it.
- [Apple: setThreadgroupMemoryLength](https://developer.apple.com/documentation/metal/mtlcomputecommandencoder/setthreadgroupmemorylength(_:index:)) — dynamic memory lengths are multiples of 16 bytes.
- [Apple: MSL specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf) — vector layout, kernel built-ins, barrier participation, atomics, and fragment-only derivatives. The canonical specification includes newer language features; use only those supported by the project's pre-4 language target.

Sources reviewed 2026-10-13.
