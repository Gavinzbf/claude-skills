#!/usr/bin/env python3
"""
精准剪切分析模块（阶段二）

使用 Gemini API 进行毫秒级精准剪切分析：
- 检测 AI 生成视频的开头死气 (Dead Air)
- 检测结尾变形 (Morphing)
- 动作分类：位移/过渡、冲击/高光、情绪/反应
- 提供变速建议 (0.5x - 5.0x)

此模块应在阶段一（内容理解）之后运行。
"""

import json
import os
import subprocess
import sys
import time
from functools import wraps
from pathlib import Path
from typing import Optional

try:
    import google.generativeai as genai
except ImportError:
    print("错误: 请先安装 google-generativeai")
    print("运行: pip install google-generativeai")
    sys.exit(1)

# 动作类型定义
ACTION_TYPES = {
    "displacement": "位移/过渡",
    "impact": "冲击/高光",
    "emotion": "情绪/反应"
}

# 速度建议范围
SPEED_RANGE = (0.5, 5.0)


def get_api_key() -> str:
    """获取 Gemini API Key"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("未设置 GEMINI_API_KEY 环境变量")
    return api_key


def setup_gemini(api_key: str) -> genai.GenerativeModel:
    """配置并返回 Gemini 模型"""
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.0-flash")


def get_video_duration_ms(video_path: Path) -> int:
    """使用 FFprobe 获取视频时长（毫秒）"""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(video_path)
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        duration_sec = float(data["format"]["duration"])
        return int(duration_sec * 1000)
    except (subprocess.CalledProcessError, KeyError, json.JSONDecodeError) as e:
        print(f"警告: 无法获取视频时长: {e}")
        return 0


def retry_on_network_error(max_retries=3, delay=5):
    """网络错误重试装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        print(f"    网络错误，{delay}秒后重试 ({attempt+1}/{max_retries})...")
                        time.sleep(delay)
            raise last_error
        return wrapper
    return decorator


def get_precision_cutting_prompt() -> str:
    """获取剪辑大师提示词"""
    return """你是一位专业的 AI 视频剪辑大师，专门处理 AI 生成的视频片段。

请仔细分析这个视频，提供毫秒级的精准剪切建议。

## AI 生成视频的常见问题

1. **开头死气 (Dead Air)**：AI 生成视频常在开头有 0.5-2 秒的静止帧或画面预热期
2. **结尾变形 (Morphing)**：AI 视频在结尾常出现物体扭曲、边缘融化、形态崩坏

## 你需要做的

1. **检测开头死气**：找出视频开头静止/无意义的部分，标记结束时间点（毫秒）
2. **检测结尾变形**：找出画面开始出问题的时间点（毫秒）
3. **分段动作分类**：将视频有效部分分成若干片段，标注每段的动作类型：
   - **位移/过渡**：主体移动、镜头移动、场景切换
   - **冲击/高光**：爆炸、碰撞、惊险时刻、视觉冲击
   - **情绪/反应**：表情特写、情感流露、角色反应
4. **速度建议**：为每个片段建议播放速度（0.5x-5.0x）
   - 高光/冲击时刻：0.5x-0.8x（慢动作突出）
   - 普通动作：1.0x
   - 位移/过渡：1.2x-2.0x（加速节省时间）
   - 无聊/重复内容：2.0x-5.0x（快速略过）

## 输出格式（JSON，不要 markdown 代码块）

{
  "filename": "视频文件名",
  "duration_ms": 8000,
  "ai_artifacts": {
    "dead_air": {
      "detected": true,
      "end_ms": 1200,
      "reason": "开头静止帧，AI 生成预热期"
    },
    "morphing": {
      "detected": true,
      "start_ms": 6800,
      "reason": "物体边缘开始扭曲"
    }
  },
  "segments": [
    {
      "start_ms": 1200,
      "end_ms": 3500,
      "action_type": "位移/过渡",
      "speed_suggestion": 1.2,
      "description": "车辆远景接近"
    },
    {
      "start_ms": 3500,
      "end_ms": 5500,
      "action_type": "冲击/高光",
      "speed_suggestion": 0.7,
      "description": "惊险时刻 - 减速突出"
    },
    {
      "start_ms": 5500,
      "end_ms": 6800,
      "action_type": "情绪/反应",
      "speed_suggestion": 1.0,
      "description": "角色表情反应"
    }
  ],
  "recommended_trim": {
    "start_ms": 1200,
    "end_ms": 6800
  },
  "overall_quality": {
    "score": 8,
    "notes": "画面清晰，动作流畅，但结尾有轻微变形"
  }
}

## 注意事项

1. 所有时间必须是毫秒（整数）
2. segments 按时间顺序排列，不重叠
3. speed_suggestion 范围 0.5-5.0
4. 如果没有检测到死气或变形，将 detected 设为 false
5. recommended_trim 应排除死气和变形部分
"""


