// Rope displacement shared by colour, depth, shadow and motion passes.
uniform mat4 hair_local_from_model;
uniform mat4 hair_model_from_local;
uniform float hair_root_radius;
uniform samplerBuffer hair_guides;
uniform int hair_guide_active;

vec3 hairGuidePosition(vec3 position, mat4 local_from_model, mat4 model_from_local,
    float radius, samplerBuffer guides)
{
    if (radius<=0.0) return position;
    vec3 local=(local_from_model*vec4(position,1)).xyz;
    if (length(local)<=radius) return position;
    int count=int(texelFetch(guides,0).w);
    if (count<4 || count>64) return position;
    float sector=mod(atan(local.y,local.x)*(float(count)/6.283185307)+float(count),float(count));
    float depth=max(-texelFetch(guides,8).z,.01);
    float along=clamp(-local.z/depth*8.0,0.0,8.0);
    int node=min(int(along),7);
    float t=along-float(node);
    vec3 movement=vec3(0);
    for (int side=0;side<2;++side)
    {
        int base=((int(sector)+side)%count)*27+node;
        float w=side==0 ? 1.0-fract(sector) : fract(sector);
        vec3 a=texelFetch(guides,base).xyz, b=texelFetch(guides,base+1).xyz;
        vec3 p=texelFetch(guides,base+9).xyz, q=texelFetch(guides,base+10).xyz;
        movement+=w*mix(p-a,q-b,t);
    }
    // Root mobility is already solved; fading again would lose collision clearance.
    return (model_from_local*vec4(local+movement,1)).xyz;
}

vec3 getHairDeformedPosition(vec3 position)
{
    return hair_guide_active!=0 ? hairGuidePosition(position,hair_local_from_model,
        hair_model_from_local,hair_root_radius,hair_guides) : position;
}

mat4 getHairSkinnedTransform(mat4 skin, vec3 position)
{
    if (hair_root_radius<=0.0 || hair_guide_active==0) return skin;
    vec3 skinned=(skin*vec4(position,1)).xyz;
    vec3 deformed=getHairDeformedPosition(skinned);
    // Preserve the authored shading basis after ordinary skinning.
    mat4 result=skin;
    result[3]=skin[3]+vec4(deformed-skinned,0.0);
    return result;
}
