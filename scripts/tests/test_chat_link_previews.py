"""Compile and exercise the production DM preview allowlist. Requires g++."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
PROGRAM = r'''
#include "llchatlinkpreview.h"
#include <cassert>
#include <iostream>

int main()
{
    unsigned checks = 0;
    auto accept = [&](const std::string& url, const std::string& thumbnail, const std::string& provider) {
        auto p = ll_chat_link_preview(url);
        assert(p.thumbnail == thumbnail);
        assert(p.provider == provider);
        assert(p.url.find("https://") == 0);
        ++checks;
    };
    const std::string youtube = "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg";
    accept("https://www.youtube.com/watch?v=dQw4w9WgXcQ", youtube, "YouTube");
    accept("HTTP://M.YOUTUBE.COM/watch?feature=share&v=dQw4w9WgXcQ&t=42#test", youtube, "YouTube");
    accept("https://youtu.be/dQw4w9WgXcQ?si=test&t=42", youtube, "YouTube");
    accept("https://youtube.com/shorts/dQw4w9WgXcQ", youtube, "YouTube");
    accept("https://youtube.com/embed/dQw4w9WgXcQ", youtube, "YouTube");
    accept("https://youtube.com/live/dQw4w9WgXcQ/", youtube, "YouTube");
    assert(ll_chat_link_preview("https://youtu.be/dQw4w9WgXcQ?t=42").url
        == "https://youtu.be/dQw4w9WgXcQ?t=42");

    const std::string imgur = "https://i.imgur.com/7iqCyFwm.jpg";
    accept("https://imgur.com/7iqCyFw", imgur, "Imgur");
    accept("https://i.imgur.com/7iqCyFw.png?x=1", imgur, "Imgur");
    accept("https://i.imgur.com/7iqCyFw.gifv", imgur, "Imgur");
    accept("https://WWW.IMGUR.COM/7iqCyFw.JPG", imgur, "Imgur");
    accept("https://imgur.com/abc12", "https://i.imgur.com/abc12m.jpg", "Imgur");

    const std::string giphy = "https://media.giphy.com/media/cZ7rmKfFYOvYI/480w_s.jpg";
    accept("https://giphy.com/gifs/superman-cZ7rmKfFYOvYI", giphy, "GIPHY");
    accept("https://www.giphy.com/gifs/cZ7rmKfFYOvYI", giphy, "GIPHY");
    accept("https://giphy.com/stickers/flying-superman-cZ7rmKfFYOvYI/", giphy, "GIPHY");
    accept("https://giphy.com/embed/cZ7rmKfFYOvYI", giphy, "GIPHY");
    accept("https://media2.giphy.com/media/cZ7rmKfFYOvYI/giphy.gif", giphy, "GIPHY");
    accept("https://media.giphy.com/media/v1.Y2lkPT_test/cZ7rmKfFYOvYI/giphy.gif?cid=123", giphy, "GIPHY");
    accept("https://i.giphy.com/cZ7rmKfFYOvYI.gif", giphy, "GIPHY");

    for (const std::string url : {
        "", "https://example.com/a.jpg", "https://imgur.com.evil.test/7iqCyFw",
        "https://evilimgur.com/7iqCyFw", "https://imgur.com@evil.test/7iqCyFw",
        "https://evil.test@imgur.com/7iqCyFw", "https://imgur.com:444/7iqCyFw",
        "https://imgur.com.:443/7iqCyFw", "https://imgur%2ecom/7iqCyFw",
        "https://imgur.com\\@evil.test/7iqCyFw", "https://i.imgur.com/../7iqCyFw.jpg",
        "https://imgur.com/%2e%2e/7iqCyFw", "https://imgur.com/7iqCyFw\r\nHost: evil.test",
        "file://imgur.com/7iqCyFw", "ftp://imgur.com/7iqCyFw", "javascript:imgur.com/7iqCyFw",
        "https://127.0.0.1/7iqCyFw", "https://youtube.com/redirect?q=https://example.com",
        "https://youtube.com/watch?v=short", "https://youtube.com/watch?v=dQw4w9WgXcQevil",
        "https://youtube.com/watch?notv=dQw4w9WgXcQ", "https://youtu.be/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/channel/dQw4w9WgXcQ", "https://evil.giphy.com/media/cZ7rmKfFYOvYI/giphy.gif",
        "https://giphy.com/gifs/%2e%2e", "https://giphy.com/search/cats",
        "https://imgur.com/a/7iqCyFw", "https://imgur.com/gallery/7iqCyFw",
        "https://imgur.com/7iqCyFw/extra", "https://imgur.com/7iqCyFw.html",
        "https://imgur.com/7iqCyFw#fragment\ttext",
        "https://imgur.com/7iqCyFw?x=\x7f", "https://imgur.com/7iqCyFw?x=\v"
    }) {
        assert(ll_chat_link_preview(url).thumbnail.empty());
        ++checks;
    }
    assert(ll_chat_link_preview("https://imgur.com/7iqCyFw?" + std::string(2048, 'a')).thumbnail.empty());
    std::cout << checks + 2 << " preview URL checks passed\n";
}
'''

with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "previews.cpp"
    exe = Path(directory) / "previews.exe"
    cpp.write_text(PROGRAM, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-I", str(ROOT / "indra/newview"),
                    str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

settings = ET.parse(ROOT / "indra/newview/app_settings/settings.xml")
keys = settings.findall("./map/key")
assert sum(key.text == "ChatLinkPreviews" for key in keys) == 1
panel = ET.parse(ROOT / "indra/newview/skins/default/xui/en/panel_preferences_chat.xml")
assert panel.find(".//check_box[@control_name='ChatLinkPreviews']") is not None
strings = ET.parse(ROOT / "indra/newview/skins/default/xui/en/strings.xml")
for name in ("ChatLinkPreviewOpen", "ChatLinkPreviewLoading", "ChatLinkPreviewUnavailable"):
    assert strings.find(f"./string[@name='{name}']") is not None
print("Preview settings and UI resources passed")
