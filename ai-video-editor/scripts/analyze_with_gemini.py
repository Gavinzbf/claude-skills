#!/usr/bin/env python3
"""
AI 视频内容理解与自动剪辑分析脚本

使用 Google Gemini API 分析视频内容，生成剪辑方案。

使用方法:
    # 分析整个目录
    python analyze_with_gemini.py <视频目录>

    # 分析单个视频
    python analyze_with_gemini.py --single <视频文件路径>

    # 只生成剪辑方案（基于已有分析）
    python analyze_with_gemini.py --plan-only <视频目录>

环境变量:
    GEMINI_API_KEY: Google Gemini API 密钥

输出:
    <视频目录>/.ai-editor-analysis/
    ├── clip_001_analysis.json    # 单个视频的分析结果
    ├── clip_002_analysis.json
    ├── ...
    ├── story_summary.json        # 整体故事理解
    └── edit_plan.json            # 剪辑方案
"""

import argparse
import json
import os
import ssl
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


# 支持的视频格式
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4v'}

# 分析输出目录名
ANALYSIS_DIR = ".ai-editor-analysis"


def get_api_key() -> str:
    """获取 Gemini API Key"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("错误: 未设置 GEMINI_API_KEY 环境变量")
        print("请访问 https://aistudio.google.com/apikey 获取 API Key")
        print("然后设置环境变量:")
        print("  Windows: set GEMINI_API_KEY=your-api-key")
        print("  Linux/Mac: export GEMINI_API_KEY=your-api-key")
        sys.exit(1)
    return api_key


def setup_gemini(api_key: str) -> genai.GenerativeModel:
    """配置并返回 Gemini 模型"""
    genai.configure(api_key=api_key)
    # 使用 Gemini 2.0 Flash，支持视频理解
    return genai.GenerativeModel("gemini-2.0-flash")


def get_video_files(directory: Path) -> list[Path]:
    """获取目录中所有视频文件"""
    videos = set()  # 使用 set 去重，避免 Windows 大小写不敏感导致重复
    for ext in VIDEO_EXTENSIONS:
        videos.update(directory.glob(f"*{ext}"))
        videos.update(directory.glob(f"*{ext.upper()}"))
    return sorted(videos, key=lambda p: p.name)


def retry_on_network_error(max_retries=3, delay=5):
    """网络错误重试装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (ssl.SSLError, ConnectionError, TimeoutError) as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        print(f"    网络错误，{delay}秒后重试 ({attempt+1}/{max_retries})...")
                        time.sleep(delay)
            raise last_error
        return wrapper
    return decorator


