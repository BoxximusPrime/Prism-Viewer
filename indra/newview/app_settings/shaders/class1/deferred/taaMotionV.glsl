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
void main()
{
#ifdef HAS_SKIN
    // Keep the operation order identical to diffuseV/pbrOpaqueV for D24 equality.
    mat4 skin_view = modelview_matrix * getObjectSkinnedTransform();
    vec4 current_position = skin_view * vec4(position, 1);
    gl_Position = projection_matrix * current_position;
    vec4 old_position = vec4(previousSkinnedPosition(), 1);
#else
    gl_Position = modelview_projection_matrix * vec4(position, 1);
    vec4 old_position = vec4(position, 1);
#endif
    previous_clip = taa_previous_mvp * old_position;
    previous_depth = -(taa_previous_modelview * old_position).z;
}
