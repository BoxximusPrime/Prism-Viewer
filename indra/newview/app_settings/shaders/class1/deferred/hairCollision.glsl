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

vec4 hairFinitePatch(vec3 gap, vec3 face, vec3 normal, float margin, out float support)
{
    vec3 geometric=normalize(face)*(dot(face,normal)<0.0 ? -1.0 : 1.0);
    float side=dot(gap,geometric), distance=length(gap);
    float lateral=length(gap-geometric*side);
    support=1.0-smoothstep(0.0,margin,lateral);
    // Outside a convex edge, both faces share the same closest-feature direction.
    float front=smoothstep(0.0,margin,side);
    if (distance>1.e-8) normal=normalize(mix(normal,gap/distance,front));
    support=mix(support,1.0,front);
    return vec4(normal,dot(gap,normal));
}

float hairContactExtent(vec4 plane, vec3 direction, vec3 reference, float margin, float support)
{
    float alignment=dot(plane.xyz,direction);
    if (alignment<=0.0) return -1.e20;
    float excess=margin-plane.w;
    // Fade the correction itself; normalizing a weighted plane would undo this support.
    if (excess>0.0) excess*=support*smoothstep(0.0,.25,dot(plane.xyz,reference));
    return excess/max(alignment,.25);
}

// At most two nearby surfaces per corner: the body and an independent hand candidate.
ivec2 hairCachedTriangles(vec3 local, samplerBuffer mesh, int offset, int corner)
{
    vec4 grid=texelFetch(mesh,offset);
    ivec3 cell=ivec3(floor(clamp((local-grid.xyz)/grid.w,vec3(0),vec3(19,19,30))));
    cell+=ivec3(corner&1,(corner>>1)&1,corner>>2);
    return ivec2(texelFetch(mesh,offset+1+cell.x+21*(cell.y+21*cell.z)).xy)-1;
}

void hairInsertCandidate(vec3 point, samplerBuffer mesh, int offset, int nodes, int end,
    inout ivec4 body, inout ivec4 hands, inout vec4 body_distance, inout vec4 hand_distance)
{
    if (offset<nodes*2 || offset+5>=end || (offset-nodes*2)%6!=0) return;
    if (any(equal(body,ivec4(offset))) || any(equal(hands,ivec4(offset)))) return;
    vec4 a=texelFetch(mesh,offset), b=texelFetch(mesh,offset+2), c=texelFetch(mesh,offset+4);
    vec3 face=cross(b.xyz-a.xyz,c.xyz-a.xyz);
    if (dot(face,face)<1.e-16) return;
    vec3 w=hairClosestWeights(point,a.xyz,b.xyz,c.xyz);
    vec3 gap=point-(a.xyz*w.x+b.xyz*w.y+c.xyz*w.z);
    float distance=dot(gap,gap);
    bool hand=max(max(a.w,b.w),c.w)>.15;
    ivec4 ids=hand ? hands : body;
    vec4 distances=hand ? hand_distance : body_distance;
    for (int i=0;i<4;++i)
        if (distance<distances[i])
        {
            for (int j=3;j>i;--j) { ids[j]=ids[j-1]; distances[j]=distances[j-1]; }
            ids[i]=offset; distances[i]=distance; break;
        }
    if (hand) { hands=ids; hand_distance=distances; }
    else { body=ids; body_distance=distances; }
}

