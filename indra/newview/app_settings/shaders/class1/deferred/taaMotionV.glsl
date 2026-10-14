// TAA geometry motion. Previous skinning is evaluated at the current mesh vertex;
// a root transform alone cannot describe a dancing avatar's arms and legs.
uniform mat4 modelview_projection_matrix;
uniform mat4 modelview_matrix;
uniform mat4 projection_matrix;
uniform mat4 taa_previous_mvp;
uniform mat4 taa_previous_modelview;
in vec3 position;
out vec4 previous_clip;
out float previous_depth;
#ifdef HAS_SKIN
mat4 getObjectSkinnedTransform();
in vec4 weight4;
uniform mat3x4 taa_previous_palette[MAX_JOINTS_PER_MESH_OBJECT];
vec3 previousSkinnedPosition()
{
    ivec4 index = ivec4(clamp(floor(weight4), vec4(0), vec4(MAX_JOINTS_PER_MESH_OBJECT-1)));
    vec4 weights = fract(weight4);
    weights /= max(dot(weights, vec4(1)), 0.00001);
    mat3x4 skin = taa_previous_palette[index.x] * weights.x +
                 taa_previous_palette[index.y] * weights.y +
                 taa_previous_palette[index.z] * weights.z +
                 taa_previous_palette[index.w] * weights.w;
    return mat3(skin) * position + vec3(skin[0].w, skin[1].w, skin[2].w);
}
#endif
uniform mat4 hair_previous_local_from_model;
uniform mat4 hair_previous_model_from_local;
uniform float hair_previous_root_radius;
uniform samplerBuffer hair_previous_guides;
uniform int hair_previous_guide_active;
uniform int hair_previous_guide_bind;
#ifdef HAS_SKIN
mat4 hairGuideSkin(samplerBuffer guides, int offset, vec4 encoded);
#endif
vec3 hairGuidePosition(vec3 position, mat4 local_from_model, mat4 model_from_local,
    float radius, samplerBuffer guides);
mat4 getHairSkinnedTransform(mat4 skin, vec3 position);
vec3 getHairDeformedPosition(vec3 position);
void main()
{
#ifdef HAS_SKIN
    // Keep the operation order identical to diffuseV/pbrOpaqueV for D24 equality.
    mat4 skin_view = modelview_matrix * getHairSkinnedTransform(getObjectSkinnedTransform(), position);
    vec4 current_position = skin_view * vec4(position, 1);
    gl_Position = projection_matrix * current_position;
    vec4 old_position = vec4(previousSkinnedPosition(), 1);
#else
    gl_Position = modelview_projection_matrix * vec4(getHairDeformedPosition(position), 1);
    vec4 old_position = vec4(position, 1);
#endif
    if (hair_previous_guide_active!=0)
    {
#ifdef HAS_SKIN
        if (hair_previous_root_radius>0.0 && hair_previous_guide_bind>0)
            old_position=hair_previous_model_from_local*hairGuideSkin(hair_previous_guides,hair_previous_guide_bind,weight4)*vec4(position,1);
#endif
        old_position.xyz=hairGuidePosition(old_position.xyz,hair_previous_local_from_model,
            hair_previous_model_from_local,hair_previous_root_radius,hair_previous_guides);
    }
    previous_clip = taa_previous_mvp * old_position;
    previous_depth = -(taa_previous_modelview * old_position).z;
}
