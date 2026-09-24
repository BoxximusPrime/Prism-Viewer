/**
 * @file llareasearchquery.h
 * @brief Bounded parser and matcher for area search queries.
 *
 * $LicenseInfo:firstyear=2026&license=viewerlgpl$
 * Copyright (C) 2026 Boxxy Viewer contributors
 * $/LicenseInfo$
 */

#ifndef LL_LLAREASEARCHQUERY_H
#define LL_LLAREASEARCHQUERY_H

#include <algorithm>
#include <cstddef>
#include <string>
#include <vector>

class LLAreaSearchQuery
{
public:
    LLAreaSearchQuery() = default;

    // The query and fields must already be lowercased by the caller.
    bool parse(const std::u32string& lowercased_query)
    {
        mValid = false;
        mEmpty = false;
        mRoot = -1;
        mTokens.clear();
        mNodes.clear();
        mPosition = 0;
        mNesting = 0;

        if (!lex(lowercased_query))
        {
            return false;
        }
        if (mTokens.empty())
        {
            mEmpty = true;
            mValid = true;
            return true;
        }

        mRoot = parseOr();
        if (mRoot < 0 || mPosition != mTokens.size())
        {
            mNodes.clear();
            return false;
        }
        mValid = true;
        return true;
    }

    bool matches(const std::u32string& lowercased_name,
                 const std::u32string& lowercased_description,
                 bool fuzzy) const
    {
        return mValid && (mEmpty || evaluate(mRoot, lowercased_name, lowercased_description, fuzzy));
    }

    bool valid() const { return mValid; }

private:
    enum class TokenKind { TERM, PHRASE, AND, OR, NOT, LEFT_PAREN, RIGHT_PAREN };
    enum class NodeKind { TERM, PHRASE, NOT, AND, OR };

    struct Token
    {
        TokenKind kind;
        std::u32string value;
    };

    struct Node
    {
        NodeKind kind;
        std::u32string value;
        int left = -1;
        int right = -1;
    };

    static constexpr std::size_t MAX_QUERY_CHARS = 1024;
    static constexpr std::size_t MAX_TOKENS = 128;
    static constexpr std::size_t MAX_TERMS = 64;
    static constexpr std::size_t MAX_NESTING = 16;
    static constexpr int MAX_NODES = 256;

    bool mValid = false;
    bool mEmpty = false;
    int mRoot = -1;
    std::size_t mPosition = 0;
    std::size_t mNesting = 0;
    std::vector<Token> mTokens;
    std::vector<Node> mNodes;

    static bool whitespace(char32_t value)
    {
        return value == U' ' || value == U'\t' || value == U'\n' || value == U'\r' || value == U'\f' || value == U'\v';
    }

    bool addToken(TokenKind kind, std::u32string value = std::u32string())
    {
        if (mTokens.size() >= MAX_TOKENS)
        {
            return false;
        }
        mTokens.push_back({kind, value});
        return true;
    }

    bool lex(const std::u32string& query)
    {
        if (query.size() > MAX_QUERY_CHARS)
        {
            return false;
        }

        std::size_t terms = 0;
        for (std::size_t i = 0; i < query.size();)
        {
            const char32_t ch = query[i];
            if (whitespace(ch))
            {
                ++i;
                continue;
            }
            if (ch == U'(' || ch == U')')
            {
                if (!addToken(ch == U'(' ? TokenKind::LEFT_PAREN : TokenKind::RIGHT_PAREN))
                {
                    return false;
                }
                ++i;
                continue;
            }
            if (ch == U'"')
            {
                ++i;
                std::u32string phrase;
                bool closed = false;
                while (i < query.size())
                {
                    if (query[i] == U'\\' && i + 1 < query.size() && (query[i + 1] == U'"' || query[i + 1] == U'\\'))
                    {
                        phrase.push_back(query[i + 1]);
                        i += 2;
                    }
                    else if (query[i] == U'"')
                    {
                        ++i;
                        closed = true;
                        break;
                    }
                    else
                    {
                        phrase.push_back(query[i++]);
                    }
                }
                if (!closed || phrase.empty() || (i < query.size() && !whitespace(query[i]) && query[i] != U'(' && query[i] != U')'))
                {
                    return false;
                }
                if (++terms > MAX_TERMS || !addToken(TokenKind::PHRASE, phrase))
                {
                    return false;
                }
                continue;
            }

            std::u32string word;
            while (i < query.size() && !whitespace(query[i]) && query[i] != U'(' && query[i] != U')' && query[i] != U'"')
            {
                word.push_back(query[i++]);
            }
            if (word.empty() || (i < query.size() && query[i] == L'"'))
            {
                return false;
            }

            TokenKind kind = TokenKind::TERM;
            if (word == U"and") kind = TokenKind::AND;
            else if (word == U"or") kind = TokenKind::OR;
            else if (word == U"not") kind = TokenKind::NOT;
            else if (++terms > MAX_TERMS) return false;
            if (!addToken(kind, kind == TokenKind::TERM ? word : std::u32string()))
            {
                return false;
            }
        }
        return true;
    }

    bool startsUnary() const
    {
        if (mPosition >= mTokens.size()) return false;
        const TokenKind kind = mTokens[mPosition].kind;
        return kind == TokenKind::TERM || kind == TokenKind::PHRASE || kind == TokenKind::NOT || kind == TokenKind::LEFT_PAREN;
    }

