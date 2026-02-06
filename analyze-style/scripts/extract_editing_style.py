#!/usr/bin/env python3
"""
剪辑手法提取脚本

通过对比原片和剪辑结果，使用 Gemini 提取可复用的剪辑手法规则。

使用方法:
    # 创建新风格
    python extract_editing_style.py <原片文件夹> <结果视频> --name <风格名称>

    # 更新已有风格
    python extract_editing_style.py <原片文件夹> <结果视频> --update <已有风格.yaml>

    # 列出所有已保存的风格
    python extract_editing_style.py --list

环境变量:
    GEMINI_API_KEY: Google Gemini API 密钥

输出:
    styles/<style_name>.yaml: 结构化的剪辑手法描述文件
"""

import argparse
import json
import os
import ssl
import sys
import time
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Optional, Any

try:
    import yaml
except ImportError:
    print("错误: 请先安装 PyYAML")
    print("运行: pip install pyyaml")
    sys.exit(1)

try:
    import google.generativeai as genai
except ImportError:
    print("错误: 请先安装 google-generativeai")
    print("运行: pip install google-generativeai")
    sys.exit(1)


# 支持的视频格式
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4v'}

# 脚本目录
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent
STYLES_DIR = PROJECT_DIR / "styles"


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
    return genai.GenerativeModel("gemini-3-pro-preview")


def get_video_files(directory: Path) -> list[Path]:
    """获取目录中所有视频文件"""
    videos = set()
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


def upload_video(video_path: Path, verbose: bool = True) -> Any:
    """上传视频到 Gemini"""
    if verbose:
        print(f"  正在上传: {video_path.name}...")

    video_file = genai.upload_file(str(video_path))

    while video_file.state.name == "PROCESSING":
        if verbose:
            print("    等待处理中...")
        time.sleep(2)
        video_file = genai.get_file(video_file.name)

    if video_file.state.name == "FAILED":
        raise ValueError(f"视频处理失败: {video_path.name}")

    return video_file


def cleanup_file(video_file: Any):
    """清理上传的文件"""
    try:
        genai.delete_file(video_file.name)
    except Exception:
        pass


@retry_on_network_error(max_retries=3, delay=5)
def analyze_source_clips(model: genai.GenerativeModel, source_folder: Path, verbose: bool = True) -> dict:
    """
    分析所有原片片段

    返回原片的整体信息：总数、总时长、内容类型分布等
    """
    videos = get_video_files(source_folder)

    if not videos:
        raise ValueError(f"原片文件夹中没有找到视频文件: {source_folder}")

    print(f"\n原片分析: 发现 {len(videos)} 个片段")

    # 上传所有视频
    uploaded_files = []
    for video in videos:
        try:
            video_file = upload_video(video, verbose)
            uploaded_files.append((video.name, video_file))
        except Exception as e:
            print(f"  警告: 跳过 {video.name}: {e}")

    if not uploaded_files:
        raise ValueError("没有成功上传任何视频文件")

    print(f"  成功上传 {len(uploaded_files)} 个视频，正在分析...")

    # 构建分析 prompt
    prompt = """你是专业的视频剪辑分析师。请分析这些原始视频片段。

请以 JSON 格式输出（不要包含 markdown 代码块标记）：
{
  "total_clips": 数量,
  "clips_summary": [
    {
      "filename": "文件名",
      "duration_estimate": "估计时长（秒）",
      "content_type": "内容类型（如：人物特写、动作场景、环境空镜、产品展示等）",
      "quality_score": 1-10,
      "key_content": "主要内容简述",
      "notable_moments": ["值得注意的时刻描述"]
    }
  ],
  "content_distribution": {
    "类型1": 数量,
    "类型2": 数量
  },
  "overall_quality": "整体质量评价",
  "total_estimated_duration": "估计总时长（秒）"
}

分析要点：
1. 识别每个片段的主要内容类型
2. 评估画面质量（稳定性、清晰度、光线）
3. 找出每个片段中最有价值的内容
4. 注意可能被剪辑时选用的精彩瞬间
"""

    try:
        # 将所有视频文件加入请求
        content = [f for _, f in uploaded_files]
        content.append(prompt)

        response = model.generate_content(content)

        response_text = response.text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        analysis = json.loads(response_text.strip())
        analysis["source_folder"] = str(source_folder)
        analysis["analyzed_files"] = [name for name, _ in uploaded_files]

        return analysis

    except json.JSONDecodeError as e:
        print(f"  警告: JSON 解析失败")
        return {
            "source_folder": str(source_folder),
            "analyzed_files": [name for name, _ in uploaded_files],
            "raw_response": response.text,
            "parse_error": str(e)
        }
    finally:
        # 清理上传的文件
        for _, video_file in uploaded_files:
            cleanup_file(video_file)


