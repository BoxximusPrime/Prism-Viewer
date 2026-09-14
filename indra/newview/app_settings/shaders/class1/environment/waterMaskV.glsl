uniform mat4 modelview_projection_matrix;
uniform vec4 color;
in vec3 position;
out vec4 vertex_color;
out vec4 vertex_position;
vec3 waterDisplacedPosition(vec3 position);

void main()
{
    vertex_position = modelview_projection_matrix * vec4(waterDisplacedPosition(position), 1.0);
    gl_Position = vertex_position;
    vertex_color = color;
}
