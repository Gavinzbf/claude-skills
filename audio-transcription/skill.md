---
name: audio-transcription
description: |
  将音频或视频文件转换为文字稿。支持 mp3, wav, m4a, mp4, flac, ogg, webm 等格式。
  使用云雾AI Whisper API进行高质量语音识别，支持中文、英文等多语言。
  触发场景：(1) 转录音频 (2) 音频转文字 (3) 语音识别 (4) 会议录音整理
  (5) 播客转文字 (6) 视频字幕提取 (7) 语音笔记转文字
---

# Audio Transcription

将音频/视频文件转换为文字稿，并进行润色整理。

## 工作流程（必须严格按顺序执行）

1. 获取用户提供的音频/视频文件路径
2. **必须使用 -o 参数保存到文件**（避免 Windows 控制台编码乱码）
3. 用 Read 工具读取转录结果
4. 对文本进行润色整理
5. **自动保存润色版到 `*_polished.txt`**（无需询问用户）
6. 向用户展示润色后的内容和两个文件路径

## 文件命名规范

- 原始转录：`<原文件名>_raw.txt`（如 `meeting_raw.txt`）
- 润色版本：`<原文件名>_polished.txt`（如 `meeting_polished.txt`）
- 保存位置：与源音频文件相同目录

## 使用方法

### 运行转录脚本

**⚠️ 重要：必须使用 -o 参数输出到文件，不要直接输出到控制台！**

```bash
python scripts/transcribe.py --file <音频文件路径> -o <输出文件路径> [选项]
```

**参数说明:**
- `--file, -f`: 音频/视频文件路径（必需）
- `--output, -o`: 输出文件路径（**必须指定，避免编码问题**）
- `--language, -l`: 语言代码，如 `zh`(中文)、`en`(英文)，不指定则自动检测
- `--model, -m`: 模型选择，`whisper-1`(默认) 或 `gpt-4o-mini-transcribe`
- `--prompt, -p`: 提示词，用于指导转录风格

**正确示例:**
```bash
# 中文音频转录（推荐写法）
python scripts/transcribe.py -f "D:/path/to/meeting.mp3" -l zh -o "D:/path/to/meeting_raw.txt"

# 视频转录
python scripts/transcribe.py -f "D:/path/to/video.mp4" -l zh -o "D:/path/to/video_raw.txt"
```

**❌ 错误示例（会导致乱码）:**
```bash
# 不要这样做！
python scripts/transcribe.py -f meeting.mp3
```

## 润色指南

转录完成后，对文本进行以下处理：

1. **添加标点**: 补充句号、逗号、问号等标点符号
2. **分段**: 按话题或停顿合理分段，添加小标题
3. **去语气词**: 删除"嗯"、"啊"、"那个"等口语填充词
4. **修正错误**: 修正明显的语音识别错误
5. **格式化**: 使用 Markdown 格式整理（标题、列表、引用等）

## 完整执行示例

```
输入文件: D:/project/interview.m4a

步骤1: python scripts/transcribe.py -f "D:/project/interview.m4a" -l zh -o "D:/project/interview_raw.txt"
步骤2: Read interview_raw.txt
步骤3: 润色整理内容
步骤4: Write 润色内容到 interview_polished.txt
步骤5: 告知用户：
       - 原始转录：D:/project/interview_raw.txt
       - 润色版本：D:/project/interview_polished.txt
```

## 环境要求

- Python 3.8+
- requests 库: `pip install requests`
- API Key 配置（二选一）:
  - 在项目根目录创建 `.env` 文件，添加 `YUNWU_API_KEY=你的Key`
  - 或设置环境变量 `YUNWU_API_KEY`

## 支持格式

音频: mp3, wav, m4a, flac, ogg, webm, mpga
视频: mp4, mpeg
