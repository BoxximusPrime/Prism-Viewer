"""Run Pose Studio's file helpers against the built Release LLSD/file libraries.

Requires the configured Windows Release build. No viewer or account interaction.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build-vc170-64"
NS = {"m": "http://schemas.microsoft.com/developer/msbuild/2003"}


def release_settings(project):
    root = ET.parse(project).getroot()
    return next(e for e in root.findall("m:ItemDefinitionGroup", NS)
                if "Release|x64" in e.get("Condition", ""))


def entries(group, tag):
    return [v for v in group.find(f".//m:{tag}", NS).text.split(";") if not v.startswith("%")]


source = (ROOT / "indra/newview/llfloaterposestudio.cpp").read_text(encoding="utf-8")
helpers = source[source.index("bool writePoseFile("):source.index("void poseFileError(")]
program = r'''
#include "linden_common.h"
#include "llcommon.h"
#include "llerrorcontrol.h"
#include "llfile.h"
#include "llsdserialize.h"
#include "lluuid.h"
#include <cassert>
#include <filesystem>
#include <sstream>
#include <iostream>
''' + helpers + r'''
#undef assert
#define assert(condition) do { if (!(condition)) {std::cerr<<"FAILED "<<#condition<<" at "<<__LINE__<<"\n";return 1;} } while (0)
int main() try {
    LLCommon::initClass();
    LLError::initForApplication(".", ".", true);
    const std::string filename = "pose test é骨.xml";
    LLSD pose;
    pose["format"] = "PrismPose"; pose["version"] = 1;
    for (int bone=0; bone<160; ++bone) {
        auto& joint=pose["joints"]["mBone"+std::to_string(bone)];
        for (int i=0; i<3; ++i) joint["position"].append((bone-i)*.001234567);
        for (double v : {.1,.2,.3,.92736185}) joint["rotation"].append(v);
    }
    assert(writePoseFile(filename,pose));
    const auto restored=readPoseFile(filename);
    assert(restored["format"].asString()=="PrismPose" && restored["version"].asInteger()==1);
    assert(restored["joints"].size()==160);
    for (int bone=0; bone<160; ++bone) {
        const auto name="mBone"+std::to_string(bone);
        for (const auto key : {"position","rotation"})
            for (int i=0;i<pose["joints"][name][key].size();++i)
                assert(fabs(restored["joints"][name][key][i].asReal()-pose["joints"][name][key][i].asReal())<1e-8);
    }
    pose["joints"]["mBone0"]["position"][0]=.75;
    assert(writePoseFile(filename,pose)); // overwrite existing file
    assert(readPoseFile(filename)["joints"]["mBone0"]["position"][0].asReal()==.75);
    const auto wide=std::filesystem::u8path(filename).wstring();
    HANDLE locked=CreateFileW(wide.c_str(),GENERIC_READ,0,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    assert(locked!=INVALID_HANDLE_VALUE);
    pose["joints"]["mBone0"]["position"][0]=.5;
    assert(!writePoseFile(filename,pose));
    // Replacement failed; the original must survive.
    CloseHandle(locked);
    assert(readPoseFile(filename)["joints"]["mBone0"]["position"][0].asReal()==.75);
    assert(!writePoseFile("missing_folder/pose.xml",pose));
    assert(!readPoseFile("missing.xml").isMap());
    { llofstream bad("bad.xml"); bad<<"<llsd><map><key>unfinished</key>"; }
    assert(!readPoseFile("bad.xml").isMap());
    { llofstream large("large.xml"); large<<std::string(2*1024*1024+1,'x'); }
    assert(!readPoseFile("large.xml").isMap());
    { llofstream empty("empty.xml"); }
    assert(!readPoseFile("empty.xml").isMap());
    for (const auto& file : std::filesystem::directory_iterator("."))
        assert(file.path().extension()!=".tmp");
    std::cout<<"PASS: native XML round-trip, Unicode paths, overwrite, locked-file preservation, temporary cleanup and malformed/oversized/missing files\n";
} catch (const std::exception& error) { std::cerr<<"EXCEPTION: "<<error.what()<<"\n";return 2; }
'''

cache = (BUILD / "CMakeCache.txt").read_text(encoding="utf-8")
vs = Path(re.search(r"^CMAKE_GENERATOR_INSTANCE:[^=]+=(.+)$", cache, re.M)[1].strip())
setup = subprocess.run(f'"{vs / "VC/Auxiliary/Build/vcvars64.bat"}" >nul && set',
                       shell=True, capture_output=True, text=True, check=True)
env = dict(os.environ)
for line in setup.stdout.splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        env[key] = value
common = release_settings(BUILD / "llcommon/llcommon.vcxproj")
viewer = release_settings(BUILD / "newview/secondlife-bin.vcxproj")
includes = ["/I" + v for e in common.findall(".//m:AdditionalIncludeDirectories", NS)
            for v in e.text.split(";") if not v.startswith("%")]
defines = ["/D" + v for v in entries(common, "PreprocessorDefinitions")
           if v != "NDEBUG" and not v.startswith("CMAKE_INTDIR")]
libraries = [str((BUILD / "newview" / v).resolve()) if "\\" in v else v
             for v in entries(viewer, "AdditionalDependencies")]
with tempfile.TemporaryDirectory(prefix="prism-pose-files-") as directory:
    folder = Path(directory)
    # The Release library includes Tracy. Supply a test-only copy whose listen
    # operation fails before opening a socket, avoiding firewall prompts.
    tracy = BUILD / "packages/include/tracy"
    sockets = (tracy / "common/TracySocket.cpp").read_text(encoding="utf-8")
    start = sockets.index("bool ListenSocket::Listen(")
    end = sockets.index("\n}", start) + 2
    sockets = sockets[:start] + "bool ListenSocket::Listen(uint16_t, int) { return false; }" + sockets[end:]
    (folder / "test_sockets.cpp").write_text(sockets, encoding="utf-8")
    profiler = (tracy / "TracyClient.cpp").read_text(encoding="utf-8").replace('"common/TracySocket.cpp"', '"test_sockets.cpp"')
    (folder / "test_profiler.cpp").write_text(profiler, encoding="utf-8")
    (folder / "files.cpp").write_text(program, encoding="utf-8")
    compiler = sorted((vs / "VC/Tools/MSVC").glob("*/bin/Hostx64/x64/cl.exe"))[-1]
    command = [str(compiler), "/nologo", "/std:c++20", "/EHsc", "/MD", "/O2", "/utf-8",
               *includes, "/I" + str(tracy / "common"), *defines,
               "files.cpp", "test_profiler.cpp", "/Fe:files.exe", "/link",
               "/LIBPATH:" + str(BUILD / "packages/lib/release"), *libraries]
    result = subprocess.run(command, cwd=folder, env=env, capture_output=True, text=True)
    if result.returncode:
        print(result.stdout, result.stderr)
        raise SystemExit(result.returncode)
    subprocess.run([str(folder / "files.exe")], cwd=folder, env=env, check=True)
