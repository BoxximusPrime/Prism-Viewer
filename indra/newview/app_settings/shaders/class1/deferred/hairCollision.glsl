// Bounded animated-mesh queries shared by the collision cache and rope solver.
vec3 hairClosestWeights(vec3 p, vec3 a, vec3 b, vec3 c)
{
    vec3 ab=b-a, ac=c-a, ap=p-a;
    float d1=dot(ab,ap), d2=dot(ac,ap);
    if (d1<=0 && d2<=0) return vec3(1,0,0);
    vec3 bp=p-b;
    float d3=dot(ab,bp), d4=dot(ac,bp);
    if (d3>=0 && d4<=d3) return vec3(0,1,0);
    float vc=d1*d4-d3*d2;
    if (vc<=0 && d1>=0 && d3<=0) { float v=d1/(d1-d3); return vec3(1-v,v,0); }
    vec3 cp=p-c;
    float d5=dot(ab,cp), d6=dot(ac,cp);
    if (d6>=0 && d5<=d6) return vec3(0,0,1);
    float vb=d5*d2-d1*d6;
    if (vb<=0 && d2>=0 && d6<=0) { float w=d2/(d2-d6); return vec3(1-w,0,w); }
    float va=d3*d6-d5*d4;
    if (va<=0 && d4-d3>=0 && d5-d6>=0)
    { float w=(d4-d3)/((d4-d3)+(d5-d6)); return vec3(0,1-w,w); }
    float sum=1.0/(va+vb+vc);
    return vec3(va,vb,vc)*sum;
}

vec3 hairMeshNormal(samplerBuffer mesh, int offset, vec3 weights, vec3 face)
{
    vec3 n=texelFetch(mesh,offset+1).xyz*weights.x + texelFetch(mesh,offset+3).xyz*weights.y +
           texelFetch(mesh,offset+5).xyz*weights.z;
    return normalize(dot(n,n)>1.e-12 ? n : face);
}

// At most two nearby surfaces per corner: the body and an independent hand candidate.
ivec2 hairCachedTriangles(vec3 local, samplerBuffer mesh, int offset, int corner)
{
    vec4 grid=texelFetch(mesh,offset);
    ivec3 cell=ivec3(floor(clamp((local-grid.xyz)/grid.w,vec3(0),vec3(19,19,30))));
    cell+=ivec3(corner&1,(corner>>1)&1,corner>>2);
    return ivec2(texelFetch(mesh,offset+1+cell.x+21*(cell.y+21*cell.z)).xy)-1;
}

// Blend distinct nearby patches: cache identity changes must not choose a new push direction.
void hairMeshPlanes(vec3 local, samplerBuffer mesh, mat4 from_local, int cache,
    out vec4 planes[2], out vec2 nearest)
{
    planes[0]=planes[1]=vec4(0);
    nearest=vec2(.20*.20,.12*.12);
    if (cache<=0) return;
    vec4 grid=texelFetch(mesh,cache);
    ivec3 centre=ivec3(floor((local-grid.xyz)/grid.w+.5));
    vec3 point=(from_local*vec4(local,1)).xyz;
    vec3 normals[2]; normals[0]=normals[1]=vec3(0);
    vec3 nearest_normal[2]; nearest_normal[0]=nearest_normal[1]=vec3(0);
    vec2 clearance=vec2(0), total=vec2(0);
    int seen[54], seen_count=0;
    for (int z=-1;z<=1;++z)
    for (int y=-1;y<=1;++y)
    for (int x=-1;x<=1;++x)
    {
        ivec3 cell=clamp(centre+ivec3(x,y,z),ivec3(0),ivec3(20,20,31));
        ivec2 candidates=ivec2(texelFetch(mesh,cache+1+cell.x+21*(cell.y+21*cell.z)).xy)-1;
        for (int kind=0;kind<2;++kind)
        {
            int offset=candidates[kind];
            if (offset<0) continue;
            bool duplicate=false;
            for (int i=0;i<seen_count;++i) if (abs(seen[i])==offset) duplicate=true;
            if (duplicate) continue;
            seen[seen_count++]=kind==0 ? offset : -offset;
            vec3 a=texelFetch(mesh,offset).xyz, b=texelFetch(mesh,offset+2).xyz, c=texelFetch(mesh,offset+4).xyz;
            vec3 face=cross(b-a,c-a);
            if (dot(face,face)<1.e-16) continue;
            vec3 w=hairClosestWeights(point,a,b,c);
            vec3 gap=point-(a*w.x+b*w.y+c*w.z);
            float distance2=dot(gap,gap);
            if (distance2<nearest[kind])
            {
                nearest[kind]=distance2;
                nearest_normal[kind]=hairMeshNormal(mesh,offset,w,face);
            }
        }
    }
    for (int i=0;i<seen_count;++i)
    {
        int kind=seen[i]<0 ? 1 : 0, offset=abs(seen[i]);
        vec3 a=texelFetch(mesh,offset).xyz, b=texelFetch(mesh,offset+2).xyz, c=texelFetch(mesh,offset+4).xyz;
        vec3 face=cross(b-a,c-a);
        if (dot(face,face)<1.e-16) continue;
        vec3 w=hairClosestWeights(point,a,b,c), gap=point-(a*w.x+b*w.y+c*w.z);
        vec3 n=hairMeshNormal(mesh,offset,w,face);
        float distance2=dot(gap,gap), range=kind==0 ? .20 : .12;
        // Never blend through the back of the closest surface into the other side of a thin body part.
        float influence=(1.0-smoothstep(range*.5,range,sqrt(distance2)))/(.0004+distance2)*
            smoothstep(.25,.5,dot(n,nearest_normal[kind]))*
            (1.0-smoothstep(.005,.02,sqrt(distance2)-sqrt(nearest[kind])));
        normals[kind]+=n*influence;
        clearance[kind]+=dot(gap,n)*influence;
        total[kind]+=influence;
    }
    for (int kind=0;kind<2;++kind)
    {
        float magnitude=length(normals[kind]);
        if (total[kind]<1.e-6 || magnitude<total[kind]*.2) continue;
        vec3 n=normals[kind]/magnitude;
        planes[kind]=vec4(n,dot(n,point)+.005-clearance[kind]/magnitude);
    }
}

