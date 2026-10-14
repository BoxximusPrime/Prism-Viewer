// Cache topology once; skin the current pose and refit its BVH from leaves to root.
layout(local_size_x = 128) in;
layout(std430, binding = 4) buffer Shell { vec4 shell[]; };
uniform int mesh_node_count;
#ifdef MESH_SKIN
struct Vertex { vec4 position; vec4 normal; vec4 weights; uvec4 joints; };
layout(std430, binding = 0) readonly buffer Source { Vertex vertices[]; };
layout(std430, binding = 3) readonly buffer Palette { vec4 palette[]; };
uniform int mesh_vertex_count;
uniform float mesh_padding;
mat3x4 joint(uint i) { return mat3x4(palette[i*3u], palette[i*3u+1u], palette[i*3u+2u]); }
#else
layout(std430, binding = 1) readonly buffer Topology { uvec4 nodes[]; };
layout(std430, binding = 2) readonly buffer Levels { uint levels[]; };
uniform int mesh_level_first, mesh_level_count;
#endif
void main()
{
    uint index = gl_GlobalInvocationID.x;
#ifdef MESH_SKIN
    if (index >= uint(mesh_vertex_count)) return;
    Vertex v = vertices[index];
    mat3x4 m = joint(v.joints.x)*v.weights.x + joint(v.joints.y)*v.weights.y +
                joint(v.joints.z)*v.weights.z + joint(v.joints.w)*v.weights.w;
    vec3 p = mat3(m)*v.position.xyz + vec3(m[0].w,m[1].w,m[2].w);
    vec3 n = vec3(0);
    if (abs(determinant(mat3(m))) > 1.e-12) n = transpose(inverse(mat3(m)))*v.normal.xyz;
    if (any(isnan(p)) || any(isinf(p))) { p=vec3(1.e20); n=vec3(0); }
    if (any(isnan(n)) || any(isinf(n))) n=vec3(0);
    if (length(n) > 1.e-8) p += normalize(n) * clamp(mesh_padding, 0.0, 0.1);
    uint offset = uint(mesh_node_count)*2u + index*2u;
    shell[offset] = vec4(p,v.normal.w);
    shell[offset+1u] = vec4(n,0);
#else
    if (index >= uint(mesh_level_count)) return;
    uint id = levels[uint(mesh_level_first)+index];
    uvec4 node = nodes[id];
    vec3 lo = vec3(1.e30), hi = vec3(-1.e30);
    bool hand = false, body = false;
    if (node.y != 0u)
    {
        for (uint i=0u; i<node.y; ++i)
        {
            uint offset=uint(mesh_node_count)*2u+(node.x+i)*6u;
            vec4 a=shell[offset], b=shell[offset+2u], c=shell[offset+4u];
            bool moving_hand=max(max(a.w,b.w),c.w)>.15;
            hand=hand || moving_hand; body=body || !moving_hand;
            lo=min(lo,min(a.xyz,min(b.xyz,c.xyz))); hi=max(hi,max(a.xyz,max(b.xyz,c.xyz)));
        }
    }
    else
    {
        lo=min(shell[node.x*2u].xyz, shell[node.w*2u].xyz);
        hi=max(shell[node.x*2u+1u].xyz, shell[node.w*2u+1u].xyz);
        hand = shell[node.x*2u].w < 0.0 || shell[node.w*2u].w < 0.0;
        body = fract(abs(shell[node.x*2u].w)) > 0.0 || fract(abs(shell[node.w*2u].w)) > 0.0;
    }
    // Sign marks hands, half-texel marks body; escape integer remains exact under the triangle limit.
    float escape=float(node.z)+(body ? .5 : 0.0);
    shell[id*2u]=vec4(lo,hand ? -escape : escape);
    shell[id*2u+1u]=vec4(hi,node.y!=0u ? float(node.x*8u+node.y) : 0.0);
#endif
}
