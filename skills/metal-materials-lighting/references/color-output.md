# Color, emission, and output

Write down the chain: asset encoding → texture interpretation → linear shading/compositing → exposure/tone mapping → output encoding/display color space. Match the application's existing chain instead of adding a second correction to fix a dark preview.

## Texture and alpha contracts

- Color textures authored in sRGB normally use an sRGB texture format; sampling decodes RGB. Normal, roughness, metallic, masks, and lookup data use linear formats. A texture-loader option or view can change interpretation, so inspect the actual texture.
- Keep lighting and emission in linear working-space RGB. Match primaries as well as transfer functions; sRGB decoding alone does not convert Display P3 into another gamut.
- State whether RGB is straight or premultiplied. Composite in linear light with matching blend factors. Alpha is coverage/opacity, not a gamma-encoded color channel. Unpremultiply only where required, with a zero-alpha guard.

Apple documents automatic sRGB conversion and linear alpha in [MTLPixelFormat](https://developer.apple.com/documentation/metal/mtlpixelformat). Inspect the attachment format before adding a transfer function.

## Exactly one final encoding

For SDR, expose and map HDR radiance into the display range. If the render attachment is `.bgra8Unorm_srgb` or another sRGB format, return linear RGB; the attachment performs the encoding. For an ordinary unorm attachment that the application intentionally treats as sRGB-encoded output, encode in the shader once. Earlier lighting passes should stay linear.

This original example demonstrates a simple SDR preview curve, not a production filmic transform. Inputs are finite nonnegative radiance at practical scene scales. `mapPreviewSDR` returns linear display-range values; `encodeSRGB` is used only for the manual-encoding output path. Apply output mapping to opaque output or follow the project's compositing design for transparency: tone mapping premultiplied RGB directly can change coverage-dependent appearance.

```metal
#include <metal_stdlib>
using namespace metal;

float3 mapPreviewSDR(float3 linearRadiance, float exposure) {
    float3 x = max(linearRadiance, float3(0.0f)) * max(exposure, 0.0f);
    return x / (1.0f + x);
}

float encodeSRGBChannel(float linearValue) {
    float x = clamp(linearValue, 0.0f, 1.0f);
    return x <= 0.0031308f ? 12.92f * x
        : 1.055f * pow(x, 1.0f / 2.4f) - 0.055f;
}

float3 encodeSRGB(float3 linearValue) {
    return float3(encodeSRGBChannel(linearValue.x),
                  encodeSRGBChannel(linearValue.y),
                  encodeSRGBChannel(linearValue.z));
}
```

The [Apple resource guide](https://developer.apple.com/library/archive/documentation/Miscellaneous/Conceptual/MetalProgrammingGuide/Mem-Obj/Mem-Obj.html) specifies the piecewise sRGB transfer curve. `pow(color, 1/2.2)` is only an approximation, and applying either curve before writing an sRGB attachment double-encodes the output.

## HDR and appearance checks

Use an appropriate floating-point intermediate, such as `.rgba16Float`, when radiance can exceed 1. Retain precision and finite bounds through emission, bloom, and exposure. HDR/EDR presentation requires the host layer's supported format, color space, and display policy; a float texture alone does not enable it. Preserve values above SDR white when the established presentation path expects extended linear output. Apple's [custom EDR tone-mapping guidance](https://developer.apple.com/documentation/metal/performing-your-own-tone-mapping) covers that host contract.

Check a neutral ramp with tone mapping bypassed: linear 0.18 encodes near 0.461 in sRGB, while alpha 0.18 stays 0.18. Check transparent edges over dark and bright backgrounds, emissive values above 1, and an exposure sweep. Record whether each inspected image represents linear intermediate data or encoded display output; a screenshot cannot establish the absence of internal NaNs or confirm every HDR presentation condition.

Sources reviewed 2026-10-13.
