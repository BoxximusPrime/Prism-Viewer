/** An exact predicate for same-frame vanilla fallback. No early fragment tests:
 * discarded fragments must not contribute to the occlusion query. */
layout(std430, binding = 1) readonly buffer OITControl
{
    uint oitNodeCount;
    uint oitNodeCapacity;
    uint oitOverflow;
    uint oitMaximumList;
};
out vec4 frag_color;
void main()
{
    if (oitOverflow == 0u && oitNodeCount <= oitNodeCapacity) discard;
    frag_color = vec4(0.0);
}
