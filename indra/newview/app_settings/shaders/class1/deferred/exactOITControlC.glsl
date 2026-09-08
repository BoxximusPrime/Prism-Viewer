/** GPU counter reset, exact list-depth reduction, and indirect draw preparation. */

layout(local_size_x = 16, local_size_y = 16) in;
layout(binding = 1, r32ui) uniform readonly uimage2D oitListCounts;
layout(std430, binding = 1) buffer OITControl
{
    uint oitNodeCount;
    uint oitNodeCapacity;
    uint oitOverflow;
    uint oitMaximumList;
};
layout(std430, binding = 4) writeonly buffer OITCommands
{
    // 26 sort passes cover the 2 GiB / 32-byte node limit; entry 26 blends.
    uvec4 commands[27];
};
uniform int oitControlPass; // 0 reset, 1 reduce counts, 2 prepare draws
uniform int oitCapacity;
shared uint groupMaximum;

void main()
{
    uint lane = gl_LocalInvocationIndex;
    if (oitControlPass == 0)
    {
        if (lane == 0u)
        {
            oitNodeCount = 0u;
            oitNodeCapacity = uint(oitCapacity);
            oitOverflow = 0u;
            oitMaximumList = 0u;
        }
        return;
    }
    if (oitControlPass == 2)
    {
        if (lane == 0u)
        {
            bool valid = oitOverflow == 0u && oitNodeCount <= oitNodeCapacity;
            for (uint pass = 0u; pass < 26u; ++pass)
            {
                commands[pass] = uvec4(valid && (1u << pass) < oitMaximumList ? 3u : 0u,
                                       1u, 0u, 0u);
            }
            commands[26] = uvec4(valid ? 3u : 0u, 1u, 0u, 0u);
        }
        return;
    }

    if (lane == 0u) groupMaximum = 0u;
    barrier();
    ivec2 pixel = ivec2(gl_GlobalInvocationID.xy);
    if (all(lessThan(pixel, imageSize(oitListCounts))))
    {
        atomicMax(groupMaximum, imageLoad(oitListCounts, pixel).r);
    }
    barrier();
    if (lane == 0u && groupMaximum != 0u)
    {
        atomicMax(oitMaximumList, groupMaximum);
    }
}
