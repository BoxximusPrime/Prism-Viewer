// Convert the two real height fields into additive, mip-filterable slopes.
uniform sampler2D waterWaveSpectrum;
out vec4 frag_color;
uniform int water_wave_resolve_height;

vec2 waterHeightAt(ivec2 pixel)
{
    return texelFetch(waterWaveSpectrum, pixel & ivec2(255), 0).xz;
}

void main()
{
    ivec2 p = ivec2(gl_FragCoord.xy);
    if (water_wave_resolve_height != 0)
    {
        frag_color = vec4(waterHeightAt(p), 0.0, 0.0);
        return;
    }
    vec2 texel_metres = vec2(256.0, 64.0) / 256.0;
    vec2 dx = -(waterHeightAt(p + ivec2(1,0)) - waterHeightAt(p - ivec2(1,0))) / (2.0 * texel_metres);
    vec2 dy = -(waterHeightAt(p + ivec2(0,1)) - waterHeightAt(p - ivec2(0,1))) / (2.0 * texel_metres);
    frag_color = vec4(dx.x, dy.x, dx.y, dy.y);
}
