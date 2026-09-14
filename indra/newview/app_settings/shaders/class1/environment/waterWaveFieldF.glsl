// Dense directional height spectra. RG/BA are complex swell/chop coefficients.
// The inverse FFT and resolve passes produce the surface slopes used for lighting.
uniform float water_wave_time;
uniform float water_cross_swell;
uniform float water_wave_scale;
out vec4 frag_color;

uint waterHash(uint value)
{
    value ^= value >> 16;
    value *= 0x7feb352du;
    value ^= value >> 15;
    value *= 0x846ca68bu;
    return value ^ (value >> 16);
}

vec2 waterGaussian(ivec2 index, uint seed)
{
    uint key = uint(index.x) + uint(index.y) * 256u + seed;
    float u = (float(waterHash(key) & 0x00ffffffu) + 0.5) / 16777216.0;
    float v = (float(waterHash(key + 19349663u) & 0x00ffffffu) + 0.5) / 16777216.0;
    float radius = sqrt(-2.0 * log(u));
    return radius * vec2(cos(6.28318530718 * v), sin(6.28318530718 * v));
}

vec2 waterInitialSpectrum(ivec2 index, int band)
{
    // DC and self-conjugate Nyquist rows contain no wave energy.
    if (all(equal(index, ivec2(0))) || index.x == 128 || index.y == 128)
        return vec2(0.0);
    ivec2 frequency = ivec2(index.x < 128 ? index.x : index.x - 256,
                           index.y < 128 ? index.y : index.y - 256);
    float length_m = band == 0 ? 256.0 : 64.0;
    vec2 kvec = 6.28318530718 * vec2(frequency) / length_m;
    float k = length(kvec);
    // Keep the spectrum in reference metres. The surface scales its sampling
    // domain (and implicitly wave heights) together, preserving resolved slopes
    // even at 0.01 size instead of pushing energy past the FFT's Nyquist limit.
    float peak_length = band == 0 ? 14.4 : 1.92;
    float spread = band == 0 ? 0.40 : 0.65;
    float angle = atan(kvec.y, kvec.x);
    float directional = exp(-0.5 * pow(angle / spread, 2.0));
    if (band == 0)
        directional += water_cross_swell * water_cross_swell *
                       exp(-0.5 * pow((angle - 1.05) / 0.30, 2.0));
    float log_frequency = log(k * peak_length / 6.28318530718) / 0.48;
    float power = exp(-0.5 * log_frequency * log_frequency) * directional;
    // Normalization for a 256-square IFFT: expected RMS slopes .13/.08.
    // The k^-4 power factor controls energy per log-wavenumber interval.
    float normalization = band == 0 ? 95.19036 : 183.84053;
    return waterGaussian(index, band == 0 ? 937u : 185u) *
           (normalization * sqrt(power) / (k*k));
}

vec2 waterEvolveSpectrum(ivec2 index, int band)
{
    vec2 a = waterInitialSpectrum(index, band);
    vec2 b = waterInitialSpectrum((-index) & ivec2(255), band);
    b.y = -b.y;
    ivec2 frequency = ivec2(index.x < 128 ? index.x : index.x - 256,
                           index.y < 128 ? index.y : index.y - 256);
    float k = 6.28318530718 * length(vec2(frequency)) / (band == 0 ? 256.0 : 64.0);
    // Dispersion uses physical metres: smaller waves have faster oscillations
    // but a slower crest travel speed. Resolve still uses reference metres.
    k /= clamp(water_wave_scale, 0.01, 2.0);
    // Quantize dispersion to a seamless 20-minute cycle. CPU time wrapping
    // avoids float phase jitter during long sessions without a visible reset.
    float omega = floor(sqrt(9.81 * k) * 1200.0 / 6.28318530718 + 0.5) * 6.28318530718 / 1200.0;
    float phase = omega * water_wave_time;
    float c = cos(phase), s = sin(phase);
    return vec2(a.x*c + a.y*s, a.y*c - a.x*s) +
           vec2(b.x*c - b.y*s, b.y*c + b.x*s);
}

void main()
{
    ivec2 index = ivec2(gl_FragCoord.xy);
    frag_color = vec4(waterEvolveSpectrum(index, 0), waterEvolveSpectrum(index, 1));
}
