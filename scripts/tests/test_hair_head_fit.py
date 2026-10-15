"""Production radial head fitting: nested mouth surfaces cannot trap pinned roots."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
CODE = r'''
#include "llhairguidefit.h"
#include <array>
#include <cassert>
#include <iostream>
using Triangle=std::array<glm::vec3,3>;
int main() {
    for (int nodes : {9,17,32}) for (int chains : {4,30,64}) {
        std::vector<glm::vec4> guides(chains*nodes*3);
        for(int c=0;c<chains;++c)for(int n=0;n<nodes;++n) {
            float angle=6.28318530718f*c/chains;
            guides[c*nodes*3+n]=glm::vec4(.04f*cosf(angle),.04f*sinf(angle),-.392f*n/(nodes-1),1);
        }
        std::vector<Triangle> shell;
        // Head box plus an inner mouth wall, deliberately with either winding.
        for(float x : {-.10f,.12f,.055f}) {
            glm::vec3 a(x,-.1f,-.12f),b(x,.1f,-.12f),c(x,.1f,.05f),d(x,-.1f,.05f);
            shell.push_back({a,b,c});shell.push_back({a,c,d});
        }
        for(float y : {-.1f,.1f}) {
            glm::vec3 a(-.1f,y,-.12f),b(.12f,y,-.12f),c(.12f,y,.05f),d(-.1f,y,.05f);
            shell.push_back({a,b,c});shell.push_back({a,c,d});
        }
        std::vector<float> baseline;
        for(int order=0;order<2;++order) {
            std::vector<float> radii(chains*nodes);unsigned tests=0;
            for(auto& triangle : shell)
                assert(LLHairMesh::headClearanceTriangle(triangle.data(),guides,chains,nodes,radii,tests));
            for(int c=0;c<chains;++c) {
                // Head nodes use the outer silhouette. Interior and negative hits cannot win.
                for(int n=0;n<nodes;++n) {
                    if(guides[c*nodes*3+n].z>=-.12f) assert(radii[c*nodes+n]>.109f && radii[c*nodes+n]<.18f);
                    else assert(radii[c*nodes+n]==0.f);
                }
            }
            assert(std::abs(radii[0]-.13f)<1.e-5f); // mouth is at .055, exterior at .12
            if(order==0)baseline=radii;else for(size_t i=0;i<radii.size();++i)assert(std::abs(radii[i]-baseline[i])<1.e-6f);
            assert(tests<=1000000);
            std::reverse(shell.begin(),shell.end());
            for(auto& triangle:shell)std::swap(triangle[0],triangle[2]);
        }
        unsigned tests=1000000;std::vector<float> radii(chains*nodes);
        assert(!LLHairMesh::headClearanceTriangle(shell[0].data(),guides,chains,nodes,radii,tests));
        Triangle degenerate={glm::vec3(0),glm::vec3(0),glm::vec3(0)};tests=0;
        assert(LLHairMesh::headClearanceTriangle(degenerate.data(),guides,chains,nodes,radii,tests));
        for(float r:radii)assert(r==0.f);
    }
    // Card nodes are not at the same height as the corresponding radial nodes.
    std::vector<glm::vec4> guides(54, glm::vec4(.05f,0,-.3f,1));
    guides[27]=glm::vec4(.05f,0,.02f,1);
    Triangle wall={glm::vec3(.1f,-.1f,0),glm::vec3(.1f,.1f,0),glm::vec3(.1f,0,.1f)};
    unsigned tests=0;std::vector<float> radii(18);
    assert(LLHairMesh::headClearanceTriangle(wall.data(),guides,2,9,radii,tests));
    assert(radii[0]==0.f && std::abs(radii[9]-.11f)<1.e-6f);
    std::cout<<"PASS: outer head envelope, inner mouth rejection, both windings/orders, 4/30/64 ropes, head-only heights, hard budget, degenerates\n";
}
'''
with tempfile.TemporaryDirectory(dir=ROOT / '.logs') as directory:
    cpp, exe = Path(directory) / 'head_fit.cpp', Path(directory) / 'head_fit.exe'
    cpp.write_text(CODE)
    subprocess.run(['g++', '-std=c++17', '-O2', '-I'+str(ROOT/'indra/newview'),
                    '-I'+str(ROOT/'build-vc170-64/packages/include'), str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
