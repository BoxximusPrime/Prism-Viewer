#include "../../llinventorycleanupplan.h"
#include <cstdlib>
#include <iostream>
using namespace LLInventoryCleanupPlan;
void check(bool result, const char* description)
{
    if (!result) { std::cerr << "FAIL: " << description << '\n'; std::exit(1); }
}
int main()
{
    const Entry a{"item-a", "name=Demo;parent=folder-a;asset=v1;permissions=copy", true};
    const Entry b{"item-b", "name=Demo;parent=folder-b;asset=v2;permissions=no-copy", true};
    const std::vector<Entry> plan{a,b};
    const std::map<std::string, Entry> baseline{{a.id,a},{b.id,b}};
    check(validate(plan,baseline), "unchanged reviewed IDs authorized");
    check(!validate({},baseline), "empty plan rejected");
    check(!validate({a,a},baseline), "duplicate IDs rejected");
    auto current=baseline;
    current.erase(b.id);
    check(!validate(plan,current), "missing LAST item rejects entire batch");
    current=baseline;
    current[b.id].fingerprint += ";asset=v3";
    check(!validate(plan,current), "changed LAST item rejects entire batch");
    current=baseline;
    current[b.id].eligible=false;
    check(!validate(plan,current), "newly protected, worn, or linked item rejects entire batch");
    current=baseline;
    current[a.id].id=b.id;
    check(!validate(plan,current), "identity substitution rejected");
    current=baseline;
    current.emplace("new-demo", Entry{"new-demo",a.fingerprint,true});
    check(validate(plan,current), "unselected new same-name item does not expand authorization");
    auto invalid=plan;
    invalid[0].eligible=false;
    check(!validate(invalid,baseline), "ineligible scanned item cannot authorize a move");
    invalid[0] = {"",a.fingerprint,true};
    check(!validate(invalid,baseline), "empty identity rejected");
    std::vector<Entry> large;
    current.clear();
    for (size_t i=0; i<MAX_ITEMS; ++i)
    {
        Entry e{std::to_string(i),"snapshot",true};
        large.push_back(e); current.emplace(e.id,e);
    }
    check(validate(large,current), "200 reviewed items accepted");
    Entry extra{"extra","snapshot",true};
    large.push_back(extra); current.emplace(extra.id,extra);
    check(!validate(large,current), "201 reviewed items rejected");
    LoadState loaded{true, true, true, 4481, 4481, 59088, 59088};
    check(loaded.ready(), "complete personal inventory is ready without a library-history flag");
    auto loading = loaded;
    loading.completeFolders = 4480;
    check(!loading.ready(), "idle fetch with one incomplete folder remains blocked");
    loading = loaded; loading.completeItems = 59087;
    check(!loading.ready(), "idle fetch with unfinished item metadata remains blocked");
    loading = loaded; loading.requestsIdle = false;
    check(!loading.ready(), "in-flight requests still block authorization");
    loading = loaded; loading.traversalFinished = false;
    check(!loading.ready(), "matching cached counts do not bypass unfinished traversal");
    loading = loaded; loading.usable = false;
    check(!loading.ready(), "uninitialized inventory is not ready");
    loading = loaded; loading.knownFolders = loading.completeFolders = 0;
    check(!loading.ready(), "missing inventory root cannot look like complete empty inventory");
    loading = loaded; loading.knownItems = loading.completeItems = 0;
    check(loading.ready(), "fully loaded inventory with no items is valid");
    Entry package{"shoe-demo-folder", "folder-and-descendant-metadata", true, true, {"hud", "landmark", "shoes"}};
    std::map<std::string, Entry> packages{{package.id, package}};
    check(validate({package}, packages), "whole package with explicitly reviewed members accepted");
    auto modified = packages;
    modified[package.id].contents.push_back("new-notecard");
    check(!validate({package}, modified), "new descendant invalidates whole folder review");
    modified = packages; modified[package.id].contents.pop_back();
    check(!validate({package}, modified), "removed descendant invalidates whole folder review");
    modified = packages; modified[package.id].fingerprint += "changed-descendant-permissions";
    check(!validate({package}, modified), "changed descendant metadata invalidates whole folder review");
    modified = packages; modified[package.id].eligible = false;
    check(!validate({package}, modified), "protected descendant blocks entire package");
    Entry landmark{"landmark", "metadata", true};
    modified = packages; modified.emplace(landmark.id, landmark);
    check(!validate({package, landmark}, modified), "folder and its descendant cannot both be moved");
    check(!validate({landmark, package}, modified), "overlap detection is independent of selection order");
    Entry nested{"nested-folder", "metadata", true, true, {"shoes"}};
    modified = packages; modified.emplace(nested.id, nested);
    check(!validate({package, nested}, modified), "overlapping subtrees rejected");
    modified = packages; modified[package.id].folder = false;
    check(!validate({package}, modified), "folder cannot silently become an item move");
    package.contents.clear();
    for (size_t i=1; i<MAX_AFFECTED; ++i) package.contents.push_back(std::to_string(i));
    check(validate({package}, {{package.id, package}}), "2000 affected entries including root accepted");
    package.contents.push_back("one-too-many");
    check(!validate({package}, {{package.id, package}}), "2001 affected entries rejected");
    std::cout << "23 authorization and 8 loading checks passed\n";
}
