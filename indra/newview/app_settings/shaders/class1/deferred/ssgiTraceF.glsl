// Half-resolution primary rays. Unsupported full-resolution receivers are
// traced by the composite using the same transport estimator.
out vec4 frag_color;
in vec2 vary_fragcoord;
uniform vec2 screen_res;
uniform vec2 ssgi_half_res;
vec4 traceSSGI(vec2 tc);
void main()
{
    vec2 tc = (floor(gl_FragCoord.xy) + 0.5) / ssgi_half_res;
    tc = (floor(tc * screen_res) + 0.5) / screen_res;
    frag_color = traceSSGI(tc);
}
