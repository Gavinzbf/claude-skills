---
name: video-downloader
description: 下载在线视频和音频。当用户提供视频链接（如 YouTube、Bilibili、Twitter/X、抖音等）并要求下载时触发。触发词：下载视频、下载音频、保存视频、video download
tools: Bash
---

# 视频下载 Skill

使用 yt-dlp 下载在线视频和音频。

## 默认配置
- **下载目录**: `D:\CursorCode\video`
- **文件命名**: `%(title)s.%(ext)s`

## 使用方式

### 1. 默认下载（视频+音频+字幕）
用户提供视频链接时，默认同时下载视频、音频(MP3)、字幕(如有)：
```bash
yt-dlp -k -x --audio-format mp3 --write-sub --write-auto-sub --sub-lang zh,en -o "D:\CursorCode\video\%(title)s.%(ext)s" "<URL>"
```

### 2. 仅下载视频
当用户明确要求"只要视频"时：
```bash
yt-dlp -o "D:\CursorCode\video\%(title)s.%(ext)s" "<URL>"
```

### 3. 仅下载音频 (MP3)
当用户明确要求"只要音频"时：
```bash
yt-dlp -x --audio-format mp3 -o "D:\CursorCode\video\%(title)s.%(ext)s" "<URL>"
```

### 4. 仅下载字幕
当用户明确要求"只要字幕"时：
```bash
yt-dlp --write-sub --write-auto-sub --sub-lang zh,en --skip-download -o "D:\CursorCode\video\%(title)s.%(ext)s" "<URL>"
```

## 故障排除

### 问题1: YouTube 提示 "Sign in to confirm you're not a bot"
**解决方案**: 先更新 yt-dlp 到最新版本
```bash
pip install -U yt-dlp
```
更新后重新执行下载命令。

### 问题2: 下载失败或格式缺失
**解决方案**:
1. 首先尝试更新 yt-dlp: `pip install -U yt-dlp`
2. 如果仍然失败，尝试使用 cookies（需要关闭浏览器）:
```bash
yt-dlp --cookies-from-browser chrome -o "D:\CursorCode\video\%(title)s.%(ext)s" "<URL>"
```

### 问题3: 字幕下载显示 "no subtitles"
这表示该视频没有提供字幕。这是正常情况，不是错误。

### 问题4: JavaScript runtime 警告
这是警告信息，不影响下载。如需消除，可安装 deno 运行时。

## 注意事项
- 下载完成后告知用户文件保存位置和文件名
- 如果用户指定了其他目录，使用用户指定的目录
- 遇到下载失败时，**优先尝试更新 yt-dlp**，这能解决大部分问题
- 下载完成后用 `dir` 命令确认文件已保存
- 默认会同时生成：视频文件 + .mp3 音频 + .vtt/.srt 字幕（如有）
