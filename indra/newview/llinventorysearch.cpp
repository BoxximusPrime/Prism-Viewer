/**
 * @file llinventorysearch.cpp
 * @brief Text query matching for inventory search.
 */

#include "llviewerprecompiledheaders.h"

#include "llinventorysearch.h"

#include "llstring.h"

namespace
{
bool is_separator(char character)
{
    return LLStringOps::isSpace(character) || character == '+';
}
}

LLInventorySearchQuery::LLInventorySearchQuery(const std::string& query)
{
    std::string normalized = query;
    LLStringUtil::trim(normalized);
    LLStringUtil::toUpper(normalized);

    mIncludedClauses.emplace_back();
    for (size_t position = 0; position < normalized.size();)
    {
        while (position < normalized.size() && is_separator(normalized[position]))
        {
            ++position;
        }
        if (position == normalized.size())
        {
            break;
        }
        if (normalized[position] == '|')
        {
            if (!mIncludedClauses.back().empty())
            {
                mIncludedClauses.emplace_back();
            }
            ++position;
            continue;
        }

        const bool excluded = normalized[position] == '-' && position + 1 < normalized.size();
        if (excluded)
        {
            ++position;
        }

        const bool quoted = position < normalized.size() && normalized[position] == '"';
        if (quoted)
        {
            ++position;
        }

        const size_t start = position;
        while (position < normalized.size()
               && (quoted ? normalized[position] != '"'
                          : !is_separator(normalized[position]) && normalized[position] != '|'))
        {
            ++position;
        }

        if (position > start)
        {
            if (excluded)
            {
                mExcludedTerms.push_back(normalized.substr(start, position - start));
            }
            else
            {
                mIncludedClauses.back().push_back(normalized.substr(start, position - start));
            }
        }

        if (quoted && position < normalized.size())
        {
            ++position;
        }
    }

    while (mIncludedClauses.size() > 1 && mIncludedClauses.back().empty())
    {
        mIncludedClauses.pop_back();
    }

    mExactWord = mExcludedTerms.empty()
                 && mIncludedClauses.size() == 1
                 && mIncludedClauses.front().size() == 1
                 && normalized.size() > 2
                 && normalized.front() == '"'
                 && normalized.back() == '"'
                 && mIncludedClauses.front().front().find_first_of(" \t\r\n") == std::string::npos;
}

bool LLInventorySearchQuery::matches(const std::string& text) const
{
    std::string searchable = text;
    LLStringUtil::toUpper(searchable);

    for (const std::string& term : mExcludedTerms)
    {
        if (searchable.find(term) != std::string::npos)
        {
            return false;
        }
    }

    if (mExactWord)
    {
        const std::string& term = mIncludedClauses.front().front();
        size_t position = searchable.find(term);
        while (position != std::string::npos)
        {
            const size_t end = position + term.size();
            if ((position == 0 || LLStringOps::isSpace(searchable[position - 1]))
                && (end == searchable.size() || LLStringOps::isSpace(searchable[end])))
            {
                return true;
            }
            position = searchable.find(term, position + 1);
        }
        return false;
    }

    for (const auto& clause : mIncludedClauses)
    {
        bool clause_matches = true;
        for (const std::string& term : clause)
        {
            if (searchable.find(term) == std::string::npos)
            {
                clause_matches = false;
                break;
            }
        }
        if (clause_matches)
        {
            return true;
        }
    }
    return false;
}

const std::string& LLInventorySearchQuery::getFirstIncludedTerm() const
{
    static const std::string empty;
    return mIncludedClauses.empty() || mIncludedClauses.front().empty()
        ? empty
        : mIncludedClauses.front().front();
}
