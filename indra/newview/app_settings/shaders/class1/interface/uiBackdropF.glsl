// Composite only inside the panel, keeping its border and children sharp.
uniform sampler2D diffuseMap;
uniform vec4 capture_rect; // framebuffer pixels: left, bottom, width, height
uniform vec2 blur_uv_scale;
uniform vec2 panel_size; // UI pixels, independent of display scale
uniform float corner_radius;
in vec2 vary_texcoord0;
in vec4 vertex_color;
out vec4 frag_color;

void main()
{
    vec2 half_size = panel_size * 0.5;
    float radius = min(corner_radius, min(half_size.x, half_size.y));
    vec2 q = abs((vary_texcoord0 - 0.5) * panel_size) - half_size + radius;
    float distance = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - radius;
    float coverage = 1.0 - smoothstep(-fwidth(distance), 0.0, distance);
    vec2 uv = (gl_FragCoord.xy - capture_rect.xy) / capture_rect.zw * blur_uv_scale;
    vec2 half_texel = 0.5 / vec2(textureSize(diffuseMap, 0));
    uv = clamp(uv, half_texel, blur_uv_scale - half_texel);
    frag_color = vec4(texture(diffuseMap, uv).rgb, coverage * vertex_color.a);
}
