"""
多平台视频解析模块
支持：抖音、快手、B站、微博、小红书、TikTok、YouTube、Instagram、Twitter/X、西瓜视频
"""

import re
import json
import random
import asyncio
import logging
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _headers(referer: str = "https://www.douyin.com/", mobile: bool = False) -> Dict[str, str]:
    return {
        "User-Agent": MOBILE_UA if mobile else DESKTOP_UA,
        "Referer": referer,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _empty_result(message: str = "") -> Dict[str, Any]:
    return {"success": False, "message": message, "data": None}


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, "message": "解析成功", "data": data}


def _make_info(**kwargs) -> Dict[str, Any]:
    info = {
        "id": "", "title": "无标题", "author": "未知作者", "author_avatar": "",
        "cover": "", "duration": 0, "video_url": "", "video_url_no_watermark": "",
        "platform": "", "create_time": 0, "digg_count": 0, "comment_count": 0, "share_count": 0,
    }
    info.update(kwargs)
    return info


async def _follow_redirects(url: str, timeout: float = 10.0) -> str:
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout, verify=False) as c:
        r = await c.get(url, headers=_headers())
        count = 0
        while r.is_redirect and count < 10:
            loc = r.headers.get("location", "")
            if not loc:
                break
            if loc.startswith("/"):
                p = urlparse(str(r.url))
                loc = f"{p.scheme}://{p.netloc}{loc}"
            r = await c.get(loc, headers=_headers())
            count += 1
        return str(r.url)


async def _fetch(url: str, headers: Dict = None, timeout: float = 15.0, follow: bool = True) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=follow) as c:
            r = await c.get(url, headers=headers or _headers())
            if r.status_code == 200:
                return r.text
    except Exception as e:
        logger.warning(f"Fetch {url} failed: {e}")
    return None


def _extract_url(text: str) -> Optional[str]:
    """从任意文本中提取 URL"""
    m = re.search(r"https?://[^\s<>\"'\)]+", text)
    return m.group(0) if m else None


# ─── 抖音 ────────────────────────────────────────────
DOMAINS_DOUYIN = ["v.douyin.com", "www.douyin.com", "www.iesdouyin.com", "m.douyin.com"]

async def parse_douyin(url: str) -> Dict[str, Any]:
    url = url.rstrip("/")
    # 短链接重定向
    parsed = urlparse(url)
    if "v.douyin.com" in parsed.netloc:
        url = await _follow_redirects(url)
        parsed = urlparse(url)

    # 提取 video ID
    video_id = None
    for pat in [r"/video/(\d+)", r"/note/(\d+)", r"modal_id=(\d+)", r"aweme_id=(\d+)"]:
        m = re.search(pat, url)
        if m:
            video_id = m.group(1)
            break
    if not video_id:
        parts = parsed.path.strip("/").split("/")
        if parts and parts[-1].isdigit():
            video_id = parts[-1]
    if not video_id:
        return _empty_result("无法提取视频 ID")

    # 通过 iesdouyin 移动端页面获取数据
    page_url = f"https://www.iesdouyin.com/share/video/{video_id}/"
    html = await _fetch(page_url, headers=_headers(mobile=True))
    if not html:
        return _empty_result("获取页面失败")

    # 提取 item_list
    marker = '"item_list":['
    start = html.find(marker)
    if start < 0:
        return _empty_result("页面解析失败，链接可能已失效")

    bracket_start = html.index("[", start)
    depth = 0
    end = bracket_start
    for i in range(bracket_start, len(html)):
        if html[i] == "[":
            depth += 1
        elif html[i] == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    try:
        items = json.loads(html[bracket_start:end])
    except Exception:
        return _empty_result("JSON 解析失败")

    item = items[0]
    author = item.get("author", {})
    video = item.get("video", {})
    stats = item.get("statistics", {})
    cover = video.get("cover", {})
    cover_url = cover.get("url_list", [""])[0] if isinstance(cover, dict) else ""
    play = video.get("play_addr", {})
    play_urls = play.get("url_list", []) if isinstance(play, dict) else []
    video_url = play_urls[0].replace("\\u002F", "/") if play_urls else ""
    avatar = author.get("avatar_thumb", {})
    avatar_url = avatar.get("url_list", [""])[0] if isinstance(avatar, dict) else ""

    info = _make_info(
        id=video_id, platform="douyin",
        title=item.get("desc", "") or "无标题",
        author=author.get("nickname", "未知作者"),
        author_avatar=avatar_url,
        cover=cover_url,
        duration=video.get("duration", 0) // 1000,
        video_url=video_url,
        video_url_no_watermark=video_url.replace("playwm", "play"),
        create_time=item.get("create_time", 0),
        digg_count=stats.get("digg_count", 0),
        comment_count=stats.get("comment_count", 0),
        share_count=stats.get("share_count", 0),
    )

    # 图文笔记：aweme_type=2 表示图片帖
    aweme_type = item.get("aweme_type", 0)
    images = item.get("images") or []
    is_image_post = aweme_type == 2 or (isinstance(images, list) and len(images) > 0)
    if is_image_post and images:
        image_list = []
        for img in images:
            url_list = img.get("download_url_list") or img.get("url_list") or []
            if url_list:
                img_url = url_list[0]
                if img_url:
                    image_list.append(img_url)
        if image_list:
            info["image_list"] = image_list
            info["note_type"] = "image"
            info["video_url"] = ""
            info["video_url_no_watermark"] = ""
    else:
        info["note_type"] = "video"

    return _ok(info)


