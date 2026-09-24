"""Compile and exercise the production area search query matcher with g++.

Run: python scripts/tests/test_area_search_query.py
"""
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''#include "llareasearchquery.h"
#include <cassert>
#include <string>

int main()
{
    LLAreaSearchQuery query;

    assert(query.parse(U""));
    assert(query.valid() && query.matches(U"anything", U"at all", false));
    assert(query.parse(U" \t\n"));
    assert(query.matches(U"", U"", false));

    assert(query.parse(U"red or blue and green"));
    assert(query.matches(U"red", U"", false));
    assert(!query.matches(U"blue", U"", false));
    assert(query.matches(U"blue", U"green", false));
    assert(query.parse(U"(red or blue) and green"));
    assert(!query.matches(U"red", U"", false));
    assert(query.matches(U"red", U"green", false));
    assert(query.parse(U"red blue")); // adjacent terms are ANDed
    assert(query.matches(U"red", U"blue", false));
    assert(!query.matches(U"red", U"", false));
    assert(query.parse(U"not red and blue")); // NOT binds before AND
    assert(query.matches(U"blue", U"", false));
    assert(!query.matches(U"red", U"blue", false));

    assert(query.parse(U"\"red and blue\""));
    assert(query.matches(U"a red and blue house", U"", false));
    assert(!query.matches(U"red", U"and blue", false)); // fields are never joined
    assert(query.parse(U"\"red blue\""));
    assert(!query.matches(U"red blu", U"", true)); // phrases never use fuzzy matching
    assert(query.parse(U"\"say \\\"hi\\\"\""));
    assert(query.matches(U"say \"hi\" today", U"", false));

    assert(query.parse(U"m\u00fcnchen"));
    assert(query.matches(U"m\u00fcnchen plaza", U"", false));
    assert(query.parse(U"\"東京 駅\""));
    assert(query.matches(U"near 東京 駅 today", U"", false));
    assert(query.parse(U"a\U0001F984bc"));
    assert(query.matches(U"a\U0001F984bc", U"", false));
    assert(!query.matches(U"a\U0001F985bc", U"", false)); // supplementary code points stay distinct
    assert(query.matches(U"a\U0001F985bc", U"", true)); // code points count as one fuzzy character

    assert(query.parse(U"alce"));
    assert(!query.matches(U"alice", U"", false));
    assert(query.matches(U"alice", U"", true)); // adjacent transposition
    assert(!query.matches(U"al", U"ice", true)); // no matching across fields
    assert(query.parse(U"abcd"));
    assert(!query.matches(U"abxy", U"", true)); // four to seven chars allow one edit
    assert(query.parse(U"abcdefgh"));
    assert(query.matches(U"abXYefgh", U"", true)); // eight or more allow two edits
    assert(!query.matches(U"abcXYZgh", U"", true));
    assert(query.parse(U"elephant"));
    assert(query.matches(U"elephnat", U"", true));
    assert(query.matches(U"elephnxt", U"", true));
    assert(!query.matches(U"elxphnxt", U"", true));
    assert(query.parse(U"alice"));
    assert(query.matches(U"new-alice-name", U"", false)); // substring remains available

    const char32_t* malformed[] = {
        U"and red", U"red or", U"red and", U"not", U"red or and blue",
        U"(red", U"red)", U"()", U"\"unfinished", U"\"\"", U"red\"blue\""
    };
    for (const char32_t* text : malformed)
    {
        assert(!query.parse(text));
        assert(!query.valid() && !query.matches(U"red", U"blue", true));
    }

    assert(!query.parse(std::u32string(1025, U'x')));
    assert(!query.valid());
    std::u32string too_many_terms = U"term";
    for (int i = 1; i < 65; ++i) too_many_terms += U" term";
    assert(!query.parse(too_many_terms));
    std::u32string too_deep(17, U'(');
    too_deep += U"word";
    too_deep += std::u32string(17, U')');
    assert(!query.parse(too_deep));
}
'''


def main():
    compiler = shutil.which("g++")
    if compiler is None:
        raise SystemExit("g++ is required to run this test")
    with tempfile.TemporaryDirectory(prefix="area-search-query-") as temporary:
        temporary = Path(temporary)
        source = temporary / "test.cpp"
        executable = temporary / "test-area-search-query"
        source.write_text(HARNESS, encoding="utf-8")
        subprocess.run(
            [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
             "-I", str(ROOT / "indra/newview"), str(source), "-o", str(executable)],
            check=True,
        )
        subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    main()
