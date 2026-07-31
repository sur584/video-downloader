# 多平台视频解析下载工具_已更新项目融合

一个本地运行的网页版视频下载工具，支持 9+ 主流平台的视频链接解析、无水印下载、在线预览。

## 支持平台

| 平台 | 域名 | 无水印下载 | 在线预览 |
|------|------|:----------:|:--------:|
| 抖音 | douyin.com, iesdouyin.com | ✅ | ✅ |
| B站 | bilibili.com, b23.tv | ✅ | ✅ |
| 微博 | weibo.com, weibo.cn | ✅ | ✅ |
| 小红书 | xiaohongshu.com, xhslink.com | ✅ | ✅ |
| TikTok | tiktok.com | ✅ | ✅ |
| YouTube | youtube.com, youtu.be | ✅ | ✅ |
| Instagram | instagram.com | ⬡ | 新窗口 |
| Twitter/X | twitter.com, x.com, t.co | ⬡ | 新窗口 |
| 西瓜视频 | ixigua.com | ✅ | ✅ |

## 环境要求

- Python 3.10+
- pip
- ffmpeg（YouTube/TikTok 下载合并音视频需要）

## 安装与启动

```bash
cd "download video/backend"
pip install -r requirements.txt
python main.py
```

或双击 `start.bat`（Windows）。

启动后访问 http://127.0.0.1:8866

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/platforms` | 支持的平台列表 |
| POST | `/api/parse` | 解析单个链接 `{"url": "..."}` |
| POST | `/api/batch-parse` | 批量解析（最多 20 个）`{"urls": ["...", "..."]}` |
| GET | `/api/proxy?video_url=...&referer=...` | 视频代理（在线预览） |
| GET | `/api/download?video_url=...&title=...` | 下载视频文件 |
| GET | `/api/history?limit=50` | 历史记录 |
| DELETE | `/api/history` | 清空历史 |
| DELETE | `/api/history/{id}` | 删除单条 |

## 项目结构

```
download video/
├── backend/
│   ├── main.py              # FastAPI 后端（含视频代理）
│   ├── parsers/
│   │   ├── __init__.py      # 统一入口（缓存/重试/并发）
│   │   ├── _utils.py        # 共享工具函数
│   │   ├── douyin.py        # 抖音解析器
│   │   ├── bilibili.py      # B站解析器
│   │   ├── weibo.py         # 微博解析器
│   │   ├── xiaohongshu.py   # 小红书解析器
│   │   ├── tiktok.py        # TikTok 解析器
│   │   ├── youtube.py       # YouTube 解析器
│   │   ├── instagram.py     # Instagram 解析器
│   │   ├── twitter.py       # Twitter/X 解析器
│   │   └── xigua.py         # 西瓜视频解析器
│   ├── requirements.txt     # Python 依赖
│   └── downloads/           # 下载保存目录
├── frontend/
│   ├── index.html           # 主页面
│   ├── css/style.css        # 样式（暗黑/亮色主题）
│   └── js/app.js            # 前端交互逻辑
├── start.bat                # Windows 启动脚本
└── README.md
```

## 功能特性

- 自动识别链接所属平台
- 短链接自动重定向解析
- 无水印视频下载
- 后端视频代理（解决跨域/Referer 限制）
- 在线视频预览
- 批量跨平台混合解析
- 历史记录管理
- 暗黑/亮色主题
- 响应式设计（PC + 移动端）
- 输入智能提取（支持粘贴带文字的分享文本）
- 平台解析缓存 + 失败重试
- 并发批量解析（最多 3 路并发）
- 安全防护：SSRF 拦截、XSS 转义、CORS 限制

## 安全说明

- 仅监听 `127.0.0.1`，不暴露到外网
- 禁止访问内网/本地地址（SSRF 防护）
- 前端输出自动转义（XSS 防护）
- CORS 限制为本地来源

## 注意事项

- 仅供学习交流使用
- 请遵守各平台使用条款
- Instagram/Twitter 因平台限制，仅支持 embed 预览
- 频繁请求可能触发风控
- YouTube/TikTok 下载需要安装 ffmpeg
