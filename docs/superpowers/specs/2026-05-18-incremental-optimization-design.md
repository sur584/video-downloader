# Incremental Optimization Design Spec

**Date**: 2026-05-18
**Approach**: A — Incremental Targeted Fixes
**Status**: Approved

---

## Goal

Improve code quality, reliability, and user experience of the video downloader through targeted, low-risk changes. No full rewrites.

---

## 1. Parser Module Split

### Current State

`backend/parser.py` (672 lines) contains 10 platform parsers + shared utilities in a single file.

### Target Structure

```
backend/
  parsers/
    __init__.py      # parse_link, batch_parse, detect_platform, PLATFORM_MAP, parse_with_cache
    _utils.py        # MOBILE_UA, DESKTOP_UA, _headers, _fetch, _follow_redirects, _extract_url, _make_info, _empty_result, _ok
    douyin.py        # parse_douyin
    kuaishou.py      # parse_kuaishou
    bilibili.py      # parse_bilibili
    weibo.py         # parse_weibo
    xiaohongshu.py   # parse_xiaohongshu
    tiktok.py        # parse_tiktok
    youtube.py       # parse_youtube
    instagram.py     # parse_instagram
    twitter.py       # parse_twitter
    xigua.py         # parse_xigua
```

### Changes

- `_utils.py`: All shared constants and helper functions
- Each platform file: exports `async def parse_xxx(url) -> Dict`
- `__init__.py`: Re-exports `parse_link`, `batch_parse`, `detect_platform`
- `main.py`: `from parser import ...` → `from parsers import ...` (only import path changes)

---

## 2. Cache + Retry

### Cache

- In-memory `dict` keyed by normalized URL
- TTL: 600 seconds (10 minutes)
- Only successful results are cached

```python
_cache = {}
CACHE_TTL = 600

async def parse_with_cache(url):
    now = time.time()
    if url in _cache and now - _cache[url][0] < CACHE_TTL:
        return _cache[url][1]
    result = await _parse_with_retry(url)
    if result["success"]:
        _cache[url] = (now, result)
    return result
```

### Retry

- On parse failure, retry once after 1-second delay
- Only retries on non-success results (not on exceptions that already propagate)

---

## 3. Parallel Batch Parsing

### Current

Sequential processing with random 0.5-1.5s delay.

### Target

- `asyncio.gather` with `asyncio.Semaphore(3)` — up to 3 concurrent parses
- Random delay preserved between batches for anti-detection
- Progress callback for frontend (optional, future use)

---

## 4. Platform-Specific Error Messages

Each parser returns contextual error messages instead of generic failures:

| Scenario | Message |
|----------|---------|
| Login required | "该视频需要登录才能访问" |
| Link expired | "链接已过期或失效，请重新获取" |
| Content type unsupported | "该平台暂不支持此类型内容" |
| Network timeout | "解析超时，请稍后重试" |
| Parse failure | "页面解析失败，可能需要登录或链接已失效" |

---

## 5. Frontend Micro-Interactions

### Skeleton Loading

Replace blank result panel with skeleton placeholder during parse:
- Animated pulse effect on cover, title, meta areas
- Shows immediately on parse click, replaced by real content on success

### Selective Image Download

For multi-image posts (Douyin/XHS), support selective download:

**UI in result panel:**
- Each image in the gallery gets a checkbox overlay (top-left corner)
- "全选" checkbox above the gallery
- Action bar below gallery: "下载选中 (3)" | "下载全部 (8)" | "复制选中链接"

**Behavior:**
- Click image to toggle selection (visual highlight border)
- Checkbox reflects selection state
- "下载选中" downloads only checked images
- "下载全部" downloads all images (clears selection)
- "复制选中链接" copies only selected image URLs

**Implementation:**
- Track selection state in `Set` of image indices
- Download function accepts index array
- Progress: "3/8 下载中..." with per-image progress bar

---

## Files Modified

| File | Change |
|------|--------|
| `backend/parser.py` | **Deleted** — replaced by `parsers/` package |
| `backend/parsers/__init__.py` | **New** — entry point, cache, retry |
| `backend/parsers/_utils.py` | **New** — shared utilities |
| `backend/parsers/douyin.py` | **New** — Douyin parser |
| `backend/parsers/kuaishou.py` | **New** — Kuaishou parser |
| `backend/parsers/bilibili.py` | **New** — Bilibili parser |
| `backend/parsers/weibo.py` | **New** — Weibo parser |
| `backend/parsers/xiaohongshu.py` | **New** — XHS parser |
| `backend/parsers/tiktok.py` | **New** — TikTok parser |
| `backend/parsers/youtube.py` | **New** — YouTube parser |
| `backend/parsers/instagram.py` | **New** — Instagram parser |
| `backend/parsers/twitter.py` | **New** — Twitter parser |
| `backend/parsers/xigua.py` | **New** — Xigua parser |
| `backend/main.py` | Import path change only |
| `frontend/js/app.js` | Skeleton loading, selective image download, progress |
| `frontend/css/style.css` | Skeleton styles, gallery selection styles |
| `frontend/index.html` | Gallery action bar, select all checkbox |

---

## Out of Scope

- Database migration (stays JSON)
- Frontend build tooling (stays vanilla JS)
- WebSocket real-time progress
- New platform additions
- Docker/deployment changes
