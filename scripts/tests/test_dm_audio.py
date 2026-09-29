"""Check DM cues, conversation restoration and attachment routing. Requires g++."""
from pathlib import Path
import re
import subprocess
import tempfile
import wave
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
viewer = root / "indra/newview"
im = (viewer / "llimview.cpp").read_text(encoding="utf-8")
container = (viewer / "llfloaterimcontainer.cpp").read_text(encoding="utf-8")
messages = (viewer / "llviewermessage.cpp").read_text(encoding="utf-8")
audio = (viewer / "llaudiosourcevo.cpp").read_text(encoding="utf-8")
dm = im.split("else if (session->isP2PSessionType())", 1)[1].split(
    "else if (session->isAdHocSessionType())", 1)[0]
restore = container.split("        if (focus_floater && session_floater->isTornOff())", 1)[1]
restore = "if (focus_floater && session_floater->isTornOff())" + restore.split(
    "\n    }\n    flashConversationItemWidget", 1)[0]
trigger = re.search(r"    const bool is_gesture_sound = [\s\S]*?;", messages).group()
attached = re.search(r"    setType\(mObjectp->getRootEdit\(\)->isAttachment\(\)[\s\S]*?;", audio).group()

# Opening-message state must survive both normal and translated delivery.
assert "timestamp, new_session);" in im
assert "time_stamp, request_id, new_session);" in im
assert "time_stamp, LLUUID::null, new_session);" in im
assert 'arg["new_session"] = new_session;' in im
assert "if (!session->isP2PSessionType() && !skip_message && !play_message_sound" in im

settings = list(ET.parse(viewer / "app_settings/settings.xml").getroot().find("map"))
settings = {key.text: dict(zip(list(value)[::2], list(value)[1::2]))
            for key, value in zip(settings[::2], settings[1::2])}
sound = {key.text: value.text for key, value in settings["UISndNewIncomingDM"].items()}["Value"]
with wave.open(str(viewer / "app_settings/sounds" / (sound + ".wav"))) as wav:
    assert wav.getnframes() > 0
panel = ET.parse(viewer / "skins/default/xui/en/panel_preferences_sound_ui.xml")
assert len(panel.findall('.//button.commit_callback[@parameter="UISndNewIncomingDM"]')) == 3
assert sound in (viewer / "llfloaterpreference.cpp").read_text(encoding="utf-8")

program = r'''
#include <cassert>
#include <map>
#include <string>
#include <vector>
std::vector<std::string> sounds;
void make_ui_sound(const char* sound) { sounds.emplace_back(sound); }
struct Settings {
    std::map<std::string, bool> values;
    bool getBOOL(const char* key) { return values[key]; }
    std::string getString(const char*) { return {}; }
} gSavedSettings;
struct Agent { bool dnd = false; bool isDoNotDisturb() { return dnd; } } gAgent;
struct LLAvatarTracker {
    bool buddy = false;
    static LLAvatarTracker& instance() { static LLAvatarTracker self; return self; }
    bool isBuddy(int) { return buddy; }
};
struct Value { bool value; bool asBoolean() { return value; } };
struct Message { bool opening; Value operator[](const char*) { return {opening}; } };
void receive(bool opening, bool play_snd_mention = false) {
    Message msg{opening}; int participant_id = 2; std::string user_preferences;
''' + dm + r'''
}
struct Floater {
    bool torn = true, minimized = true, visible = false, focus = false, expanded = false;
    bool isTornOff() { return torn; }
    bool isMinimized() { return minimized; }
    bool hasFocus() { return focus; }
    void restoreFloater() { expanded = true; }
    void setMinimized(bool b) { minimized = b; }
    void setVisibleAndFrontmost(bool b) { visible = true; focus = b; }
    void setFocus(bool b) { focus = b; }
};
void select(Floater* session_floater, bool focus_floater) {
''' + restore + r'''
}
struct Object {
    bool attachment = false, avatar = false; Object* parent = nullptr;
    bool isAttachment() { return attachment; }
    bool isAvatar() { return avatar; }
    Object* getRootEdit() { return parent && !parent->isAvatar() ? parent->getRootEdit() : this; }
};
bool gesture(int object_id, int owner_id, Object* sound_object, Object* sound_parent = nullptr) {
''' + trigger + r'''
    return is_gesture_sound;
}
struct LLAudioEngine { enum { AUDIO_TYPE_SFX, AUDIO_TYPE_GESTURE }; };
int type; void setType(int t) { type = t; }
void update(Object* mObjectp) {
''' + attached + r'''
}
int main() {
    for (bool buddy : {false, true}) {
        LLAvatarTracker::instance().buddy = buddy;
        for (bool opening : {false, true})
        for (bool reply_pref : {false, true})
        for (bool new_pref : {false, true})
        for (bool dnd : {false, true})
        for (bool mention : {false, true}) {
            gSavedSettings.values = {{"PlaySoundFriendIM", buddy && reply_pref},
                {"PlaySoundNonFriendIM", !buddy && reply_pref}, {"PlaySoundNewConversation", new_pref}};
            gAgent.dnd = dnd; sounds.clear(); receive(opening, mention);
            bool play = !dnd && !mention && (reply_pref || (opening && new_pref));
            assert(sounds.size() == (play ? 1u : 0u));
            if (play) assert(sounds[0] == (opening ? "UISndNewIncomingDM" : "UISndNewIncomingIMSession"));
        }
    }
    Floater minimized;
    select(&minimized, false);
    assert(minimized.minimized && !minimized.visible && !minimized.expanded);
    select(&minimized, true);
    assert(!minimized.minimized && minimized.visible && minimized.focus && minimized.expanded);
    Floater hidden; hidden.minimized = false;
    select(&hidden, true); assert(hidden.visible && hidden.focus);
    Floater hosted; hosted.torn = false;
    select(&hosted, true); assert(hosted.minimized && !hosted.visible);

    Object avatar{false, true}, attachment{true, false, &avatar}, child{false, false, &attachment};
    Object world, world_child{false, false, &world};
    assert(gesture(1, 1, &avatar));
    assert(gesture(2, 1, &attachment)); assert(gesture(3, 1, &child));
    assert(gesture(3, 1, nullptr, &attachment)); assert(gesture(2, 1, nullptr, &avatar));
    assert(!gesture(4, 1, &world)); assert(!gesture(5, 1, &world_child));
    assert(!gesture(6, 1, nullptr)); assert(!gesture(6, 1, nullptr, &world));
    update(&attachment); assert(type == LLAudioEngine::AUDIO_TYPE_GESTURE);
    update(&child); assert(type == LLAudioEngine::AUDIO_TYPE_GESTURE);
    attachment.attachment = false; attachment.parent = nullptr;
    update(&child); assert(type == LLAudioEngine::AUDIO_TYPE_SFX);
    update(&world); assert(type == LLAudioEngine::AUDIO_TYPE_SFX);
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "check.cpp"
    exe = Path(directory) / "check.exe"
    cpp.write_text(program, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("DM sounds, conversation restoration and attachment audio checks passed")