@retry_on_network_error(max_retries=3, delay=5)
def analyze_single_video(model: genai.GenerativeModel, video_path: Path, verbose: bool = True) -> dict:
    """
    分析单个视频

    Args:
        model: Gemini 模型实例
        video_path: 视频文件路径
        verbose: 是否输出详细信息

    Returns:
        视频分析结果字典
    """
    if verbose:
        print(f"  正在上传视频: {video_path.name}...")

    # 上传视频文件到 Gemini
    video_file = genai.upload_file(str(video_path))

    # 等待文件处理完成
    while video_file.state.name == "PROCESSING":
        if verbose:
            print("    等待处理中...")
        time.sleep(2)
        video_file = genai.get_file(video_file.name)

    if video_file.state.name == "FAILED":
        raise ValueError(f"视频处理失败: {video_path.name}")

    if verbose:
        print(f"  正在分析视频内容...")

    # 视频分析 Prompt
    prompt = """你是一位专业的视频剪辑师。请仔细观看这个视频片段，并提供详细分析。

请以 JSON 格式输出（不要包含 markdown 代码块标记）：
{
  "scene": "场景描述（地点、时间、氛围、背景）",
  "subjects": ["主要主体列表（人物、物体、动物等）"],
  "action": "发生了什么事，主要动作或事件描述",
  "key_moments": [
    {"time": "MM:SS", "description": "这个时刻发生了什么"}
  ],
  "mood": "情绪氛围（如：欢快、紧张、悲伤、宁静等）",
  "audio_description": "声音描述（背景音乐、对话、环境音等）",
  "visual_quality": {
    "stability": "画面稳定性（稳定/轻微抖动/严重抖动）",
    "clarity": "清晰度（高清/一般/模糊）",
    "lighting": "光线条件（良好/一般/较差）"
  },
  "quality_score": 8,
  "highlight_segment": {
    "start": "MM:SS",
    "end": "MM:SS",
    "reason": "为什么这段是精华"
  },
  "recommendation": "完整保留/裁剪到XX:XX-XX:XX/跳过",
  "recommendation_reason": "推荐理由",
  "suitable_for": ["适合的用途，如：开场、高潮、结尾、过渡等"]
}

注意事项：
1. 时间戳格式为 MM:SS（如 00:02 表示第 2 秒）
2. quality_score 范围 1-10，考虑画面稳定性、清晰度、内容价值
3. key_moments 至少包含 1 个关键时刻，最多 5 个
4. 如果视频很短（< 3 秒），可能没有明显的关键时刻
"""

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
        analysis["filename"] = video_path.name
        analysis["filepath"] = str(video_path)

        return analysis

    except json.JSONDecodeError as e:
        print(f"  警告: JSON 解析失败，返回原始响应")
        return {
            "filename": video_path.name,
            "filepath": str(video_path),
            "raw_response": response.text,
            "parse_error": str(e)
        }
    finally:
        # 清理上传的文件
        try:
            genai.delete_file(video_file.name)
        except Exception:
            pass


def analyze_directory(model: genai.GenerativeModel, video_dir: Path, verbose: bool = True) -> list[dict]:
    """
    分析目录中所有视频

    Args:
        model: Gemini 模型实例
        video_dir: 视频目录路径
        verbose: 是否输出详细信息

    Returns:
        所有视频的分析结果列表
    """
    videos = get_video_files(video_dir)

    if not videos:
        print(f"错误: 目录 {video_dir} 中没有找到视频文件")
        print(f"支持的格式: {', '.join(VIDEO_EXTENSIONS)}")
        sys.exit(1)

    print(f"找到 {len(videos)} 个视频文件")

    # 创建输出目录
    output_dir = video_dir / ANALYSIS_DIR
    output_dir.mkdir(exist_ok=True)

    results = []
    for i, video in enumerate(videos, 1):
        print(f"\n[{i}/{len(videos)}] 分析: {video.name}")

        # 检查是否已有分析结果
        analysis_file = output_dir / f"{video.stem}_analysis.json"
        if analysis_file.exists():
            print(f"  已有分析结果，跳过...")
            with open(analysis_file, 'r', encoding='utf-8') as f:
                analysis = json.load(f)
            results.append(analysis)
            continue

        try:
            analysis = analyze_single_video(model, video, verbose)

            # 保存单个视频的分析结果
            with open(analysis_file, 'w', encoding='utf-8') as f:
                json.dump(analysis, f, ensure_ascii=False, indent=2)

            results.append(analysis)
            print(f"  分析完成: 质量评分 {analysis.get('quality_score', 'N/A')}")

            # API 调用间隔，避免频率限制
            if i < len(videos):
                time.sleep(1)

        except Exception as e:
            print(f"  错误: {e}")
            results.append({
                "filename": video.name,
                "filepath": str(video),
                "error": str(e)
            })

    return results


