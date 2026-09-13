// Shared by colour capture and ordinary/Exact OIT transparency. The depth guide
// is frozen before any alpha depth writes, so both passes make the same decision.
uniform sampler2D sssOverlayGuide;
uniform int sss_overlay;

bool isSSSOverlay(vec3 positionEye)
{
    if (sss_overlay == 0 || positionEye.z >= -0.001) return false;
    float skin_z = texelFetch(sssOverlayGuide, ivec2(gl_FragCoord.xy), 0).r;
    if (skin_z >= -0.001 || positionEye.z < skin_z) return false;
    // Limit separation along the viewing ray to 3 cm. Distant skin, clothing,
    // background and the back of the sleeve must retain ordinary transparency.
    float separation = (positionEye.z - skin_z) * length(positionEye) / -positionEye.z;
    return separation <= 0.03;
}
