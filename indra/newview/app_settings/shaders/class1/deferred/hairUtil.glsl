// SPDX-License-Identifier: LGPL-2.1-only
// Shared card/mesh hair response for deferred and forward lighting.
uniform float hair_object;
uniform float hair_direction;
uniform vec4 hair_params; // roughness, highlight strength, transmission, optical thickness
uniform vec3 hair_flow; // automatic direction, detection scale in texels, spatial smoothing
uniform vec3 hair_detail; // enabled strength, detail scale in texels, broad-shading rejection
uniform float hair_variation_strength;
uniform float hair_brightness_compensation;
uniform int hair_debug; // 0 lighting, 1 direction, 2 confidence

vec4 encodeNormal(vec3 n, float env, float flag);

vec3 hairSafeNormalize(vec3 v, vec3 fallback)
{
    // Derivative tangents shrink with resolution and zoom; their length is not degeneracy.
    float scale = max(abs(v.x), max(abs(v.y), abs(v.z)));
    if (scale == 0.0) return fallback;
    v /= scale;
    return v * inversesqrt(dot(v, v));
}

vec3 hairBasis(vec3 n)
{
    return normalize(cross(abs(n.z) < 0.999 ? vec3(0,0,1) : vec3(0,1,0), n));
}

vec3 hairSmoothDirection(vec3 direction, vec3 dx, vec3 dy, vec3 n, vec3 fallback)
{
    vec3 face = hairSafeNormalize(cross(dx, dy), n);
    face *= dot(face, n) < 0.0 ? -1.0 : 1.0;
    // Rotate the triangle frame onto the smooth surface without shearing strand angles.
    direction -= (face + n) * (dot(direction, n) / (1.0 + dot(face, n)));
    return hairSafeNormalize(direction - n * dot(n, direction), fallback);
}

// Call before discards, while the derivative quad is intact.
vec3 hairDirectionVector(vec3 pos, vec2 uv, vec3 n, vec2 axis)
{
    vec3 dx = dFdx(pos), dy = dFdy(pos);
    vec2 ux = dFdx(uv), uy = dFdy(uv);
    float determinant = ux.x * uy.y - ux.y * uy.x;
    vec3 u = dx * uy.y - dy * ux.y;
    vec3 v = dy * ux.x - dx * uy.x;
    vec3 t = (axis.x * u + axis.y * v) * sign(determinant);
    return hairSmoothDirection(t, dx, dy, n, hairBasis(n));
}

vec3 hairTangent(vec3 pos, vec2 uv, vec3 n)
{
    return hairDirectionVector(pos, uv, n, vec2(sin(hair_direction), cos(hair_direction)));
}

// Samples are untinted diffuse texels at -step, +step, -4*step and +4*step.
// Call before discards, only when no authored normal/bump map exists.
vec3 hairDetailNormal(mat3 frame, vec3 n, vec2 axis, float footprint, vec4 center,
    vec4 nearL, vec4 nearR, vec4 farL, vec4 farR)
{
    const vec3 luminance = vec3(0.2126, 0.7152, 0.0722);
    vec4 h = log(max(vec4(dot(nearL.rgb, luminance), dot(nearR.rgb, luminance),
        dot(farL.rgb, luminance), dot(farR.rgb, luminance)), vec4(0.02)));
    // Subtract the broad slope so painted lighting contributes less than strand detail.
    float slope = (h.y - h.x) - 0.25 * hair_detail.z * (h.w - h.z);
    float coverage = min(center.a, min(min(nearL.a, nearR.a), min(farL.a, farR.a)));
    float strength = smoothstep(0.1, 0.8, coverage) / (1.0 + 0.25 * footprint * footprint);
    vec3 across = frame[0] * axis.y - frame[1] * axis.x;
    across = hairSafeNormalize(across - n * dot(n, across), vec3(0));
    return normalize(n - across * clamp(hair_detail.x * slope, -0.5, 0.5) * strength);
}

vec3 hairTensor(vec2 g)
{
    return vec3(g.x * g.x, g.y * g.y, g.x * g.y);
}

