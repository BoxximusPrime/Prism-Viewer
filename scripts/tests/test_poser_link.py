"""Run production Poser protocol/session code with deterministic socket/UI doubles.

No login or avatar changes. Pose application/restoration is separately covered by
test_pose_studio.py. Real viewer skinning, UI and background pacing need an in-world check.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'indra/newview/llposerlink.cpp').read_text(encoding='utf-8')
source = re.sub(r'^#include .*$', '', source, flags=re.MULTILINE)
harness = r'''
#include "llposerlink.h"
#include "llposerlinkprotocol.h"
#include <cassert>
#include <algorithm>
#include <deque>
#include <functional>
#include <memory>
#include <vector>
#include <iostream>
#include <limits>
#include <cstring>
using U32=unsigned;using U64=unsigned long long;
using apr_size_t=size_t;using apr_status_t=int;using apr_pool_t=int;
constexpr int APR_SUCCESS=0, AGAIN=1, EOF_RESULT=2, APR_TCP_NODELAY=0;
#define APR_STATUS_IS_EAGAIN(x) ((x)==AGAIN)
struct apr_socket_t {std::string input,output;bool eof=false,blocked=false;size_t chunk=8192,send_chunk=99999;};
std::deque<apr_socket_t*> incoming;
int apr_pool_create(apr_pool_t** pool,void*){*pool=new int;return 0;}
void apr_pool_destroy(apr_pool_t* pool){delete pool;}
int apr_socket_accept(apr_socket_t** out,apr_socket_t*,apr_pool_t*) {
    if(incoming.empty())return AGAIN;*out=incoming.front();incoming.pop_front();return 0;
}
int apr_socket_opt_set(apr_socket_t*,int,int){return 0;}
int apr_socket_recv(apr_socket_t* s,char* buffer,size_t* n) {
    if(s->input.empty()){*n=0;return s->eof?EOF_RESULT:AGAIN;}
    *n=std::min({*n,s->input.size(),s->chunk});std::memcpy(buffer,s->input.data(),*n);s->input.erase(0,*n);return 0;
}
int apr_socket_send(apr_socket_t* s,const char* buffer,size_t* n) {
    if(s->blocked){*n=0;return AGAIN;}*n=std::min(*n,s->send_chunk);s->output.append(buffer,*n);return 0;
}
struct LLSocket {
    using ptr_t=std::shared_ptr<LLSocket>;static constexpr int STREAM_TCP=1;
    apr_socket_t* socket;apr_pool_t* pool=nullptr;
    ~LLSocket(){delete pool;}
    apr_socket_t* getSocket(){return socket;}
    static ptr_t create(void*,int,unsigned short port,const char* host) {
        assert(port==17635&&std::string(host)=="127.0.0.1");static apr_socket_t listener;
        return std::make_shared<LLSocket>(LLSocket{&listener});
    }
    static ptr_t create(apr_socket_t* s,apr_pool_t* p){auto v=std::make_shared<LLSocket>();v->socket=s;v->pool=p;return v;}
};
float now=0;
struct LLTimer {float start=now;float getElapsedTimeF32()const{return now-start;}void reset(){start=now;}};
struct LLSD {int option=0;std::string text;LLSD& operator[](const char*){return *this;}LLSD& operator=(const std::string& s){text=s;return *this;}};
using LLNotificationPtr=std::shared_ptr<int>;
namespace LLNotificationsUtil {
    using Callback=std::function<void(const LLSD&,const LLSD&)>;
    std::vector<Callback> callbacks;int notices=0;
    LLNotificationPtr add(const std::string&){++notices;return {};}
    LLNotificationPtr add(const std::string&,const LLSD& args,const LLSD&,Callback fn){
        assert(args.text=="123456");callbacks.push_back(fn);return std::make_shared<int>(int(callbacks.size()-1));
    }
    void cancel(LLNotificationPtr p){auto callback=callbacks.at(*p);LLSD no;no.option=1;callback({},no);}
    int getSelectedOption(const LLSD&,const LLSD& reply){return reply.option;}
    void respond(int option){auto callback=callbacks.back();LLSD reply;reply.option=option;callback({},reply);}
}
constexpr int STATE_STARTED=1,AGENT_CONTROL_STOP=1;
bool connected=true,gDisconnected=false;
struct LLStartUp {static int getStartupState(){return connected?STATE_STARTED:0;}};
struct LLAppViewer {bool quit=false;static LLAppViewer* instance(){static LLAppViewer v;return &v;}bool quitRequested(){return quit;}};
struct Avatar {bool isBuilt(){return true;}bool getIsAppearanceAnimating(){return false;}} avatar;
Avatar* gAgentAvatarp=&avatar;bool isAgentAvatarValid(){return gAgentAvatarp!=nullptr;}
struct LLAgent {static constexpr int TELEPORT_NONE=0;int teleport=0;int getTeleportState(){return teleport;}
    void stopAutoPilot(bool){}void resetControlFlags(){}void setControlFlags(int){}
} gAgent;
struct Camera {void clearGeneralKeys(){}} gAgentCamera;
struct LLPoseStudio {
    bool active=false;U32 session=0;int poses=0,ends=0;LLPoserLinkProtocol::Rotations last;
    static LLPoseStudio& instance(){static LLPoseStudio v;return v;}static bool instanceExists(){return true;}
    bool isActive()const{return active;}U32 getSession()const{return session;}
    bool begin(Avatar&){if(active)return false;active=true;++session;return true;}
    void end(){active=false;++ends;}
    bool applyLocalRotations(const LLPoserLinkProtocol::Rotations& r){last=r;++poses;return true;}
};
'''+source+r'''
void connect(apr_socket_t& socket){incoming.push_back(&socket);LLPoserLink::update();}
void request(apr_socket_t& socket){socket.input="POSER-LINK 1 123456\n";connect(socket);}
void approve(){LLNotificationsUtil::respond(0);LLPoserLink::update();assert(LLPoserLink::isLinked());}
int main(){
    using namespace LLPoserLinkProtocol;
    std::string code;
    assert(hello("POSER-LINK 1 123456",code)&&code=="123456");
    for(const auto text:{"POSER-LINK 2 123456","POSER-LINK 1 x23456","GET / HTTP/1.1","POSER-LINK 1 123456 extra"})assert(!hello(text,code));
    Rotations decoded;
    assert(decodePose("POSE 2 mPelvis 0 0 0 1 mWristLeft 0.7071068 0 0 0.7071068",decoded));
    assert(decoded.size()==2);
    for(const auto text:{"POSE 0","POSE 161","POSE -1","POSE 1 mPelvis 0 0 0 0","POSE 1 mPelvis 0 0 0 2",
        "POSE 1 mPelvis nan 0 0 1","POSE 1 mPelvis inf 0 0 1","POSE 1 mPelvis 1e999 0 0 1",
        "POSE 1 mPelvis 0 0 0 1 trailing","POSE 2 mPelvis 0 0 0 1 mPelvis 0 0 0 1","POSE 2 mPelvis 0 0 0 1"}) {
        assert(!decodePose(text,decoded));assert(decoded.size()==2);
    }
    assert(!decodePose(std::string(MAX_LINE+1,'x'),decoded));
    auto& studio=LLPoseStudio::instance();
    {apr_socket_t s;request(s);assert(s.output=="WAIT\n"&&!studio.active&&studio.poses==0);
     LLNotificationsUtil::respond(1);LLPoserLink::update();assert(s.output=="WAIT\nREJECT\n"&&!studio.active);}
    {apr_socket_t s;s.chunk=2;s.send_chunk=2;request(s);
     for(int i=0;i<20;++i)LLPoserLink::update();assert(s.output=="WAIT\n"&&!studio.active);
     approve();s.input="POSE 1 mPelvis 0 0 0 1\n";
     for(int i=0;i<20;++i)LLPoserLink::update();assert(studio.poses==1&&s.output=="WAIT\nREADY\nOK\n");
     apr_socket_t busy;connect(busy);assert(busy.output=="BUSY\n"&&LLPoserLink::isLinked());
     s.input="POSE 1 mPelvis 0.7071068 0 0 0.7071068\n";
     for(int i=0;i<20;++i)LLPoserLink::update();assert(studio.poses==2&&studio.last.at("mPelvis")[0]>.7f);
     LLPoserLink::disconnect();assert(!studio.active);for(int i=0;i<10;++i)LLPoserLink::update();assert(s.output.ends_with("STOP\n"));}
    {apr_socket_t s;request(s);auto stale=LLNotificationsUtil::callbacks.back();LLPoserLink::shutdown();
     apr_socket_t next;request(next);stale({},{});assert(!studio.active&&next.output=="WAIT\n");LLPoserLink::shutdown();}
    {apr_socket_t s;s.input="POSER-LINK 1 123456\nPOSE 1 mPelvis 0 0 0 1\n";connect(s);
     assert(!studio.active&&s.output=="WAIT\nERROR\n");}
    {apr_socket_t s;s.input="POSE 1 mPelvis 0 0 0 1\n";connect(s);assert(!studio.active&&s.output=="ERROR\n");}
    {apr_socket_t s;request(s);approve();s.eof=true;LLPoserLink::update();assert(!studio.active);}
    {apr_socket_t s;request(s);approve();now+=11;LLPoserLink::update();assert(!studio.active&&!link().client);}
    {apr_socket_t s;request(s);now+=121;LLPoserLink::update();assert(!link().client&&!studio.active);}
    {apr_socket_t s;request(s);approve();s.input=std::string(MAX_LINE+1,'x');LLPoserLink::update();assert(!studio.active);}
    {apr_socket_t s;request(s);approve();studio.end();studio.begin(avatar);LLPoserLink::update();
     assert(studio.active&&s.output.ends_with("STOP\n"));studio.end();}
    {apr_socket_t s;request(s);approve();gAgent.teleport=1;LLPoserLink::update();assert(!studio.active&&!link().listener);gAgent.teleport=0;}
    {apr_socket_t s;request(s);approve();gDisconnected=true;LLPoserLink::update();assert(!studio.active);gDisconnected=false;}
    {apr_socket_t s;request(s);approve();s.input="POSE 1 mPelvis 0 0 0 0\n";LLPoserLink::update();assert(!studio.active&&s.output.ends_with("ERROR\n"));}
    {apr_socket_t s;request(s);approve();s.blocked=true;LLPoserLink::disconnect();assert(!studio.active);
     now+=2;LLPoserLink::update();assert(!link().client);}
    LLPoserLink::shutdown();
    std::cout<<"PASS: protocol validation, split reads/writes, consent/reject, stale approval, no pre-approval poses, busy, updates, stop, EOF, timeout, flood, ownership, teleport/logout and blocked peer\n";
}
'''
notifications = ET.parse(ROOT / 'indra/newview/skins/default/xui/en/notifications.xml').getroot()
prompt = notifications.find("notification[@name='PoserLinkRequest']")
assert prompt.get('type') == 'alertmodal'
assert prompt.find(".//button[@index='1']").get('default') == 'true'
assert prompt.find('ignore') is None
with tempfile.TemporaryDirectory(prefix='poser-link-test-') as tmp:
    path = Path(tmp)
    (path / 'test.cpp').write_text(harness, encoding='utf-8')
    subprocess.run(['g++', '-std=c++20', '-O1', '-I'+str(ROOT / 'indra/newview'), str(path / 'test.cpp'), '-o', str(path / 'test.exe')], check=True)
    subprocess.run([str(path / 'test.exe')], check=True)
