// Native-resolution HDR TAA. History is unjittered and stores linear view depth
// in alpha (negative = rejected, for diagnostics). No UI enters this history.
out vec4 frag_data[2];
#define frag_color frag_data[0]
uniform sampler2D taa_current;
uniform sampler2D taa_history;
// Remaining static-detail lifetime, two surface depths, stable background luma.
uniform sampler2D taa_detail;
uniform sampler2D taa_motion;
uniform sampler2D taa_opaque;
uniform sampler2D depthMap;
uniform mat4 taa_inv_projection;
uniform vec2 taa_rcp_res;
uniform vec2 taa_jitter;
uniform int taa_history_valid;
uniform float taa_history_weight;
uniform float taa_motion_protection;
uniform float taa_clip_gamma;
uniform float taa_transparency;
uniform int taa_static_details;

vec3 compressColor(vec3 c) { c = max(c, vec3(0)); return c / (1.0 + max(max(c.r,c.g),c.b)); }
vec3 expandColor(vec3 c) { return c / max(1.0 - max(max(c.r,c.g),c.b), 0.0001); }
vec3 toYCoCg(vec3 c) { return vec3(dot(c,vec3(.25,.5,.25)), (c.r-c.b)*.5, (-c.r+2.0*c.g-c.b)*.25); }
vec3 toRGB(vec3 c) { return vec3(c.x+c.y-c.z, c.x+c.z, c.x-c.y-c.z); }
vec3 clipBox(vec3 c, vec3 lo, vec3 hi)
{
    vec3 center = (lo+hi)*.5, extent = max((hi-lo)*.5, vec3(0.00001));
    vec3 delta = c-center;
    float scale = max(max(abs(delta.x/extent.x),abs(delta.y/extent.y)),abs(delta.z/extent.z));
    return center + delta/max(scale,1.0);
}
float viewDepth(ivec2 p, float d)
{
    if (d >= 1.0) return 0.0;
    vec4 v = taa_inv_projection * vec4((vec2(p)+.5)*taa_rcp_res*2.0-1.0,d*2.0-1.0,1);
    return min(max(-v.z/v.w, 0.001),65000.0);
}
bool sameDepth(float a, float b)
{
    return (a==0.0)==(b==0.0) && abs(a-b)<=max(.015,max(a,b)*.02);
}
void main()
{
    ivec2 size = textureSize(taa_current,0);
    vec2 uv = gl_FragCoord.xy * taa_rcp_res;
    vec2 current_uv = clamp(uv + taa_jitter, .5*taa_rcp_res, 1.0-.5*taa_rcp_res);
    ivec2 center = clamp(ivec2(current_uv*vec2(size)),ivec2(0),size-1);
    vec3 current = texture(taa_current,current_uv).rgb;
    vec3 lo = vec3(1e10), hi = vec3(-1e10), mean = vec3(0), square = vec3(0);
    float closest = 1.0, reactive = 0.0, depth_min = 1e10, depth_max = 0.0;
    ivec2 motion_pixel = center;
    bool static_detail = taa_static_details!=0;
    // Dilate closest-surface motion and reactive coverage by one pixel so a
    // rapidly moving limb owns its antialiased silhouette as well as its interior.
    for(int y=-1;y<=1;++y) for(int x=-1;x<=1;++x)
    {
        ivec2 p = clamp(center+ivec2(x,y),ivec2(0),size-1);
        vec3 raw = texelFetch(taa_current,p,0).rgb;
        vec3 c = toYCoCg(compressColor(raw));
        lo=min(lo,c); hi=max(hi,c); mean+=c; square+=c*c;
        float d = texelFetch(depthMap,p,0).r;
        if(d<closest) { closest=d; motion_pixel=p; }
        float z = viewDepth(p,d);
        depth_min=min(depth_min,z); depth_max=max(depth_max,z);
        vec3 opaque = texelFetch(taa_opaque,p,0).rgb;
        vec3 difference = abs(compressColor(raw)-compressColor(opaque));
        reactive=max(reactive,clamp(max(max(difference.r,difference.g),difference.b)*4.0*taa_transparency,0.0,1.0));
        vec4 local_motion=texelFetch(taa_motion,p,0);
        reactive=max(reactive,local_motion.a);
        static_detail=static_detail && local_motion.a<0.0 && length(local_motion.rg/taa_rcp_res)<.01;
    }
    mean/=9.0; square/=9.0;
    static_detail=static_detail && reactive<.01;
    vec2 luma_range=vec2(lo.x,hi.x);
    bool detail_sample=static_detail && depth_max>0.0 && hi.x-lo.x>.05;
    float background=mean.x<(lo.x+hi.x)*.5 ? lo.x : hi.x;
    vec4 detail=vec4(static_detail ? (detail_sample ? 8.0 : 0.0) : -1.0,depth_min,depth_max,background);
    vec3 deviation = sqrt(max(square-mean*mean,vec3(0)));
    lo=max(lo,mean-taa_clip_gamma*deviation); hi=min(hi,mean+taa_clip_gamma*deviation);
    vec4 motion=texelFetch(taa_motion,motion_pixel,0);
    vec2 history_uv=uv+motion.rg;
    // History color covers the silhouette, so its depth must follow the same
    // dilated surface that owns reprojection. Saving center depth here alternates
    // between foreground/background with jitter and rejects a stationary edge.
    float current_depth=viewDepth(motion_pixel,texelFetch(depthMap,motion_pixel,0).r);
    if (taa_history_valid==0)
    {
        frag_data[1]=detail;
        frag_color=vec4(min(max(current,vec3(0)),vec3(65000)),-current_depth);
        return;
    }
    float weight=taa_history_valid!=0 ? taa_history_weight : 0.0;
    if(any(lessThan(history_uv,.5*taa_rcp_res)) || any(greaterThan(history_uv,1.0-.5*taa_rcp_res))) weight=0.0;
    vec4 history=texture(taa_history,clamp(history_uv,.5*taa_rcp_res,1.0-.5*taa_rcp_res));
    vec4 old_detail=texelFetch(taa_detail,ivec2(gl_FragCoord.xy),0);
    // A static wire/highlight can miss a jitter sample completely. Keep its
    // accumulated coverage for at most one eight-sample cycle, provided both
    // frames contain only static surfaces, the camera is still, the surrounding
    // shading agrees, and depth belongs to the same foreground/background pair.
    // Rigged, active, flexible, untracked and reactive geometry cannot earn this
    // retention; movement continues through the strict depth/clipping path.
    bool background_agrees=min(abs(luma_range.x-old_detail.a),abs(luma_range.y-old_detail.a))<.05;
    bool known_surfaces=(sameDepth(depth_min,old_detail.g) || sameDepth(depth_min,old_detail.b)) &&
                        (sameDepth(depth_max,old_detail.g) || sameDepth(depth_max,old_detail.b));
    bool old_surface_visible=sameDepth(abs(history.a),depth_min) || sameDepth(abs(history.a),depth_max);
    bool retain_detail=static_detail && old_detail.r>=0.0 && background_agrees &&
        ((old_detail.r>0.0 && known_surfaces) || (detail_sample && old_surface_visible));
    if(retain_detail)
    {
        detail.r=detail_sample ? 8.0 : max(old_detail.r-1.0,0.0);
        if(!detail_sample) detail.gb=old_detail.gb;
        detail.a=old_detail.a;
    }
    frag_data[1]=detail;
    // Validate contributing bilinear history taps. A zero-weight neighbor on
    // another surface must not reject an otherwise stationary history sample.
    ivec2 hp=ivec2(floor(history_uv*vec2(size)-.5));
    vec2 fraction=fract(history_uv*vec2(size)-.5);
    float tolerance=max(.015,motion.b*.01);
    // Limited slope allowance; never permit a depth edge to widen validation.
    tolerance+=min(depth_max-depth_min,motion.b*.01);
    for(int y=0;y<=1;++y) for(int x=0;x<=1;++x)
    {
        vec2 tap_weight=mix(1.0-fraction,fraction,vec2(x,y));
        if(tap_weight.x*tap_weight.y<0.0001) continue;
        float old_depth=abs(texelFetch(taa_history,clamp(hp+ivec2(x,y),ivec2(0),size-1),0).a);
        if(!retain_detail && ((motion.b==0.0)!=(old_depth==0.0) || abs(old_depth-motion.b)>tolerance)) weight=0.0;
    }
    vec3 old=toYCoCg(compressColor(history.rgb));
    vec3 clipped=retain_detail ? old : clipBox(old,lo,hi);
    // Clipping alone can leave a plausible trail within a high-contrast region.
    // Reduce its lifetime as color disagreement or motion grows.
    float disagreement=length(old-clipped)/max(length(hi-lo),.02);
    float speed=length(motion.rg/taa_rcp_res);
    weight*=1.0-clamp(disagreement,0.0,1.0)*taa_motion_protection;
    weight=min(weight,mix(taa_history_weight,.50,clamp(speed/16.0,0.0,1.0)*taa_motion_protection));
    weight*=1.0-reactive;
    vec3 resolved=mix(compressColor(current),max(toRGB(clipped),vec3(0)),weight);
    frag_color=vec4(min(expandColor(resolved),vec3(65000)),weight<.05 ? -current_depth : current_depth);
}
