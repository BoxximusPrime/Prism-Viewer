uniform mat4 modelview_projection_matrix;
uniform samplerBuffer hair_mesh;
uniform int hair_mesh_nodes;
uniform samplerBuffer hair_guides;
uniform int guide_debug;
uniform float hair_root_radius;
out vec3 shell_normal;
out vec4 guide_color;
void main()
{
    if (guide_debug!=0)
    {
        int chain=guide_debug==3 ? gl_VertexID/9 : gl_VertexID/16;
        int node=guide_debug==3 ? gl_VertexID%9 : (gl_VertexID%16)/2+(gl_VertexID&1);
        int base=chain*27+node;
        vec3 rest=texelFetch(hair_guides,base).xyz;
        vec3 p=texelFetch(hair_guides,base+9).xyz;
        bool pinned=node==0 || length(rest)<=hair_root_radius;
        bool contact=texelFetch(hair_guides,base+18).w>0.0;
        guide_color=guide_debug==1 ? vec4(.7,.7,.7,.4) :
            (pinned ? vec4(1,.8,.05,1) : (contact ? vec4(1,.15,.05,1) : vec4(0,1,1,1)));
        shell_normal=vec3(0,0,1);
        gl_Position=modelview_projection_matrix*vec4(guide_debug==1 ? rest : p,1);
        gl_PointSize=pinned ? 9.0 : 6.0;
        return;
    }
    guide_color=vec4(0);
    int offset=hair_mesh_nodes*2+gl_VertexID*2;
    vec3 p=texelFetch(hair_mesh,offset).xyz;
    shell_normal=texelFetch(hair_mesh,offset+1).xyz;
    gl_Position=modelview_projection_matrix*vec4(p,1);
}