// Return a UV-space line axis and confidence; gradients are measured on a 3x3 stencil.
vec3 hairFlowAxis(vec4 row0, vec4 row1, vec4 row2, vec2 stepUV, vec2 fallback)
{
    vec3 central = hairTensor(0.5 * vec2(row1.z - row1.x, row2.y - row0.y));
    vec3 averaged = 0.25 * (
        hairTensor(0.5 * vec2(row0.y-row0.x+row1.y-row1.x, row1.x-row0.x+row1.y-row0.y)) +
        hairTensor(0.5 * vec2(row0.z-row0.y+row1.z-row1.y, row1.y-row0.y+row1.z-row0.z)) +
        hairTensor(0.5 * vec2(row1.y-row1.x+row2.y-row2.x, row2.x-row1.x+row2.y-row1.y)) +
        hairTensor(0.5 * vec2(row1.z-row1.y+row2.z-row2.y, row2.y-row1.y+row2.z-row1.z)));
    vec3 j = mix(central, averaged, hair_flow.z);
    vec2 orientation = vec2(j.x - j.y, 2.0 * j.z);
    float anisotropy = length(orientation);
    float energy = j.x + j.y;
    float confidence = smoothstep(0.2, 0.8, anisotropy / max(energy, 1e-8)) *
        smoothstep(0.0004, 0.01, energy) * min(row0.w, min(row1.w, row2.w));
    if (confidence <= 0.0) return vec3(fallback, 0.0);
    float angle = 0.5 * atan(orientation.y, orientation.x);
    vec2 axis = normalize(vec2(-sin(angle), cos(angle)) * stepUV);
    // Line orientations are pi-periodic: blend double angles so opposite signs agree.
    vec2 a = vec2(axis.x*axis.x-axis.y*axis.y, 2.0*axis.x*axis.y);
    vec2 b = vec2(fallback.x*fallback.x-fallback.y*fallback.y, 2.0*fallback.x*fallback.y);
    vec2 blended = mix(b, a, confidence);
    if (dot(blended, blended) < 1e-8) return vec3(fallback, confidence);
    angle = 0.5 * atan(blended.y, blended.x);
    return vec3(cos(angle), sin(angle), confidence);
}

// Each surface shader supplies its own indexed/non-indexed diffuse lookup.
vec4 hairDiffuseLookup(vec2 uv);
vec2 hairTextureSize();

vec2 hairFlowSample(vec2 uv)
{
    vec4 c = hairDiffuseLookup(uv);
    return vec2(log(max(dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)), 0.02)),
        smoothstep(0.1, 0.8, c.a));
}

// Transform sampled texture directions through the interpolated mesh frame.
mat3 hairMeshFrame(vec3 pos, vec2 uv, vec2 meshUV, vec3 n, vec4 tangent)
{
    n = normalize(n);
    vec2 dx = dFdx(uv), dy = dFdy(uv);
    vec2 mx = dFdx(meshUV), my = dFdy(meshUV);
    float det = dx.x * dy.y - dx.y * dy.x;
    if (det == 0.0) return mat3(vec3(0), vec3(0), n);
    if (dot(tangent.xyz, tangent.xyz) > 0.0 && abs(tangent.w) > 0.5 && det != 0.0)
    {
        vec3 t = hairSafeNormalize(tangent.xyz - n * dot(n, tangent.xyz), hairBasis(n));
        vec3 b = cross(n, t) * sign(tangent.w);
        vec2 u = (mx * dy.y - my * dx.y) * sign(det);
        vec2 v = (my * dx.x - mx * dy.x) * sign(det);
        float scale = max(max(abs(u.x), abs(u.y)), max(abs(v.x), abs(v.y)));
        if (scale > 0.0) return mat3((t*u.x+b*u.y)/scale, (t*v.x+b*v.y)/scale, n);
    }
    return mat3(hairDirectionVector(pos, uv, n, vec2(1,0)),
                hairDirectionVector(pos, uv, n, vec2(0,1)), n);
}

mat3 hairVertexFrame();

float hairStrandVariation(vec4 center, vec4 alongL, vec4 alongR, vec4 acrossL, vec4 acrossR, float footprint)
{
    const vec3 luminance = vec3(0.2126, 0.7152, 0.0722);
    vec4 h = log(max(vec4(dot(alongL.rgb, luminance), dot(alongR.rgb, luminance),
        dot(acrossL.rgb, luminance), dot(acrossR.rgb, luminance)), vec4(0.02)));
    float strand = 0.5 * log(max(dot(center.rgb, luminance), 0.02)) + 0.25 * (h.x + h.y);
    float coverage = min(center.a, min(min(alongL.a, alongR.a), min(acrossL.a, acrossR.a)));
    // Symmetric local contrast rejects painted gradients; along-strand averaging steadies the finish.
    return 0.5 + 0.5 * clamp(2.0 * (strand - 0.5 * (h.z + h.w)), -1.0, 1.0) *
        smoothstep(0.1, 0.8, coverage) / (1.0 + 0.25 * footprint * footprint);
}

