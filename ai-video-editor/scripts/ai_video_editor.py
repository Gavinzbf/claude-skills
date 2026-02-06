#!/usr/bin/env python3
"""
AI 视频自动剪辑器 - 主协调脚本

工作流程：
1. 阶段一：内容理解（调用 analyze_with_gemini.py）
2. 阶段二：精准剪切分析（调用 precision_cutter.py）
3. 步骤一：展示方案，等待用户确认
4. 步骤二：执行剪辑（调用 ffmpeg_executor.py）

使用方法：
    # 只运行分析阶段（不执行剪辑）
    python ai_video_editor.py "D:\\Videos\\ai-clips" --analyze-only

    # 执行完整流程
    python ai_video_editor.py "D:\\Videos\\ai-clips"

    # 跳过分析，直接从已有方案执行
    python ai_video_editor.py "D:\\Videos\\ai-clips" --execute
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None

# 导入子模块
try:
    from analyze_with_gemini import (
        get_api_key, setup_gemini, analyze_directory,
        generate_edit_plan, load_existing_analyses, get_video_files
    )
    from precision_cutter import (
        analyze_directory_precision, merge_phase1_and_phase2
    )
    from ffmpeg_executor import execute_edit_plan, check_ffmpeg
except ImportError:
    # 尝试相对导入
    import importlib.util

    def import_from_path(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    scripts_dir = Path(__file__).parent
    analyze_mod = import_from_path("analyze_with_gemini", scripts_dir / "analyze_with_gemini.py")
    precision_mod = import_from_path("precision_cutter", scripts_dir / "precision_cutter.py")
    ffmpeg_mod = import_from_path("ffmpeg_executor", scripts_dir / "ffmpeg_executor.py")

    get_api_key = analyze_mod.get_api_key
    setup_gemini = analyze_mod.setup_gemini
    analyze_directory = analyze_mod.analyze_directory
    generate_edit_plan = analyze_mod.generate_edit_plan
    load_existing_analyses = analyze_mod.load_existing_analyses
    get_video_files = analyze_mod.get_video_files
    analyze_directory_precision = precision_mod.analyze_directory_precision
    merge_phase1_and_phase2 = precision_mod.merge_phase1_and_phase2
    execute_edit_plan = ffmpeg_mod.execute_edit_plan
    check_ffmpeg = ffmpeg_mod.check_ffmpeg


# 分析输出目录
ANALYSIS_DIR = ".ai-editor-analysis"

# 风格文件搜索路径
STYLES_SEARCH_PATHS = [
    Path(__file__).parent.parent.parent.parent / "styles",  # 项目根目录/styles
    Path(__file__).parent.parent / "styles",  # skill目录/styles
    Path.cwd() / "styles",  # 当前工作目录/styles
]


def load_style_config(style_arg: str) -> Optional[dict]:
    """
    加载风格配置文件

    支持:
    - 完整 YAML 文件路径: D:\\styles\\kpop_story.yaml
    - 相对路径: styles/kpop_story.yaml
    - 风格名称（自动查找）: kpop_story
    - 空或默认值: 返回 None

    Returns:
        风格配置字典，或 None（使用默认行为）
    """
    if not style_arg or style_arg in ("抖音/TikTok 短视频", "default"):
        return None

    if yaml is None:
        print("警告: PyYAML 未安装，无法加载风格文件")
        print("运行: pip install pyyaml")
        return None

    # 尝试作为完整路径
    style_path = Path(style_arg)
    if style_path.exists() and style_path.suffix in (".yaml", ".yml"):
        try:
            with open(style_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            print(f"已加载风格配置: {style_path}")
            return config
        except Exception as e:
            print(f"警告: 加载风格文件失败: {e}")
            return None

    # 尝试在搜索路径中查找
    style_name = style_arg.replace(".yaml", "").replace(".yml", "")

    for search_dir in STYLES_SEARCH_PATHS:
        if not search_dir.exists():
            continue

        for suffix in (".yaml", ".yml"):
            candidate = search_dir / f"{style_name}{suffix}"
            if candidate.exists():
                try:
                    with open(candidate, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f)
                    print(f"已加载风格配置: {candidate}")
                    return config
                except Exception as e:
                    print(f"警告: 加载风格文件失败: {e}")
                    return None

    # 未找到风格文件
    print(f"提示: 未找到风格文件 '{style_arg}'，将使用默认设置")
    print(f"搜索路径: {[str(p) for p in STYLES_SEARCH_PATHS if p.exists()]}")
    return None


def print_banner():
    """打印欢迎横幅"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║            AI 视频自动剪辑器 v2.0                             ║
