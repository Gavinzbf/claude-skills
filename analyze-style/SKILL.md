---
name: analyze-style
description: |
  分析剪辑手法，通过对比原片和结果视频提取可复用的剪辑规则。
  触发场景：(1) 用户说"分析剪辑风格"、"提取剪辑手法"、"学习剪辑方式"
  (2) 用户提供原片和成片要求分析 (3) 用户说 /analyze-style
---

# 剪辑手法分析器

通过对比原片和剪辑结果，使用 Gemini AI 提取可复用的剪辑规则。

## 快速开始

```bash
python scripts/extract_editing_style.py <原片文件夹> <结果视频> --name <风格名称>
```

## 前置要求

1. **Gemini API Key**: `$env:GEMINI_API_KEY="your-key"`
2. **依赖**: `pip install google-generativeai pyyaml`

## 工作流程

1. **收集信息** → 原片文件夹、结果视频、风格名称
2. **AI 分析** → Gemini 对比原片与成片
3. **提取规则** → 选片规则、节奏、转场偏好
4. **输出文件** → `styles/<风格名>.yaml`

## 分析维度

- 片段选择规则（保留/删除标准）
- 结构编排（开场/主体/高潮/结尾）
- 节奏控制（时长分布）
- 转场偏好
- 变速/特效使用

## 命令选项

| 命令 | 说明 |
|------|------|
| `--name <名称>` | 创建新风格 |
| `--update <文件>` | 更新已有风格 |
| `--list` | 查看所有风格 |

## 输出格式

风格文件保存在 `styles/<风格名>.yaml`：

```yaml
meta:
  version: 1
  style_name: "风格名称"

selection:
  keep_criteria: [...]
  remove_criteria: [...]

rhythm:
  overall_tempo: "medium"
  clip_duration: { min: 1.5, max: 5.0, avg: 2.5 }

transitions:
  default: "hard_cut"
```

## 脚本

| 脚本 | 用途 |
|------|------|
| `scripts/extract_editing_style.py` | 主入口 |

## 资源

| 资源 | 用途 |
|------|------|
| `assets/_template.yaml` | 风格文件模板 |