@retry_on_network_error(max_retries=3, delay=5)
def analyze_precision_cutting(
    model: genai.GenerativeModel,
    video_path: Path,
    verbose: bool = True
) -> dict:
    """
    对单个视频进行精准剪切分析

    Args:
        model: Gemini 模型实例
        video_path: 视频文件路径
        verbose: 是否输出详细信息

    Returns:
        精准剪切分析结果字典
    """
    if verbose:
        print(f"  [阶段二] 精准剪切分析: {video_path.name}...")

    # 获取视频时长
    duration_ms = get_video_duration_ms(video_path)

    # 上传视频
    if verbose:
        print(f"    上传视频...")
    video_file = genai.upload_file(str(video_path))

    # 等待处理完成
    while video_file.state.name == "PROCESSING":
        if verbose:
            print("    等待处理中...")
        time.sleep(2)
        video_file = genai.get_file(video_file.name)

    if video_file.state.name == "FAILED":
        raise ValueError(f"视频处理失败: {video_path.name}")

    if verbose:
        print(f"    AI 分析中...")

    prompt = get_precision_cutting_prompt()

    try:
        response = model.generate_content([video_file, prompt])

        # 解析 JSON 响应
        response_text = response.text.strip()
        # 移除可能的 markdown 代码块标记
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        analysis = json.loads(response_text.strip())

        # 补充/校正信息
        analysis["filename"] = video_path.name
        analysis["filepath"] = str(video_path)
        if duration_ms > 0:
            analysis["duration_ms"] = duration_ms

        return analysis

    except json.JSONDecodeError as e:
        print(f"  警告: JSON 解析失败，返回原始响应")
        return {
            "filename": video_path.name,
            "filepath": str(video_path),
            "duration_ms": duration_ms,
            "raw_response": response.text,
            "parse_error": str(e)
        }
    finally:
        # 清理上传的文件
        try:
            genai.delete_file(video_file.name)
        except Exception:
            pass


def analyze_directory_precision(
    model: genai.GenerativeModel,
    video_dir: Path,
    phase1_analyses: list[dict],
    verbose: bool = True
) -> list[dict]:
    """
    对目录中所有视频进行精准剪切分析

    Args:
        model: Gemini 模型实例
        video_dir: 视频目录
        phase1_analyses: 阶段一分析结果列表
        verbose: 是否输出详细信息

    Returns:
        所有视频的精准剪切分析结果列表
    """
    output_dir = video_dir / ".ai-editor-analysis"
    output_dir.mkdir(exist_ok=True)

    results = []
    total = len(phase1_analyses)

    for i, phase1 in enumerate(phase1_analyses, 1):
        filename = phase1.get("filename")
        if not filename:
            continue

        video_path = video_dir / filename
        if not video_path.exists():
            print(f"  警告: 视频文件不存在: {filename}")
            continue

        print(f"\n[{i}/{total}] 精准剪切分析: {filename}")

        # 检查是否已有精准分析结果
        precision_file = output_dir / f"{video_path.stem}_precision.json"
        if precision_file.exists():
            print(f"  已有精准分析结果，跳过...")
            with open(precision_file, 'r', encoding='utf-8') as f:
                precision = json.load(f)
            results.append(precision)
            continue

        try:
            precision = analyze_precision_cutting(model, video_path, verbose)

            # 保存结果
            with open(precision_file, 'w', encoding='utf-8') as f:
                json.dump(precision, f, ensure_ascii=False, indent=2)

            results.append(precision)

            # 输出摘要
            if "recommended_trim" in precision:
                trim = precision["recommended_trim"]
                print(f"    推荐裁剪: {trim['start_ms']}ms - {trim['end_ms']}ms")
            if "segments" in precision:
                print(f"    分段数: {len(precision['segments'])}")

            # API 调用间隔
            if i < total:
                time.sleep(1)

        except Exception as e:
            print(f"  错误: {e}")
            results.append({
                "filename": filename,
                "filepath": str(video_path),
                "error": str(e)
            })

    return results


