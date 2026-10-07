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

size_t find_term(const std::string& text, const std::string& term, bool whole_word, bool space_boundary)
{
    size_t position = text.find(term);
    while (position != std::string::npos)
    {
        const size_t end = position + term.size();
        const auto boundary = [space_boundary](char character)
        {
            return space_boundary ? LLStringOps::isSpace(character) : !LLStringUtil::isPartOfWord(character);
        };
        if (!whole_word || ((position == 0 || boundary(text[position - 1]))
            && (end == text.size() || boundary(text[end]))))
        {
            return position;
        }
        position = text.find(term, position + 1);
    }
    return std::string::npos;
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

bool LLInventorySearchQuery::matches(const std::string& text, std::pair<size_t, size_t>* match) const
{
    if (match) *match = {std::string::npos, 0};
    std::string searchable = text;
    LLStringUtil::toUpper(searchable);

    for (const std::string& term : mExcludedTerms)
    {
        if (searchable.find(term) != std::string::npos)
        {
            return false;
        }
    }

    const bool whole_word = mExactWord || mIncludedClauses.size() > 1;
    for (const auto& clause : mIncludedClauses)
    {
        bool clause_matches = true;
        std::pair<size_t, size_t> first_match{std::string::npos, 0};
        for (const std::string& term : clause)
        {
            const size_t position = find_term(searchable, term, whole_word, mExactWord);
            if (position == std::string::npos)
            {
                clause_matches = false;
                break;
            }
            if (first_match.first == std::string::npos) first_match = {position, term.size()};
        }
        if (clause_matches)
        {
            if (match) *match = first_match;
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
