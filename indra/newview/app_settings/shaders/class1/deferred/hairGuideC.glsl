uniform int guide_first;
// One invocation owns a complete rope; no cross-workgroup constraint races.
layout(local_size_x=16) in;
layout(std430,binding=5) buffer GuideOutput { vec4 guide_out[]; };
layout(std430,binding=6) buffer GuideProbe { vec4 guide_probe[]; };
uniform int guide_diagnostics=0;
uniform samplerBuffer hair_previous_guides;
uniform samplerBuffer hair_mesh;
uniform samplerBuffer hair_previous_mesh;
uniform int guide_history;
uniform int guide_mesh_history;
uniform vec3 guide_previous_mesh_offset;
uniform float guide_dt;
uniform mat4 guide_from_previous;
uniform vec3 guide_gravity;
uniform float guide_stiffness;
uniform float guide_retention;
uniform float guide_damping=7.0;
uniform float guide_friction=.35;
uniform float guide_bend=1.0;
uniform float guide_bend_gradient=0.0;
uniform float guide_elasticity=.25;
uniform float guide_travel=0.0;
uniform float hair_root_radius;
uniform float hair_root_gradient;
uniform float hair_collision_smoothing;
uniform mat4 hair_mesh_from_local;
uniform int hair_mesh_nodes;
uniform int hair_mesh_contact;
vec3 hairMeshMovement(vec3 p, vec3 movement, samplerBuffer mesh, mat4 from_local, float smoothing, int cache);
ivec2 hairCachedTriangles(vec3 p, samplerBuffer mesh, int offset, int corner);
vec3 hairClosestWeights(vec3 p, vec3 a, vec3 b, vec3 c);
vec3 hairMeshNormal(samplerBuffer mesh, int offset, vec3 weights, vec3 face);
vec4 hairFinitePatch(vec3 gap, vec3 face, vec3 normal, float margin, out float support);
float hairContactExtent(vec4 plane, vec3 direction, vec3 reference, float margin, float support);
void hairContactCandidates(vec3 local, samplerBuffer mesh, mat4 from_local, int nodes, int cache,
    out ivec4 body, out ivec4 hands);

float contact_fraction=1.0;
vec3 contact_velocity=vec3(0);
vec4 probe_nearest=vec4(0), probe_motion=vec4(0);
vec4 probe_normal=vec4(0), probe_face=vec4(0);

struct GuideContact
{
    vec4 plane[2];
    vec3 velocity[2];
};

struct GuideRayContact { vec4 plane; vec4 velocity; }; // velocity.w is the contact fraction along the segment.
const int guide_ray_nodes=64, guide_ray_triangles=32, guide_ray_substeps=2;

