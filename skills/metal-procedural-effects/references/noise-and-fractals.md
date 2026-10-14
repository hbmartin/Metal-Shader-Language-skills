# Noise and fractals

Choose a field from its visual and numerical needs. Value noise is a small smooth building block; gradient noise better fits many organic textures; cellular distances expose cells and cracks. A cheap hash is a source of decorrelated values, not a smooth field or a guarantee of statistical quality. MSL has no general procedural-noise intrinsic.

## Periodicity is a contract

Wrap the lattice before hashing to make a periodic field. Applying `fract` to an arbitrary noise input can create a seam. The square-lattice example below supports positive integer periods on either axis, with zero disabling wrapping on that axis. Both values and interpolation derivatives agree at the seams. Keep coordinates finite and within the useful integer/fractional precision of `float`; move the origin near the region being shaded for large worlds.

The following is a complete helper translation unit. It uses a small integer-mixed value field and quintic interpolation, rather than a copied simplex implementation. `pe_value_noise_2d` returns values in `[0, 1)` for the valid coordinates described above; this is not a Perlin or simplex algorithm. Floating-point evaluation can make the quintic weight overshoot, so the final result is clamped to zero through `0x1.fffffep-1f`, the largest float below one. When using noise to select a palette entry, also bound the integer index to the palette's valid range.

The fixed nonzero hash salt prevents cell `(0, 0)` from being an absorbing zero. For a given integer cell, the hash and its 24-bit conversion to a power-of-two-scaled float are exact. Interpolation and fBm use floating-point arithmetic: results are repeatable within the same complete compiled shader program with fixed inputs, GPU, compiler, and math settings. Separately compiled kernels and fragment shaders can optimize the same helper text differently; bitwise equality between those programs or across configurations is not promised. Keep the salt and octave transforms stable when an asset or effect needs repeatable noise values.

```metal
#include <metal_stdlib>
using namespace metal;

int pe_wrap_cell(int cell, int period) {
    if (period <= 0) return cell;
    int r = cell % period;
    return r < 0 ? r + period : r;
}

float pe_hash_cell(int2 cell) {
    uint h = uint(cell.x) * 1597334677u ^ uint(cell.y) * 3812015801u;
    h ^= 0x9E3779B9u;
    h ^= h >> 16;
    h *= 2246822519u;
    h ^= h >> 13;
    h *= 3266489917u;
    h ^= h >> 16;
    return float(h >> 8) * (1.0f / 16777216.0f);
}

float pe_lattice_value(int2 cell, int2 period) {
    cell = int2(pe_wrap_cell(cell.x, period.x),
                pe_wrap_cell(cell.y, period.y));
    return pe_hash_cell(cell);
}

float pe_value_noise_2d(float2 p, int2 period) {
    int2 cell = int2(floor(p));
    float2 f = fract(p);
    float2 u = f * f * f * (f * (f * 6.0f - 15.0f) + 10.0f);
    float a = pe_lattice_value(cell, period);
    float b = pe_lattice_value(cell + int2(1, 0), period);
    float c = pe_lattice_value(cell + int2(0, 1), period);
    float d = pe_lattice_value(cell + int2(1, 1), period);
    float value = mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
    return clamp(value, 0.0f, 0x1.fffffep-1f);
}

// Signed fBm, up to eight octaves in this example. Footprint is the
// approximate base-coordinate distance covered by one output pixel.
float pe_fbm_2d(float2 p, float footprint, int octaves) {
    float value = 0.0f;
    float amplitude = 0.5f;
    float frequency = 1.0f;
    float2 q = p;
    for (int i = 0; i < clamp(octaves, 0, 8); ++i) {
        float width = max(footprint, 0.0f) * frequency;
        float visibility = 1.0f - smoothstep(0.25f, 0.5f, width);
        if (visibility <= 0.0f) break;
        value += amplitude * visibility *
                 (2.0f * pe_value_noise_2d(q, int2(0)) - 1.0f);
        q = 2.0f * float2(0.8f * q.x - 0.6f * q.y,
                         0.6f * q.x + 0.8f * q.y) + float2(13.37f, 7.91f);
        amplitude *= 0.5f;
        frequency *= 2.0f;
    }
    return value;
}
```

## Fractals and warps

The fBm cutoff above is a practical octave fade, not an exact reconstruction filter. In a fragment shader, estimate a scalar footprint from `max(length(dfdx(p)), length(dfdy(p)))` before divergent flow. Fade out high octaves instead of restoring their contrast through renormalization. Choose gain/lacunarity from the look and available cost; the eight-octave cap is a property of this example.

Each fBm octave rotates, doubles, and offsets the previous coordinate to reduce correlated lattice structure. The rotation preserves lengths, so `frequency` still tracks the footprint scale. This is a visual quality choice; quintic value noise is smooth at cell boundaries even when grids align.

For axis-aligned periodic fBm, use unrotated coordinates and wrap each octave consistently. With integer frequency `f` and base period `P`, evaluate `p * f` with period `P * f`, checking integer overflow. Arbitrary octave rotation does not preserve those axis-aligned periods. The supplied `pe_fbm_2d` deliberately makes no periodicity promise; the wrapping contract of `pe_value_noise_2d` is unchanged.

A domain warp changes the sampling footprint. Construct the warped coordinate first and measure its derivatives before evaluating filtered detail, or use a known Jacobian when derivatives are unavailable. Multiple warp levels multiply noise evaluations; expose scale and warp amplitude before increasing octaves. Derivative-based filtering also reduces sparkling in animated patterns and displaced normals.

## Author sources

- [Gustavson's noise overview](https://stegu.github.io/webgl-noise/) distinguishes the older classic/4D/cellular library from the newer 2D/3D simplex work.
- [Gustavson and McEwan, Tiling Simplex Noise and Flow Noise](https://jcgt.org/published/0011/01/02/paper.pdf) covers explicit periodicity, rotating-gradient animation, and analytic derivatives. Its 2D simplex grid requires integer x and even-integer y periods; those constraints are specific to that algorithm, not the square-grid helper above.
- [Author implementation and license](https://github.com/stegu/psrdnoise) and [Ashima/Gustavson license](https://github.com/ashima/webgl-noise/blob/master/LICENSE): preserve their MIT copyright and permission notices if reusing substantial implementation code. Linking to the mathematical source does not make copied code original.
- [Apple: mathMode](https://developer.apple.com/documentation/metal/mtlcompileoptions/mathmode) and [fastMathEnabled](https://developer.apple.com/documentation/metal/mtlcompileoptions/fastmathenabled) — compiler math settings affect floating-point behavior; select the API supported by the project's SDK.

Sources reviewed 2026-10-13.