void hairContactCandidates(vec3 local, samplerBuffer mesh, mat4 from_local, int nodes, int cache,
    out ivec4 body, out ivec4 hands)
{
    body=hands=ivec4(-1);
    if (nodes<=0 || cache<=nodes*2) return;
    vec3 point=(from_local*vec4(local,1)).xyz;
    vec4 body_distance=vec4(.24*.24), hand_distance=body_distance;
    for (int corner=0;corner<8;++corner)
    {
        ivec2 seed=hairCachedTriangles(local,mesh,cache,corner);
        for (int kind=0;kind<2;++kind)
            hairInsertCandidate(point,mesh,seed[kind],nodes,cache,body,hands,body_distance,hand_distance);
    }
    // The 6 cm cache seeds a finite-triangle query; its triangles do not cover the whole cell.
    // shortcut: retain the best four per kind within this budget; dense overlapping shells can hide a better patch.
    int node=0, pending[32], pending_count=0, tested=0;
    for (int visited=0;visited<64 && node<nodes && tested<32;++visited)
    {
        vec4 lo=texelFetch(mesh,node*2), hi=texelFetch(mesh,node*2+1);
        vec3 gap=max(max(lo.xyz-point,point-hi.xyz),vec3(0));
        float distance=dot(gap,gap);
        if ((fract(abs(lo.w))==0.0 || distance>min(body_distance.w,body_distance.x+.02*.02)) &&
            (lo.w>=0.0 || distance>min(hand_distance.w,hand_distance.x+.02*.02)))
        { node=pending_count>0 ? pending[--pending_count] : nodes; continue; }
        int leaf=int(hi.w), first=leaf/8, count=leaf%8;
        if (leaf==0)
        {
            int left=node+1;
            if (left>=nodes || pending_count>=32) break;
            int right=int(abs(texelFetch(mesh,left*2).w));
            if (right<=left || right>=nodes) break;
            vec3 a=max(max(texelFetch(mesh,left*2).xyz-point,point-texelFetch(mesh,left*2+1).xyz),vec3(0));
            vec3 b=max(max(texelFetch(mesh,right*2).xyz-point,point-texelFetch(mesh,right*2+1).xyz),vec3(0));
            bool left_first=dot(a,a)<=dot(b,b);
            pending[pending_count++]=left_first ? right : left;
            node=left_first ? left : right;
            continue;
        }
        if (count<1 || count>4 || tested+count>32) break;
        for (int i=0;i<count;++i)
        {
            ++tested;
            hairInsertCandidate(point,mesh,nodes*2+(first+i)*6,nodes,cache,body,hands,body_distance,hand_distance);
        }
        node=pending_count>0 ? pending[--pending_count] : nodes;
    }
}

uniform int hair_mesh_nodes;

void hairMeshPlanes(vec3 local, samplerBuffer mesh, mat4 from_local, int cache,
    out vec4 planes[2], out vec2 nearest)
{
    planes[0]=planes[1]=vec4(0);
    nearest=vec2(.20*.20,.12*.12);
    if (cache<=0) return;
    vec3 point=(from_local*vec4(local,1)).xyz;
    ivec4 body, hands;
    hairContactCandidates(local,mesh,from_local,hair_mesh_nodes,cache,body,hands);
    for (int kind=0;kind<2;++kind)
    {
        ivec4 candidates=kind==0 ? body : hands;
        vec4 patches[4];
        float distances[4], supports[4];
        vec3 reference=vec3(0);
        float total=0.0;
        for (int i=0;i<4;++i)
        {
            patches[i]=vec4(0); distances[i]=1.e20; supports[i]=0.0;
            int offset=candidates[i];
            if (offset<0) continue;
            vec3 a=texelFetch(mesh,offset).xyz, b=texelFetch(mesh,offset+2).xyz, c=texelFetch(mesh,offset+4).xyz;
            vec3 face=cross(b-a,c-a);
            if (dot(face,face)<1.e-16) continue;
            vec3 w=hairClosestWeights(point,a,b,c);
            vec3 gap=point-(a*w.x+b*w.y+c*w.z);
            vec3 n=hairMeshNormal(mesh,offset,w,face);
            patches[i]=hairFinitePatch(gap,face,n,.005,supports[i]);
            distances[i]=length(gap);
            if (supports[i]>0.0) nearest[kind]=min(nearest[kind],dot(gap,gap));
        }
        for (int i=0;i<4;++i)
        {
            float range=kind==0 ? .20 : .12;
            supports[i]*=(1.0-smoothstep(range,range+.04,distances[i]))*
                (1.0-smoothstep(.005,.02,distances[i]-sqrt(nearest[kind])));
            float weight=supports[i]/(.0001+distances[i]*distances[i]);
            reference+=patches[i].xyz*weight;
            total+=weight;
        }
        if (total<=0.0) continue;
        // A continuous reference replaces the nearest-normal winner; opposing contacts fade without a singularity.
        vec3 average=reference/total;
        float magnitude=length(average);
        if (magnitude<1.e-6) continue;
        vec3 n=average/magnitude;
        float extent=-1.e20;
        for (int i=0;i<4;++i)
            if (supports[i]>0.0)
                extent=max(extent,hairContactExtent(patches[i],n,average,.005,supports[i]));
        planes[kind]=vec4(n,dot(n,point)+extent);
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
                // Only the rope thickness extends a finite triangle's swept footprint.
                float coverage=margin;
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

