"""
视频解析下载工具 - 后端服务
基于 FastAPI 提供多平台视频解析、下载、预览代理等 API
"""

import os
import json
import time
import uuid
import logging
import asyncio
from pathlib import Path
from typing import List

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import yt_dlp

from parsers import parse_link, batch_parse
from parsers._utils import _is_safe_url, _extract_url

# ─── 配置 ─────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
HISTORY_FILE = BASE_DIR / "history.json"
FRONTEND_DIR = BASE_DIR.parent / "frontend"

DOWNLOAD_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger(__name__)

# ─── FastAPI 应用 ─────────────────────────────────────
app = FastAPI(title="视频解析下载工具", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8866", "http://localhost:8866"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── 数据模型 ─────────────────────────────────────────
class ParseRequest(BaseModel):
    url: str

class BatchParseRequest(BaseModel):
    urls: List[str]


# ─── 历史记录 ─────────────────────────────────────────
def _load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def _save_history(history: list):
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

def _add_to_history(video_info: dict):
    history = _load_history()
    record = {"id": str(uuid.uuid4())[:8], "parse_time": time.strftime("%Y-%m-%d %H:%M:%S"), **video_info}
    history.insert(0, record)
    _save_history(history[:200])


# ─── API 路由 ─────────────────────────────────────────
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "2.0.0"}


@app.get("/api/platforms")
async def supported_platforms():
    """返回支持的平台列表"""
    return {"platforms": [
        {"id": "douyin", "name": "抖音", "domains": ["douyin.com", "iesdouyin.com"]},
        {"id": "bilibili", "name": "B站", "domains": ["bilibili.com", "b23.tv"]},
        {"id": "weibo", "name": "微博", "domains": ["weibo.com", "weibo.cn"]},
        {"id": "xiaohongshu", "name": "小红书", "domains": ["xiaohongshu.com", "xhslink.com"]},
        {"id": "tiktok", "name": "TikTok", "domains": ["tiktok.com"]},
        {"id": "youtube", "name": "YouTube", "domains": ["youtube.com", "youtu.be"]},
        {"id": "instagram", "name": "Instagram", "domains": ["instagram.com"]},
        {"id": "twitter", "name": "Twitter/X", "domains": ["twitter.com", "x.com", "t.co"]},
        {"id": "xigua", "name": "西瓜视频", "domains": ["ixigua.com"]},
    ]}


@app.post("/api/parse")
async def parse_video(req: ParseRequest):
    """解析视频链接（自动识别平台）"""
    from urllib.parse import urlparse as _urlparse
    # 从输入文本中提取 URL（支持粘贴带文字的分享文本）
    raw = req.url.strip()
    extracted = _extract_url(raw)
    url = extracted or raw
    parsed = _urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="仅支持 http/https 链接")
    if not _is_safe_url(url):
        raise HTTPException(status_code=403, detail="不允许访问该地址")
    result = await parse_link(url)
    if result["success"] and result["data"]:
        _add_to_history(result["data"])
    return result


@app.post("/api/batch-parse")
async def batch_parse_videos(req: BatchParseRequest):
    """批量解析（最多 20 个）"""
    if len(req.urls) > 20:
        raise HTTPException(status_code=400, detail="批量解析最多支持 20 个链接")
    # 从每行文本中提取 URL
    urls = [_extract_url(u.strip()) or u.strip() for u in req.urls]
    results = await batch_parse(urls)
    for r in results:
        if r["success"] and r["data"]:
            _add_to_history(r["data"])
    return {"results": results}


@app.get("/api/proxy")
async def proxy_video(video_url: str = Query(...), referer: str = Query("https://www.douyin.com/")):
    """
    视频代理：解决浏览器跨域和 Referer 限制
    前端通过此接口加载视频进行在线预览
    """
    if not video_url:
        raise HTTPException(status_code=400, detail="URL 不能为空")
    if not _is_safe_url(video_url):
        raise HTTPException(status_code=403, detail="不允许访问该地址")

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": referer,
        }
        # 先获取完整内容再返回（避免流式传输的 chunked encoding 问题）
        async with httpx.AsyncClient(timeout=60, verify=False, follow_redirects=True) as client:
            resp = await client.get(video_url, headers=headers)

            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"上游返回 {resp.status_code}")

            content_type = resp.headers.get("content-type", "video/mp4")
            content = resp.content

        return StreamingResponse(
            iter([content]),
            media_type=content_type,
            headers={"Accept-Ranges": "bytes", "Content-Length": str(len(content))},
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="代理请求超时")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"代理失败: {str(e)}")


