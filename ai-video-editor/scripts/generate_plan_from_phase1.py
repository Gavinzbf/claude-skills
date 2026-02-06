#!/usr/bin/env python3
"""
从阶段一分析结果生成剪辑方案（当阶段二失败时使用）

使用 highlight_segment 信息来确定裁剪区间
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None


def parse_time_to_ms(time_str: str) -> int:
    """解析时间字符串为毫秒"""
    if not time_str:
        return 0

    # 处理 "00:00" 或 "00:01" 格式
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) == 2:
            minutes, seconds = parts
            return (int(minutes) * 60 + int(seconds)) * 1000
        elif len(parts) == 3:
            hours, minutes, seconds = parts
            return (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1000

    # 尝试直接解析为秒数
    try:
        return int(float(time_str) * 1000)
    except ValueError:
        return 0


def generate_plan_from_phase1(
    video_dir: Path,
    target_duration: Optional[int] = None,
    style_config: Optional[dict] = None
) -> dict:
    """
    从阶段一分析结果生成剪辑方案
    """
    analysis_dir = video_dir / ".ai-editor-analysis"

    # 加载阶段一分析结果
    phase1_analyses = []
    for f in sorted(analysis_dir.glob("*_analysis.json")):
        if f.name.startswith("merged_"):
            continue
        with open(f, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
            phase1_analyses.append(data)

    if not phase1_analyses:
        print("错误: 没有找到分析结果")
        return None

    print(f"加载了 {len(phase1_analyses)} 个分析结果")

    # 从风格配置提取参数
    if style_config:
        rhythm = style_config.get("rhythm", {})
        clip_dur = rhythm.get("clip_duration", {})
        avg_clip_duration = clip_dur.get("avg", 2.6)
        use_speed_ramp = style_config.get("techniques", {}).get("speed_ramp", False)
        default_transition = style_config.get("transitions", {}).get("default", "Hard Cut")
        style_name = style_config.get("meta", {}).get("style_name", "custom")
    else:
        avg_clip_duration = 3.0
        use_speed_ramp = False
        default_transition = "cut"
        style_name = "default"

    # 按质量评分排序
    sorted_analyses = sorted(
        phase1_analyses,
        key=lambda x: x.get("quality_score", 0),
        reverse=True
    )

    clip_sequence = []
    excluded_clips = []
    total_duration_ms = 0
    order = 1

    for item in sorted_analyses:
        filename = item.get("filename")
        quality_score = item.get("quality_score", 5)

        # 质量过滤
        if quality_score < 4:
            excluded_clips.append({
                "filename": filename,
                "reason": f"质量评分过低: {quality_score}"
            })
            continue

        # 从 highlight_segment 获取裁剪区间
        highlight = item.get("highlight_segment", {})
        start_str = highlight.get("start", "00:00")
        end_str = highlight.get("end", "00:05")

        start_ms = parse_time_to_ms(start_str)
        end_ms = parse_time_to_ms(end_str)

        # 确保有效区间
        if end_ms <= start_ms:
            end_ms = start_ms + 5000  # 默认5秒

        clip_duration_ms = end_ms - start_ms
        total_duration_ms += clip_duration_ms

        # 确定角色
        suitable_for = item.get("suitable_for", [])
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
            "filename": filename,
            "phase1": {
                "scene": item.get("scene"),
                "quality_score": quality_score,
                "mood": item.get("mood"),
                "suitable_for": suitable_for
            },
            "phase2": {
                "trim": {
                    "start_ms": start_ms,
                    "end_ms": end_ms
                },
                "speed_segments": [{
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "speed": 1.0
                }],
                "ai_artifacts": {}
            },
            "role": role,
            "transition_to_next": default_transition
        })

        order += 1

        # 检查目标时长
        if target_duration and total_duration_ms >= target_duration * 1000:
            break

    # 重新分配角色
    if len(clip_sequence) > 1:
        clip_sequence[-1]["role"] = "结尾"

    edit_plan = {
        "version": "2.0",
        "created_at": datetime.now().isoformat(),
        "style": style_name,
        "style_config_applied": style_config is not None,
        "generated_from": "phase1_only",
        "story_summary": {
            "title": "AI 生成视频集锦",
            "description": "自动剪辑的短视频（基于阶段一分析）",
            "target_audience": "社交媒体用户"
        },
        "clip_sequence": clip_sequence,
        "excluded_clips": excluded_clips,
        "estimated_duration_ms": int(total_duration_ms)
    }

    return edit_plan


def main():
    import argparse

    parser = argparse.ArgumentParser(description="从阶段一生成剪辑方案")
    parser.add_argument("video_dir", help="视频目录")
    parser.add_argument("--style", help="风格配置文件路径")
    parser.add_argument("--duration", type=int, help="目标时长（秒）")

    args = parser.parse_args()

    video_dir = Path(args.video_dir)
    if not video_dir.exists():
        print(f"错误: 目录不存在: {video_dir}")
        sys.exit(1)

    # 加载风格配置
    style_config = None
    if args.style and yaml:
        style_path = Path(args.style)
        if style_path.exists():
            with open(style_path, 'r', encoding='utf-8') as f:
                style_config = yaml.safe_load(f)
            print(f"已加载风格配置: {style_path}")

    # 生成方案
    edit_plan = generate_plan_from_phase1(
        video_dir, args.duration, style_config
    )

    if edit_plan:
        # 保存方案
        output_file = video_dir / ".ai-editor-analysis" / "edit_plan_v2.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(edit_plan, f, ensure_ascii=False, indent=2)

        print(f"\n剪辑方案已保存: {output_file}")
        print(f"包含 {len(edit_plan['clip_sequence'])} 个片段")
        print(f"预计时长: {edit_plan['estimated_duration_ms'] / 1000:.1f} 秒")


if __name__ == "__main__":
    main()