GuideRayContact traceGuideSegment(vec3 local_a, vec3 local_b)
{
    GuideRayContact empty=GuideRayContact(vec4(0),vec4(0)), result=empty;
    vec3 start=(hair_mesh_from_local*vec4(local_a,1)).xyz;
    vec3 delta=mat3(hair_mesh_from_local)*(local_b-local_a);
    if (hair_mesh_nodes<=0 || hair_mesh_contact<=hair_mesh_nodes*2 || dot(delta,delta)<1.e-12) return empty;
    float closest=1.0;
    int node=0, tested=0;
    // A slow frame or a dense/overlapping shell must never expand this query's work budget.
    for (int visit=0;visit<guide_ray_nodes && node<hair_mesh_nodes && tested<guide_ray_triangles;++visit)
    {
        vec4 low=texelFetch(hair_mesh,node*2), high=texelFetch(hair_mesh,node*2+1);
        vec3 lo=low.xyz, hi=high.xyz;
        if (guide_mesh_history!=0)
        {
            lo=mix(texelFetch(hair_previous_mesh,node*2).xyz+guide_previous_mesh_offset,lo,contact_fraction);
            hi=mix(texelFetch(hair_previous_mesh,node*2+1).xyz+guide_previous_mesh_offset,hi,contact_fraction);
        }
        float near=0.0, far=closest;
        for (int axis=0;axis<3;++axis)
        {
            if (abs(delta[axis])<1.e-8)
            {
                if (start[axis]<lo[axis] || start[axis]>hi[axis]) far=-1.0;
            }
            else
            {
                float a=(lo[axis]-start[axis])/delta[axis], b=(hi[axis]-start[axis])/delta[axis];
                near=max(near,min(a,b)); far=min(far,max(a,b));
            }
        }
        int escape=int(abs(low.w)), leaf=int(high.w);
        if (escape<=node || escape>hair_mesh_nodes) return empty;
        if (near>far) { node=escape; continue; }
        if (leaf==0) { ++node; continue; }
        int first=leaf/8, count=leaf%8;
        if (count<1 || count>4) return empty;
        if (tested+count>guide_ray_triangles) return empty;
        for (int triangle=0;triangle<count;++triangle)
        {
            ++tested;
            int offset=hair_mesh_nodes*2+(first+triangle)*6;
            if (offset<hair_mesh_nodes*2 || offset+5>=hair_mesh_contact) return empty;
            vec3 a=texelFetch(hair_mesh,offset).xyz, b=texelFetch(hair_mesh,offset+2).xyz, c=texelFetch(hair_mesh,offset+4).xyz;
            vec3 da=vec3(0), db=vec3(0), dc=vec3(0);
            if (guide_mesh_history!=0)
            {
                da=a-texelFetch(hair_previous_mesh,offset).xyz-guide_previous_mesh_offset;
                db=b-texelFetch(hair_previous_mesh,offset+2).xyz-guide_previous_mesh_offset;
                dc=c-texelFetch(hair_previous_mesh,offset+4).xyz-guide_previous_mesh_offset;
                a-=da*(1.0-contact_fraction); b-=db*(1.0-contact_fraction); c-=dc*(1.0-contact_fraction);
            }
            vec3 ab=b-a, ac=c-a, h=cross(delta,ac);
            float determinant=dot(ab,h);
            if (abs(determinant)<1.e-10) continue;
            vec3 v=start-a, cross_v=cross(v,ab);
            float u=dot(v,h)/determinant, w=dot(delta,cross_v)/determinant, t=dot(ac,cross_v)/determinant;
            if (u<0.0 || w<0.0 || u+w>1.0 || t<0.0 || t>closest) continue;
            vec3 weights=vec3(1-u-w,u,w), face=cross(ab,ac);
            if (dot(face,face)<1.e-16) continue;
            vec3 normal=hairMeshNormal(hair_mesh,offset,weights,face);
            if (guide_mesh_history!=0)
                normal=mix(hairMeshNormal(hair_previous_mesh,offset,weights,face),normal,contact_fraction);
            // Two-sided intersection, with outward orientation preserved for start-inside rays.
            vec3 n=normalize(face)*(dot(normal,face)<0.0 ? -1.0 : 1.0);
            n=transpose(mat3(hair_mesh_from_local))*n;
            closest=t;
            // Point contacts own thickness; rays only need a small numerical separation at a crossing.
            result.plane=vec4(n,dot(n,mix(local_a,local_b,t))+.0005);
            // Clip the projected segment to the finite triangle; its plane cannot constrain an entire fold.
            float inverse_area=1.0/dot(face,face);
            vec2 uv=vec2(dot(cross(v,ac),face),dot(cross(ab,v),face))*inverse_area;
            vec2 duv=vec2(dot(cross(delta,ac),face),dot(cross(ab,delta),face))*inverse_area;
            vec3 start_weights=vec3(1-uv.x-uv.y,uv), change=vec3(-duv.x-duv.y,duv);
            float first_inside=0.0, last_inside=1.0;
            for (int edge=0;edge<3;++edge)
            {
                if (change[edge]>1.e-8) first_inside=max(first_inside,-start_weights[edge]/change[edge]);
                if (change[edge]<-1.e-8) last_inside=min(last_inside,-start_weights[edge]/change[edge]);
            }
            float along=clamp(dot(n,local_b-local_a)<0.0 ? last_inside : first_inside,0.0,1.0);
            weights=max(start_weights+change*along,vec3(0)); weights/=max(dot(weights,vec3(1)),1.e-8);
            result.velocity=vec4(guide_dt>0.0 ? transpose(mat3(hair_mesh_from_local))*(da*weights.x+db*weights.y+dc*weights.z)/guide_dt : vec3(0),along);
        }
        node=escape;
    }
    // shortcut: an unfinished search falls back to point contacts; improve candidate selection before raising budgets.
    return node>=hair_mesh_nodes ? result : empty;
}