@retry_on_network_error(max_retries=3, delay=5)
def analyze_result_video(model: genai.GenerativeModel, result_video: Path, verbose: bool = True) -> dict:
    """
    分析剪辑后的结果视频

    返回结果视频的结构、节奏、转场等信息
    """
    print(f"\n结果视频分析: {result_video.name}")

    video_file = upload_video(result_video, verbose)

    print(f"  正在分析剪辑手法...")

    prompt = """你是专业的视频剪辑分析师。请详细分析这个剪辑完成的视频，提取其剪辑手法和风格。

请以 JSON 格式输出（不要包含 markdown 代码块标记）：
{
  "duration_seconds": 总时长（秒）,
  "segment_count": 片段数量估计,
  "structure": {
    "intro": {
      "duration_seconds": 开场时长,
      "content_description": "开场内容描述",
      "technique": "开场手法"
    },
    "body": {
      "arrangement": "内容编排方式（按时间/按主题/按情绪）",
      "segment_descriptions": ["各片段简述"]
    },
    "climax": {
      "position_percent": 高潮位置百分比,
      "technique": "高潮处理手法"
    },
    "outro": {
      "duration_seconds": 结尾时长,
      "content_description": "结尾内容描述",
      "technique": "结尾手法"
    }
  },
  "rhythm": {
    "overall_tempo": "slow/medium/fast",
    "clip_durations": {
      "min_seconds": 最短片段,
      "max_seconds": 最长片段,
      "avg_seconds": 平均时长
    },
    "pacing_pattern": "节奏变化模式描述"
  },
  "transitions": {
    "types_used": ["使用的转场类型"],
    "default_type": "主要转场类型",
    "transition_duration_ms": 转场时长估计
  },
  "visual": {
    "color_grading": "调色风格",
    "effects_used": ["使用的效果"],
    "crop_style": "画面裁剪风格"
  },
  "audio": {
    "original_audio_treatment": "原声处理方式",
    "background_music": "背景音乐风格（如有）",
    "sound_effects": ["使用的音效"]
  },
  "techniques": {
    "speed_changes": "是否有变速",
    "text_overlays": "是否有文字叠加",
    "other_effects": ["其他特效"]
  },
  "key_observations": ["关键剪辑手法观察"]
}

分析要点：
1. 仔细观察视频的节奏和片段切换
2. 注意转场类型和时机
3. 分析视频的整体结构（开场-主体-高潮-结尾）
4. 识别任何特殊的剪辑技巧
5. 注意音频处理方式
"""

    try:
        response = model.generate_content([video_file, prompt])

        response_text = response.text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        analysis = json.loads(response_text.strip())
        analysis["result_video"] = str(result_video)

        return analysis

    except json.JSONDecodeError as e:
        print(f"  警告: JSON 解析失败")
        return {
            "result_video": str(result_video),
            "raw_response": response.text,
            "parse_error": str(e)
        }
    finally:
        cleanup_file(video_file)


