/** Small, closed allowlist for DM thumbnail links. */
#ifndef LL_LLCHATLINKPREVIEW_H
#define LL_LLCHATLINKPREVIEW_H

#include <algorithm>
#include <cctype>
#include <regex>
#include <string>

struct LLChatLinkPreview
{
    std::string url;
    std::string thumbnail;
    std::string provider;
};

inline LLChatLinkPreview ll_chat_link_preview(const std::string& url)
{
    // Match the entire authority, never a domain substring. No credentials,
    // ports, escaped hosts, or arbitrary subdomains are accepted.
    if (url.size() > 2048 || std::any_of(url.begin(), url.end(),
        [](unsigned char c) { return c <= 0x20 || c == 0x7f || c == '\\'; }))
        return {};
    static const std::regex uri(R"(^https?://([^/?#]+)(/[^?#]*)?(\?[^#]*)?(#[^\r\n]*)?$)", std::regex::icase);
    std::smatch parts;
    if (!std::regex_match(url, parts, uri))
        return {};
    std::string host = parts[1];
    std::transform(host.begin(), host.end(), host.begin(), [](unsigned char c) { return std::tolower(c); });
    const std::string path = parts[2];
    const std::string query = parts[3];
    std::smatch match;
    std::string id, thumbnail, provider;

    if (host == "youtube.com" || host == "www.youtube.com" || host == "m.youtube.com" || host == "youtu.be")
    {
        static const std::regex short_path(R"(^/([A-Za-z0-9_-]{11})/?$)");
        static const std::regex video_path(R"(^/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})/?$)");
        static const std::regex video_query(R"([?&]v=([A-Za-z0-9_-]{11})(?:&|$))");
        if (host == "youtu.be" && std::regex_match(path, match, short_path))
            id = match[1];
        else if (host != "youtu.be" && std::regex_match(path, match, video_path))
            id = match[1];
        else if (host != "youtu.be" && path == "/watch" && std::regex_search(query, match, video_query))
            id = match[1];
        if (!id.empty())
        {
            thumbnail = "https://i.ytimg.com/vi/" + id + "/hqdefault.jpg";
            provider = "YouTube";
        }
    }
    else if (host == "imgur.com" || host == "www.imgur.com" || host == "m.imgur.com" || host == "i.imgur.com")
    {
        // ponytail: single-image links only; albums need a separate cover lookup.
        static const std::regex image_path(R"(^/([A-Za-z0-9]{5}|[A-Za-z0-9]{7})(?:\.(?:jpg|jpeg|png|gif|gifv|mp4|webp))?/?$)", std::regex::icase);
        if (std::regex_match(path, match, image_path))
        {
            thumbnail = "https://i.imgur.com/" + match[1].str() + "m.jpg";
            provider = "Imgur";
        }
    }
    else if (host == "giphy.com" || host == "www.giphy.com" || host == "i.giphy.com"
        || host == "media.giphy.com" || host == "media0.giphy.com" || host == "media1.giphy.com"
        || host == "media2.giphy.com" || host == "media3.giphy.com" || host == "media4.giphy.com")
    {
        static const std::regex share_path(R"(^/(?:gifs|stickers)/(?:[A-Za-z0-9_-]*-)?([A-Za-z0-9]{1,64})/?$)");
        static const std::regex embed_path(R"(^/embed/([A-Za-z0-9]{1,64})/?$)");
        static const std::regex media_path(R"(^/media/(?:v1\.[A-Za-z0-9_-]+/)?([A-Za-z0-9]{1,64})/[A-Za-z0-9_.-]+$)");
        static const std::regex direct_path(R"(^/([A-Za-z0-9]{1,64})\.(?:gif|webp|mp4)$)");
        if ((host == "giphy.com" || host == "www.giphy.com")
            && (std::regex_match(path, match, share_path) || std::regex_match(path, match, embed_path)))
            id = match[1];
        else if (std::regex_match(path, match, media_path)
            || (host == "i.giphy.com" && std::regex_match(path, match, direct_path)))
            id = match[1];
        if (!id.empty())
        {
            thumbnail = "https://media.giphy.com/media/" + id + "/480w_s.jpg";
            provider = "GIPHY";
        }
    }
    return thumbnail.empty() ? LLChatLinkPreview{} : LLChatLinkPreview{
        "https://" + host + path + query + parts[4].str(), thumbnail, provider};
}

#endif
