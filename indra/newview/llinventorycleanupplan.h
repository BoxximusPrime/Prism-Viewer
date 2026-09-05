/** Inventory cleanup authorization: exact reviewed identities and metadata only. */
#ifndef LL_LLINVENTORYCLEANUPPLAN_H
#define LL_LLINVENTORYCLEANUPPLAN_H
#include <map>
#include <set>
#include <string>
#include <vector>
namespace LLInventoryCleanupPlan
{
constexpr size_t MAX_ITEMS = 200;
constexpr size_t MAX_AFFECTED = 2000;
struct LoadState
{
    bool usable = false;
    bool traversalFinished = false;
    bool requestsIdle = false;
    size_t knownFolders = 0;
    size_t completeFolders = 0;
    size_t knownItems = 0;
    size_t completeItems = 0;
    bool ready() const
    {
        return usable && traversalFinished && requestsIdle && knownFolders > 0 &&
            completeFolders == knownFolders && completeItems == knownItems;
    }
};
struct Entry
{
    std::string id;
    std::string fingerprint;
    bool eligible = false;
    bool folder = false;
    std::vector<std::string> contents;
};
// Validate the ENTIRE plan before the caller sends any mutation. Never substitute
// another identity, change reviewed folder membership, or silently drop a stale selection.
inline bool validate(const std::vector<Entry>& plan, const std::map<std::string, Entry>& current)
{
    if (plan.empty() || plan.size() > MAX_ITEMS) return false;
    std::set<std::string> seen;
    for (const auto& entry : plan)
    {
        const auto found = current.find(entry.id);
        if (entry.id.empty() || !entry.eligible || !seen.insert(entry.id).second ||
            found == current.end() || !found->second.eligible ||
            found->second.id != entry.id || found->second.fingerprint != entry.fingerprint ||
            found->second.folder != entry.folder || found->second.contents != entry.contents)
            return false;
        if (!entry.folder && !entry.contents.empty()) return false;
        for (const auto& id : entry.contents)
            if (id.empty() || !seen.insert(id).second) return false;
        if (seen.size() > MAX_AFFECTED) return false;
    }
    return true;
}
}
#endif
