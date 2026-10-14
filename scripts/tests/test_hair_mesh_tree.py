"""Check the production shell tree covers every triangle and refits conservatively."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
CODE = r'''
#include "llhairmeshtree.h"
#include <cassert>
#include <random>
#include <iostream>
int main() {
    std::mt19937 random(42);
    for (unsigned count : {0,1,4,5,13,317,10000}) {
        std::vector<std::array<float,3>> centres(count);
        for (auto& p:centres) for(auto& x:p) x=float(random()%10000)/1000;
        LLHairMesh::Tree tree(centres);
        assert(tree.order.size()==count);
        auto order=tree.order;
        std::sort(order.begin(),order.end());
        for(unsigned i=0;i<count;++i) assert(order[i]==i);
        std::vector<unsigned> covered(count), visited(tree.nodes.size());
        std::vector<std::array<float,3>> lo(tree.nodes.size()),hi(lo.size());
        for(auto level=tree.levels.rbegin();level!=tree.levels.rend();++level)
            for(auto id:*level) {
                assert(++visited[id]==1);
                auto n=tree.nodes[id];
                assert(n[2]>id && n[2]<=tree.nodes.size());
                if(n[1]) {
                    assert(n[1]<=4 && n[0]+n[1]<=count && n[2]==id+1);
                    lo[id].fill(1e30f);hi[id].fill(-1e30f);
                    for(unsigned j=n[0];j<n[0]+n[1];++j) {
                        ++covered[j];
                        auto p=centres[tree.order[j]];
                        // Arbitrary deformation after construction must still be enclosed by refitting.
                        for(int a=0;a<3;++a) {
                            p[a]=p[a]*float((j%7)+1)-20;
                            lo[id][a]=std::min(lo[id][a],p[a]);hi[id][a]=std::max(hi[id][a],p[a]);
                        }
                    }
                } else {
                    assert(n[0]==id+1 && n[3]>n[0] && n[3]<n[2]);
                    assert(visited[n[0]] && visited[n[3]]);
                    for(int a=0;a<3;++a) {
                        lo[id][a]=std::min(lo[n[0]][a],lo[n[3]][a]);
                        hi[id][a]=std::max(hi[n[0]][a],hi[n[3]][a]);
                    }
                }
            }
        for(auto c:covered) assert(c==1);
        for(unsigned j=0;j<count;++j) for(int a=0;a<3;++a) {
            float p=centres[tree.order[j]][a]*float((j%7)+1)-20;
            assert(p>=lo[0][a] && p<=hi[0][a]);
        }
    }
    std::cout << "PASS: production BVH ordering, coverage, escape links and animated bound refits\n";
}
'''

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='hair-tree-', dir=ROOT/'build-vc170-64') as directory:
        src, exe = Path(directory)/'test.cpp', Path(directory)/'test.exe'
        src.write_text(CODE)
        subprocess.run(['g++','-std=c++17','-O2','-I',str(ROOT/'indra/newview'),str(src),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