void projectGuideRay(GuideRayContact hit, inout vec3 a, inout vec3 b, float ma, float mb,
    inout vec3 ca, inout vec3 cb, inout vec3 sa, inout vec3 sb, inout float weight_a, inout float weight_b)
{
    vec3 n=hit.plane.xyz;
    if (dot(n,n)<.5) return;
    float depth_a=max(hit.plane.w-dot(n,a),0.0), depth_b=max(hit.plane.w-dot(n,b),0.0);
    float along=hit.velocity.w, wa=ma*(1.0-along), wb=mb*along;
    if (max(wa,wb)<1.e-6) return;
    // Exempt the pinned endpoint's penetration continuously; keep constraining the free endpoint.
    float plane_offset=hit.plane.w-(ma<=0.0 ? depth_a*(1.0-along) : 0.0)-(mb<=0.0 ? depth_b*along : 0.0);
    // Contact acts at its actual position along the segment; neighbours share the mass-weighted correction.
    float correction=max(plane_offset-dot(n,mix(a,b,along)),0.0)/max(wa*(1.0-along)+wb*along,1.e-8);
    correction=min(correction,.002/max(wa,wb));
    float da=wa*correction, db=wb*correction;
    a+=n*da; b+=n*db; ca+=n*da; cb+=n*db;
    sa+=hit.velocity.xyz*da; sb+=hit.velocity.xyz*db; weight_a+=da; weight_b+=db;
}

GuideContact sampleGuideContact(vec3 p, ivec4 body, ivec4 hands)
{
    if (guide_diagnostics!=0) { probe_nearest=probe_motion=probe_normal=probe_face=vec4(0); }
    GuideContact result;
    for (int kind=0;kind<2;++kind) { result.plane[kind]=vec4(0); result.velocity[kind]=vec3(0); }
    if (hair_mesh_contact<=0) return result;
    vec3 point=(hair_mesh_from_local*vec4(p,1)).xyz;
    for (int kind=0;kind<2;++kind)
    {
        vec3 reference=vec3(0), surface_motion=vec3(0);
        float total=0.0;
        float margin=.005+min(hair_collision_smoothing,.02)*.25;
        vec4 patches[4], motions[4];
        float distances[4], supports[4];
        ivec4 candidates=kind==0 ? body : hands;
        float nearest_distance=1.e20;
        for (int index=0;index<4;++index)
        {
            patches[index]=motions[index]=vec4(0); distances[index]=1.e20; supports[index]=0.0;
            // shortcut: final-pose candidates cover local motion; fast remote crossings need a swept cache.
            int offset=candidates[index];
            if (offset<0) continue;
            vec3 a=texelFetch(hair_mesh,offset).xyz, b=texelFetch(hair_mesh,offset+2).xyz, c=texelFetch(hair_mesh,offset+4).xyz;
            vec3 da=vec3(0), db=vec3(0), dc=vec3(0);
            if (guide_mesh_history!=0)
            {
                da=a-(texelFetch(hair_previous_mesh,offset).xyz+guide_previous_mesh_offset);
                db=b-(texelFetch(hair_previous_mesh,offset+2).xyz+guide_previous_mesh_offset);
                dc=c-(texelFetch(hair_previous_mesh,offset+4).xyz+guide_previous_mesh_offset);
                a-=da*(1.0-contact_fraction); b-=db*(1.0-contact_fraction); c-=dc*(1.0-contact_fraction);
            }
            vec3 face=cross(b-a,c-a);
            if (dot(face,face)<1.e-16) continue;
            vec3 weights=hairClosestWeights(point,a,b,c);
            vec3 gap=point-(a*weights.x+b*weights.y+c*weights.z);
            distances[index]=length(gap);
            vec3 n=hairMeshNormal(hair_mesh,offset,weights,face);
            if (guide_mesh_history!=0)
            {
                vec3 previous_normal=hairMeshNormal(hair_previous_mesh,offset,weights,face);
                vec3 blended=mix(previous_normal,n,contact_fraction);
                n=dot(blended,blended)>1.e-12 ? normalize(blended) : normalize(face);
            }
            patches[index]=hairFinitePatch(gap,face,n,margin,supports[index]);
            motions[index]=vec4(da*weights.x+db*weights.y+dc*weights.z,0);
            if (supports[index]>0.0 && distances[index]<nearest_distance)
            {
                nearest_distance=distances[index];
                if (guide_diagnostics!=0 && kind==0)
                {
                    probe_nearest=vec4(p-transpose(mat3(hair_mesh_from_local))*gap,float(offset+1));
                    probe_motion=vec4(transpose(mat3(hair_mesh_from_local))*motions[index].xyz,nearest_distance);
                    probe_normal=vec4(transpose(mat3(hair_mesh_from_local))*n,dot(gap,n));
                    probe_face=vec4(transpose(mat3(hair_mesh_from_local))*normalize(face),dot(gap,normalize(face)));
                }
            }
        }
        for (int i=0;i<4;++i)
        {
            float range=kind==0 ? .20 : .12;
            supports[i]*=(1.0-smoothstep(range,range+.04,distances[i]))*
                (1.0-smoothstep(.005,.02,distances[i]-nearest_distance));
            float weight=supports[i]/(.0001+distances[i]*distances[i]);
            reference+=patches[i].xyz*weight;
            surface_motion+=motions[i].xyz*weight;
            total+=weight;
        }
        if (total<=0.0) continue;
        // Keep compatible corner contacts together instead of switching the whole plane to one winner.
        reference/=total;
        float magnitude=length(reference);
        if (magnitude<1.e-6) continue;
        vec3 direction=reference/magnitude;
        float extent=-1.e20;
        for (int i=0;i<4;++i)
            if (supports[i]>0.0) extent=max(extent,hairContactExtent(patches[i],direction,reference,margin,supports[i]));
        vec3 n=transpose(mat3(hair_mesh_from_local))*direction;
        result.plane[kind]=vec4(n,dot(n,p)+extent);
        if (guide_dt>0.0) result.velocity[kind]=transpose(mat3(hair_mesh_from_local))*surface_motion/(total*guide_dt);
    }
    return result;
}

