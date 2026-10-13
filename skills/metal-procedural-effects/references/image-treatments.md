# Image treatments

Preserve the pipeline's working color space and alpha convention. Sample color textures through the intended sRGB decoding or linear format; lighting, bloom thresholds, and compositing generally operate in linear light. Treat normal/depth/other data textures as data. Encode display transfer once at the output boundary; an sRGB render attachment already performs that conversion. An artistic treatment in another space can be intentional, but state the choice.

## Sampling and passes

- Blur uses a distinct destination resource; sampling and writing the same subresource is not an ordinary safe filter pass.
- Use separable horizontal/vertical passes for a separable kernel. Kernel tap count, radius in pixels, boundary mode, and resolution are independent controls.
- For bloom, extract and blur bright scene-linear HDR values before tone mapping, then combine with the original scene. A bloom extraction applied after display clipping cannot recover discarded highlights.
- A neighborhood filter's UV footprint is its largest tap offset, including downsampled-resolution conversion. Clamp, zero, mirror, or repeat addressing changes the visual boundary behavior.
- Blur premultiplied color and alpha together when that is the renderer's convention. For nonlinear color edits, safely unpremultiply, edit, and premultiply again; avoid RGB leakage into fully transparent pixels.

## Complete MSL filter example

The following unit is a normalized five-tap separable filter and an alpha-preserving vignette helper. `pe_blur_fragment` expects interpolated normalized UVs from a matching vertex output, the input at texture 0, and `texelStep` at fragment buffer 0. For a one-pixel horizontal step use `(1 / width, 0)`; for the second pass use `(0, 1 / height)` with the first pass output. Larger spacing is an artistic wider filter, not an exact Gaussian of arbitrary sigma.

```metal
#include <metal_stdlib>
using namespace metal;

struct PEImageRaster {
    float4 position [[position]];
    float2 uv;
};

half4 pe_vignette(half4 color, float2 centeredAspectUV,
                 float innerRadius, float outerRadius, float strength) {
    float outer = max(outerRadius, innerRadius + 1.0e-4f);
    float edge = smoothstep(innerRadius, outer, length(centeredAspectUV));
    half scale = half(1.0f - saturate(strength) * edge);
    return half4(color.rgb * scale, color.a);
}

fragment half4 pe_blur_fragment(
    PEImageRaster in [[stage_in]],
    texture2d<half> source [[texture(0)]],
    constant float2& texelStep [[buffer(0)]]
) {
    constexpr sampler linearClamp(coord::normalized,
                                  address::clamp_to_edge,
                                  filter::linear);
    half4 value = source.sample(linearClamp, in.uv) * 0.38774h;
    value += (source.sample(linearClamp, in.uv + texelStep) +
              source.sample(linearClamp, in.uv - texelStep)) * 0.24477h;
    value += (source.sample(linearClamp, in.uv + 2.0f * texelStep) +
              source.sample(linearClamp, in.uv - 2.0f * texelStep)) * 0.06136h;
    return value;
}
```

Use `float` accumulators/samples if the HDR range or filter precision requires it. Choose a standard MPS filter when it matches the operation and fits the current pipeline; `MPSImageGaussianBlur` is an approximate Gaussian, so analytically strict kernels may need explicit convolution. Custom code is useful for a particular sample pattern or combined treatment. Neither path is universally fastest.

Verify a constant image remains constant, impulse response is symmetric, transparent edges remain clean, and texture boundaries match the chosen addressing. Inspect a neutral gray through the complete pipeline to catch double transfer encoding. Compare blur cost at the actual input/output sizes, including pass bandwidth.

## Sources

- [Metal Shading Language specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf): texture/sampler operations and stage inputs.
- [Apple's sRGB pixel format reference](https://developer.apple.com/documentation/metal/mtlpixelformat/bgra8unorm_srgb): format semantics at the rendering boundary.
- [MPSImageGaussianBlur](https://developer.apple.com/documentation/metalperformanceshaders/mpsimagegaussianblur): the standard Metal filter alternative.
