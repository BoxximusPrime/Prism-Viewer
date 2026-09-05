/**
 * @file llinventorysearch.h
 * @brief Text query matching for inventory search.
 */

#ifndef LL_LLINVENTORYSEARCH_H
#define LL_LLINVENTORYSEARCH_H

#include <string>
#include <vector>

class LLInventorySearchQuery
{
public:
    LLInventorySearchQuery() : LLInventorySearchQuery(std::string()) {}
    explicit LLInventorySearchQuery(const std::string& query);

    bool matches(const std::string& text) const;
    bool hasExclusions() const { return !mExcludedTerms.empty(); }
    const std::string& getFirstIncludedTerm() const;

private:
    std::vector<std::vector<std::string>> mIncludedClauses;
    std::vector<std::string> mExcludedTerms;
    bool mExactWord = false;
};

#endif