@retry_on_network_error(max_retries=3, delay=5)
def compare_and_extract(model: genai.GenerativeModel,
                        source_analysis: dict,
                        result_analysis: dict,
                        verbose: bool = True) -> dict:
    """
    对比原片和结果，提取剪辑手法规则
    """
    print("\n对比分析: 提取剪辑规则...")

    prompt = f"""你是专业的剪辑手法分析专家。基于原片分析和剪辑结果分析，提取出可复用的剪辑规则。

## 原片分析
{json.dumps(source_analysis, ensure_ascii=False, indent=2)}

## 剪辑结果分析
{json.dumps(result_analysis, ensure_ascii=False, indent=2)}

请对比分析，提取剪辑手法规则。以 JSON 格式输出（不要包含 markdown 代码块标记）：
{{
  "selection_rules": {{
    "keep_criteria": [
      {{"description": "保留标准描述", "priority": "high/medium/low"}}
    ],
    "remove_criteria": [
      "删除/跳过的标准"
    ],
    "content_priority": ["内容类型优先级排序"]
  }},
  "structure_rules": {{
    "intro": {{
      "duration": "时长范围",
      "content_type": "适合的内容类型",
      "notes": "开场技巧说明"
    }},
    "body": {{
      "arrangement": "编排方式",
      "avg_segment_count": 数量,
      "notes": "主体编排说明"
    }},
    "climax": {{
      "position": "位置描述",
      "treatment": "处理方式"
    }},
    "outro": {{
      "duration": "时长范围",
      "content_type": "适合的内容类型"
    }}
  }},
  "rhythm_rules": {{
    "overall_tempo": "slow/medium/fast",
    "clip_duration": {{
      "min": 最小秒数,
      "max": 最大秒数,
      "avg": 平均秒数
    }},
    "pacing_pattern": "节奏模式描述"
  }},
  "transition_rules": {{
    "default": "默认转场类型",
    "by_context": {{
      "scene_change": "场景切换转场",
      "time_skip": "时间跳跃转场",
      "same_scene": "同场景转场"
    }},
    "duration_ms": 时长毫秒
  }},
  "visual_rules": {{
    "color_grading": "调色风格",
    "effects": ["使用的效果"]
  }},
  "audio_rules": {{
    "original_audio": "原声处理",
    "music_style": "音乐风格",
    "sound_effects": ["音效类型"]
  }},
  "technique_rules": {{
    "speed_ramp": true/false,
    "text_overlays": true/false,
    "other": ["其他技巧"]
  }},
  "key_insights": ["关键洞察，描述这个剪辑风格的独特之处"]
}}

提取要点：
1. 对比原片和结果，找出选择逻辑（哪些被保留，哪些被跳过，为什么）
2. 分析结构编排的规律
3. 总结节奏和转场的模式
4. 识别独特的剪辑技巧
"""

    try:
        response = model.generate_content(prompt)

        response_text = response.text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        rules = json.loads(response_text.strip())
        return rules

    except json.JSONDecodeError as e:
        print(f"  警告: JSON 解析失败")
        return {
            "raw_response": response.text,
            "parse_error": str(e)
        }


def generate_style_yaml(style_name: str,
                        source_analysis: dict,
                        result_analysis: dict,
                        extracted_rules: dict,
                        source_folder: str,
                        result_video: str) -> dict:
    """
    生成 YAML 格式的风格描述
    """
    now = datetime.now().strftime("%Y-%m-%d")

    # 从提取的规则构建 YAML 结构
    selection = extracted_rules.get("selection_rules", {})
    structure = extracted_rules.get("structure_rules", {})
    rhythm = extracted_rules.get("rhythm_rules", {})
    transitions = extracted_rules.get("transition_rules", {})
    visual = extracted_rules.get("visual_rules", {})
    audio = extracted_rules.get("audio_rules", {})
    techniques = extracted_rules.get("technique_rules", {})

    style_data = {
        "meta": {
            "version": 1,
            "created_at": now,
            "updated_at": now,
            "samples_analyzed": 1,
            "style_name": style_name
        },
        "selection": {
            "keep_criteria": selection.get("keep_criteria", []),
            "remove_criteria": selection.get("remove_criteria", []),
            "content_priority": selection.get("content_priority", [])
        },
        "structure": {
            "intro": structure.get("intro", {
                "duration": "2-4秒",
                "content_type": "吸引注意力的镜头",
                "notes": ""
            }),
            "body": structure.get("body", {
                "arrangement": "按时间顺序",
                "avg_segment_count": 5,
                "notes": ""
            }),
            "climax": structure.get("climax", {
                "position": "60-80%",
                "treatment": ""
            }),
            "outro": structure.get("outro", {
                "duration": "2-3秒",
                "content_type": "总结性镜头"
            })
        },
        "rhythm": {
            "overall_tempo": rhythm.get("overall_tempo", "medium"),
            "clip_duration": rhythm.get("clip_duration", {
                "min": 1.5,
                "max": 6.0,
                "avg": 3.0
            }),
            "pacing_pattern": rhythm.get("pacing_pattern", "")
        },
        "transitions": {
            "default": transitions.get("default", "hard_cut"),
            "by_context": transitions.get("by_context", {
                "scene_change": "dissolve",
                "time_skip": "fade",
                "same_scene": "hard_cut"
            }),
            "duration_ms": transitions.get("duration_ms", 500)
        },
        "visual": {
            "color_grading": visual.get("color_grading", "自然"),
            "effects": visual.get("effects", [])
        },
        "audio": {
            "original_audio": audio.get("original_audio", "保留"),
            "music_style": audio.get("music_style", "无背景音乐"),
            "sound_effects": audio.get("sound_effects", [])
        },
        "techniques": {
            "speed_ramp": techniques.get("speed_ramp", False),
            "text_overlays": techniques.get("text_overlays", False),
            "custom": techniques.get("other", [])
        },
        "key_insights": extracted_rules.get("key_insights", []),
        "analysis_history": [
            {
                "date": now,
                "source_folder": source_folder,
                "result_video": result_video,
                "source_clips": source_analysis.get("total_clips", len(source_analysis.get("analyzed_files", []))),
                "result_duration": f"{result_analysis.get('duration_seconds', 0)}秒",
                "key_observations": result_analysis.get("key_observations", [])
            }
        ]
    }

    return style_data


