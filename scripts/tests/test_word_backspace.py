"""Exercise both production Backspace branches and word boundaries. Requires g++."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
harness = r'''
#include <cassert>
#include <cwctype>
#include <string>
using S32=int; using LLWString=std::wstring;
constexpr int MASK_CONTROL=1;
struct LLWStringUtil {static bool isPartOfWord(wchar_t c){return c==L'_' || std::iswalnum(c);}};
struct LLUI {static LLUI* getInstance(){static LLUI ui; return &ui;} void reportBadKeystroke(){}};
struct Text {LLWString value; const LLWString& getWString() const{return value;}};
struct Editor {
    Text mText; int mCursorPos=0,mSelectionStart=0,mSelectionEnd=0; bool mReadOnly=false;
    const LLWString& getWText() const{return mText.value;}
    int getCursor() const{return mCursorPos;}
    bool hasSelection() const{return mSelectionStart!=mSelectionEnd;}
    void setSelection(int start,int end){mSelectionStart=start; mSelectionEnd=end;}
    void deleteSelection(bool=false){
        int start=std::min(mSelectionStart,mSelectionEnd);
        mText.value.erase(start,std::abs(mSelectionEnd-mSelectionStart));
        mCursorPos=start; mSelectionStart=mSelectionEnd=start;
    }
    void removeChar(){mText.value.erase(--mCursorPos,1);}
    void removeCharOrTab(){removeChar();}
};
'''
for name, filename in [('LLLineEditor', 'lllineeditor.cpp'), ('LLTextEditor', 'lltexteditor.cpp')]:
    source = (root / 'indra/llui' / filename).read_text()
    start = source.index(f'S32 {name}::prevWordPos(')
    end = source.index(f'S32 {name}::nextWordPos(', start)
    helper = source[start:end].strip()
    start = source.index('case KEY_BACKSPACE:', source.index(f'bool {name}::handleSpecialKey('))
    end = source.index('        break;', start)
    branch = source[start:end].replace('case KEY_BACKSPACE:', '')
    harness += f'struct {name}: Editor {{ S32 prevWordPos(S32) const; void backspace(int mask); }};\n'
    harness += helper + '\n'
    guard = 'if(mReadOnly) return;' if name == 'LLTextEditor' else ''
    harness += f'void {name}::backspace(int mask){{bool handled=false; {guard}\n{branch}\n}}\n'
harness += r'''
template<class T> void check(){
    auto erase=[](std::wstring text,int cursor,int mask,std::wstring expected,int expected_cursor){
        T editor; editor.mText.value=text; editor.mCursorPos=cursor;
        editor.backspace(mask);
        assert(editor.mText.value==expected && editor.mCursorPos==expected_cursor);
    };
    erase(L"one two",7,MASK_CONTROL,L"one ",4);
    erase(L"one two",6,MASK_CONTROL,L"one o",4);
    erase(L"one two   ",10,MASK_CONTROL,L"one ",4);
    erase(L"one two_three",13,MASK_CONTROL,L"one ",4);
    erase(L"one two!",8,MASK_CONTROL,L"one ",4);
    erase(L"one\ntwo",7,MASK_CONTROL,L"one\n",4);
    erase(L"one\ntwo",4,MASK_CONTROL,L"two",0);
    erase(L"one two",7,0,L"one tw",6);
    erase(L"",0,MASK_CONTROL,L"",0);
    T editor; editor.mText.value=L"one two"; editor.mCursorPos=7;
    editor.setSelection(5,7); editor.backspace(MASK_CONTROL);
    assert(editor.mText.value==L"one t" && editor.mCursorPos==5);
    editor.mReadOnly=true; editor.backspace(MASK_CONTROL);
    assert(editor.mText.value==L"one t");
}
int main(){check<LLLineEditor>(); check<LLTextEditor>();}
'''
with tempfile.TemporaryDirectory() as directory:
    source = Path(directory) / 'check.cpp'
    binary = Path(directory) / 'check.exe'
    source.write_text(harness)
    subprocess.run(['g++', '-std=c++17', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('Both editors: word boundaries, selection, plain Backspace and read-only checks passed.')
