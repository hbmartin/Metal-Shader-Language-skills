# Noise and fractals

Choose a field from its visual and numerical needs. Value noise is a small smooth building block; gradient noise better fits many organic textures; cellular distances expose cells and cracks. A cheap hash is a source of decorrelated values, not a smooth field or a guarantee of statistical quality. MSL has no general procedural-noise intrinsic.

## Periodicity is a contract

Wrap the lattice before hashing to make a periodic field. Applying `fract` to an arbitrary noise input can create a seam. The square-lattice example below supports positive integer periods on either axis, with zero disabling wrapping on that axis. Both values and interpolation derivatives agree at the seams. Keep coordinates finite and within the useful integer/fractional precision of `float`; move the origin near the region being shaded for large worlds.

The following is a complete helper translation unit. It uses a small integer-mixed value field and quintic interpolation, rather than a copied simplex implementation. `pe_value_noise_2d` returns values in `[0, 1)`; this is not a Perlin or simplex algorithm.

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
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

// Signed fBm, up to eight octaves in this example. Footprint is the
// approximate base-coordinate distance covered by one output pixel.
float pe_fbm_2d(float2 p, float footprint, int octaves) {
    float value = 0.0f;
    float amplitude = 0.5f;
    float frequency = 1.0f;
    for (int i = 0; i < clamp(octaves, 0, 8); ++i) {
        float width = max(footprint, 0.0f) * frequency;
        float visibility = 1.0f - smoothstep(0.25f, 0.5f, width);
        if (visibility <= 0.0f) break;
        value += amplitude * visibility *
                 (2.0f * pe_value_noise_2d(p * frequency, int2(0)) - 1.0f);
        amplitude *= 0.5f;
        frequency *= 2.0f;
    }
    return value;
}
```

## Fractals and warps

The fBm cutoff above is a practical octave fade, not an exact reconstruction filter. In a fragment shader, estimate a scalar footprint from `max(length(dfdx(p)), length(dfdy(p)))` before divergent flow. Fade out high octaves instead of restoring their contrast through renormalization. Choose gain/lacunarity from the look and available cost; the eight-octave cap is a property of this example.

For periodic fBm, wrap each octave consistently. With integer frequency `f` and base period `P`, evaluate the octave with period `P * f`, checking integer overflow. The supplied `pe_fbm_2d` deliberately makes no periodicity promise.

A domain warp changes the sampling footprint. Construct the warped coordinate first and measure its derivatives before evaluating filtered detail, or use a known Jacobian when derivatives are unavailable. Multiple warp levels multiply noise evaluations; expose scale and warp amplitude before increasing octaves. Derivative-based filtering also reduces sparkling in animated patterns and displaced normals.

## Author sources

- [Gustavson's noise overview](https://stegu.github.io/webgl-noise/) distinguishes the older classic/4D/cellular library from the newer 2D/3D simplex work.
- [Gustavson and McEwan, Tiling Simplex Noise and Flow Noise](https://jcgt.org/published/0011/01/02/paper.pdf) covers explicit periodicity, rotating-gradient animation, and analytic derivatives. Its 2D simplex grid requires integer x and even-integer y periods; those constraints are specific to that algorithm, not the square-grid helper above.
- [Author implementation and license](https://github.com/stegu/psrdnoise) and [Ashima/Gustavson license](https://github.com/ashima/webgl-noise/blob/master/LICENSE): preserve their MIT copyright and permission notices if reusing substantial implementation code. Linking to the mathematical source does not make copied code original.
