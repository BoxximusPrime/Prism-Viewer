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
struct Entry
{
    std::string id;
    std::string fingerprint;
    bool eligible = false;
};
// Validate the ENTIRE plan before the caller sends any mutation. Never substitute
// another item, expand a folder, or silently drop a stale/ineligible selection.
inline bool validate(const std::vector<Entry>& plan, const std::map<std::string, Entry>& current)
{
    if (plan.empty() || plan.size() > MAX_ITEMS) return false;
    std::set<std::string> seen;
    for (const auto& entry : plan)
    {
        const auto found = current.find(entry.id);
        if (entry.id.empty() || !entry.eligible || !seen.insert(entry.id).second ||
            found == current.end() || !found->second.eligible ||
            found->second.id != entry.id || found->second.fingerprint != entry.fingerprint)
            return false;
    }
    return true;
}
}
#endif
