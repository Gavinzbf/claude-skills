---
name: ai-video-editor
description: |
  自动剪辑 AI 生成的视频片段，输出社媒短视频（抖音/TikTok、YouTube Shorts）。
  触发场景：(1) 用户说"剪辑视频"、"合成视频"、"处理AI视频"
  (2) 用户提供视频目录要求自动剪辑 (3) 用户说 /ai-video-editor
---

# AI 视频自动剪辑

使用 Gemini AI 分析视频内容，自动生成剪辑方案并执行。

## 快速开始

```bash
python scripts/ai_video_editor.py "<视频目录>"
```

## 前置要求

1. **FFmpeg**: 需安装并加入 PATH
2. **Gemini API Key**: `$env:GEMINI_API_KEY="your-key"`
3. **依赖**: `pip install google-generativeai`

## 工作流程

**阶段一：内容理解**
→ 场景/主体/情绪分析，质量评分 (1-10)

**阶段二：精准剪切**
→ 检测开头死气 (Dead Air) 和结尾变形 (Morphing)
→ 动作分类 + 毫秒级剪切点 + 变速建议 (0.5x-5.0x)

**用户确认** → 展示剪辑表格，等待确认

**执行剪辑** → FFmpeg trim + speed ramp + concat → 输出视频

## 命令选项

| 选项 | 说明 |
|------|------|
| `--analyze-only` | 只分析不执行 |
| `--execute` | 跳过分析，用已有方案执行 |
| `--duration 30` | 目标时长（秒）|
| `--style kpop_story` | 使用风格配置（由 analyze-style 生成）|
| `--preset douyin` | 输出预设 |
| `-y` | 跳过确认 |

## 使用风格配置

结合 `/analyze-style` skill 提取的剪辑风格，可以让剪辑效果更符合特定风格：

```bash
# 使用风格名称（自动查找 styles/ 目录）
python scripts/ai_video_editor.py "D:\Videos\clips" --style kpop_story

# 使用完整路径
python scripts/ai_video_editor.py "D:\Videos\clips" --style styles/kpop_story.yaml
```

**风格配置影响**:
- `rhythm.clip_duration` → 片段时长范围
- `techniques.speed_ramp` → 是否启用变速
- `transitions.default` → 默认转场类型
- `platform.max_duration` → 最大输出时长

## 输出

分析结果保存在 `<视频目录>/.ai-editor-analysis/`:
- `edit_plan_v2.json` - 剪辑方案
- `*_analysis.json` - 内容分析
- `*_precision.json` - 精准剪切

## 变速策略

- **冲击/高光**: 0.5x-0.8x（慢动作）
- **位移/过渡**: 1.2x-2.0x（加速）
- **普通动作**: 1.0x

## 脚本

| 脚本 | 用途 |
|------|------|
| `scripts/ai_video_editor.py` | 主入口 |
| `scripts/analyze_with_gemini.py` | 阶段一分析 |
| `scripts/precision_cutter.py` | 阶段二分析 |
| `scripts/ffmpeg_executor.py` | FFmpeg 执行 |