║  自动剪辑 AI 生成视频，输出社媒短视频                          ║
╚══════════════════════════════════════════════════════════════╝
""")


def print_plan_table(edit_plan: dict):
    """以表格形式打印剪辑方案"""
    print("\n" + "=" * 70)
    print("                        剪辑方案预览")
    print("=" * 70)

    # 故事摘要
    story = edit_plan.get("story_summary", {})
    if story:
        print(f"\n【故事概要】")
        print(f"  标题: {story.get('title', 'N/A')}")
        print(f"  描述: {story.get('description', 'N/A')}")
        print(f"  目标受众: {story.get('target_audience', 'N/A')}")

    # 预计时长
    estimated = edit_plan.get("estimated_duration_ms")
    if estimated:
        sec = estimated / 1000
        print(f"\n预计总时长: {sec:.1f} 秒")

    # 片段序列表格
    print("\n【片段序列】")
    print("-" * 70)
    print(f"{'序号':<4} {'文件名':<20} {'裁剪区间':<18} {'角色':<10} {'变速'}")
    print("-" * 70)

    for item in edit_plan.get("clip_sequence", []):
        order = item.get("order", "?")
        filename = item.get("filename", "?")[:18]
        phase2 = item.get("phase2", {})
        trim = phase2.get("trim", {})

        trim_start = trim.get("start_ms", 0)
        trim_end = trim.get("end_ms", 0)
        trim_str = f"{trim_start}ms - {trim_end}ms"

        role = item.get("role", "")[:8]

        # 变速信息
        speed_segs = phase2.get("speed_segments", [])
        if speed_segs:
            speeds = [f"{s.get('speed', 1.0):.1f}x" for s in speed_segs]
            speed_str = ", ".join(speeds[:3])
            if len(speeds) > 3:
                speed_str += "..."
        else:
            speed_str = "1.0x"

        print(f"{order:<4} {filename:<20} {trim_str:<18} {role:<10} {speed_str}")

    # 跳过的片段
    excluded = edit_plan.get("excluded_clips", [])
    if excluded:
        print("\n【跳过的片段】")
        print("-" * 70)
        for item in excluded:
            filename = item.get("filename", "?")
            reason = item.get("reason", "无")
            print(f"  - {filename}: {reason}")

    print("\n" + "=" * 70)


def generate_edit_plan_v2(
    merged_analyses: list[dict],
    target_duration: Optional[int] = None,
    style: str = "抖音/TikTok 短视频",
    style_config: Optional[dict] = None
) -> dict:
    """
    生成 v2 版本的剪辑方案

    Args:
        merged_analyses: 合并后的分析结果（包含 phase1 和 phase2）
        target_duration: 目标时长（秒）
        style: 目标风格描述
        style_config: 风格配置字典（从 YAML 文件加载）

    Returns:
        edit_plan_v2 格式的剪辑方案
    """
    clip_sequence = []
    excluded_clips = []
    total_duration_ms = 0

    # 从风格配置中提取规则
    if style_config:
        rhythm = style_config.get("rhythm", {})
        clip_dur = rhythm.get("clip_duration", {})
        min_clip_duration_ms = clip_dur.get("min", 1.5) * 1000
        max_clip_duration_ms = clip_dur.get("max", 6.0) * 1000
        use_speed_ramp = style_config.get("techniques", {}).get("speed_ramp", True)
        default_transition = style_config.get("transitions", {}).get("default", "cut")
        platform_max = style_config.get("platform", {}).get("max_duration")
        style_name = style_config.get("meta", {}).get("style_name", style)

        # 如果风格配置中有最大时长且没有指定目标时长，使用风格配置的值
        if platform_max and not target_duration:
            target_duration = platform_max
    else:
        min_clip_duration_ms = 1500  # 1.5秒
        max_clip_duration_ms = 6000  # 6秒
        use_speed_ramp = True
        default_transition = "cut"
        style_name = style

    # 按质量评分排序
    sorted_analyses = sorted(
        merged_analyses,
        key=lambda x: x.get("phase1", {}).get("quality_score", 0),
        reverse=True
    )

    order = 1
    for item in sorted_analyses:
        phase1 = item.get("phase1", {})
        phase2 = item.get("phase2", {})

        # 检查是否有错误
        if phase1.get("error") or phase2.get("error"):
            excluded_clips.append({
                "filename": item.get("filename"),
                "reason": phase1.get("error") or phase2.get("error")
            })
            continue

        # 检查质量评分
        quality_score = phase1.get("quality_score", 5)
        if quality_score < 4:
            excluded_clips.append({
                "filename": item.get("filename"),
                "reason": f"质量评分过低: {quality_score}"
            })
            continue

        # 获取推荐裁剪区间
        recommended_trim = phase2.get("recommended_trim", {})
        if not recommended_trim or recommended_trim.get("end_ms") is None:
            # 使用原始时长
            duration_ms = phase2.get("duration_ms", 5000)
            if duration_ms is None:
                # 跳过无法确定时长的片段
                excluded_clips.append({
                    "filename": item.get("filename"),
                    "reason": "无法确定视频时长"
                })
                continue
            recommended_trim = {"start_ms": 0, "end_ms": duration_ms}

        # 生成变速片段
        speed_segments = []
        segments = phase2.get("segments", [])

        if segments and use_speed_ramp:
            # 启用变速：使用 AI 建议的速度
            for seg in segments:
                # 确保片段在裁剪范围内
                start = max(seg.get("start_ms", 0), recommended_trim.get("start_ms", 0))
                end = min(seg.get("end_ms", 0), recommended_trim.get("end_ms", 0))

                if end > start:
                    speed_segments.append({
                        "start_ms": start,
                        "end_ms": end,
                        "speed": seg.get("speed_suggestion", 1.0),
                        "action_type": seg.get("action_type", ""),
                        "description": seg.get("description", "")
                    })
        else:
            # 禁用变速或无 AI 建议：使用 1.0x 速度
            speed_segments.append({
                "start_ms": recommended_trim.get("start_ms", 0),
                "end_ms": recommended_trim.get("end_ms", 0),
                "speed": 1.0
            })

        # 计算此片段的输出时长
        clip_duration_ms = sum(
            (seg["end_ms"] - seg["start_ms"]) / seg.get("speed", 1.0)
            for seg in speed_segments
            if seg.get("end_ms") is not None and seg.get("start_ms") is not None
        )
        total_duration_ms += clip_duration_ms

        # 确定角色
        suitable_for = phase1.get("suitable_for", [])
        if order == 1:
            role = "开场"
        elif "高潮" in suitable_for:
            role = "高潮"
        elif "结尾" in suitable_for:
            role = "结尾"
        else:
            role = "铺垫"

        clip_sequence.append({
            "order": order,
            "filename": item.get("filename"),
            "phase1": {
                "scene": phase1.get("scene"),
                "quality_score": quality_score,
                "mood": phase1.get("mood"),
                "suitable_for": suitable_for
            },
            "phase2": {
                "trim": {
                    "start_ms": recommended_trim.get("start_ms", 0),
                    "end_ms": recommended_trim.get("end_ms", 0)
                },
                "speed_segments": speed_segments,
                "ai_artifacts": phase2.get("ai_artifacts", {})
            },
            "role": role,
            "transition_to_next": default_transition
        })

        order += 1

        # 检查目标时长
        if target_duration and total_duration_ms >= target_duration * 1000:
            break

    # 重新分配角色（最后一个设为结尾）
    if len(clip_sequence) > 1:
        clip_sequence[-1]["role"] = "结尾"

    # 构建完整方案
    edit_plan = {
        "version": "2.0",
        "created_at": datetime.now().isoformat(),
        "style": style_name,
        "style_config_applied": style_config is not None,
        "story_summary": {
            "title": "AI 生成视频集锦",
            "description": "自动剪辑的短视频",
            "target_audience": "社交媒体用户"
        },
        "clip_sequence": clip_sequence,
        "excluded_clips": excluded_clips,
        "estimated_duration_ms": int(total_duration_ms)
    }

    return edit_plan


def run_phase1(
    video_dir: Path,
    model,
    verbose: bool = True
) -> list[dict]:
    """运行阶段一：内容理解"""
    print("\n" + "=" * 50)
    print("【阶段一】内容理解分析")
    print("=" * 50)

    output_dir = video_dir / ANALYSIS_DIR

    # 检查是否有现有分析
    if output_dir.exists():
        existing = load_existing_analyses(output_dir)
        if existing:
            print(f"找到 {len(existing)} 个已有分析结果")
            videos = get_video_files(video_dir)
            if len(existing) >= len(videos):
                print("所有视频已分析，跳过阶段一")
                return existing

    analyses = analyze_directory(model, video_dir, verbose)
    return analyses


def run_phase2(
    video_dir: Path,
    phase1_analyses: list[dict],
    model,
    verbose: bool = True
) -> list[dict]:
    """运行阶段二：精准剪切分析"""
    print("\n" + "=" * 50)
    print("【阶段二】精准剪切分析")
    print("=" * 50)

    phase2_results = analyze_directory_precision(
        model, video_dir, phase1_analyses, verbose
    )

    return phase2_results


def run_analysis(
    video_dir: Path,
    target_duration: Optional[int] = None,
    style: str = "抖音/TikTok 短视频",
    style_config: Optional[dict] = None,
    verbose: bool = True
) -> dict:
    """
    运行完整分析流程（阶段一 + 阶段二）

    Args:
        video_dir: 视频目录
        target_duration: 目标时长（秒）
        style: 风格描述字符串
        style_config: 风格配置字典（从 YAML 加载）
        verbose: 详细输出

    Returns:
        edit_plan_v2 格式的剪辑方案
    """
    # 获取 API 并初始化模型
    api_key = get_api_key()
    model = setup_gemini(api_key)

    # 阶段一
    phase1_analyses = run_phase1(video_dir, model, verbose)

    # 阶段二
    phase2_analyses = run_phase2(video_dir, phase1_analyses, model, verbose)

    # 合并结果
    print("\n合并分析结果...")
    merged = merge_phase1_and_phase2(phase1_analyses, phase2_analyses)

    # 保存合并结果
    output_dir = video_dir / ANALYSIS_DIR
    output_dir.mkdir(exist_ok=True)

    merged_file = output_dir / "merged_analysis.json"
    with open(merged_file, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    # 生成 v2 剪辑方案
    print("\n生成剪辑方案...")
    edit_plan = generate_edit_plan_v2(merged, target_duration, style, style_config)

    # 保存方案
    plan_file = output_dir / "edit_plan_v2.json"
    with open(plan_file, 'w', encoding='utf-8') as f:
        json.dump(edit_plan, f, ensure_ascii=False, indent=2)

    print(f"\n分析完成！")
    print(f"  合并分析: {merged_file}")
    print(f"  剪辑方案: {plan_file}")

    return edit_plan


def run_execute(
    video_dir: Path,
    edit_plan: dict,
    output_name: str = "output.mp4",
    preset: str = "douyin",
    verbose: bool = True
) -> Path:
    """
    执行剪辑

    Args:
        video_dir: 视频目录
        edit_plan: 剪辑方案
        output_name: 输出文件名
        preset: 输出预设
        verbose: 详细输出

    Returns:
        输出文件路径
    """
    print("\n" + "=" * 50)
    print("【执行剪辑】")
    print("=" * 50)

    if not check_ffmpeg():
        print("错误: FFmpeg 未安装或不在 PATH 中")
        print("请安装 FFmpeg: https://ffmpeg.org/download.html")
        sys.exit(1)

    output_path = video_dir / output_name

    def progress_callback(msg):
        if verbose:
            print(f"  {msg}")

    result = execute_edit_plan(
        edit_plan,
        video_dir,
        output_path,
        preset=preset,
        progress_callback=progress_callback
    )

    print(f"\n剪辑完成！")
    print(f"  输出文件: {result}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="AI 视频自动剪辑器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 只运行分析（不执行剪辑）
  python ai_video_editor.py "D:\\Videos\\ai-clips" --analyze-only

  # 运行完整流程（分析 + 用户确认 + 执行）
  python ai_video_editor.py "D:\\Videos\\ai-clips"

  # 跳过分析，使用已有方案执行
  python ai_video_editor.py "D:\\Videos\\ai-clips" --execute

  # 指定目标时长和输出预设
  python ai_video_editor.py "D:\\Videos\\ai-clips" --duration 30 --preset youtube_shorts

  # 使用风格配置文件（由 analyze-style 生成）
  python ai_video_editor.py "D:\\Videos\\ai-clips" --style kpop_story
  python ai_video_editor.py "D:\\Videos\\ai-clips" --style styles/kpop_story.yaml
        """
    )

    parser.add_argument("video_dir", help="视频目录路径")
    parser.add_argument("--analyze-only", action="store_true",
                        help="只运行分析，不执行剪辑")
    parser.add_argument("--execute", action="store_true",
                        help="跳过分析，直接执行已有剪辑方案")
    parser.add_argument("--duration", type=int,
                        help="目标视频时长（秒）")
    parser.add_argument("--style", default="",
                        help="风格配置: YAML文件路径 或 风格名称（自动查找 styles/ 目录）")
    parser.add_argument("--preset", default="douyin",
                        choices=["douyin", "youtube_shorts", "weixin_vertical"],
                        help="输出预设")
    parser.add_argument("-o", "--output", default="output.mp4",
                        help="输出文件名")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="减少输出")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="跳过确认，直接执行")

    args = parser.parse_args()

    print_banner()

    video_dir = Path(args.video_dir)
    if not video_dir.exists():
        print(f"错误: 目录不存在: {video_dir}")
        sys.exit(1)

    verbose = not args.quiet
    output_dir = video_dir / ANALYSIS_DIR

    # 加载风格配置
    style_config = None
    if args.style:
        style_config = load_style_config(args.style)
        if style_config:
            style_name = style_config.get("meta", {}).get("style_name", args.style)
            print(f"风格: {style_name}")

    if args.execute:
        # 直接执行模式
        plan_file = output_dir / "edit_plan_v2.json"
        if not plan_file.exists():
            print(f"错误: 剪辑方案不存在: {plan_file}")
            print("请先运行分析: python ai_video_editor.py <视频目录>")
            sys.exit(1)

        with open(plan_file, 'r', encoding='utf-8') as f:
            edit_plan = json.load(f)

        print_plan_table(edit_plan)

        if not args.yes:
            confirm = input("\n确认执行剪辑? [y/N]: ").strip().lower()
            if confirm not in ('y', 'yes'):
                print("已取消")
                sys.exit(0)

        run_execute(video_dir, edit_plan, args.output, args.preset, verbose)

    else:
        # 分析模式
        style_desc = args.style if args.style else "抖音/TikTok 短视频"
        edit_plan = run_analysis(
            video_dir, args.duration, style_desc, style_config, verbose
        )

        # 打印方案
        print_plan_table(edit_plan)

        if args.analyze_only:
            print("\n分析完成。使用 --execute 执行剪辑。")
            sys.exit(0)

        # 用户确认
        if not args.yes:
            print("\n选项:")
            print("  [y] 确认执行剪辑")
            print("  [n] 取消")
            print("  [e] 编辑方案后执行")

            choice = input("\n请选择 [y/n/e]: ").strip().lower()

            if choice == 'n':
                print("已取消")
                sys.exit(0)
            elif choice == 'e':
                plan_file = output_dir / "edit_plan_v2.json"
                print(f"\n请编辑剪辑方案: {plan_file}")
                print("编辑完成后，运行: python ai_video_editor.py <视频目录> --execute")
                sys.exit(0)
            elif choice != 'y':
                print("无效选项，已取消")
                sys.exit(0)

        # 执行剪辑
        run_execute(video_dir, edit_plan, args.output, args.preset, verbose)


if __name__ == "__main__":
    main()
