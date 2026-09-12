out vec4 frag_color;
uniform sampler2D taa_source;
uniform sampler2D taa_original;
uniform vec2 taa_rcp_res;
uniform vec2 taa_jitter;
uniform float taa_sharpen;
uniform int taa_copy_mode; // 0: copy; 1: resolve presentation; 2: motion; 3: rejection
void main()
{
    vec2 uv=gl_FragCoord.xy*taa_rcp_res;
    vec4 c=texture(taa_source,uv);
    if(taa_copy_mode==2)
    {
        c=texture(taa_source,uv+taa_jitter);
        frag_color=vec4(clamp(vec3(.5+c.r/taa_rcp_res.x*.04,.5+c.g/taa_rcp_res.y*.04,c.a),0.0,1.0),0);
        return;
    }
    if(taa_copy_mode==3) { frag_color=vec4(c.a<0.0 ? vec3(1,.15,.05) : vec3(.1,.55,.15),0); return; }
    if(taa_copy_mode==1)
    {
        vec3 a=texture(taa_source,uv+vec2(taa_rcp_res.x,0)).rgb;
        vec3 b=texture(taa_source,uv-vec2(taa_rcp_res.x,0)).rgb;
        vec3 d=texture(taa_source,uv+vec2(0,taa_rcp_res.y)).rgb;
        vec3 e=texture(taa_source,uv-vec2(0,taa_rcp_res.y)).rgb;
        vec3 lo=min(c.rgb,min(min(a,b),min(d,e))),hi=max(c.rgb,max(max(a,b),max(d,e)));
        // A strict neighborhood clamp erases sharpening at every local extremum
        // (thin lines, texture peaks/troughs). Allow a small, strength-scaled
        // extension of that range, while bounding halos and keeping HDR finite.
        vec3 margin=(hi-lo)*(.25*taa_sharpen);
        vec3 detail=c.rgb-(a+b+d+e)*.25;
        c.rgb=clamp(c.rgb+detail*(2.0*taa_sharpen),max(lo-margin,vec3(0)),min(hi+margin,vec3(65000)));
        c.a=texture(taa_original,uv+taa_jitter).a;
    }
    frag_color=c;
}
