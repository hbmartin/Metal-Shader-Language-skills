# Passes and fullscreen drawing

## A minimal procedural pass

This original classic MSL example draws one oversized fullscreen triangle, with no vertex buffer or vertex descriptor. UV origin is top left; size is the render target's pixel dimensions. `FullscreenUniforms` is one 16-byte `float4`, matched by a host `SIMD4<Float>` holding width, height, time in seconds, and intensity. Bind it at fragment buffer index 0. The shader returns opaque linear RGB.

```metal
#include <metal_stdlib>
using namespace metal;

struct FullscreenUniforms { float4 sizeTimeIntensity; };
struct FullscreenVaryings {
    float4 position [[position]];
    float2 uv;
};

vertex FullscreenVaryings fullscreenVertex(uint vertexID [[vertex_id]]) {
    const float2 positions[3] = {
        float2(-1.0f, -1.0f), float2(3.0f, -1.0f), float2(-1.0f, 3.0f)
    };
    float2 p = positions[vertexID]; // Draw exactly three vertices.
    FullscreenVaryings out;
    out.position = float4(p, 0.0f, 1.0f);
    out.uv = float2(0.5f * (p.x + 1.0f), 0.5f * (1.0f - p.y));
    return out;
}

fragment float4 fullscreenFragment(FullscreenVaryings in [[stage_in]],
                                  constant FullscreenUniforms& u [[buffer(0)]]) {
    float2 size = max(u.sizeTimeIntensity.xy, float2(1.0f));
    float2 p = (in.uv * size - 0.5f * size) / size.y;
    float phase = p.x * 5.0f + p.y * 3.0f + u.sizeTimeIntensity.z;
    float3 color = 0.5f + 0.5f * cos(phase + float3(0.0f, 2.0f, 4.0f));
    return float4(color * saturate(u.sizeTimeIntensity.w), 1.0f);
}
```

Load both functions into a cached render pipeline whose color format equals the target texture format. For an SDR sRGB target, leave RGB linear as shown. Disable depth testing and blending for this opaque pass, use no culling, and encode `drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3)`. Set viewport/scissor for the intended target. A later texture-based pass should use the same documented UV orientation instead of applying an unexplained Y flip.

The [MSL specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf) defines vertex IDs, stage interfaces, and resource attributes. Apple describes classic [render command encoding](https://developer.apple.com/library/archive/documentation/Miscellaneous/Conceptual/MetalProgrammingGuide/Render-Ctx/Render-Ctx.html); consult current SDK APIs for limits rather than treating this archived guide's limits as current.

## Attachments and pass boundaries

Choose each attachment action from its actual consumer:

| Situation | Action |
| --- | --- |
| Initialize background/depth before partial coverage | `.clear` load |
| Continue valid contents from earlier work | `.load` load |
| Fully overwrite every used sample without needing the destination | `.dontCare` load |
| Later sampling, later loading, readback, or presentation | `.store` store |
| Truly transient contents with no later consumer | `.dontCare` store |
| MSAA output needed only as single-sample pixels | `.multisampleResolve` with `resolveTexture` |
| Both MSAA samples and resolved pixels needed | Supported `.storeAndMultisampleResolve` path |

Full coverage must account for scissor, culling, depth/stencil rejection, discard, and channel write masks. Blending reads the destination, so use initialized contents even when geometry covers the whole target. Memoryless attachments cannot carry ordinary persisted contents into another pass; resolve transient MSAA color into a persistent texture if later work needs it.

Match the pipeline's color/depth/stencil formats and raster sample count to its attachments. Reallocate size-dependent textures on resize, keep old versions alive until their submissions complete, and rebuild pipelines only when their immutable configuration changes. Verify the chosen MSAA count and format support. [Load actions](https://developer.apple.com/documentation/metal/mtlloadaction), [store actions](https://developer.apple.com/documentation/metal/mtlstoreaction), and [feature tables](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf) are the primary contracts.

## Alpha blending

For source-over with add operations, set source/destination RGB factors to `.one`/`.oneMinusSourceAlpha` for premultiplied RGB, or `.sourceAlpha`/`.oneMinusSourceAlpha` for straight RGB. Alpha factors are `.one`/`.oneMinusSourceAlpha` in either case. A straight RGB shader paired with premultiplied factors creates bright fringes; multiplying premultiplied RGB by alpha again creates dark fringes. Composite in linear space and keep the output encoding agreed with the attachment.

Transparent geometry commonly uses depth testing with depth writes disabled and back-to-front ordering; preserve an existing order-independent approach when present. Alpha-to-coverage is an MSAA coverage technique with its own assumptions, not a substitute for all transparency. [Blend configuration](https://developer.apple.com/documentation/metal/mtlrenderpipelinecolorattachmentdescriptor) belongs to the pipeline.

Sources reviewed 2026-10-13.