# ─── 快手 ────────────────────────────────────────────
DOMAINS_KUAISHOU = ["v.kuaishou.com", "www.kuaishou.com", "v.kuaishou.com"]

async def parse_kuaishou(url: str) -> Dict[str, Any]:
    url = url.rstrip("/")
    parsed = urlparse(url)
    if "v.kuaishou.com" in parsed.netloc:
        url = await _follow_redirects(url)

    # 提取 photo ID
    photo_id = None
    m = re.search(r"/short-video/(\w+)", url)
    if m:
        photo_id = m.group(1)
    else:
        m = re.search(r"photoId=(\w+)", url)
        if m:
            photo_id = m.group(1)
    if not photo_id:
        return _empty_result("无法提取快手视频 ID")

    # 快手 API
    api_url = f"https://m.gifshow.com/rest/wd/photo/info?photoId={photo_id}"
    headers = _headers(referer="https://m.gifshow.com/", mobile=True)
    try:
        async with httpx.AsyncClient(timeout=15, verify=False) as c:
            r = await c.get(api_url, headers=headers)
            data = r.json()
    except Exception:
        return _empty_result("快手 API 请求失败")

    if data.get("result") != 1:
        return _empty_result(data.get("error_msg", "快手解析失败"))

    photo = data.get("photo", {})
    urls = photo.get("mainMvUrl", [])
    video_url = urls[0] if urls else ""
    # 无水印
    urls_nw = photo.get("mainMvUrlNoWatermark", [])
    video_url_nw = urls_nw[0] if urls_nw else video_url

    return _ok(_make_info(
        id=photo_id, platform="kuaishou",
        title=photo.get("caption", "") or "无标题",
        author=photo.get("userName", "未知作者"),
        cover=photo.get("coverUrl", ""),
        duration=photo.get("duration", 0) // 1000,
        video_url=video_url,
        video_url_no_watermark=video_url_nw,
        digg_count=photo.get("likeCount", 0),
        comment_count=photo.get("commentCount", 0),
        share_count=photo.get("shareCount", 0),
    ))


# ─── B站 ──────────────────────────────────────────────
DOMAINS_BILIBILI = ["b23.tv", "www.bilibili.com", "m.bilibili.com", "bilibili.com"]

