# Interfaces and layout

## Stages and bindings

A `vertex` function supplies a clip-space `[[position]]`; a `fragment` function consumes interpolated `[[stage_in]]` values and writes declared outputs; a `kernel` function operates on an explicitly dispatched grid. Match vertex/fragment varyings and attachment types at pipeline creation, not merely compilation.

Resource indices are separate namespaces for buffers, textures, and samplers, and are bound separately for each stage. Changing a declaration requires corresponding host binding and lifetime changes. Specify texture access (`sample`, `read`, or `write`) and ensure texture usage/format supports the operation. Dynamic buffer reads still need an application-level bounds contract.

`constant` is appropriate for read-only constant-address-space data; `device` describes device-address-space buffers; `threadgroup` is storage shared within a threadgroup; `thread` is private per-thread storage. Read-only `const device T*` and `constant T*` are distinct interfaces, not interchangeable qualifiers. Use the form expected by the resource and compiler.

This complete unit illustrates a bounds-safe interface, not a universal binding scheme:

```metal
#include <metal_stdlib>
using namespace metal;

struct TintParams {
    float4 tint;
    uint count;
    uint3 reserved;
};

kernel void tint_samples(device float4* samples [[buffer(0)]],
                         constant TintParams& p [[buffer(1)]],
                         uint i [[thread_position_in_grid]]) {
    if (i < p.count) samples[i] *= p.tint;
}
```

Host buffer 0 must contain at least `count` float4 elements. For this struct, `tint` begins at 0, `count` at 16, `reserved` at 32; alignment is 16 and stride is 48. The `uint3` adds alignment padding: do not represent this as five tightly packed scalars. For a smaller interface, use explicitly designed scalar padding instead.

## ABI checks

- Ordinary `float3` has 16-byte size/alignment; `packed_float3` stores three floats in 12 bytes with scalar alignment. A `.float3` vertex attribute fetched through a vertex descriptor is a different question from a buffer-struct member's ABI.
- Verify nested structs, arrays, and matrix column stride. A `float3x3` consists of padded columns; do not assume nine tightly packed floats. Match column/row convention and multiplication order independently of storage compatibility.
- On Swift hosts, check `MemoryLayout` stride/alignment and actual field offsets, not only size. On C/C++ hosts, use the appropriate SIMD/shared declarations and static assertions. Never make a Swift `Bool` or an arbitrary host enum part of an unverified GPU ABI.
- Type alignment and binding-offset alignment are separate constraints. For directly bound device buffers, retain the pointed-to type's alignment; constant-buffer offsets must also meet the target GPU/environment's minimum binding alignment. Consult the selected encoder API and applicable feature tables. The alignment guidance here covers physical Apple-family GPUs, including Apple silicon Macs, and Simulator. Apple-family GPUs currently list a 4-byte minimum constant-buffer offset alignment; Simulator requires 256 bytes even though its reported capabilities resemble Apple family 2. An allocator's 256-byte convention is not a universal MSL struct-alignment rule.

Check the Simulator environment before applying GPU-family rules; `supportsFamily(.apple2)` alone cannot select the alignment. In Swift, use `targetEnvironment(simulator)` as below; C/Objective-C uses `TARGET_OS_SIMULATOR` from `<TargetConditionals.h>`.

```swift
#if targetEnvironment(simulator)
let minimumConstantBufferOffsetAlignment = 256
#else
// Physical Apple-family GPU; retain the bound type's alignment as well.
let minimumConstantBufferOffsetAlignment = 4
#endif
```

## Coordinate contracts

Name object, world, view, clip, pixel, and normalized texture coordinates explicitly. Metal visible NDC depth is 0–1; raster viewport coordinates have their origin at the upper left. Fragment `[[position]]` is raster-space data, not the original vertex clip vector: dividing its z by w does not generally reconstruct linear depth.

Procedural UV normalization should use actual drawable/texture pixel dimensions, preserve aspect ratio intentionally, and handle zero dimensions on the host. Specify whether texture data is flipped, linear or sRGB, and straight or premultiplied alpha. Fix transforms once at the appropriate boundary.

## Sources

- [Apple MSL specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf): stage rules; coordinate system §1.7; vector/matrix/packed layout §2.2–2.5. Consult version annotations for the target; newer sections do not imply availability in pre-4 MSL.
- [MTLVertexDescriptor](https://developer.apple.com/documentation/metal/mtlvertexdescriptor): vertex attribute fetch configuration.
- [Resource fundamentals](https://developer.apple.com/documentation/metal/resource-fundamentals): host resource types and ownership.
- [setBuffer(_:offset:index:)](https://developer.apple.com/documentation/metal/mtlcomputecommandencoder/setbuffer(_:offset:index:)) and [Metal feature tables](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf): type alignment and target-specific constant-buffer binding offsets.
- [Developing Metal apps that run in Simulator](https://developer.apple.com/documentation/metal/developing-metal-apps-that-run-in-simulator): Simulator-specific constant-buffer offset restrictions.

Sources reviewed 2026-10-13. Examples are original, and their ABI is part of the example's explicit contract.