def merge_with_existing(existing_style: dict, new_analysis: dict) -> dict:
    """
    将新分析结果与已有风格合并
    """
    # 更新元数据
    existing_style["meta"]["updated_at"] = datetime.now().strftime("%Y-%m-%d")
    existing_style["meta"]["version"] = existing_style["meta"].get("version", 1) + 1
    existing_style["meta"]["samples_analyzed"] = existing_style["meta"].get("samples_analyzed", 1) + 1

    # 添加分析历史
    if "analysis_history" not in existing_style:
        existing_style["analysis_history"] = []

    existing_style["analysis_history"].append(new_analysis)

    # TODO: 更智能的规则合并逻辑
    # 目前只是添加历史记录，未来可以基于多次分析结果优化规则

    return existing_style


def save_style_yaml(style_data: dict, style_name: str) -> Path:
    """保存风格文件"""
    STYLES_DIR.mkdir(exist_ok=True)

    output_path = STYLES_DIR / f"{style_name}.yaml"

    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(style_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return output_path


def load_style_yaml(style_path: Path) -> dict:
    """加载已有的风格文件"""
    with open(style_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def list_styles():
    """列出所有已保存的风格"""
    if not STYLES_DIR.exists():
        print("暂无保存的风格")
        return

    styles = list(STYLES_DIR.glob("*.yaml"))
    styles = [s for s in styles if not s.name.startswith("_")]

    if not styles:
        print("暂无保存的风格")
        return

    print(f"\n已保存的剪辑风格 ({len(styles)} 个):")
    print("-" * 50)

    for style_path in sorted(styles):
        try:
            style_data = load_style_yaml(style_path)
            meta = style_data.get("meta", {})
            name = meta.get("style_name", style_path.stem)
            version = meta.get("version", 1)
            samples = meta.get("samples_analyzed", 0)
            updated = meta.get("updated_at", "未知")

            print(f"  {style_path.stem}.yaml")
            print(f"    名称: {name}")
            print(f"    版本: v{version} | 样本数: {samples} | 更新: {updated}")
            print()
        except Exception as e:
            print(f"  {style_path.stem}.yaml (读取失败: {e})")


def print_summary(style_data: dict):
    """打印风格摘要"""
    meta = style_data.get("meta", {})
    rhythm = style_data.get("rhythm", {})
    transitions = style_data.get("transitions", {})
    insights = style_data.get("key_insights", [])

    print("\n" + "=" * 60)
    print("剪辑风格提取完成")
    print("=" * 60)

    print(f"\n风格名称: {meta.get('style_name', '未命名')}")
    print(f"版本: v{meta.get('version', 1)}")
    print(f"分析样本数: {meta.get('samples_analyzed', 1)}")

    print("\n核心特征:")
    print(f"  - 整体节奏: {rhythm.get('overall_tempo', 'N/A')}")
    clip_dur = rhythm.get("clip_duration", {})
    print(f"  - 片段时长: {clip_dur.get('min', 'N/A')}-{clip_dur.get('max', 'N/A')}秒 (平均 {clip_dur.get('avg', 'N/A')}秒)")
    print(f"  - 默认转场: {transitions.get('default', 'N/A')}")

    if insights:
        print("\n关键洞察:")
        for insight in insights[:5]:
            print(f"  - {insight}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="剪辑手法提取工具 - 通过对比原片和结果提取可复用的剪辑规则",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 创建新风格
  python extract_editing_style.py D:\\Videos\\raw D:\\Videos\\output.mp4 --name vlog

  # 更新已有风格
  python extract_editing_style.py D:\\Videos\\raw2 D:\\Videos\\output2.mp4 --update vlog.yaml

  # 列出所有风格
  python extract_editing_style.py --list
        """
    )

    parser.add_argument("source_folder", nargs="?", help="原片文件夹路径")
    parser.add_argument("result_video", nargs="?", help="剪辑结果视频路径")
    parser.add_argument("--name", "-n", default="my_style", help="风格名称（默认: my_style）")
    parser.add_argument("--update", "-u", help="要更新的已有风格文件名（如 vlog.yaml）")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有已保存的风格")
    parser.add_argument("--quiet", "-q", action="store_true", help="减少输出")

    args = parser.parse_args()

    # 列出风格模式
    if args.list:
        list_styles()
        return

    # 检查必要参数
    if not args.source_folder or not args.result_video:
        parser.print_help()
        print("\n错误: 需要提供原片文件夹和结果视频路径")
        sys.exit(1)

    source_folder = Path(args.source_folder)
    result_video = Path(args.result_video)

    if not source_folder.exists():
        print(f"错误: 原片文件夹不存在: {source_folder}")
        sys.exit(1)

    if not result_video.exists():
        print(f"错误: 结果视频不存在: {result_video}")
        sys.exit(1)

    verbose = not args.quiet

    # 获取 API Key 并配置
    api_key = get_api_key()
    model = setup_gemini(api_key)

    print("=" * 60)
    print("剪辑手法分析器")
    print("=" * 60)
    print(f"原片文件夹: {source_folder}")
    print(f"结果视频: {result_video}")

    if args.update:
        print(f"模式: 更新已有风格 ({args.update})")
        style_path = STYLES_DIR / args.update
        if not style_path.exists():
            print(f"错误: 风格文件不存在: {style_path}")
            sys.exit(1)
    else:
        print(f"模式: 创建新风格 ({args.name})")

    # 步骤 1: 分析原片
    source_analysis = analyze_source_clips(model, source_folder, verbose)

    # 步骤 2: 分析结果视频
    result_analysis = analyze_result_video(model, result_video, verbose)

    # 步骤 3: 对比提取规则
    extracted_rules = compare_and_extract(model, source_analysis, result_analysis, verbose)

    # 步骤 4: 生成/更新风格文件
    if args.update:
        # 更新模式
        existing_style = load_style_yaml(style_path)

        new_history_entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "source_folder": str(source_folder),
            "result_video": str(result_video),
            "source_clips": source_analysis.get("total_clips", len(source_analysis.get("analyzed_files", []))),
            "result_duration": f"{result_analysis.get('duration_seconds', 0)}秒",
            "key_observations": extracted_rules.get("key_insights", [])
        }

        style_data = merge_with_existing(existing_style, new_history_entry)
        style_name = existing_style["meta"].get("style_name", args.update.replace(".yaml", ""))
        output_path = save_style_yaml(style_data, args.update.replace(".yaml", ""))

    else:
        # 创建新风格
        style_data = generate_style_yaml(
            args.name,
            source_analysis,
            result_analysis,
            extracted_rules,
            str(source_folder),
            str(result_video)
        )
        output_path = save_style_yaml(style_data, args.name)

    # 打印摘要
    print_summary(style_data)
    print(f"\n风格文件已保存: {output_path}")


if __name__ == "__main__":
    main()
