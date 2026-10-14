in vec3 shell_normal;
in vec4 guide_color;
out vec4 frag_color;
void main()
{
    float shade=.5+.5*abs(dot(normalize(shell_normal),normalize(vec3(.3,.4,1))));
    frag_color=guide_color.a>0.0 ? guide_color : vec4(vec3(.25,.04,.45)*shade,.3);
}