vec3 hairSurface(vec3 pos, vec2 uv, inout vec3 n, vec4 center, bool generateNormal, out vec3 preview, out float variation)
{
    vec2 axis = vec2(sin(hair_direction), cos(hair_direction));
    preview = vec3(0);
    variation = 0.5;
    if (hair_object <= 0.5) return hairDirectionVector(pos, uv, n, axis);
    mat3 frame = hairVertexFrame();
    vec2 texel = 1.0 / max(hairTextureSize(), vec2(1));
    vec2 footprint = max(abs(dFdx(uv)), abs(dFdy(uv)));
    float confidence = 0.0;
    if (hair_flow.x > 0.5 || hair_debug != 0)
    {
        vec2 stepUV = max(texel * hair_flow.y, footprint);
        vec2 a = hairFlowSample(uv + stepUV * vec2(-1,-1));
        vec2 b = hairFlowSample(uv + stepUV * vec2( 0,-1));
        vec2 c = hairFlowSample(uv + stepUV * vec2( 1,-1));
        vec2 d = hairFlowSample(uv + stepUV * vec2(-1, 0));
        vec2 e = vec2(log(max(dot(center.rgb, vec3(0.2126, 0.7152, 0.0722)), 0.02)), smoothstep(0.1,0.8,center.a));
        vec2 f = hairFlowSample(uv + stepUV * vec2( 1, 0));
        vec2 g = hairFlowSample(uv + stepUV * vec2(-1, 1));
        vec2 h = hairFlowSample(uv + stepUV * vec2( 0, 1));
        vec2 i = hairFlowSample(uv + stepUV * vec2( 1, 1));
        vec3 flow = hairFlowAxis(vec4(a.x,b.x,c.x,min(a.y,min(b.y,c.y))),
            vec4(d.x,e.x,f.x,min(d.y,min(e.y,f.y))), vec4(g.x,h.x,i.x,min(g.y,min(h.y,i.y))), stepUV, axis);
        confidence = flow.z;
        if (hair_flow.x > 0.5) axis = flow.xy;
    }
    vec2 across = vec2(axis.y, -axis.x);
    if (hair_variation_strength > 0.0)
    {
        vec2 along = axis * max(2.0 * length(axis * texel), length(axis * footprint));
        vec2 span = across * max(4.0 * length(across * texel), length(across * footprint));
        variation = hairStrandVariation(center, hairDiffuseLookup(uv-along), hairDiffuseLookup(uv+along),
            hairDiffuseLookup(uv-span), hairDiffuseLookup(uv+span), max(footprint.x / texel.x, footprint.y / texel.y));
    }
    if (generateNormal && hair_detail.x > 0.0)
    {
        float radius = max(length(across * texel) * hair_detail.y, length(across * footprint));
        vec2 offset = across * radius;
        float pixels = max(footprint.x / texel.x, footprint.y / texel.y) / max(hair_detail.y, 0.25);
        n = hairDetailNormal(frame, n, axis, pixels, center,
            hairDiffuseLookup(uv-offset), hairDiffuseLookup(uv+offset),
            hairDiffuseLookup(uv-4.0*offset), hairDiffuseLookup(uv+4.0*offset));
    }
    float angle = atan(axis.y, axis.x);
    preview = hair_debug == 2 ? vec3(confidence) :
        (0.5 + 0.5 * cos(2.0 * angle + vec3(0, 2.0943951, 4.1887902))) * mix(0.25, 1.0, confidence);
    vec3 strand = frame[0] * axis.x + frame[1] * axis.y;
    return hairSafeNormalize(strand - n * dot(n, strand), hairBasis(n));
}

vec4 encodeHairNormal(vec3 n, float env, float flag, vec3 tangent)
{
    vec4 result = encodeNormal(n, env, flag);
    if (hair_object > 0.5)
    {
        vec3 b = hairBasis(n);
        vec3 t = hairSafeNormalize(tangent - n * dot(n, tangent), b);
        // Hair reuses legacy environment intensity for its tangent angle; no extra G-buffer.
        result.z = atan(dot(t, cross(n, b)), dot(t, b)) / 6.28318530718 + 0.5;
        result.w = flag - 0.12 + 0.04 * GBUFFER_AVATAR_FLAG(result.w);
    }
    return result;
}

vec3 decodeHairTangent(vec3 n, float angle)
{
    vec3 b = hairBasis(n);
    float a = (angle - 0.5) * 6.28318530718;
    return b * cos(a) + cross(n, b) * sin(a);
}

