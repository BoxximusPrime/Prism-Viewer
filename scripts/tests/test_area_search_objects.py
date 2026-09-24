"""Exercise area-search scanning and throttled property requests from production C++."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "indra/newview/llfloaterareasearch.cpp").read_text(encoding="utf-8")


def extract_function(signature):
    start = SOURCE.index(signature)
    opening = SOURCE.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (SOURCE[end] == "{") - (SOURCE[end] == "}")
        end += 1
    return SOURCE[start:end]


constants = "\n".join(
    re.search(rf"constexpr (?:F64|U32) {name} = [^;]+;", SOURCE).group(0)
    for name in (
        "REQUEST_TIMEOUT",
        "MAX_ATTEMPTS",
        "MAX_OBJECTS_PER_PACKET",
        "MAX_REQUESTS_PER_REGION",
        "REFILL_REQUESTS_PER_REGION",
    )
)

HARNESS = r'''#include <algorithm>
#include <cassert>
#include <cmath>
#include <iostream>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

using F64 = double;
using F32 = float;
using U32 = unsigned int;
using S32 = int;
using LLUUID = std::string;
constexpr int LL_PCODE_VOLUME = 1;
constexpr int LL_PCODE_LEGACY_TREE = 2;
constexpr int LL_PCODE_LEGACY_GRASS = 3;
constexpr const char* _PREHASH_ObjectSelect = "ObjectSelect";
constexpr const char* _PREHASH_ObjectDeselect = "ObjectDeselect";
constexpr const char* _PREHASH_AgentData = "AgentData";
constexpr const char* _PREHASH_AgentID = "AgentID";
constexpr const char* _PREHASH_SessionID = "SessionID";
constexpr const char* _PREHASH_ObjectData = "ObjectData";
constexpr const char* _PREHASH_ObjectLocalID = "ObjectLocalID";

struct LLViewerRegion {
    std::string host;
    bool alive = true;
    bool isAlive() const { return alive; }
    const std::string& getHost() const { return host; }
};
LLViewerRegion default_region{"default"};

struct LLMessageSystem {
    struct Message {
        std::string type;
        std::string host;
        std::vector<U32> local_ids;
        bool has_agent_data = false, has_agent_id = false, has_session_id = false;
        bool object_data_open = false;
        LLUUID agent_id, session_id;
    };
    std::vector<Message> sent;
    Message current;
    U32 max_object_blocks = 100000;
    bool active = false;
    void newMessageFast(const char* type) {
        current = Message{};
        current.type = type;
        active = true;
    }
    void nextBlockFast(const char* block) {
        current.object_data_open = std::string(block) == _PREHASH_ObjectData;
        if (std::string(block) == _PREHASH_AgentData) current.has_agent_data = true;
    }
    void addUUIDFast(const char* field, const LLUUID& id) {
        assert(active && current.has_agent_data && !current.object_data_open);
        if (std::string(field) == _PREHASH_AgentID) {
            current.has_agent_id = true;
            current.agent_id = id;
        }
        if (std::string(field) == _PREHASH_SessionID) {
            current.has_session_id = true;
            current.session_id = id;
        }
    }
    void addU32Fast(const char* field, U32 id) {
        assert(active && current.object_data_open);
        assert(std::string(field) == _PREHASH_ObjectLocalID);
        current.local_ids.push_back(id);
    }
    bool isSendFull(void*) const { return current.local_ids.size() >= max_object_blocks; }
    void sendReliable(const std::string& host) {
        assert(active);
        assert(current.has_agent_data && current.has_agent_id && current.has_session_id);
        assert(current.agent_id == "agent" && current.session_id == "session");
        assert(!current.local_ids.empty());
        current.host = host;
        sent.push_back(current);
        current = Message{};
        active = false;
    }
    void clear() { sent.clear(); current = Message{}; active = false; }
};
LLMessageSystem message_system;
LLMessageSystem* gMessageSystem = &message_system;

struct LLVector3d {
    F64 x=0, y=0, z=0;
    LLVector3d operator-(const LLVector3d& other) const {
        return {x-other.x, y-other.y, z-other.z};
    }
    F64 length() const { return std::sqrt(x*x + y*y + z*z); }
};

struct LLViewerObject {
    LLUUID id;
    LLVector3d position;
    LLViewerObject* root = nullptr;
    LLViewerRegion* region = &default_region;
    U32 local_id = 0;
    int pcode = LL_PCODE_VOLUME;
    bool dead = false, orphaned = false, avatar = false, attachment = false, has_region = true;
    bool selected = false;
    explicit LLViewerObject(LLUUID object_id, LLVector3d pos = {})
        : id(std::move(object_id)), position(pos), root(this) {}
    bool isDead() const { return dead; }
    bool isOrphaned() const { return orphaned; }
    LLViewerRegion* getRegion() const { return has_region ? region : nullptr; }
    bool isAvatar() const { return avatar; }
    bool isAttachment() const { return attachment; }
    bool isSelected() const { return selected; }
    LLViewerObject* getRootEdit() const { return root ? root : const_cast<LLViewerObject*>(this); }
    int getPCode() const { return pcode; }
    LLVector3d getPositionGlobal() const { return position; }
    const LLUUID& getID() const { return id; }
    U32 getLocalID() const { return local_id; }
};

struct LLViewerObjectList {
    std::vector<LLViewerObject*> objects;
    std::map<LLUUID, LLViewerObject*> by_id;
    std::map<U32, LLViewerObject*> by_local_id;
    S32 getNumObjects() const { return static_cast<S32>(objects.size()); }
    LLViewerObject* getObject(S32 index) const {
        LLViewerObject* object = objects[index];
        return object && !object->isDead() ? object : nullptr;
    }
    LLViewerObject* findObject(const LLUUID& id) const {
        auto found = by_id.find(id);
        return found == by_id.end() ? nullptr : found->second;
    }
    void add(LLViewerObject* object) {
        objects.push_back(object);
        by_id[object->id] = object;
        by_local_id[object->local_id] = object;
    }
    void clear() { objects.clear(); by_id.clear(); by_local_id.clear(); }
} gObjectList;

struct LLAgent {
    LLVector3d position;
    bool region_available = true;
    LLViewerRegion* region = &default_region;
    LLViewerRegion* getRegion() { return region_available ? region : nullptr; }
    LLVector3d getPositionGlobal() const { return position; }
    LLUUID getID() const { return "agent"; }
    LLUUID getSessionID() const { return "session"; }
} gAgent;

struct LLFrameTimer {
    static F64 now;
    static F64 getTotalSeconds() { return now; }
};
F64 LLFrameTimer::now = 0.;

struct LLSpinCtrl {
    F64 value = 10.;
    F64 get() const { return value; }
};

class LLFloaterAreaSearch {
public:
    struct Entry {
        F64 requestedAt = 0.;
        U32 attempts = 0;
        bool ready = false;
        F32 distance = 0.f;
    };
    LLSpinCtrl radius_control;
    F32 mRadius = 96.f;
    bool mRequestPending = false;
    std::map<LLUUID, Entry> mEntries;
    template<typename T> T* getChild(const char*) { return reinterpret_cast<T*>(&radius_control); }
    bool inRange(LLViewerObject* object) const;
    void scan();
    void requestProperties();
};

''' + constants + "\n" + extract_function("bool LLFloaterAreaSearch::inRange(") + "\n" \
    + extract_function("void LLFloaterAreaSearch::scan()") + "\n" \
    + extract_function("void sendPropertyRequests(") + "\n" \
    + extract_function("void LLFloaterAreaSearch::requestProperties()") + r'''

static std::vector<U32> requestedLocalIDs(const std::string& type = "ObjectSelect")
{
    std::vector<U32> ids;
    for (const auto& message : gMessageSystem->sent)
        if (message.type == type)
            ids.insert(ids.end(), message.local_ids.begin(), message.local_ids.end());
    return ids;
}

static std::vector<LLUUID> requestedIDs(const std::string& type = "ObjectSelect")
{
    std::vector<LLUUID> ids;
    const std::vector<U32> local_ids = requestedLocalIDs(type);
    for (U32 local_id : local_ids) {
        auto found = gObjectList.by_local_id.find(local_id);
        if (found != gObjectList.by_local_id.end()) ids.push_back(found->second->id);
    }
    return ids;
}

static void resetRequests()
{
    gObjectList.clear();
    gMessageSystem->clear();
    gMessageSystem->max_object_blocks = 100000;
    gAgent.region_available = true;
    gAgent.region = &default_region;
    gAgent.position = {};
    default_region.alive = true;
    default_region.host = "default";
}

static void addEntry(LLFloaterAreaSearch& floater, LLViewerObject& object, F32 distance)
{
    object.local_id = static_cast<U32>(gObjectList.objects.size() + 1);
    gObjectList.add(&object);
    LLFloaterAreaSearch::Entry entry;
    entry.distance = distance;
    floater.mEntries.emplace(object.id, entry);
}

static void assertNoEmptyMessages()
{
    for (const auto& message : gMessageSystem->sent)
        assert(!message.local_ids.empty());
}

static void testScanAndRange()
{
    gObjectList.clear();
    gAgent.position = {};
    gAgent.region_available = true;
    LLFloaterAreaSearch floater;
    floater.radius_control.value = 20.;

    LLViewerObject root("root", {5, 0, 0});
    LLViewerObject child("child", {6, 0, 0}); child.root = &root;
    LLViewerObject distant("distant", {21, 0, 0});
    LLViewerObject avatar("avatar", {1, 0, 0}); avatar.avatar = true;
    LLViewerObject attachment("attachment", {1, 0, 0}); attachment.attachment = true;
    LLViewerObject dead("dead", {1, 0, 0}); dead.dead = true;
    LLViewerObject no_region("no-region", {1, 0, 0}); no_region.has_region = false;
    LLViewerObject orphan("orphan", {1, 0, 0}); orphan.orphaned = true;
    LLViewerObject scene_object("scene-object", {1, 0, 0}); scene_object.pcode = 99;
    for (LLViewerObject* object : {&root, &child, &distant, &avatar, &attachment, &dead,
                                   &no_region, &orphan, &scene_object})
        gObjectList.add(object);

    floater.scan(); // also snapshots the current radius control into mRadius
    assert(floater.inRange(&root));
    assert(!floater.inRange(&child));
    assert(!floater.inRange(&distant));
    assert(!floater.inRange(&avatar));
    assert(!floater.inRange(&attachment));
    assert(!floater.inRange(&dead));
    assert(!floater.inRange(&no_region));
    assert(!floater.inRange(&orphan));
    assert(!floater.inRange(&scene_object));

    assert(floater.mEntries.size() == 1);
    assert(floater.mEntries.count("root") == 1);
    assert(std::abs(floater.mEntries.at("root").distance - 5.f) < 0.001f);

    gObjectList.clear(); // objects that vanish from the viewer list leave the result set
    floater.scan();
    assert(floater.mEntries.empty());
}

static void testRealMessagePacketsSplitAt254()
{
    resetRequests();
    LLViewerRegion region{"packet-region"};
    std::vector<LLViewerObject> objects;
    objects.reserve(600);
    for (U32 i = 0; i < 600; ++i) {
        objects.emplace_back(std::to_string(i));
        objects.back().region = &region;
        objects.back().local_id = i + 1;
    }
    std::vector<LLViewerObject*> pointers;
    for (auto& object : objects) pointers.push_back(&object);

    sendPropertyRequests(&region, pointers);
    assert(gMessageSystem->sent.size() == 6);
    assert(gMessageSystem->sent[0].type == "ObjectSelect");
    assert(gMessageSystem->sent[1].type == "ObjectSelect");
    assert(gMessageSystem->sent[2].type == "ObjectSelect");
    assert(gMessageSystem->sent[3].type == "ObjectDeselect");
    for (const auto& message : gMessageSystem->sent) {
        assert(message.host == "packet-region");
        assert(message.local_ids.size() <= 254);
    }
    assert(gMessageSystem->sent[0].local_ids.size() == 254);
    assert(gMessageSystem->sent[1].local_ids.size() == 254);
    assert(gMessageSystem->sent[2].local_ids.size() == 92);
    for (int packet = 0; packet < 3; ++packet)
        assert(gMessageSystem->sent[packet].local_ids == gMessageSystem->sent[packet + 3].local_ids);
    assertNoEmptyMessages();
}

static void testSendFullEarlySplitDoesNotEmitEmptyMessages()
{
    resetRequests();
    LLViewerRegion region{"full-region"};
    std::vector<LLViewerObject> objects;
    objects.reserve(20);
    std::vector<LLViewerObject*> pointers;
    for (U32 i = 0; i < 20; ++i) {
        objects.emplace_back(std::to_string(i));
        objects.back().local_id = i + 1;
        pointers.push_back(&objects.back());
    }
    gMessageSystem->max_object_blocks = 7;
    sendPropertyRequests(&region, pointers);
    assert(gMessageSystem->sent.size() == 6);
    for (const auto& message : gMessageSystem->sent)
        assert(message.local_ids.size() > 0 && message.local_ids.size() <= 7);
    for (int packet = 0; packet < 3; ++packet)
        assert(gMessageSystem->sent[packet].local_ids == gMessageSystem->sent[packet + 3].local_ids);
    assertNoEmptyMessages();
}

static void testNearestFirstAndSelectedObjectsStaySelected()
{
    resetRequests();
    LLFloaterAreaSearch floater;
    floater.radius_control.value = 1000.;
    floater.mRadius = 1000.f;
    LLViewerObject far("far", {4, 0, 0});
    LLViewerObject near("near", {1, 0, 0});
    LLViewerObject selected("selected", {2, 0, 0}); selected.selected = true;
    LLViewerObject middle("middle", {3, 0, 0});
    addEntry(floater, far, 4.f);
    addEntry(floater, near, 1.f);
    addEntry(floater, selected, 2.f);
    addEntry(floater, middle, 3.f);

    LLFrameTimer::now = 100.;
    floater.requestProperties();
    assert((requestedIDs() == std::vector<LLUUID>{"near", "selected", "middle", "far"}));
    assert((requestedIDs("ObjectDeselect") == std::vector<LLUUID>{"near", "middle", "far"}));
    assert(gMessageSystem->sent.size() == 2);
    assert(gMessageSystem->sent[0].type == "ObjectSelect");
    assert(gMessageSystem->sent[1].type == "ObjectDeselect");
    assert(gMessageSystem->sent[0].host == "default");
    assertNoEmptyMessages();
}

static void testSelectDeselectPairsPerRegion()
{
    resetRequests();
    LLViewerRegion first_region{"first"}, second_region{"second"};
    LLFloaterAreaSearch floater;
    floater.radius_control.value = 100.;
    floater.mRadius = 100.f;
    LLViewerObject first_selected("first-selected", {1, 0, 0});
    first_selected.region = &first_region;
    first_selected.selected = true;
    LLViewerObject first_plain("first-plain", {2, 0, 0});
    first_plain.region = &first_region;
    LLViewerObject second_selected("second-selected", {3, 0, 0});
    second_selected.region = &second_region;
    second_selected.selected = true;
    LLViewerObject second_plain("second-plain", {4, 0, 0});
    second_plain.region = &second_region;
    addEntry(floater, first_selected, 1.f);
    addEntry(floater, first_plain, 2.f);
    addEntry(floater, second_selected, 3.f);
    addEntry(floater, second_plain, 4.f);
    first_selected.local_id = 77;
    second_selected.local_id = 77; // simulator-local IDs may overlap across regions

    LLFrameTimer::now = 100.;
    floater.requestProperties();
    std::map<std::string, std::set<LLUUID>> selected_by_region, deselected_by_region;
    for (const auto& message : gMessageSystem->sent) {
        assert(!message.local_ids.empty());
        for (U32 local_id : message.local_ids) {
            LLViewerObject* object = nullptr;
            for (LLViewerObject* candidate : gObjectList.objects)
                if (candidate->local_id == local_id && candidate->region->getHost() == message.host) {
                    assert(!object);
                    object = candidate;
                }
            assert(object);
            auto& ids = message.type == "ObjectSelect" ? selected_by_region[message.host]
                                                       : deselected_by_region[message.host];
            ids.insert(object->id);
        }
    }
    assert((selected_by_region["first"] == std::set<LLUUID>{"first-selected", "first-plain"}));
    assert((deselected_by_region["first"] == std::set<LLUUID>{"first-plain"}));
    assert((selected_by_region["second"] == std::set<LLUUID>{"second-selected", "second-plain"}));
    assert((deselected_by_region["second"] == std::set<LLUUID>{"second-plain"}));
}

static void testRegionWindowRefillsAt383AndAllowsPartialReplies()
{
    resetRequests();
    LLFloaterAreaSearch floater;
    floater.radius_control.value = 10000.;
    floater.mRadius = 10000.f;
    std::vector<LLViewerObject> objects;
    objects.reserve(1500);
    for (int i = 0; i < 1500; ++i) {
        objects.emplace_back(std::to_string(i), LLVector3d{static_cast<F64>(i), 0, 0});
        addEntry(floater, objects.back(), static_cast<F32>(i));
    }

    LLFrameTimer::now = 100.;
    floater.requestProperties();
    assert(requestedIDs().size() == 762);
    std::vector<LLUUID> first_batch = requestedIDs();
    for (size_t i = 0; i < 378; ++i) floater.mEntries.at(first_batch[i]).ready = true;
    LLFrameTimer::now = 101.;
    floater.requestProperties();
    assert(requestedIDs().size() == 762); // 384 outstanding is above the refill threshold

    floater.mEntries.at(first_batch[378]).ready = true; // exactly 383 remain in flight
    floater.requestProperties();
    assert(requestedIDs().size() == 1141); // refill until the 762-request window is full

    std::vector<LLUUID> all_sent = requestedIDs();
    size_t newly_replied = 0;
    for (const LLUUID& id : all_sent) {
        auto& entry = floater.mEntries.at(id);
        if (!entry.ready && newly_replied < 379) { entry.ready = true; ++newly_replied; }
    }
    assert(newly_replied == 379);
    floater.requestProperties(); // partial replies bring the in-flight count to 383 again
    assert(requestedIDs().size() == 1500);
    for (const auto& [id, entry] : floater.mEntries) {
        (void)id;
        assert(entry.attempts == 1);
    }
}

static void testBlockedRegionDoesNotStarveNeighbor()
{
    resetRequests();
    LLViewerRegion blocked{"blocked"}, neighbor{"neighbor"};
    LLFloaterAreaSearch floater;
    floater.radius_control.value = 10000.;
    floater.mRadius = 10000.f;
    std::vector<LLViewerObject> objects;
    objects.reserve(503);
    for (int i = 0; i < 500; ++i) {
        objects.emplace_back("inflight-" + std::to_string(i));
        objects.back().region = &blocked;
        addEntry(floater, objects.back(), static_cast<F32>(i));
        auto& entry = floater.mEntries.at(objects.back().id);
        entry.attempts = 1;
        entry.requestedAt = 95.;
    }
    objects.emplace_back("blocked-pending");
    objects.back().region = &blocked;
    addEntry(floater, objects.back(), 900.f);
    objects.emplace_back("neighbor-far");
    objects.back().region = &neighbor;
    addEntry(floater, objects.back(), 5.f);
    objects.emplace_back("neighbor-near");
    objects.back().region = &neighbor;
    addEntry(floater, objects.back(), 1.f);

    LLFrameTimer::now = 100.;
    floater.requestProperties();
    assert(floater.mEntries.at("blocked-pending").attempts == 0);
    assert(floater.mEntries.at("neighbor-far").attempts == 1);
    assert(floater.mEntries.at("neighbor-near").attempts == 1);
    assert((requestedIDs() == std::vector<LLUUID>{"neighbor-near", "neighbor-far"}));
    for (const auto& message : gMessageSystem->sent) assert(message.host == "neighbor");
}

static void testThirtySecondRetryAndThreeAttemptLimit()
{
    resetRequests();
    LLFloaterAreaSearch floater;
    floater.radius_control.value = 100.;
    floater.mRadius = 100.f;
    LLViewerObject object("retry", {1, 0, 0});
    addEntry(floater, object, 1.f);

    LLFrameTimer::now = 0.;
    floater.requestProperties();
    assert(floater.mEntries.at("retry").attempts == 1);
    LLFrameTimer::now = 29.99;
    floater.requestProperties();
    assert(requestedIDs().size() == 1);

    LLFrameTimer::now = 30.;
    floater.requestProperties();
    assert(floater.mEntries.at("retry").attempts == 2);
    assert(requestedIDs().size() == 2);
    LLFrameTimer::now = 59.99;
    floater.requestProperties();
    assert(requestedIDs().size() == 2);

    LLFrameTimer::now = 60.;
    floater.requestProperties();
    assert(floater.mEntries.at("retry").attempts == 3);
    assert(requestedIDs().size() == 3);
    LLFrameTimer::now = 90.;
    floater.requestProperties();
    assert(requestedIDs().size() == 3);
}

static void testDeadMissingAndDisconnectedObjectsAreSkipped()
{
    resetRequests();
    LLFloaterAreaSearch floater;
    floater.radius_control.value = 100.;
    floater.mRadius = 100.f;
    LLViewerObject dead("dead", {1, 0, 0}); dead.dead = true;
    LLViewerObject disconnected("disconnected", {1, 0, 0});
    LLViewerRegion disconnected_region{"offline"}; disconnected_region.alive = false;
    disconnected.region = &disconnected_region;
    LLViewerObject no_region("no-region", {1, 0, 0}); no_region.has_region = false;
    addEntry(floater, dead, 1.f);
    addEntry(floater, disconnected, 1.f);
    addEntry(floater, no_region, 1.f);
    floater.mEntries.emplace("missing", LLFloaterAreaSearch::Entry{}); // absent from findObject()

    LLFrameTimer::now = 50.;
    floater.requestProperties();
    assert(requestedIDs().empty());
    assert(floater.mEntries.at("dead").attempts == 0);
    assert(floater.mEntries.at("disconnected").attempts == 0);
    assert(floater.mEntries.at("no-region").attempts == 0);
    assert(floater.mEntries.at("missing").attempts == 0);
}

static void testSimulatedSevenThousandObjectRefillScenario()
{
    resetRequests();
    LLFloaterAreaSearch floater;
    floater.radius_control.value = 10000.;
    floater.mRadius = 10000.f;
    std::vector<LLViewerObject> objects;
    objects.reserve(7000);
    for (int i = 0; i < 7000; ++i) {
        objects.emplace_back("bulk-" + std::to_string(i), LLVector3d{static_cast<F64>(i), 0, 0});
        addEntry(floater, objects.back(), static_cast<F32>(i));
    }

    // SIMULATED reply/refill turns only; this demonstrates the old 32/s cap is gone,
    // but it does not measure actual viewer or simulator wall-clock speed.
    LLFrameTimer::now = 200.;
    floater.requestProperties();
    while (requestedIDs().size() < 7000) {
        size_t replied = 0;
        for (const LLUUID& id : requestedIDs()) {
            auto& entry = floater.mEntries.at(id);
            if (!entry.ready && replied < 500) { entry.ready = true; ++replied; }
        }
        assert(replied == 500);
        floater.requestProperties();
    }
    assert(requestedIDs().size() == 7000);
    for (const auto& [id, entry] : floater.mEntries) {
        (void)id;
        assert(entry.attempts == 1);
    }
    std::cout << "SIMULATED: 7000 objects requested with reply/refill turns; no real speed measured.\n";
}

int main()
{
    testScanAndRange();
    testRealMessagePacketsSplitAt254();
    testSendFullEarlySplitDoesNotEmitEmptyMessages();
    testNearestFirstAndSelectedObjectsStaySelected();
    testSelectDeselectPairsPerRegion();
    testRegionWindowRefillsAt383AndAllowsPartialReplies();
    testBlockedRegionDoesNotStarveNeighbor();
    testThirtySecondRetryAndThreeAttemptLimit();
    testDeadMissingAndDisconnectedObjectsAreSkipped();
    testSimulatedSevenThousandObjectRefillScenario();
}
'''


def main():
    compiler = shutil.which("g++")
    if compiler is None:
        raise SystemExit("g++ is required to run this test")
    with tempfile.TemporaryDirectory(prefix="area-search-objects-") as temporary:
        temporary = Path(temporary)
        source = temporary / "test.cpp"
        executable = temporary / "test-area-search-objects"
        source.write_text(HARNESS, encoding="utf-8")
        subprocess.run(
            [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(executable)],
            check=True,
        )
        subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    main()