GuideContact sampleGuideContact(vec3 p)
{
    ivec4 body, hands;
    hairContactCandidates(p,hair_mesh,hair_mesh_from_local,hair_mesh_nodes,hair_mesh_contact,body,hands);
    return sampleGuideContact(p,body,hands);
}

vec3 projectGuideContact(vec3 p, GuideContact contact)
{
    contact_velocity=vec3(0);
    float velocity_weight=0.0;
    for (int kind=0;kind<2;++kind)
    {
        vec4 plane=contact.plane[kind];
        if (dot(plane.xyz,plane.xyz)<.5) continue;
        float excess=plane.w-dot(plane.xyz,p);
        // A fixed contact plane must be idempotent; repeated soft pushes pump resting ropes outward.
        float push=clamp(excess,0.0,.10);
        p+=plane.xyz*push;
        contact_velocity+=contact.velocity[kind]*push;
        velocity_weight+=push;
    }
    if (velocity_weight>1.e-8) contact_velocity/=velocity_weight;
    return p;
}

void main()
{
    int chain=guide_first+int(gl_GlobalInvocationID.x);
    if (chain>=int(clamp(guide_out[0].w,0.0,64.0))) return;
    int nodes=int(clamp(guide_out[1].w,9.0,32.0));
    int base=chain*nodes*3;
    vec3 rest[32], previous_rest[32], target[32], p[32], v[32], free_velocity[32], before[32], contact[32], surface[32];
    GuideContact point_contacts[32], segment_contacts[32];
    ivec4 point_body[32], point_hands[32], segment_body[32], segment_hands[32];
    GuideRayContact ray_contacts[32];
    vec3 queries[32];
    vec4 nearest_probe[32], motion_probe[32];
    vec4 normal_probe[32], face_probe[32];
    float contact_weight[32];
    float mass[32];
    vec3 pin_lambda[32];
    float bend_lambda[32], length_lambda[32], bend_scale[32];
    for (int i=0;i<nodes;++i)
    {
        rest[i]=guide_out[base+i].xyz;
        previous_rest[i]=guide_history!=0 ? (guide_from_previous*vec4(rest[i],1)).xyz : rest[i];
        float root_distance=length(rest[i]);
        mass[i]=i==0 ? 0.0 : smoothstep(hair_root_radius,hair_root_radius+hair_root_gradient,root_distance);
        // Use rest distance so motion or contact cannot move the stiffness transition along the rope.
        bend_scale[i]=guide_bend_gradient>0.0 ? mix(1.0,.05,
            smoothstep(hair_root_radius,hair_root_radius+guide_bend_gradient,root_distance)) : 1.0;
        p[i]=previous_rest[i]; v[i]=vec3(0);
        if (guide_history!=0 && mass[i]>0.0)
        {
            p[i]=(guide_from_previous*texelFetch(hair_previous_guides,base+nodes+i)).xyz;
            v[i]=mat3(guide_from_previous)*texelFetch(hair_previous_guides,base+nodes*2+i).xyz;
        }
    }
    float dt=clamp(guide_dt,0.0,.25);
    int steps=max(1,int(ceil(dt*120.0)));
    float h=dt/float(steps);
    for (int step=0;step<steps;++step)
    {
        contact_fraction=float(step+1)/float(steps);
        bool trace_segments=(step+1)*guide_ray_substeps/steps>step*guide_ray_substeps/steps;
        for (int i=0;i<nodes;++i)
        {
            surface[i]=vec3(0); contact_weight[i]=0.0;
            // Move anchors throughout the frame instead of delivering its entire motion in one substep.
            target[i]=mix(previous_rest[i],rest[i],float(step+1)/float(steps));
            before[i]=p[i];
            contact[i]=vec3(0);
            bend_lambda[i]=0.0;
            length_lambda[i]=0.0;
            pin_lambda[i]=vec3(0);
            free_velocity[i]=vec3(0);
            if (mass[i]<=0.0) { p[i]=target[i]; continue; }
            vec3 force=guide_gravity+(target[i]-p[i])*guide_stiffness*guide_stiffness*guide_retention;
            v[i]=(v[i]+force*h)*exp(-guide_damping*h);
            free_velocity[i]=v[i];
            p[i]+=v[i]*h;
        }
        if (hair_mesh_nodes>0)
        {
            // Sweep once, then keep contact planes fixed while the rope constraints converge.
            if (contact_fraction>=1.0)
                for (int i=1;i<nodes;++i)
                    if (mass[i]>0.0 && length(p[i]-before[i])>.025)
                    {
                        vec3 predicted=p[i];
                        p[i]=before[i]+hairMeshMovement(before[i],p[i]-before[i],hair_mesh,hair_mesh_from_local,hair_collision_smoothing,hair_mesh_contact);
                        contact[i]+=p[i]-predicted;
                        contact_weight[i]+=length(p[i]-predicted);
                    }
            for (int i=1;i<nodes;++i)
            {
                // At most two refinements per frame, even with thirty integration substeps.
                if (step==0 || step==steps/2)
                {
                    hairContactCandidates(p[i],hair_mesh,hair_mesh_from_local,hair_mesh_nodes,hair_mesh_contact,
                        point_body[i],point_hands[i]);
                    hairContactCandidates((p[i]+p[i-1])*.5,hair_mesh,hair_mesh_from_local,hair_mesh_nodes,hair_mesh_contact,
                        segment_body[i],segment_hands[i]);
                }
                point_contacts[i]=sampleGuideContact(p[i],point_body[i],point_hands[i]);
                if (guide_diagnostics!=0)
                {
                    queries[i]=p[i]; nearest_probe[i]=probe_nearest; motion_probe[i]=probe_motion;
                    normal_probe[i]=probe_normal; face_probe[i]=probe_face;
                }
                segment_contacts[i]=sampleGuideContact((p[i]+p[i-1])*.5,segment_body[i],segment_hands[i]);
                ray_contacts[i]=trace_segments && mass[i]>0.0 ? traceGuideSegment(p[i-1],p[i]) : GuideRayContact(vec4(0),vec4(0));
                // Allow only the pinned half's penetration, without switching the whole contact off.
                if (mass[i-1]<=0.0)
                for (int kind=0;kind<2;++kind)
                    segment_contacts[i].plane[kind].w-=.5*max(0.0,segment_contacts[i].plane[kind].w-
                        dot(segment_contacts[i].plane[kind].xyz,p[i-1]));
            }
            // A midpoint plane cannot override endpoint contacts on opposite sides of a fold.
            for (int i=1;i<nodes;++i)
            for (int kind=0;kind<2;++kind)
            {
                vec3 n=segment_contacts[i].plane[kind].xyz;
                if (dot(n,point_contacts[i].plane[kind].xyz)<0.0 ||
                    (i>1 && dot(n,point_contacts[i-1].plane[kind].xyz)<0.0))
                    segment_contacts[i].plane[kind]=vec4(0);
            }
            for (int i=1;i<nodes;++i)
            for (int kind=0;kind<2;++kind)
            {
                // A new ray must not fight established endpoint contacts on opposite sides of a fold.
                vec3 n=ray_contacts[i].plane.xyz;
                if (dot(n,point_contacts[i].plane[kind].xyz)<0.0 ||
                    (i>1 && dot(n,point_contacts[i-1].plane[kind].xyz)<0.0))
                    ray_contacts[i].plane=vec4(0);
            }
        }
        for (int iteration=0;iteration<12;++iteration)
        {
            // Inverse mass alone does not resist gravity/inertia. Fade a compliant rest attachment instead.
            if (h>0.0)
            for (int i=1;i<nodes;++i)
            {
                if (mass[i]<=0.0 || mass[i]>=1.0) continue;
                float compliance=.01*mass[i]*mass[i]/((1.0-mass[i])*h*h);
                vec3 change=(-(p[i]-target[i])-compliance*pin_lambda[i])/(mass[i]+compliance);
                pin_lambda[i]+=change;
                p[i]+=change*mass[i];
            }
            if (guide_travel>0.0)
            for (int i=1;i<nodes;++i)
            {
                // Bound free motion first; body contact takes priority over the artistic travel limit.
                float limit=(.04+guide_travel*length(rest[i]-rest[0]))*mass[i];
                vec3 offset=p[i]-target[i];
                p[i]=target[i]+offset*min(1.0,limit/max(length(offset),1.e-6));
            }
            // Compliant second-neighbour distances resist kinks without tethering the rope to world axes.
            if (h>0.0 && guide_bend>0.0)
            for (int i=1;i<nodes-1;++i)
            {
                vec3 edge=p[i+1]-p[i-1];
                float distance=length(edge), total=mass[i-1]+mass[i+1];
                if (distance<1.e-6 || total<=0.0) continue;
                float compliance=.002/(max(guide_stiffness,1.0)*guide_bend*bend_scale[i]*h*h);
                float change=(-(distance-length(rest[i+1]-rest[i-1]))-compliance*bend_lambda[i])/(total+compliance);
                bend_lambda[i]+=change;
                vec3 correction=edge*(change/distance);
                p[i+1]+=correction*mass[i+1]; p[i-1]-=correction*mass[i-1];
            }
            for (int i=1;i<nodes;++i)
            {
                vec3 edge=p[i]-p[i-1];
                float distance=length(edge), total=mass[i]+mass[i-1];
                if (distance>1.e-6 && total>0.0)
                {
                    float rest_length=length(rest[i]-rest[i-1]);
                    // Compliant lengths yield under load without changing the rope's resting shape.
                    float compliance=h>0.0 ? .001*rest_length*guide_elasticity/(h*h) : 0.0;
                    float change=(-(distance-rest_length)-compliance*length_lambda[i])/(total+compliance);
                    length_lambda[i]+=change;
                    vec3 correction=edge*(change/distance);
                    p[i]+=correction*mass[i]; p[i-1]-=correction*mass[i-1];
                }
            }
            // Contact is interleaved with length constraints so it pulls neighbouring nodes.
            if (hair_mesh_nodes>0 && iteration%3==2)
            for (int i=1;i<nodes;++i)
            {
                if (mass[i]<=0.0) continue;
                vec3 corrected=projectGuideContact(p[i],point_contacts[i]);
                float weight=length(corrected-p[i]);
                surface[i]+=contact_velocity*weight; contact_weight[i]+=weight;
                contact[i]+=corrected-p[i];
                p[i]=corrected;
                // Mid-segment probes catch obstacles between sparse rope nodes.
                vec3 midpoint=(p[i]+p[i-1])*.5;
                vec3 correction=projectGuideContact(midpoint,segment_contacts[i])-midpoint;
                weight=length(correction);
                surface[i]+=contact_velocity*weight*mass[i]; contact_weight[i]+=weight*mass[i];
                surface[i-1]+=contact_velocity*weight*mass[i-1]; contact_weight[i-1]+=weight*mass[i-1];
                float total=mass[i]+mass[i-1];
                p[i]+=correction*(2.0*mass[i]/total);
                p[i-1]+=correction*(2.0*mass[i-1]/total);
                contact[i]+=correction*mass[i];
                contact[i-1]+=correction*mass[i-1];
                projectGuideRay(ray_contacts[i],p[i-1],p[i],mass[i-1],mass[i],contact[i-1],contact[i],
                        surface[i-1],surface[i],contact_weight[i-1],contact_weight[i]);
            }
        }
        // A neighbouring segment's correction must not leave a point behind its own contact plane.
        if (hair_mesh_nodes>0)
        for (int i=1;i<nodes;++i)
        {
            if (mass[i]<=0.0) continue;
            vec3 corrected=projectGuideContact(p[i],point_contacts[i]);
            float weight=length(corrected-p[i]);
            surface[i]+=contact_velocity*weight; contact_weight[i]+=weight;
            contact[i]+=corrected-p[i]; p[i]=corrected;
        }
        bool mesh_recovery=hair_mesh_nodes>0;
        if (guide_diagnostics!=0)
        for (int i=1;i<nodes;++i)
        {
            int index=(chain*nodes+i)*7;
            float correction=length(p[i]-before[i]-free_velocity[i]*h);
            if (step==0 || correction>guide_probe[index].w)
            {
                guide_probe[index]=vec4(hair_mesh_nodes>0 ? queries[i] : before[i],correction);
                guide_probe[index+1]=hair_mesh_nodes>0 ? point_contacts[i].plane[0] : vec4(0);
                guide_probe[index+2]=hair_mesh_nodes>0 ? point_contacts[i].plane[1] : vec4(0);
                guide_probe[index+3]=hair_mesh_nodes>0 ? nearest_probe[i] : vec4(0);
                guide_probe[index+4]=hair_mesh_nodes>0 ? motion_probe[i] : vec4(0);
                guide_probe[index+5]=hair_mesh_nodes>0 ? normal_probe[i] : vec4(0);
                guide_probe[index+6]=hair_mesh_nodes>0 ? face_probe[i] : vec4(0);
            }
        }
        for (int i=0;i<nodes;++i)
        {
            // Split penetration recovery from kinetic motion, including corrections passed to neighbours.
            v[i]=h>0.0 ? (p[i]-before[i])/h : vec3(0);
            if (mesh_recovery && mass[i]>0.0)
                v[i]*=min(1.0,length(free_velocity[i])/max(length(v[i]),1.e-6));
        }
        if (mesh_recovery)
        for (int iteration=0;iteration<8;++iteration)
        for (int i=1;i<nodes;++i)
        {
            vec3 edge=p[i]-p[i-1];
            float distance=length(edge), total=mass[i]+mass[i-1];
            if (distance<1.e-6 || total<=0.0) continue;
            vec3 n=edge/distance;
            float compliance=h>0.0 ? .001*length(rest[i]-rest[i-1])*guide_elasticity/(h*h) : 0.0;
            vec3 impulse=n*(dot(v[i]-v[i-1],n)/(total+compliance));
            v[i]-=impulse*mass[i]; v[i-1]+=impulse*mass[i-1];
        }
        for (int i=0;i<nodes;++i)
        {
            if (mass[i]<=0.0) { v[i]=vec3(0); continue; }
            if (dot(contact[i],contact[i])>1.e-12)
            {
                vec3 normal=normalize(contact[i]);
                vec3 moving=surface[i]/max(contact_weight[i],1.e-8);
                float push_speed=max(0.0,dot(moving,normal));
                // Keep genuine separation, excluding outward speed created by position correction.
                float separating=max(0.0,min(dot(free_velocity[i],normal),dot(v[i],normal)));
                v[i]-=normal*dot(v[i],normal);
                vec3 tangent_motion=moving-normal*dot(moving,normal);
                vec3 relative=v[i]-tangent_motion;
                float impulse=max(0.0,push_speed-dot(free_velocity[i],normal));
                // Friction acts relative to the surface and only while contact supplies a normal impulse.
                v[i]-=relative*min(1.0,guide_friction*impulse/max(length(relative),1.e-6));
                v[i]+=normal*max(push_speed,separating);
            }
            // Contact projection must not become an arbitrarily large kick on the next step.
            v[i]*=min(1.0,3.0/max(length(v[i]),1.e-6));
        }
    }
    for (int i=0;i<nodes;++i)
    {
        guide_out[base+nodes+i]=vec4(p[i],1);
        guide_out[base+nodes*2+i]=vec4(v[i],contact_weight[i]>1.e-7 ? 1.0 : 0.0);
    }
}