@app.get("/api/download")
async def download_video(
    video_url: str = Query(..., description="视频直链"),
    title: str = Query("video", description="保存文件名"),
):
    """下载视频文件"""
    if not video_url:
        raise HTTPException(status_code=400, detail="视频 URL 不能为空")
    # yt-dlp 前缀（yt:// / tt://）跳过 URL 安全检查，因为它们不直接 fetch
    if not (video_url.startswith("yt://") or video_url.startswith("tt://")):
        if not _is_safe_url(video_url):
            raise HTTPException(status_code=403, detail="不允许访问该地址")

    safe_title = "".join(c for c in title if c.isalnum() or c in " _-").strip() or "video"

    def _is_valid_video(p):
        """检查文件是否为有效视频（而非 HTML 错误页面）"""
        if not p.exists() or p.stat().st_size < 1024:
            return False
        with open(p, "rb") as f:
            header = f.read(16)
        return b"ftyp" in header or b"skip" in header

    # yt-dlp 下载（YouTube / TikTok 等需要特殊处理的平台）
    if video_url.startswith("yt://") or video_url.startswith("tt://"):
        is_youtube = video_url.startswith("yt://")
        vid = video_url[5:]  # skip "yt://" or "tt://"
        page_url = f"https://www.youtube.com/watch?v={vid}" if is_youtube else f"https://www.tiktok.com/@/video/{vid}"
        platform_name = "YouTube" if is_youtube else "TikTok"
        filepath = DOWNLOAD_DIR / f"{safe_title}.mp4"

        if _is_valid_video(filepath):
            return FileResponse(path=str(filepath), filename=f"{safe_title}.mp4", media_type="video/mp4")

        if filepath.exists():
            filepath.unlink()

        def _download_with_ytdlp():
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "outtmpl": str(filepath),
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "merge_output_format": "mp4",
                "nocheckcertificate": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([page_url])

        try:
            await asyncio.to_thread(_download_with_ytdlp)
            if not filepath.exists():
                for f in DOWNLOAD_DIR.glob(f"{safe_title}.*"):
                    filepath = f
                    break
            if not _is_valid_video(filepath):
                raise HTTPException(status_code=500, detail=f"{platform_name} 下载失败: 下载的文件不是有效视频")
            return FileResponse(path=str(filepath), filename=f"{safe_title}.mp4", media_type="video/mp4")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"{platform_name} 下载失败: {str(e)[:200]}")

    filename = f"{safe_title}.mp4"
    filepath = DOWNLOAD_DIR / filename

    if filepath.exists() and filepath.stat().st_size > 0:
        return FileResponse(path=str(filepath), filename=filename, media_type="video/mp4")

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.douyin.com/",
        }
        async with httpx.AsyncClient(timeout=120, verify=False, follow_redirects=True) as client:
            resp = await client.get(video_url, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"下载失败 (HTTP {resp.status_code})")
            filepath.write_bytes(resp.content)

        return FileResponse(path=str(filepath), filename=filename, media_type="video/mp4")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="下载超时")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")


@app.get("/api/history")
async def get_history(limit: int = Query(50, ge=1, le=200)):
    return {"history": _load_history()[:limit]}


@app.delete("/api/history")
async def clear_history():
    _save_history([])
    return {"message": "历史记录已清空"}


@app.delete("/api/history/{record_id}")
async def delete_history_record(record_id: str):
    history = [h for h in _load_history() if h.get("id") != record_id]
    _save_history(history)
    return {"message": "已删除"}


# ─── 挂载前端 ─────────────────────────────────────────
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  多平台视频解析下载工具 v2.0")
    print("  支持：抖音/快手/B站/微博/小红书/TikTok/YouTube/Instagram/Twitter/西瓜视频")
    print("  打开浏览器访问: http://127.0.0.1:8866")
    print("=" * 50 + "\n")
    uvicorn.run("main:app", host="127.0.0.1", port=8866, reload=True, log_level="info")
