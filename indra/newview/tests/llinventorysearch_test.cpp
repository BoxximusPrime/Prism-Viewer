/**
 * @file llinventorysearch_test.cpp
 * @brief Tests for inventory text-search operators.
 */

#include "linden_common.h"

#include "llinventorysearch.h"
#include "../test/lltut.h"

namespace tut
{
struct inventory_search_test {};
typedef test_group<inventory_search_test> inventory_search_test_t;
typedef inventory_search_test_t::object inventory_search_test_object_t;
inventory_search_test_t inventory_search_test("LLInventorySearch");

template<> template<>
void inventory_search_test_object_t::test<1>()
{
    ensure(LLInventorySearchQuery().matches("Any inventory item"));
    ensure(LLInventorySearchQuery("boots -demo").matches("Black leather boots"));
    ensure(!LLInventorySearchQuery("boots -demo").matches("Black boots demo"));
    ensure(LLInventorySearchQuery("boots leather | shoes -demo").matches("Leather boots"));
    ensure(LLInventorySearchQuery("boots leather | shoes -demo").matches("Canvas shoes"));
    ensure(LLInventorySearchQuery("boots|shoes").matches("Canvas shoes"));
    ensure(!LLInventorySearchQuery("boots leather | shoes -demo").matches("Demo shoes"));
    ensure(LLInventorySearchQuery("\"red boots\"").matches("Tall red boots"));
    ensure(!LLInventorySearchQuery("\"red boots\"").matches("Red leather boots"));
    ensure(LLInventorySearchQuery("boots+leather").matches("Leather boots"));
}
}