def generate_edit_plan(model: genai.GenerativeModel, analyses: list[dict],
                       target_duration: Optional[int] = None,
                       style: str = "抖音/TikTok 短视频") -> dict:
    """
    基于所有分析结果生成剪辑方案

    Args:
        model: Gemini 模型实例
        analyses: 所有视频的分析结果
        target_duration: 目标时长（秒），None 表示自动决定
        style: 目标视频风格

    Returns:
        剪辑方案字典
    """
    print("\n正在生成剪辑方案...")

    # 过滤掉有错误的分析结果
    valid_analyses = [a for a in analyses if "error" not in a and "parse_error" not in a]

    if not valid_analyses:
        print("错误: 没有有效的视频分析结果")
        return {"error": "没有有效的视频分析结果"}

    # 构建剪辑方案生成 Prompt
    duration_hint = f"目标时长约 {target_duration} 秒" if target_duration else "时长自动决定，但要节奏紧凑"

    prompt = f"""你是一位专业的短视频剪辑师，擅长制作吸引人的{style}。

以下是所有视频片段的分析结果：

{json.dumps(valid_analyses, ensure_ascii=False, indent=2)}

请基于这些分析，生成一个完整的剪辑方案。{duration_hint}

输出 JSON 格式（不要包含 markdown 代码块标记）：
{{
  "story_summary": {{
    "title": "建议的视频标题",
    "description": "这些片段讲述的整体故事/主题",
    "target_audience": "目标观众",
    "emotional_arc": "情感曲线描述（如：开场吸引 -> 铺垫 -> 高潮 -> 结尾）"
  }},
  "clip_sequence": [
    {{
      "order": 1,
      "filename": "clip_001.mp4",
      "trim": {{
        "start": "MM:SS",
        "end": "MM:SS"
      }},
      "role": "开场/铺垫/高潮/过渡/结尾",
      "reason": "为什么放在这个位置",
      "transition_to_next": "淡入淡出/硬切/交叉溶解/无"
    }}
  ],
  "excluded_clips": [
    {{
      "filename": "clip_xxx.mp4",
      "reason": "跳过原因"
    }}
  ],
  "music_suggestion": {{
    "tempo": "节奏建议（如：快节奏/中等/慢节奏）",
    "mood": "音乐氛围建议",
    "sync_points": ["建议音乐节拍对齐的时刻"]
  }},
  "text_overlays": [
    {{
      "time": "MM:SS",
      "text": "建议的文字内容",
      "purpose": "目的（如：标题/说明/呼吁行动）"
    }}
  ],
  "estimated_duration": "预计最终时长（MM:SS 格式）",
  "production_notes": "给剪辑师的其他建议"
}}

剪辑原则：
1. 开头 3 秒必须抓住注意力
2. 保持节奏紧凑，避免拖沓
3. 质量评分低的片段考虑跳过或只用精华部分
4. 转场要自然，符合内容逻辑
5. 如果片段之间有明显的故事线，按故事顺序排列
6. 如果没有明显故事线，按视觉冲击力和情绪起伏排列
"""

    try:
        response = model.generate_content(prompt)

        # 解析 JSON 响应
        response_text = response.text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        plan = json.loads(response_text.strip())
        return plan

    except json.JSONDecodeError as e:
        print(f"警告: 剪辑方案 JSON 解析失败")
        return {
            "raw_response": response.text,
            "parse_error": str(e)
        }


def load_existing_analyses(output_dir: Path) -> list[dict]:
    """加载已有的分析结果"""
    analyses = []
    for analysis_file in sorted(output_dir.glob("*_analysis.json")):
        with open(analysis_file, 'r', encoding='utf-8') as f:
            analyses.append(json.load(f))
    return analyses


