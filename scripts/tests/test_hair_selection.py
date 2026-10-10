"""Compile the production name matcher and check hair/SSS selection boundaries."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    source = (ROOT / 'indra/newview/llvovolume.cpp').read_text()
    matcher = source[source.index('bool matchesSurfaceNames('):
                     source.index('bool isUsableSSSDescription(')]
    cpp = r'''
#include <algorithm>
#include <cassert>
#include <cctype>
#include <cstdio>
#include <map>
#include <sstream>
#include <string>
#include <vector>
std::map<std::string, std::string> gSavedSettings;
template<class T> struct LLCachedControl {
    std::string key;
    LLCachedControl(decltype(gSavedSettings)&, const char* name) : key(name) {}
    operator const T&() const { return gSavedSettings[key]; }
};
struct LLStringUtil {
    static void toLower(std::string& s) {
        for (char& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    static void trim(std::string& s) {
        const auto first = s.find_first_not_of(" \t\r\n");
        s = first == std::string::npos ? "" : s.substr(first, s.find_last_not_of(" \t\r\n") - first + 1);
    }
    static std::vector<std::string> getTokens(const std::string& s, const char*) {
        std::vector<std::string> result;
        std::istringstream stream(s);
        for (std::string token; std::getline(stream, token, ',');) result.push_back(token);
        return result;
    }
};
@MATCHER@
int main() {
    gSavedSettings["BoxxyHairNames"] = "hair";
    for (const char* name : {"hair", "HAIRSTYLE", "[Brand] hair - black", "Brand_hair", "chair hair"})
        assert(matchesSurfaceNames(name, 2));
    for (const char* name : {"chair", "armchair", "wheelchair", "", "ha ir", "1hair"})
        assert(!matchesSurfaceNames(name, 2));
    gSavedSettings["BoxxyHairNames"] = "  PONYTAIL , , hair  ";
    assert(matchesSurfaceNames("Brand Ponytail", 2));
    assert(matchesSurfaceNames("Hair", 2));
    assert(!matchesSurfaceNames("chair", 2));
    gSavedSettings["BoxxyHairNames"] = "";
    assert(!matchesSurfaceNames("Hair", 2));
    gSavedSettings["BoxxyHairNames"] = "wig";
    assert(!matchesSurfaceNames("Hair", 2));
    assert(matchesSurfaceNames("[WIG]", 2));
    // The shared cache must preserve SSS's existing substring semantics.
    gSavedSettings["BoxxySSSWhitelist"] = "body";
    gSavedSettings["BoxxySSSOverlayNames"] = "tattoo";
    assert(matchesSurfaceNames("eBODY"));
    assert(matchesSurfaceNames("eTattoo", 1));
    assert(!matchesSurfaceNames("eBODY", 2));
    assert(!matchesSurfaceNames("wig"));
    puts("Passed hair name boundaries, case, custom terms, cache invalidation and SSS isolation");
}
'''.replace('@MATCHER@', matcher)
    compiler = shutil.which('g++')
    assert compiler, 'g++ is required'
    with tempfile.TemporaryDirectory(prefix='boxxy-hair-selection-') as directory:
        src, exe = Path(directory) / 'test.cpp', Path(directory) / 'test.exe'
        src.write_text(cpp)
        subprocess.run([compiler, '-std=c++17', str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