vec3 hairMeshMovement(vec3 original, vec3 movement, samplerBuffer mesh, mat4 from_local, float smoothing, int cache)
{
    if (cache<=0) return movement;
    vec3 start=(from_local*vec4(original,1)).xyz;
    vec3 delta=mat3(from_local)*movement;
    float soft=min(smoothing,.02), margin=.005;
    // Select contact planes once; projection must not change its target between passes.
    vec3 end=start+delta, local_end=original+transpose(mat3(from_local))*delta;
    vec2 best;
    vec4 planes[2];
    hairMeshPlanes(local_end,mesh,from_local,cache,planes,best);
    vec3 closest[2], normals[2];
    for (int kind=0;kind<2;++kind)
    {
        normals[kind]=planes[kind].xyz;
        closest[kind]=end+normals[kind]*(planes[kind].w-dot(normals[kind],end)-margin);
    }
    float hit=1.0;
    vec3 hit_normal=vec3(0);
    bool swept=dot(delta,delta)>1.e-10;
    int steps=clamp(int(ceil(length(delta)/.06)),1,4), last=-1;
    // Bounded sweep through cached candidates; never walk the body BVH per point.
    for (int sample_index=0; sample_index<(swept ? steps : 0); ++sample_index)
    for (int corner=0; corner<8; ++corner)
    {
        vec3 query=mix(original,local_end,float(sample_index+1)/float(steps));
        ivec2 candidates=hairCachedTriangles(query,mesh,cache,corner);
        for (int kind=0; kind<2; ++kind)
        {
            int offset=candidates[kind];
            if (offset<0 || offset==last) continue;
            last=offset;
            vec4 av=texelFetch(mesh,offset), bv=texelFetch(mesh,offset+2), cv=texelFetch(mesh,offset+4);
            vec3 a=av.xyz, ab=bv.xyz-a, ac=cv.xyz-a, face=cross(ab,ac);
            if (dot(face,face)<1.e-16) continue;
            int group=max(max(av.w,bv.w),cv.w)>.15 ? 1 : 0;
            vec3 h=cross(delta,ac);
            float determinant=dot(ab,h);
            if (abs(determinant)<1.e-10) continue;
            vec3 v=start-a, cross_v=cross(v,ab);
            float u=dot(v,h)/determinant, t=dot(ac,cross_v)/determinant, vv=dot(delta,cross_v)/determinant;
            if (t<0 || t>=hit) continue;
            vec3 contact_weights=vec3(1-u-vv,u,vv);
            if (u<0 || vv<0 || u+vv>1)
            {
                vec3 crossing=start+t*delta;
                contact_weights=hairClosestWeights(crossing,a,bv.xyz,cv.xyz);
                vec3 gap=crossing-(a*contact_weights.x+bv.xyz*contact_weights.y+cv.xyz*contact_weights.z);
                // Keep torso coverage broad; fingers must not act like 8 cm paddles.
                float coverage=group==1 ? .02 : .08;
                if (dot(gap,gap)>coverage*coverage) continue;
            }
            vec3 n=hairMeshNormal(mesh,offset,contact_weights,face);
            if (dot(delta,n)>=-1.e-7) continue;
            hit=t; hit_normal=n;
        }
    }
    if (hit<1.0)
    {
        // A crossing owns the contact plane; the predicted endpoint may already be behind the obstacle.
        normals[0]=hit_normal; closest[0]=start+hit*delta; best.x=0.0;
        normals[1]=vec3(0);
    }
    for (int pass=0; pass<2; ++pass)
    {
        vec3 end=start+delta;
        if (pass==0 && hit<1.0)
        {
            delta+=hit_normal*(max(-dot(delta*(1.0-hit),hit_normal),0.0)+margin);
            continue;
        }
        float correction=0.0;
        vec3 normal=vec3(0);
        for (int kind=0; kind<2; ++kind)
        {
            if (dot(normals[kind],normals[kind])<.5) continue;
            // Nearby hand contact takes priority over a distant body recovery plane.
            if (kind==0 && best.x>.10*.10 && dot(normals[1],normals[1])>.5) continue;
            // shortcut: cached triangles approximate nearby surface patches; sharp creases can lose detail.
            float excess=margin-dot(end-closest[kind],normals[kind]);
            float h=soft>0.0 ? clamp(.5+.5*excess/soft,0.0,1.0) : float(excess>0.0);
            float push=excess*h+soft*h*(1.0-h);
            if (push>correction) { correction=push; normal=normals[kind]; }
        }
        if (correction<=1.e-6) break;
        delta+=normal*min(correction,.10);
    }
    return transpose(mat3(from_local))*delta;
}