def print_edit_plan_summary(plan: dict):
    """打印剪辑方案摘要"""
    if "error" in plan or "parse_error" in plan:
        print("\n剪辑方案生成失败")
        return

    print("\n" + "=" * 60)
    print("剪辑方案摘要")
    print("=" * 60)

    story = plan.get("story_summary", {})
    print(f"\n标题建议: {story.get('title', 'N/A')}")
    print(f"故事概要: {story.get('description', 'N/A')}")
    print(f"预计时长: {plan.get('estimated_duration', 'N/A')}")

    print("\n片段顺序:")
    print("-" * 40)
    for clip in plan.get("clip_sequence", []):
        trim = clip.get("trim", {})
        trim_str = f"{trim.get('start', '00:00')}-{trim.get('end', 'END')}"
        print(f"  {clip.get('order', '?')}. {clip.get('filename', '?')} [{trim_str}]")
        print(f"     角色: {clip.get('role', 'N/A')}")

    excluded = plan.get("excluded_clips", [])
    if excluded:
        print("\n跳过的片段:")
        print("-" * 40)
        for clip in excluded:
            print(f"  - {clip.get('filename', '?')}: {clip.get('reason', 'N/A')}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="使用 Gemini API 分析视频内容并生成剪辑方案",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 分析目录中所有视频
  python analyze_with_gemini.py D:\\Videos\\ai-clips

  # 分析单个视频
  python analyze_with_gemini.py --single D:\\Videos\\clip_001.mp4

  # 只生成剪辑方案（使用已有分析）
  python analyze_with_gemini.py --plan-only D:\\Videos\\ai-clips

  # 指定目标时长
  python analyze_with_gemini.py D:\\Videos\\ai-clips --duration 60
        """
    )

    parser.add_argument("path", help="视频目录或文件路径")
    parser.add_argument("--single", action="store_true", help="分析单个视频文件")
    parser.add_argument("--plan-only", action="store_true", help="只生成剪辑方案（使用已有分析）")
    parser.add_argument("--duration", type=int, help="目标视频时长（秒）")
    parser.add_argument("--style", default="抖音/TikTok 短视频", help="目标视频风格")
    parser.add_argument("--quiet", "-q", action="store_true", help="减少输出")

    args = parser.parse_args()

    # 获取 API Key 并配置
    api_key = get_api_key()
    model = setup_gemini(api_key)

    verbose = not args.quiet

    if args.single:
        # 单个视频分析模式
        video_path = Path(args.path)
        if not video_path.exists():
            print(f"错误: 文件不存在: {video_path}")
            sys.exit(1)

        print(f"分析视频: {video_path.name}")
        analysis = analyze_single_video(model, video_path, verbose)

        # 输出结果
        print("\n分析结果:")
        print(json.dumps(analysis, ensure_ascii=False, indent=2))

        # 保存结果
        output_file = video_path.parent / f"{video_path.stem}_analysis.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {output_file}")

    else:
        # 目录分析模式
        video_dir = Path(args.path)
        if not video_dir.exists():
            print(f"错误: 目录不存在: {video_dir}")
            sys.exit(1)

        output_dir = video_dir / ANALYSIS_DIR

        if args.plan_only:
            # 只生成剪辑方案
            if not output_dir.exists():
                print(f"错误: 分析目录不存在: {output_dir}")
                print("请先运行完整分析")
                sys.exit(1)

            analyses = load_existing_analyses(output_dir)
            if not analyses:
                print("错误: 没有找到已有的分析结果")
                sys.exit(1)

            print(f"加载了 {len(analyses)} 个视频的分析结果")

        else:
            # 完整分析流程
            analyses = analyze_directory(model, video_dir, verbose)

        # 生成剪辑方案
        plan = generate_edit_plan(model, analyses, args.duration, args.style)

        # 保存剪辑方案
        output_dir.mkdir(exist_ok=True)
        plan_file = output_dir / "edit_plan.json"
        with open(plan_file, 'w', encoding='utf-8') as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)

        # 保存故事摘要
        if "story_summary" in plan:
            summary_file = output_dir / "story_summary.json"
            with open(summary_file, 'w', encoding='utf-8') as f:
                json.dump(plan["story_summary"], f, ensure_ascii=False, indent=2)

        # 打印摘要
        print_edit_plan_summary(plan)

        print(f"\n分析结果保存在: {output_dir}")
        print(f"剪辑方案: {plan_file}")


if __name__ == "__main__":
    main()
