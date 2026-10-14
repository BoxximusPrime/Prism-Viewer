/** Prism Collections: independently swappable groups of inventory links. */
#ifndef LL_LLPRISMCOLLECTIONS_H
#define LL_LLPRISMCOLLECTIONS_H

#include "lluuid.h"
#include <map>
#include <set>
#include <string>
#include <vector>

namespace LLPrismCollections
{
struct Selection
{
    LLUUID set;
    uuid_vec_t items;
};
using Selections = std::map<LLUUID, Selection>;
struct Change
{
    uuid_vec_t add, remove;
    std::set<LLUUID> managed;
};
Change planChange(const Selections& selections, const std::set<LLUUID>& managed,
                  const std::set<LLUUID>& worn, const uuid_vec_t& applying);

LLUUID root();
uuid_vec_t folders(const LLUUID& parent);
bool isCategory(const LLUUID& id);
bool validItem(const LLUUID& id);
bool validBodyParts(const uuid_vec_t& items);
bool readSet(const LLUUID& id, uuid_vec_t& items, std::string& error);
bool validName(const LLUUID& parent, const LLUUID& id, std::string name);
LLUUID activeSet(const LLUUID& category);
bool busy();
void setWriting(bool writing);
bool wear(const LLUUID& category, const LLUUID& set, bool remove = false);
void forget(const LLUUID& folder);
void error(const std::string& message);
}
#endif
