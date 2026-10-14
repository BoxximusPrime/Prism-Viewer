// Cache nearby animated body and hand triangles once per frame.
layout(local_size_x=128) in;
layout(std430,binding=4) buffer Shell { vec4 shell[]; };
uniform samplerBuffer hair_mesh, hair_previous_mesh;
uniform mat4 contact_to_mesh;
uniform int mesh_node_count, contact_offset, contact_history;
uniform int contact_first=0;
vec3 hairClosestWeights(vec3 p, vec3 a, vec3 b, vec3 c);

const vec4 grid=vec4(-.6,-.6,-1.56,.06);
const int count=21*21*32;

void main()
{
    int index=contact_first+int(gl_GlobalInvocationID.x);
    if (index>=count) return;
    ivec3 cell=ivec3(index%21,(index/21)%21,index/441);
    vec3 rest=grid.xyz+vec3(cell)*grid.w;
    if (index == 0) shell[contact_offset] = grid;
    vec3 point=(contact_to_mesh*vec4(rest,1)).xyz;
    vec2 best=vec2(.24*.24);
    ivec2 nearest=ivec2(-1);
    ivec2 retained=contact_history!=0 ? ivec2(texelFetch(hair_previous_mesh,contact_offset+1+index).xy)-1 : ivec2(-1);
    vec2 retained_distance=vec2(1.0);
    // Warm-start with current geometry, so resting contacts prune the tree before its first leaf.
    for (int kind=0;kind<2;++kind)
    {
        int offset=retained[kind];
        if (offset<mesh_node_count*2 || offset+5>=contact_offset || (offset-mesh_node_count*2)%6!=0) continue;
        vec4 a=texelFetch(hair_mesh,offset), b=texelFetch(hair_mesh,offset+2), c=texelFetch(hair_mesh,offset+4);
        vec3 face=cross(b.xyz-a.xyz,c.xyz-a.xyz);
        int group=max(max(a.w,b.w),c.w)>.15 ? 1 : 0;
        if (group!=kind || dot(face,face)<1.e-16) continue;
        vec3 w=hairClosestWeights(point,a.xyz,b.xyz,c.xyz), gap=point-(a.xyz*w.x+b.xyz*w.y+c.xyz*w.z);
        retained_distance[kind]=length(gap);
        if (dot(gap,gap)<best[kind]) { best[kind]=dot(gap,gap); nearest[kind]=offset; }
    }
    int node=0, pending[32], pending_count=0, tested=0;
    // shortcut: bounded nearest search may miss a better patch; retain valid history until a local search finds it.
    for (int visited=0;visited<128 && node<mesh_node_count && tested<64;++visited)
    {
        vec4 lo=texelFetch(hair_mesh,node*2), hi=texelFetch(hair_mesh,node*2+1);
        vec3 gap=max(max(lo.xyz-point,point-hi.xyz),vec3(0));
        float distance2=dot(gap,gap);
        if ((fract(abs(lo.w))==0.0 || distance2>best.x) && (lo.w>=0.0 || distance2>best.y))
        { node=pending_count>0 ? pending[--pending_count] : mesh_node_count; continue; }
        int leaf=int(hi.w), first=leaf/8, triangles=leaf-first*8;
        if (leaf==0)
        {
            int left=node+1;
            if (left>=mesh_node_count || pending_count>=32) break;
            int right=int(abs(texelFetch(hair_mesh,left*2).w));
            if (right<=left || right>=mesh_node_count) break;
            vec3 a=max(max(texelFetch(hair_mesh,left*2).xyz-point,point-texelFetch(hair_mesh,left*2+1).xyz),vec3(0));
            vec3 b=max(max(texelFetch(hair_mesh,right*2).xyz-point,point-texelFetch(hair_mesh,right*2+1).xyz),vec3(0));
            bool left_first=dot(a,a)<=dot(b,b);
            pending[pending_count++]=left_first ? right : left;
            node=left_first ? left : right;
            continue;
        }
        if (triangles<1 || triangles>4 || tested+triangles>64) break;
        for (int i=0; i<triangles; ++i)
        {
            int offset=mesh_node_count*2+(first+i)*6;
            if (offset<mesh_node_count*2 || offset+5>=contact_offset) break;
            ++tested;
            vec4 a=texelFetch(hair_mesh,offset), b=texelFetch(hair_mesh,offset+2), c=texelFetch(hair_mesh,offset+4);
            vec3 face=cross(b.xyz-a.xyz,c.xyz-a.xyz);
            if (dot(face,face)<1.e-16 || any(greaterThan(abs(a.xyz+b.xyz+c.xyz),vec3(1.e10)))) continue;
            vec3 w=hairClosestWeights(point,a.xyz,b.xyz,c.xyz), q=a.xyz*w.x+b.xyz*w.y+c.xyz*w.z;
            distance2=dot(point-q,point-q);
            int group=max(max(a.w,b.w),c.w)>.15 ? 1 : 0;
            if (distance2<best[group]) { best[group]=distance2; nearest[group]=offset; }
        }
        node=pending_count>0 ? pending[--pending_count] : mesh_node_count;
    }
    for (int kind=0;kind<2;++kind)
    {
        // Keep contact identity through near ties; always evaluate its current animated geometry.
        if (nearest[kind]>=0 && retained_distance[kind]<=min(.24,sqrt(best[kind])+.005)) nearest[kind]=retained[kind];
    }
    shell[contact_offset+1+index]=vec4(vec2(nearest+1),0,0);
}
