"""Exercise production media priorities and Windows timer transitions with stubs."""
from pathlib import Path
import subprocess
import tempfile
from test_camera_smoothing import ROOT, function


def main():
    source = (ROOT / 'indra/llplugin/slplugin/slplugin.cpp').read_text()
    timer = source[source.index('        const bool needs_high_resolution'):]
    timer = timer[:timer.index('#endif')]
    code = r'''
#include <cassert>
#include <cmath>
#include <iostream>
#include <string>
#define LLPLUGIN_MESSAGE_CLASS_MEDIA "media"
#define LL_DEBUGS(x) std::cout
#define LL_ENDL std::endl
struct LLPluginMessage {
    LLPluginMessage(const char*, const char*) {}
    void setValue(const char*, const std::string&) {}
};
struct Plugin {
    double sleep = 0;
    void setSleepTime(double v) { sleep = v; }
    double getSleepTime() const { return sleep; }
};
struct LLPluginClassMedia {
    enum EPriority { PRIORITY_UNLOADED, PRIORITY_STOPPED, PRIORITY_HIDDEN,
        PRIORITY_SLIDESHOW, PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_HIGH };
    EPriority mPriority = PRIORITY_UNLOADED;
    double mSleepTime = 1;
    Plugin* mPlugin;
    int sends = 0, sizes = 0;
    static const char* priorityToString(EPriority);
    void setPriority(EPriority);
    void sendMessage(const LLPluginMessage&) { ++sends; }
    void setSizeInternal() { ++sizes; }
};
constexpr int TIMERR_NOERROR = 0;
int begins = 0, ends = 0;
bool timer_ok = true;
int timeBeginPeriod(int period) { assert(period == 1); ++begins; return timer_ok ? 0 : 1; }
void timeEndPeriod(int period) { assert(period == 1); ++ends; }
void near(double a, double b) { assert(std::abs(a-b) < 1e-8); }
'''
    path = 'indra/llplugin/llpluginclassmedia.cpp'
    code += function(path, 'const char* LLPluginClassMedia::priorityToString(')
    code += function(path, 'void LLPluginClassMedia::setPriority(')
    code += '\nvoid tick(Plugin* plugin, bool& high_resolution_timer) {\n' + timer + '\n}\n'
    code += r'''
int main() {
    Plugin process; LLPluginClassMedia media; media.mPlugin = &process;
    bool precise = false;
    media.setPriority(LLPluginClassMedia::PRIORITY_NORMAL);
    near(process.sleep, 1.0/120); tick(&process, precise);
    assert(precise && begins == 1 && ends == 0);
    media.setPriority(LLPluginClassMedia::PRIORITY_HIGH);
    near(process.sleep, 1.0/120); tick(&process, precise);
    assert(begins == 1); // no duplicate timer request while active
    media.setPriority(LLPluginClassMedia::PRIORITY_LOW);
    near(process.sleep, 1.0/25); tick(&process, precise);
    assert(!precise && ends == 1);
    for (auto priority : {LLPluginClassMedia::PRIORITY_HIDDEN, LLPluginClassMedia::PRIORITY_SLIDESHOW,
                         LLPluginClassMedia::PRIORITY_STOPPED, LLPluginClassMedia::PRIORITY_UNLOADED}) {
        media.setPriority(priority); near(process.sleep, 1); tick(&process, precise);
        assert(!precise && begins == 1 && ends == 1);
    }
    media.setPriority(LLPluginClassMedia::PRIORITY_NORMAL);
    timer_ok = false; tick(&process, precise); assert(!precise && ends == 1);
    timer_ok = true; tick(&process, precise); assert(precise && begins == 3);
    int sends = media.sends;
    media.setPriority(LLPluginClassMedia::PRIORITY_NORMAL);
    assert(media.sends == sends && media.sends == media.sizes);
    media.mPlugin = nullptr;
    media.setPriority(LLPluginClassMedia::PRIORITY_LOW);
    near(media.mSleepTime, 1.0/25);
}
'''
    with tempfile.TemporaryDirectory() as temp:
        cpp = Path(temp) / 'pacing.cpp'; exe = Path(temp) / 'pacing.exe'
        cpp.write_text(code)
        subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print('Browser priority and timer transitions passed.')


if __name__ == '__main__':
    main()
