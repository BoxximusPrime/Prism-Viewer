"""Exercise production IM echo matching with minimal C++ stubs. Requires g++."""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[2] / "indra/newview/llimview.cpp").read_text(encoding="utf-8")
receive = source.split("void LLIMModel::addMessage(const LLUUID& session_id,", 1)[1]
receive = receive[receive.index("    if (from_id == gAgentID)"):receive.index('    if (gSavedSettings.getBOOL("TranslateChat")')]
send = source.split("void LLIMModel::sendMessage(", 1)[1]
send = send[send.index("        if (dialog != IM_NOTHING_SPECIAL && !local_echo_text.empty())"):send.index("    // If there is a mute list")]
send = send[:send.rfind("    }")]
program = r'''
#include <cassert>
#include <map>
#include <string>
#include <vector>
struct LLIMSession { std::multimap<std::string, std::string> mPendingLocalEchoes; };
std::map<int, LLIMSession> sessions;
std::vector<std::string> displayed;
constexpr int gAgentID = 1, IM_NOTHING_SPECIAL = 0;
LLIMSession* findIMSession(int id) {
    auto it = sessions.find(id);
    return it == sessions.end() ? nullptr : &it->second;
}
void processAddingMessage(int, const std::string&, int, const std::string& text, bool, bool, unsigned) {
    displayed.push_back(text);
}
void send(int id, int dialog, const std::string& utf8_text, const std::string& local_echo_text) {
    auto* session = findIMSession(id);
''' + send + r'''
}
void receive(int session_id, int from_id, const std::string& utf8_text) {
    std::string from = "Resident";
    bool log2file = true, is_region_msg = false;
    unsigned time_stamp = 0;
''' + receive + r'''
    displayed.push_back(utf8_text);
}
int main() {
    sessions[10]; sessions[20];
    send(10, 1, "Hola", "Hola (Hello)");
    send(10, 1, "Hola", "Hola (Hi)");
    send(10, 1, "Adios", "Adios (Bye)");
    send(20, 1, "Hola", "Hola (Hey)");
    receive(10, 2, "Hola"); // Other people's messages cannot consume our echo.
    receive(10, 1, "Adios"); // Different translations may arrive out of order.
    receive(20, 1, "Hola"); // Conversations keep their own originals.
    receive(10, 1, "Hola");
    receive(10, 1, "Hola"); // Identical translations retain send order.
    receive(10, 1, "Hola"); // Consumed once, no duplicate display.
    send(10, 0, "DM", "DM (original)"); // P2P retains its existing local echo.
    send(10, 1, "Plain", "");
    receive(99, 1, "Missing session");
    assert((displayed == std::vector<std::string>{"Hola", "Adios (Bye)", "Hola (Hey)",
        "Hola (Hello)", "Hola (Hi)", "Hola", "Missing session"}));
    assert(sessions[10].mPendingLocalEchoes.empty());
    assert(sessions[20].mPendingLocalEchoes.empty());
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "test.cpp"
    exe = Path(directory) / "test.exe"
    cpp.write_text(program, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("IM translation echo checks passed")