async def parse_bilibili(url: str) -> Dict[str, Any]:
    url = url.rstrip("/")
    parsed = urlparse(url)
    if "b23.tv" in parsed.netloc:
        url = await _follow_redirects(url)

    # 提取 BV 号
    m = re.search(r"(BV[\w]{10})", url)
    if not m:
        return _empty_result("无法提取 B 站视频 BV 号")
    bvid = m.group(1)

    # 获取 cid
    api = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    headers = _headers(referer="https://www.bilibili.com/")
    try:
        async with httpx.AsyncClient(timeout=15, verify=False) as c:
            r = await c.get(api, headers=headers)
            data = r.json()
    except Exception:
        return _empty_result("B 站 API 请求失败")

    if data.get("code") != 0:
        return _empty_result(data.get("message", "B 站解析失败"))

    vdata = data.get("data", {})
    cid = vdata.get("cid", 0)
    if not cid:
        pages = vdata.get("pages", [])
        cid = pages[0]["cid"] if pages else 0

    # 获取播放地址
    play_api = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&qn=80&fnval=1"
    try:
        async with httpx.AsyncClient(timeout=15, verify=False) as c:
            r = await c.get(play_api, headers=headers)
            play_data = r.json()
    except Exception:
        return _empty_result("B 站播放地址获取失败")

    durl = play_data.get("data", {}).get("durl", [])
    video_url = durl[0]["url"] if durl else ""

    stat = vdata.get("stat", {})
    owner = vdata.get("owner", {})
    pic = vdata.get("pic", "")

    return _ok(_make_info(
        id=bvid, platform="bilibili",
        title=vdata.get("title", "") or "无标题",
        author=owner.get("name", "未知作者"),
        author_avatar=owner.get("face", ""),
        cover=pic if pic.startswith("http") else f"https:{pic}" if pic.startswith("//") else pic,
        duration=vdata.get("duration", 0),
        video_url=video_url,
        video_url_no_watermark=video_url,
        create_time=vdata.get("pubdate", 0),
        digg_count=stat.get("like", 0),
        comment_count=stat.get("reply", 0),
        share_count=stat.get("share", 0),
    ))


# ─── 微博 ────────────────────────────────────────────
DOMAINS_WEibo = ["weibo.com", "m.weibo.cn", "video.weibo.com"]

async def parse_weibo(url: str) -> Dict[str, Any]:
    url = url.rstrip("/")
    # 提取微博视频 ID
    m = re.search(r"/video/(\w+)", url) or re.search(r"video_id=(\w+)", url)
    if not m:
        # 尝试从页面提取
        html = await _fetch(url, headers=_headers(referer="https://weibo.com/", mobile=True))
        if html:
            m = re.search(r'"video_id"\s*:\s*"(\w+)"', html)
    if not m:
        return _empty_result("无法提取微博视频 ID")
    vid = m.group(1)

    api = f"https://m.weibo.cn/api/container/getIndex?containerid=231248{vid}"
    try:
        async with httpx.AsyncClient(timeout=15, verify=False) as c:
            r = await c.get(api, headers=_headers(referer="https://m.weibo.cn/", mobile=True))
            data = r.json()
    except Exception:
        return _empty_result("微博 API 请求失败")

    card = data.get("data", {}).get("card", {})
    info_data = card.get("mblog", {}) or card.get("card_info", {})
    page_info = info_data.get("page_info", {})
    media = page_info.get("urls", {}) or page_info.get("media_info", {})

    video_url = ""
    for key in ["mp4_720p_mp4", "mp4_hd_mp4", "mp4_ld_mp4", "stream_url_hd", "stream_url"]:
        if key in media:
            video_url = media[key]
            break

    return _ok(_make_info(
        id=vid, platform="weibo",
        title=info_data.get("text", "无标题")[:100],
        author=info_data.get("user", {}).get("screen_name", "未知作者"),
        cover=page_info.get("page_pic", {}).get("url", ""),
        duration=page_info.get("media_info", {}).get("duration", 0),
        video_url=video_url,
        video_url_no_watermark=video_url,
    ))


# ─── 小红书 ──────────────────────────────────────────
DOMAINS_XHS = ["xiaohongshu.com", "xhslink.com", "www.xiaohongshu.com"]

