#include "llalphalightselection.h"
#include <cassert>
#include <chrono>
#include <iostream>
#include <random>
#ifdef ALPHA_TEST_GLM
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/type_ptr.hpp>
#endif
using namespace LLAlphaLightSelection;
Candidate point(uint32_t id, Vec3 p = {}, float radius = 10.f, float strength = 1.f)
{ Candidate c; c.id=id; c.position=p; c.radius=radius; c.strength=strength; return c; }
Candidate beam(uint32_t id)
{
    auto c=point(id, {}, 20.f); c.projector=true;
    c.planes={{{1,0,0,.2f},{-1,0,0,.2f},{0,1,0,.2f},{0,-1,0,.2f},{0,0,1,10},{0,0,-1,10}}};
    return c;
}
Selection brute(const std::vector<Candidate>& candidates, const Bounds& box)
{
    std::vector<std::pair<double,int>> ranked;
    for (const auto& c:candidates)
    {
        double squared=0;
        for(int i=0;i<3;++i) { const double d=std::max({double(box.min[i])-c.position[i],double(c.position[i])-box.max[i],0.}); squared+=d*d; }
        if(squared>=double(c.radius)*c.radius) continue;
        bool reject=false;
        if(c.projector) for(const auto& p:c.planes)
        {
            double maximum=p[3]; for(int i=0;i<3;++i) maximum+=double(p[i])*(p[i]>=0?box.max[i]:box.min[i]);
            if(maximum < -1.e-5) reject=true;
        }
        if(reject) continue;
        const double a=1.-std::clamp((std::sqrt(squared)/c.radius+c.falloff)/(1.+c.falloff),0.,1.);
        if(a>0) ranked.emplace_back(c.strength*a*a*2.,int(c.id));
    }
    std::sort(ranked.begin(),ranked.end(),[](const auto& a,const auto& b){ return a.first!=b.first?a.first>b.first:a.second<b.second; });
    Selection result; result.count=std::min(size_t(6),ranked.size());
    for(size_t i=0;i<result.count;++i) result.ids[i]=ranked[i].second;
    return result;
}
int main()
{
    Selector s; const Bounds origin{{-1,-1,-1},{1,1,1}};
    Bounds accumulated; assert(!accumulated.valid()); accumulated.include(Vec3{{2,3,4}}); accumulated.include(origin);
    assert(accumulated.valid() && accumulated.min[0]==-1 && accumulated.max[2]==4);
    const std::array<float,16> affine{{0,2,0,0,-3,0,0,0,0,0,.5f,0,10,20,30,1}};
    const Bounds source{{-1,-2,-4},{3,5,6}};
    const Bounds transformed=transform(source,affine);
    assert((transformed.min==Vec3{{-5,18,28}} && transformed.max==Vec3{{16,26,33}}));
    // Independently transformed vertices all lie inside the returned box.
    for(int corner=0;corner<8;++corner)
    {
        const float x=(corner&1)?3.f:-1.f,y=(corner&2)?5.f:-2.f,z=(corner&4)?6.f:-4.f;
        const Vec3 vertex{{10-3*y,20+2*x,30+.5f*z}};
        for(int axis=0;axis<3;++axis) assert(vertex[axis]>=transformed.min[axis] && vertex[axis]<=transformed.max[axis]);
    }
    auto invalidMatrix=affine; invalidMatrix[2]=std::numeric_limits<float>::infinity();
    assert(!transform(source,invalidMatrix).valid());
    invalidMatrix=affine; invalidMatrix[3]=.1f; assert(!transform(source,invalidMatrix).valid());
    assert(!transform(Bounds{},affine).valid());
#ifdef ALPHA_TEST_GLM
    for (int pose = 0; pose < 1000; ++pose)
    {
        const float angle = pose * .173f;
        const glm::vec3 eye(std::cos(angle)*17.f, std::sin(angle)*23.f, 3.f+std::sin(angle*.77f)*5.f);
        const glm::mat4 camera = glm::lookAt(eye, glm::vec3(1,2,1), glm::vec3(0,0,1));
        const glm::mat4 asset = glm::scale(glm::rotate(glm::translate(glm::mat4(1.f),
            glm::vec3(11,-7,3)), angle, glm::vec3(0,0,1)), glm::vec3(.7f,2.3f,1.1f));
        const glm::mat4 recovered = glm::inverse(camera) * (camera * asset);
        std::array<float,16> values;
        std::copy_n(glm::value_ptr(recovered),16,values.begin());
        const auto box = transform(source,values);
        assert(box.valid());
        for(int corner=0;corner<8;++corner)
        {
            const glm::vec4 point((corner&1)?source.max[0]:source.min[0],
                (corner&2)?source.max[1]:source.min[1],(corner&4)?source.max[2]:source.min[2],1);
            const glm::vec4 vertex = recovered * point;
            for(int axis=0;axis<3;++axis)
                assert(vertex[axis]>=box.min[axis]-1.e-5f && vertex[axis]<=box.max[axis]+1.e-5f);
        }
    }
    std::cout << "Bundled GLM: 1000 camera/asset affine round trips passed\n";
#endif
    // Nonnegative normalized joint weights form a convex combination of
    // transformed positions, so the union of joint boxes encloses the blend.
    auto secondJoint=affine; secondJoint[12]=-15; secondJoint[13]=3;
    Bounds jointUnion; jointUnion.include(transform(source,affine)); jointUnion.include(transform(source,secondJoint));
    for(float weight:{0.f,.1f,.5f,.9f,1.f}) for(int corner=0;corner<8;++corner)
    {
        const float x=(corner&1)?3.f:-1.f,y=(corner&2)?5.f:-2.f,z=(corner&4)?6.f:-4.f;
        Vec3 blended{{weight*(10-3*y)+(1-weight)*(-15-3*y),weight*(20+2*x)+(1-weight)*(3+2*x),30+.5f*z}};
        for(int axis=0;axis<3;++axis) assert(blended[axis]>=jointUnion.min[axis] && blended[axis]<=jointUnion.max[axis]);
    }
    assert(s.select(origin).count==0);
    s.build({point(8),point(2),point(7),point(1),point(6),point(3),point(5)});
    const auto six=s.select(origin); assert(six.count==6);
    assert((six.ids==std::array<int,6>{{1,2,3,5,6,7}}));
    assert(s.select(origin,0).count==0 && s.select(origin,2).count==2 && s.select(origin,99).count==6);
    assert(s.select({{2,0,0},{1,1,1}}).count==0);
    std::vector<Candidate> irrelevant;
    for(int i=0;i<7;++i) irrelevant.push_back(point(i,{100.f+i,0,0},1,100));
    irrelevant.push_back(point(42)); s.build(irrelevant); assert(s.select(origin).ids[0]==42);
    irrelevant.clear(); for(int i=0;i<7;++i) { auto b=beam(i); b.position={0,0,0}; b.planes[0][3]=-5; irrelevant.push_back(b); }
    irrelevant.push_back(point(42)); s.build(irrelevant); assert(s.select(origin).count==1 && s.select(origin).ids[0]==42);
    // A narrow beam crosses this box while every box corner is outside the beam.
    s.build({beam(9)}); assert(s.select(origin).count==1);
    // Touching a frustum boundary must not be rejected by the broad phase.
    assert(s.select({{.2f,-1,-1},{1,1,1}}).count==1);
    auto invalid=point(1); invalid.radius=0; auto nan=point(2); nan.position[0]=std::numeric_limits<float>::quiet_NaN();
    auto badPlane=beam(3); badPlane.planes[0]={0,0,0,0};
    s.build({invalid,nan,badPlane}); assert(s.select(origin).count==0);
    // Geometry, strength and shader falloff all affect contribution ordering.
    auto weak=point(1,{},10,.01f), far=point(2,{8,0,0},10,1), near=point(3,{2,0,0},10,1);
    s.build({weak,far,near}); assert(s.select(origin).ids[0]==3);
    std::reverse(irrelevant.begin(),irrelevant.end()); s.build(irrelevant); assert(s.select(origin).ids[0]==42);
    std::vector<Candidate> ties;
    for (int i=19;i>=0;--i) ties.push_back(point(i));
    s.build(ties); assert((s.select(origin).ids==std::array<int,6>{{0,1,2,3,4,5}}));
    std::reverse(ties.begin(),ties.end()); s.build(ties);
    assert((s.select(origin).ids==std::array<int,6>{{0,1,2,3,4,5}}));
    std::mt19937 rng(12345); std::uniform_real_distribution<float> unit(-1.f,1.f);
    for(int round=0;round<50;++round)
    {
        std::vector<Candidate> mixed;
        for(int i=0;i<257;++i)
        {
            auto c=i%3==0?beam(i):point(i);
            c.position={unit(rng)*20,unit(rng)*20,unit(rng)*20};
            c.radius=1+(unit(rng)+1)*20; c.strength=.1f+(unit(rng)+1)*5;
            c.falloff=-.9f+(unit(rng)+1)*2;
            mixed.push_back(c);
        }
        std::shuffle(mixed.begin(),mixed.end(),rng); s.build(mixed);
        for(int j=0;j<100;++j)
        {
            Vec3 p{unit(rng)*20,unit(rng)*20,unit(rng)*20};
            Bounds b{{p[0]-2,p[1]-2,p[2]-2},{p[0]+2,p[1]+2,p[2]+2}};
            auto actual=s.select(b),expected=brute(mixed,b);
            assert(actual.count==expected.count && actual.ids==expected.ids);
        }
    }
    std::cout << "Native selection checks passed (5000 mixed-light brute-force comparisons)\n";
    for(bool dense:{false,true}) for(int n:{256,1024,4096})
    {
        std::vector<Candidate> lights; std::vector<Bounds> receivers;
        const float extent=dense ? 5.f : 250.f;
        for(int i=0;i<n;++i) lights.push_back(point(i,{unit(rng)*extent,unit(rng)*extent,unit(rng)*extent},10));
        for(int i=0;i<1000;++i) { Vec3 p{unit(rng)*extent,unit(rng)*extent,unit(rng)*extent}; receivers.push_back({{p[0]-1,p[1]-1,p[2]-1},{p[0]+1,p[1]+1,p[2]+1}}); }
        std::vector<double> times; size_t visits=0,scored=0; volatile size_t sink=0;
        for(int run=0;run<31;++run)
        {
            auto start=std::chrono::steady_clock::now(); s.build(lights);
            size_t v=0,c=0;
            for(const auto& receiver:receivers) { sink+=s.select(receiver).count; auto stats=s.statistics(); v+=stats.visits; c+=stats.scored; }
            auto end=std::chrono::steady_clock::now();
            if(run) times.push_back(std::chrono::duration<double,std::milli>(end-start).count());
            visits=v; scored=c;
        }
        std::sort(times.begin(),times.end());
        std::cout<<(dense?"dense":"sparse")<<","<<n<<",median_ms="<<times[15]<<",p95_ms="<<times[28]<<",visits="<<visits<<",scored="<<scored<<"\n";
    }
}
