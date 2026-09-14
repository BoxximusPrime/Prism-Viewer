// Radix-2 inverse FFT. Two complex fields share RGBA; each axis is normalized.
uniform sampler2D waterWaveSpectrum;
uniform int water_fft_stage;
uniform int water_fft_axis;
out vec4 frag_color;

int waterReverseBits(int index, int size)
{
    int result = 0;
    for (int bit = 1; bit < size; bit *= 2)
    {
        result = result * 2 + (index & 1);
        index >>= 1;
    }
    return result;
}

void main()
{
    ivec2 pixel = ivec2(gl_FragCoord.xy);
    int index = water_fft_axis == 0 ? pixel.x : pixel.y;
    int span = 1 << water_fft_stage;
    int half_span = span / 2;
    int j = index % half_span;
    int first = (index / span) * span + j;
    int second = first + half_span;
    if (water_fft_stage == 1)
    {
        int size = textureSize(waterWaveSpectrum, 0).x;
        first = waterReverseBits(first, size);
        second = waterReverseBits(second, size);
    }
    ivec2 pa = water_fft_axis == 0 ? ivec2(first, pixel.y) : ivec2(pixel.x, first);
    ivec2 pb = water_fft_axis == 0 ? ivec2(second, pixel.y) : ivec2(pixel.x, second);
    vec4 a = texelFetch(waterWaveSpectrum, pa, 0);
    vec4 b = texelFetch(waterWaveSpectrum, pb, 0);
    float angle = 6.28318530718 * float(j) / float(span);
    vec2 w = vec2(cos(angle), sin(angle));
    vec4 rotated = vec4(b.x*w.x-b.y*w.y, b.x*w.y+b.y*w.x,
                        b.z*w.x-b.w*w.y, b.z*w.y+b.w*w.x);
    frag_color = 0.5 * (a + (index % span < half_span ? rotated : -rotated));
}
