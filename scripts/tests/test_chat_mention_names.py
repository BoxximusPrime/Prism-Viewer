"""Exercise the production name matcher with small UI/settings stubs. Requires g++."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
source = (root / 'indra/newview/llviewerchat.cpp').read_text()
start = source.index('bool LLViewerChat::containsMention(')
end = source.index('\n}\n', start) + 3
harness = r'''
#include <cassert>
#include <string>
#include <vector>
#include <map>
#include <cwctype>
#include <locale>
#include <codecvt>
using LLWString = std::wstring;
LLWString utf8str_to_wstring(const std::string& s) {
    return std::wstring_convert<std::codecvt_utf8<wchar_t>>().from_bytes(s);
}
struct LLStringUtil {
    static std::vector<std::string> getTokens(const std::string& s, const std::string& delimiters) {
        std::vector<std::string> result;
        for (auto start = s.find_first_not_of(delimiters); start != std::string::npos;) {
            auto end = s.find_first_of(delimiters, start);
            result.push_back(s.substr(start, end - start));
            start = end == std::string::npos ? end : s.find_first_not_of(delimiters, end);
        }
        return result;
    }
};
struct LLWStringUtil {
    static void toLower(LLWString& s) { for (auto& c : s) c = std::towlower(c); }
    static bool isPartOfWord(wchar_t c) { return c == '_' || std::iswalnum(c); }
    static void trim(LLWString& s) {
        while (!s.empty() && std::iswspace(s.front())) s.erase(s.begin());
        while (!s.empty() && std::iswspace(s.back())) s.pop_back();
    }
};
struct Settings {
    std::map<std::string, bool> flags{{"ChatMentionNamesEnabled",true},{"ChatMentionInNearby",true},
        {"ChatMentionInIM",true},{"ChatMentionWholeWords",true},{"ChatMentionCaseSensitive",false}};
    std::string names;
    bool getBOOL(const std::string& key) { return flags.at(key); }
    std::string getString(const std::string& key) { assert(key == "ChatMentionNames"); return names; }
} gSavedSettings;
struct LLUrlRegistry {
    static LLUrlRegistry& instance() { static LLUrlRegistry registry; return registry; }
    bool containsAgentMention(const std::string& s) {
        return s.find("secondlife:///app/agent/self/mention") != std::string::npos;
    }
};
struct LLViewerChat { static bool containsMention(const std::string&, bool = false); };
''' + source[start:end] + r'''
int main() {
    assert(!LLViewerChat::containsMention("anything"));
    gSavedSettings.names = " , Ann ,\nTrevor Resident\n t.revor, ++ ";
    for (auto text : {"Ann", "@ANN!", "Hi, Ann.", "annex then Ann", "Trevor Resident?", "t.revor!", "hey ++!"})
        assert(LLViewerChat::containsMention(text));
    for (auto text : {"announcement", "Ann2", "x_Ann", "Ann_name", "tXrevor", "TrevorResidents", ""})
        assert(!LLViewerChat::containsMention(text));
    gSavedSettings.flags["ChatMentionCaseSensitive"] = true;
    assert(!LLViewerChat::containsMention("ann"));
    assert(LLViewerChat::containsMention("Ann"));
    gSavedSettings.flags["ChatMentionWholeWords"] = false;
    assert(LLViewerChat::containsMention("Announcement"));
    gSavedSettings.flags["ChatMentionInNearby"] = false;
    assert(!LLViewerChat::containsMention("Ann", true));
    assert(LLViewerChat::containsMention("Ann", false));
    gSavedSettings.flags["ChatMentionInIM"] = false;
    assert(!LLViewerChat::containsMention("Ann", false));
    gSavedSettings.flags["ChatMentionNamesEnabled"] = false;
    assert(LLViewerChat::containsMention("secondlife:///app/agent/self/mention", true));
    assert(LLViewerChat::containsMention("secondlife:///app/agent/self/mention", false));
    gSavedSettings.flags["ChatMentionNamesEnabled"] = true;
    gSavedSettings.flags["ChatMentionInIM"] = true;
    gSavedSettings.names = "\n,\t, ";
    assert(!LLViewerChat::containsMention("anything"));
    gSavedSettings.names = "çŒ«";
    assert(LLViewerChat::containsMention("hello çŒ«!"));
}
'''
settings = ET.parse(root / 'indra/newview/app_settings/settings.xml').getroot()
keys = {k.text for k in settings.iter('key')}
ui = ET.parse(root / 'indra/newview/skins/default/xui/en/floater_chat_mention_settings.xml').getroot()
for control in ui.iter():
    if control.get('control_name'):
        assert control.get('control_name') in keys
im = (root / 'indra/newview/llimview.cpp').read_text()
assert 'containsAgentMention(' not in im
assert im.count('LLViewerChat::containsMention(') == 3
nearby = (root / 'indra/newview/llfloaterimnearbychathandler.cpp').read_text()
assert 'LLViewerChat::containsMention(chat_msg.mText, true)' in nearby
assert 'chat_msg.mChatStyle != CHAT_STYLE_HISTORY && !gAgent.isDoNotDisturb()' in nearby
assert source.count('&& containsMention(chat.mText, chat.mSessionID.isNull())') == 2
prefs = ET.parse(root / 'indra/newview/skins/default/xui/en/panel_preferences_chat.xml').getroot()
button = next(n for n in prefs if n.get('name') == 'mention_settings')
assert button.find('button.commit_callback').get('parameter') == 'chat_mention_settings'
with tempfile.TemporaryDirectory() as directory:
    cpp, binary = Path(directory) / 'check.cpp', Path(directory) / 'check.exe'
    cpp.write_text(harness, encoding='utf-8')
    subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('Mention names, scopes, literal matching, Unicode, word boundaries and integrations passed.')
