/** Standalone tests for the production AO notecard parser (no viewer required).
 * Example: g++ -std=c++17 -Iindra/newview indra/newview/llboxxyaonotecard.cpp
 *          indra/newview/tests/llboxxyaonotecard_test.cpp -o ao_notecard_test
 */
#include "llboxxyaonotecard.h"
#include <cstdlib>
#include <iostream>

using namespace LLBoxxyAONotecard;

static void require(bool condition, const char* description)
{
    if (!condition)
    {
        std::cerr << "FAILED: " << description << '\n';
        std::exit(1);
    }
}

int main()
{
    Animations parsed;
    std::string error, encoded;
    require(parse("\xef\xbb\xbf# comment\r\n[ Standing ] First | Second\r\n"
                  "[Standing]Third\n[Walk.N]Walk\n// comment\n[Swim.D]Dive\n", parsed, error),
            "BOM, CRLF, comments, repeated states and Oracul aliases");
    require(parsed[0] == std::vector<std::string>({"First", "Second", "Third"}), "preserve animation order");
    require(parsed[1] == std::vector<std::string>({"Walk"}) && parsed[24][0] == "Dive", "alias mapping");
    require(stateIndex("stand.3") == 0 && stateIndex("  sitting on ground ") == 4, "state normalization");
    require(stateIndex("Always") == -1 && stateIndex("unknown") == -1, "unsupported states");
    Animations original;
    for (size_t i = 0; i < STATE_COUNT; ++i)
    {
        original[i] = {"[Brand] motion " + std::to_string(i), "UTF-8 \xc3\xa9 motion", "repeat", "repeat"};
    }
    require(serialize(original, encoded, error), "serialize all supported states");
    require(parse(encoded, parsed, error) && parsed == original, "all-state round trip including Unicode and duplicates");
    const std::vector<std::string> invalid = {
        "", "# only a comment\n", "[Standing]", "[Standing missing bracket",
        "Standing]Animation", "[Always]Animation", "[Standing]One,Two",
        "[Standing]Good\n[Unknown]Bad", std::string(65537, 'x')
    };
    for (const auto& input : invalid)
    {
        parsed = original;
        require(!parse(input, parsed, error) && !error.empty(), "reject invalid/unsupported input");
        require(parsed == Animations{}, "failed import is atomic, without partial states");
    }
    for (const std::string name : {"A|B", "A,B", "A\nB", "A\rB", " Leading", "Trailing ", ""})
    {
        original = {};
        original[0] = {name};
        require(!serialize(original, encoded, error) && encoded.empty(), "reject unrepresentable names atomically");
    }
    original[0] = {std::string(300, 'x')};
    require(!serialize(original, encoded, error), "export line limit");
    original[0] = std::vector<std::string>(1000, std::string(100, 'x'));
    require(!serialize(original, encoded, error), "export total limit");
    require(parse("[Standing]A|| \t|B\n[Typing]", parsed, error) && parsed[0].size() == 2,
            "ignore empty separators and empty state assignments");
    std::cout << "AO notecard compatibility tests passed.\n";
}