float hairLobe(vec3 t, vec3 n, vec3 h, float shift, float roughness)
{
    vec3 shifted = normalize(t + n * shift);
    float th = clamp(dot(shifted, h), -1.0, 1.0);
    float exponent = max(2.0 / (roughness * roughness) - 2.0, 1.0);
    float lobe = pow(max(1.0 - th * th, 0.0), 0.5 * exponent);
    if (hair_flow.x > 0.5)
    {
        // Texture flow identifies an axis, not root/tip polarity; keep both signs equivalent.
        float reverse = clamp(dot(normalize(t - n * shift), h), -1.0, 1.0);
        lobe = 0.5 * (lobe + pow(max(1.0 - reverse * reverse, 0.0), 0.5 * exponent));
    }
    // A strand highlight is a one-dimensional band, not a two-dimensional Phong spot.
    return sqrt((exponent + 2.0) / 6.28318530718) * lobe;
}

vec3 hairDiffuseVisibility(vec3 base, vec3 n, vec3 t, vec3 v, vec3 l, float surface, float transmission)
{
    n *= dot(n, v) < 0.0 ? -1.0 : 1.0;
    float tl = clamp(dot(t, l), -1.0, 1.0);
    float cylinder = sqrt(max(1.0 - tl * tl, 0.0));
    float nl = dot(n, l);
    float wrap = clamp((nl + 0.35) / 1.35, 0.0, 1.0);
    float tv = clamp(dot(t, v), -1.0, 1.0);
    float viewCylinder = sqrt(max(1.0 - tv * tv, 0.0));
    float azimuth = clamp((dot(l, v) - tl * tv) / max(cylinder * viewCylinder, 0.001), -1.0, 1.0);
    float forward = pow(0.5 - 0.5 * azimuth, 2.0) * exp(-4.0 * (tl + tv) * (tl + tv));
    // shortcut: texture colour proxies fiber absorption; replace with authored pigment when available.
    vec3 transmitted = pow(clamp(base, vec3(0), vec3(1)),
        vec3(hair_params.w / max(cylinder * viewCylinder, 0.35)));
    vec3 scattered = 0.5 * transmitted * transmitted / (vec3(1) - 0.5 * transmitted);
    float amount = clamp(hair_params.z, 0.0, 1.0);
    vec3 diffuse = (1.0 - 0.25 * amount) * base * wrap;
    vec3 internal = 0.75 * transmitted * forward * (1.0 - wrap) +
        0.25 * scattered * (0.35 + 0.65 * wrap);
    return 0.9 * cylinder * (diffuse * surface + amount * internal * transmission);
}

vec3 hairDiffuse(vec3 base, vec3 n, vec3 t, vec3 v, vec3 l)
{
    return hairDiffuseVisibility(base, n, t, v, l, 1.0, 1.0);
}

vec3 hairDirectVisibility(vec3 base, vec3 n, vec3 t, vec3 v, vec3 l, float variation, float surface, float transmission)
{
    n *= dot(n, v) < 0.0 ? -1.0 : 1.0;
    t = hairSafeNormalize(t - n * dot(n, t), hairBasis(n));
    vec3 h = hairSafeNormalize(l + v, n);
    float roughness = clamp(hair_params.x * (1.0 + 0.3 * clamp(hair_variation_strength, 0.0, 2.0) *
        (2.0 * clamp(variation, 0.0, 1.0) - 1.0)), 0.12, 1.0);
    float fresnel = 0.046 + 0.954 * pow(1.0 - max(dot(v, h), 0.0), 5.0);
    float visibility = sqrt(max(1.0 - pow(clamp(dot(t, l), -1.0, 1.0), 2.0), 0.0)) *
        clamp((dot(n, l) + 0.25) / 1.25, 0.0, 1.0);
    vec3 specular = fresnel * hair_params.y * visibility *
        (vec3(0.7 * hairLobe(t, n, h, 0.08, roughness)) +
         0.3 * sqrt(clamp(base, vec3(0.0), vec3(1.0))) *
         hairLobe(t, n, h, -0.16, min(roughness * 1.5, 1.0)));
    // Artistic contrast compensation, anchored to 18% linear grey; never follows scene lighting.
    float brightness = dot(clamp(base, vec3(0), vec3(1)), vec3(0.2126, 0.7152, 0.0722));
    specular *= pow(clamp(sqrt(brightness / 0.18), 0.25, 2.0), clamp(hair_brightness_compensation, 0.0, 4.0));
    return hairDiffuseVisibility(base, n, t, v, l, surface, transmission) + specular * surface;
}

vec3 hairDirect(vec3 base, vec3 n, vec3 t, vec3 v, vec3 l, float variation)
{
    return hairDirectVisibility(base, n, t, v, l, variation, 1.0, 1.0);
}