async def parse_xiaohongshu(url: str) -> Dict[str, Any]:
    url = url.rstrip("/")
    parsed = urlparse(url)
    if "xhslink.com" in parsed.netloc:
        url = await _follow_redirects(url)

    # 提取笔记 ID
    m = re.search(r"/explore/(\w+)", url) or re.search(r"/discovery/item/(\w+)", url)
    if not m:
        parts = urlparse(url).path.strip("/").split("/")
        m_val = parts[-1] if len(parts) > 1 else None
    else:
        m_val = m.group(1)

    if not m_val:
        return _empty_result("无法提取小红书笔记 ID")

    # 使用桌面端 UA（带 xsec_token 的完整 URL 需要桌面端）
    headers = {
        "User-Agent": DESKTOP_UA,
        "Referer": "https://www.xiaohongshu.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    html = await _fetch(url, headers=headers)
    if not html:
        return _empty_result("获取小红书页面失败")

    m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>', html, re.DOTALL)
    if not m:
        return _empty_result("页面解析失败")

    try:
        raw = m.group(1).replace("undefined", "null")
        state = json.loads(raw)
    except Exception:
        return _empty_result("JSON 解析失败")

    # 数据路径: state.note.noteDetailMap[note_id].note
    note_map = state.get("note", {}).get("noteDetailMap", {})
    if not note_map:
        return _empty_result("未找到笔记数据")

    note_data = note_map.get(m_val, {}).get("note", {})
    if not note_data:
        # 尝试取第一个
        first_key = next(iter(note_map))
        note_data = note_map[first_key].get("note", {})

    if not note_data:
        return _empty_result("笔记数据为空")

    user = note_data.get("user", {})
    video = note_data.get("video", {})
    image_list = note_data.get("imageList", [])

    # 封面
    cover = ""
    if image_list:
        cover = image_list[0].get("urlDefault", "") or image_list[0].get("url", "")

    # 视频 URL（优先使用 backupUrls，它们不过期）
    video_url = ""
    media = video.get("media", {})
    if isinstance(media, dict):
        stream = media.get("stream", {})
        for codec in ["h264", "h265", "av1"]:
            streams = stream.get(codec, [])
            if isinstance(streams, list) and streams:
                entry = streams[0]
                backups = entry.get("backupUrls", [])
                if backups:
                    video_url = backups[0]
                else:
                    video_url = entry.get("masterUrl", "")
                if video_url:
                    break

    # 判断是视频还是图文
    is_video = bool(video_url)
    title = note_data.get("title", "") or note_data.get("desc", "") or "无标题"

    info = _make_info(
        id=m_val, platform="xiaohongshu",
        title=title,
        author=user.get("nickname", "未知作者"),
        author_avatar=user.get("avatar", ""),
        cover=cover,
        video_url=video_url,
        video_url_no_watermark=video_url,
    )

    # 图文笔记：存储图片列表
    if not is_video and image_list:
        info["image_list"] = [img.get("urlDefault", "") or img.get("url", "") for img in image_list if img.get("urlDefault") or img.get("url")]
        info["note_type"] = "image"
    else:
        info["note_type"] = "video" if is_video else "unknown"

    return _ok(info)


# ─── TikTok ──────────────────────────────────────────
DOMAINS_TIKTOK = ["vm.tiktok.com", "www.tiktok.com", "tiktok.com"]

async def parse_tiktok(url: str) -> Dict[str, Any]:
    url = url.rstrip("/")
    parsed = urlparse(url)
    if "vm.tiktok.com" in parsed.netloc:
        url = await _follow_redirects(url)

    m = re.search(r"/video/(\d+)", url)
    if not m:
        return _empty_result("无法提取 TikTok 视频 ID")
    video_id = m.group(1)

    # TikTok 页面
    html = await _fetch(f"https://www.tiktok.com/@/video/{video_id}",
                        headers=_headers(referer="https://www.tiktok.com/", mobile=True))
    if not html:
        return _empty_result("获取 TikTok 页面失败")

    # 尝试提取 SIGI_STATE
    m = re.search(r'<script\s+id="SIGI_STATE"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        m = re.search(r'window\.__NEXT_DATA__\s*=\s*(\{.*?\})\s*</script>', html, re.DOTALL)
    if not m:
        return _empty_result("TikTok 页面解析失败")

    try:
        data = json.loads(m.group(1))
    except Exception:
        return _empty_result("JSON 解析失败")

    # 从数据中提取视频信息
    item_module = data.get("ItemModule", {}) or data.get("props", {}).get("pageProps", {}).get("itemInfo", {})
    items = item_module.get("items", {}) if isinstance(item_module, dict) else {}
    if isinstance(items, dict):
        item = list(items.values())[0] if items else {}
    elif isinstance(items, list):
        item = items[0] if items else {}
    else:
        item = {}

    author = item.get("author", {}) or item.get("authorInfo", {})
    video_info = item.get("video", {})
    stats = item.get("stats", {}) or item.get("statsV2", {})

    play_addr = video_info.get("playAddr", "")
    if isinstance(play_addr, list):
        play_addr = play_addr[0] if play_addr else ""
    if isinstance(play_addr, dict):
        play_addr = play_addr.get("url", "")

    return _ok(_make_info(
        id=video_id, platform="tiktok",
        title=item.get("desc", "") or "无标题",
        author=author.get("uniqueId", "") or author.get("nickname", "未知作者"),
        cover=video_info.get("cover", "") or video_info.get("originCover", ""),
        duration=video_info.get("duration", 0),
        video_url=play_addr,
        video_url_no_watermark=play_addr,
        digg_count=stats.get("diggCount", 0) if isinstance(stats, dict) else 0,
        comment_count=stats.get("commentCount", 0) if isinstance(stats, dict) else 0,
        share_count=stats.get("shareCount", 0) if isinstance(stats, dict) else 0,
    ))


# ─── YouTube ─────────────────────────────────────────
DOMAINS_YOUTUBE = ["youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"]

async def parse_youtube(url: str) -> Dict[str, Any]:
    # 提取 video ID
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([\w-]{11})", url)
    if not m:
        return _empty_result("无法提取 YouTube 视频 ID")
    vid = m.group(1)

    # 使用 oembed API 获取基本信息
    oembed = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"
    try:
        async with httpx.AsyncClient(timeout=15, verify=False) as c:
            r = await c.get(oembed, headers=_headers(referer="https://www.youtube.com/"))
            info = r.json()
    except Exception:
        return _empty_result("YouTube oEmbed 请求失败")

    title = info.get("title", "无标题")
    author = info.get("author_name", "未知作者")
    thumbnail = info.get("thumbnail_url", "")

    # YouTube 视频无法直接获取下载链接，使用第三方服务
    # 返回 embed 预览链接
    embed_url = f"https://www.youtube.com/embed/{vid}"

    return _ok(_make_info(
        id=vid, platform="youtube",
        title=title, author=author,
        cover=thumbnail,
        video_url=embed_url,
        video_url_no_watermark=embed_url,
    ))


# ─── Instagram Reels ──────────────────────────────────
DOMAINS_INSTAGRAM = ["instagram.com", "www.instagram.com", "instagr.am"]

async def parse_instagram(url: str) -> Dict[str, Any]:
    url = url.rstrip("/")
    m = re.search(r"/reel/(\w+)", url) or re.search(r"/p/(\w+)", url) or re.search(r"/tv/(\w+)", url)
    if not m:
        return _empty_result("无法提取 Instagram 帖子 ID")
    post_id = m.group(1)

    # Instagram 需要登录才能获取视频，返回 embed 链接
    embed_url = f"https://www.instagram.com/reel/{post_id}/embed/"

    return _ok(_make_info(
        id=post_id, platform="instagram",
        title="Instagram Reels",
        video_url=embed_url,
        video_url_no_watermark=embed_url,
    ))


# ─── Twitter/X ────────────────────────────────────────
DOMAINS_TWITTER = ["twitter.com", "x.com", "www.twitter.com", "www.x.com", "t.co"]

async def parse_twitter(url: str) -> Dict[str, Any]:
    url = url.rstrip("/")
    if "t.co" in urlparse(url).netloc:
        url = await _follow_redirects(url)

    m = re.search(r"/status/(\d+)", url)
    if not m:
        return _empty_result("无法提取推文 ID")
    tweet_id = m.group(1)

    # Twitter/X 嵌入
    embed_url = f"https://platform.twitter.com/embed/Tweet.html?id={tweet_id}"

    return _ok(_make_info(
        id=tweet_id, platform="twitter",
        title="Twitter/X 视频",
        video_url=embed_url,
        video_url_no_watermark=embed_url,
    ))


# ─── 西瓜视频 ────────────────────────────────────────
DOMAINS_XIGUA = [".ixigua.com", "www.ixigua.com", "m.ixigua.com"]

async def parse_xigua(url: str) -> Dict[str, Any]:
    url = url.rstrip("/")
    m = re.search(r"/(\d{15,})", url)
    if not m:
        return _empty_result("无法提取西瓜视频 ID")
    vid = m.group(1)

    # 西瓜视频 API
    api = f"https://ib.365yg.com/api/news/feed/v88/?group_id={vid}&item_id={vid}"
    try:
        async with httpx.AsyncClient(timeout=15, verify=False) as c:
            r = await c.get(api, headers=_headers(referer="https://www.ixigua.com/"))
            data = r.json()
    except Exception:
        return _empty_result("西瓜视频 API 请求失败")

    item_list = data.get("data", [])
    if not item_list:
        return _empty_result("西瓜视频解析失败")

    item = item_list[0] if isinstance(item_list, list) else item_list
    video_url = item.get("video_url", "") or item.get("mp4_url", "")

    return _ok(_make_info(
        id=vid, platform="xigua",
        title=item.get("title", "") or "无标题",
        author=item.get("source", "未知作者"),
        cover=item.get("large_image_url", ""),
        video_url=video_url,
        video_url_no_watermark=video_url,
    ))


# ─── 平台路由 ────────────────────────────────────────
PLATFORM_MAP = {
    "douyin": (DOMAINS_DOUYIN, parse_douyin),
    "kuaishou": (DOMAINS_KUAISHOU, parse_kuaishou),
    "bilibili": (DOMAINS_BILIBILI, parse_bilibili),
    "weibo": (DOMAINS_WEibo, parse_weibo),
    "xiaohongshu": (DOMAINS_XHS, parse_xiaohongshu),
    "tiktok": (DOMAINS_TIKTOK, parse_tiktok),
    "youtube": (DOMAINS_YOUTUBE, parse_youtube),
    "instagram": (DOMAINS_INSTAGRAM, parse_instagram),
    "twitter": (DOMAINS_TWITTER, parse_twitter),
    "xigua": (DOMAINS_XIGUA, parse_xigua),
}


def detect_platform(url: str) -> Optional[str]:
    """根据 URL 自动检测平台"""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    for platform, (domains, _) in PLATFORM_MAP.items():
        for d in domains:
            if d in netloc:
                return platform
    return None


async def parse_link(url: str) -> Dict[str, Any]:
    """统一入口：自动检测平台并解析"""
    raw_url = _extract_url(url)
    if raw_url:
        url = raw_url

    url = url.strip().rstrip("/")
    platform = detect_platform(url)

    if platform:
        _, parser = PLATFORM_MAP[platform]
        return await parser(url)

    return _empty_result("不支持的平台或无效链接")


async def batch_parse(urls: List[str]) -> List[Dict[str, Any]]:
    """批量解析"""
    results = []
    for u in urls:
        u = u.strip()
        if not u:
            continue
        if results:
            await asyncio.sleep(random.uniform(0.5, 1.5))
        results.append(await parse_link(u))
    return results