    int addNode(NodeKind kind, const std::u32string& value = std::u32string(), int left = -1, int right = -1)
    {
        if (mNodes.size() >= static_cast<std::size_t>(MAX_NODES)) return -1;
        mNodes.push_back({kind, value, left, right});
        return static_cast<int>(mNodes.size() - 1);
    }

    int parseOr()
    {
        int left = parseAnd();
        if (left < 0) return -1;
        while (mPosition < mTokens.size() && mTokens[mPosition].kind == TokenKind::OR)
        {
            ++mPosition;
            const int right = parseAnd();
            if (right < 0 || (left = addNode(NodeKind::OR, std::u32string(), left, right)) < 0) return -1;
        }
        return left;
    }

    int parseAnd()
    {
        int left = parseUnary();
        if (left < 0) return -1;
        while (mPosition < mTokens.size())
        {
            if (mTokens[mPosition].kind == TokenKind::AND)
            {
                ++mPosition;
            }
            else if (!startsUnary())
            {
                break;
            }
            const int right = parseUnary();
            if (right < 0 || (left = addNode(NodeKind::AND, std::u32string(), left, right)) < 0) return -1;
        }
        return left;
    }

    int parseUnary()
    {
        if (mPosition < mTokens.size() && mTokens[mPosition].kind == TokenKind::NOT)
        {
            ++mPosition;
            const int child = parseUnary();
            return child < 0 ? -1 : addNode(NodeKind::NOT, std::u32string(), child);
        }
        if (mPosition >= mTokens.size()) return -1;

        const Token& token = mTokens[mPosition++];
        if (token.kind == TokenKind::TERM) return addNode(NodeKind::TERM, token.value);
        if (token.kind == TokenKind::PHRASE) return addNode(NodeKind::PHRASE, token.value);
        if (token.kind != TokenKind::LEFT_PAREN || ++mNesting > MAX_NESTING) return -1;

        const int child = parseOr();
        --mNesting;
        if (child < 0 || mPosition >= mTokens.size() || mTokens[mPosition].kind != TokenKind::RIGHT_PAREN) return -1;
        ++mPosition;
        return child;
    }

    bool evaluate(int index, const std::u32string& name, const std::u32string& description, bool fuzzy) const
    {
        const Node& node = mNodes[static_cast<std::size_t>(index)];
        switch (node.kind)
        {
        case NodeKind::TERM:
            return matchesTerm(node.value, name, fuzzy) || matchesTerm(node.value, description, fuzzy);
        case NodeKind::PHRASE:
            return name.find(node.value) != std::u32string::npos || description.find(node.value) != std::u32string::npos;
        case NodeKind::NOT:
            return !evaluate(node.left, name, description, fuzzy);
        case NodeKind::AND:
            return evaluate(node.left, name, description, fuzzy) && evaluate(node.right, name, description, fuzzy);
        case NodeKind::OR:
            return evaluate(node.left, name, description, fuzzy) || evaluate(node.right, name, description, fuzzy);
        }
        return false;
    }

    static bool wordCharacter(char32_t value)
    {
        return (value >= U'a' && value <= U'z') || (value >= U'A' && value <= U'Z') ||
               (value >= U'0' && value <= U'9') || value >= U'\u0080';
    }

    static bool restrictedDistanceWithin(const std::u32string& left, const std::u32string& right, std::size_t limit)
    {
        const std::size_t left_size = left.size();
        const std::size_t right_size = right.size();
        if (left_size > right_size + limit || right_size > left_size + limit) return false;

        const int infinity = static_cast<int>(limit + 1);
        std::vector<int> previous(right_size + 1, infinity);
        std::vector<int> current(right_size + 1, infinity);
        std::vector<int> before_previous(right_size + 1, infinity);
        for (std::size_t column = 0; column <= right_size && column <= limit; ++column)
        {
            previous[column] = static_cast<int>(column);
        }

        for (std::size_t row = 1; row <= left_size; ++row)
        {
            std::fill(current.begin(), current.end(), infinity);
            if (row <= limit) current[0] = static_cast<int>(row);
            const std::size_t first = row > limit ? row - limit : 1;
            const std::size_t last = std::min(right_size, row + limit);
            for (std::size_t column = first; column <= last; ++column)
            {
                const int substitution = left[row - 1] == right[column - 1] ? 0 : 1;
                current[column] = std::min(std::min(current[column - 1] + 1, previous[column] + 1),
                                           previous[column - 1] + substitution);
                if (row > 1 && column > 1 && left[row - 1] == right[column - 2] && left[row - 2] == right[column - 1])
                {
                    current[column] = std::min(current[column], before_previous[column - 2] + 1);
                }
            }
            before_previous.swap(previous);
            previous.swap(current);
        }
        return previous[right_size] <= static_cast<int>(limit);
    }

    static bool fuzzyWordMatch(const std::u32string& term, const std::u32string& field)
    {
        const std::size_t limit = term.size() >= 8 ? 2 : 1;
        for (std::size_t start = 0; start < field.size();)
        {
            while (start < field.size() && !wordCharacter(field[start])) ++start;
            std::size_t end = start;
            while (end < field.size() && wordCharacter(field[end])) ++end;
            if (end > start && restrictedDistanceWithin(term, field.substr(start, end - start), limit)) return true;
            start = end;
        }
        return false;
    }

    static bool matchesTerm(const std::u32string& term, const std::u32string& field, bool fuzzy)
    {
        if (field.find(term) != std::u32string::npos) return true;
        return fuzzy && term.size() >= 4 && fuzzyWordMatch(term, field);
    }
};

#endif // LL_LLAREASEARCHQUERY_H