def merge_phase1_and_phase2(
    phase1_analyses: list[dict],
    phase2_analyses: list[dict]
) -> list[dict]:
    """
    合并阶段一和阶段二的分析结果

    Args:
        phase1_analyses: 阶段一内容理解结果
        phase2_analyses: 阶段二精准剪切结果

    Returns:
        合并后的分析结果列表
    """
    # 建立阶段二结果索引
    phase2_by_filename = {
        p.get("filename"): p for p in phase2_analyses
    }

    merged = []
    for p1 in phase1_analyses:
        filename = p1.get("filename")
        p2 = phase2_by_filename.get(filename, {})

        merged_item = {
            "filename": filename,
            "filepath": p1.get("filepath"),
            "phase1": {
                "scene": p1.get("scene"),
                "subjects": p1.get("subjects"),
                "action": p1.get("action"),
                "mood": p1.get("mood"),
                "quality_score": p1.get("quality_score"),
                "highlight_segment": p1.get("highlight_segment"),
                "recommendation": p1.get("recommendation"),
                "suitable_for": p1.get("suitable_for")
            },
            "phase2": {
                "duration_ms": p2.get("duration_ms"),
                "ai_artifacts": p2.get("ai_artifacts"),
                "segments": p2.get("segments"),
                "recommended_trim": p2.get("recommended_trim"),
                "overall_quality": p2.get("overall_quality")
            }
        }

        # 处理错误情况
        if "error" in p1:
            merged_item["phase1"]["error"] = p1["error"]
        if "error" in p2:
            merged_item["phase2"]["error"] = p2["error"]

        merged.append(merged_item)

    return merged


def main():
    """测试入口"""
    import argparse

    parser = argparse.ArgumentParser(description="精准剪切分析（阶段二）")
    parser.add_argument("path", help="视频文件或目录路径")
    parser.add_argument("--single", action="store_true", help="分析单个视频")
    parser.add_argument("-q", "--quiet", action="store_true", help="安静模式")

    args = parser.parse_args()

    api_key = get_api_key()
    model = setup_gemini(api_key)
    verbose = not args.quiet

    if args.single:
        video_path = Path(args.path)
        if not video_path.exists():
            print(f"错误: 文件不存在: {video_path}")
            sys.exit(1)

        result = analyze_precision_cutting(model, video_path, verbose)
        print("\n分析结果:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        video_dir = Path(args.path)
        if not video_dir.exists():
            print(f"错误: 目录不存在: {video_dir}")
            sys.exit(1)

        # 加载阶段一结果
        analysis_dir = video_dir / ".ai-editor-analysis"
        if not analysis_dir.exists():
            print("错误: 请先运行阶段一分析")
            sys.exit(1)

        phase1_analyses = []
        for f in sorted(analysis_dir.glob("*_analysis.json")):
            with open(f, 'r', encoding='utf-8') as fp:
                phase1_analyses.append(json.load(fp))

        if not phase1_analyses:
            print("错误: 没有找到阶段一分析结果")
            sys.exit(1)

        print(f"加载了 {len(phase1_analyses)} 个阶段一分析结果")

        # 运行阶段二分析
        phase2_results = analyze_directory_precision(
            model, video_dir, phase1_analyses, verbose
        )

        # 合并结果
        merged = merge_phase1_and_phase2(phase1_analyses, phase2_results)

        # 保存合并结果
        merged_file = analysis_dir / "merged_analysis.json"
        with open(merged_file, 'w', encoding='utf-8') as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)

        print(f"\n合并结果已保存到: {merged_file}")


if __name__ == "__main__":
    main()
