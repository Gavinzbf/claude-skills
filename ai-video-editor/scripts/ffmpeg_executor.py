#!/usr/bin/env python3
"""
FFmpeg 命令生成与执行模块

功能：
- 生成分段变速 FFmpeg 命令
- 执行裁剪、变速、拼接操作
- 支持进度回调
"""

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass
class SpeedSegment:
    """变速片段"""
    start_ms: int
    end_ms: int
    speed: float

    @property
    def start_sec(self) -> float:
        return self.start_ms / 1000.0

    @property
    def end_sec(self) -> float:
        return self.end_ms / 1000.0

    @property
    def duration_sec(self) -> float:
        return (self.end_ms - self.start_ms) / 1000.0

    @property
    def output_duration_sec(self) -> float:
        """变速后的输出时长"""
        return self.duration_sec / self.speed

    @property
    def pts_factor(self) -> float:
        """setpts 的乘数因子（速度的倒数）"""
        return 1.0 / self.speed


@dataclass
class ClipEdit:
    """单个片段的剪辑参数"""
    filename: str
    filepath: str
    trim_start_ms: int
    trim_end_ms: int
    speed_segments: list[SpeedSegment]
    order: int
    role: str = ""
    transition: str = "cut"

    @property
    def has_speed_change(self) -> bool:
        """是否有变速"""
        return any(seg.speed != 1.0 for seg in self.speed_segments)


def check_ffmpeg() -> bool:
    """检查 FFmpeg 是否可用"""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            check=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_video_info(video_path: Path) -> dict:
    """获取视频信息"""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(video_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def ms_to_timestamp(ms: int) -> str:
    """毫秒转 FFmpeg 时间戳格式 HH:MM:SS.mmm"""
    total_sec = ms / 1000.0
    hours = int(total_sec // 3600)
    minutes = int((total_sec % 3600) // 60)
    seconds = total_sec % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


def generate_trim_command(
    input_path: Path,
    output_path: Path,
    start_ms: int,
    end_ms: int,
    video_codec: str = "libx264",
    audio_codec: str = "aac",
    video_bitrate: str = "4M",
    audio_bitrate: str = "128k"
) -> list[str]:
    """生成简单裁剪命令"""
    return [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-ss", ms_to_timestamp(start_ms),
        "-to", ms_to_timestamp(end_ms),
        "-c:v", video_codec,
        "-c:a", audio_codec,
        "-b:v", video_bitrate,
        "-b:a", audio_bitrate,
        str(output_path)
    ]


def generate_speed_segment_filter(segments: list[SpeedSegment]) -> str:
    """
    生成分段变速的 filter_complex 字符串

    使用 split + trim + setpts + concat 实现分段变速
    """
    n = len(segments)
    if n == 0:
        return ""

    filters = []

    # 分割输入流
    split_outputs = "".join(f"[v{i}]" for i in range(n))
    filters.append(f"[0:v]split={n}{split_outputs}")

    # 处理每个片段
    segment_outputs = []
    for i, seg in enumerate(segments):
        # trim + setpts 处理视频
        filters.append(
            f"[v{i}]trim=start={seg.start_sec:.3f}:end={seg.end_sec:.3f},"
            f"setpts={seg.pts_factor:.4f}*(PTS-STARTPTS)[seg{i}]"
        )
        segment_outputs.append(f"[seg{i}]")

    # 合并所有片段
    concat_inputs = "".join(segment_outputs)
    filters.append(f"{concat_inputs}concat=n={n}:v=1:a=0[vout]")

    return ";".join(filters)


def generate_audio_speed_filter(segments: list[SpeedSegment]) -> str:
    """
    生成音频变速的 filter_complex 字符串

    注意：atempo 范围是 0.5-2.0，超出需要链式处理
    """
    n = len(segments)
    if n == 0:
        return ""

    filters = []

    # 分割音频流
    split_outputs = "".join(f"[a{i}]" for i in range(n))
    filters.append(f"[0:a]asplit={n}{split_outputs}")

    # 处理每个片段
    segment_outputs = []
    for i, seg in enumerate(segments):
        # atrim + atempo 处理音频
        tempo_chain = build_atempo_chain(seg.speed)
        filters.append(
            f"[a{i}]atrim=start={seg.start_sec:.3f}:end={seg.end_sec:.3f},"
            f"asetpts=PTS-STARTPTS,{tempo_chain}[aseg{i}]"
        )
        segment_outputs.append(f"[aseg{i}]")

    # 合并所有片段
    concat_inputs = "".join(segment_outputs)
    filters.append(f"{concat_inputs}concat=n={n}:v=0:a=1[aout]")

    return ";".join(filters)


def build_atempo_chain(speed: float) -> str:
    """
    构建 atempo 链，处理超出 0.5-2.0 范围的情况

    例如：4x 速度 = atempo=2.0,atempo=2.0
    """
    if speed < 0.5:
        # 极慢速度需要多次 0.5
        chain = []
        remaining = speed
        while remaining < 0.5:
            chain.append("atempo=0.5")
            remaining *= 2
        chain.append(f"atempo={remaining:.4f}")
        return ",".join(chain)
    elif speed > 2.0:
        # 快速需要多次 2.0
        chain = []
        remaining = speed
        while remaining > 2.0:
            chain.append("atempo=2.0")
            remaining /= 2
        chain.append(f"atempo={remaining:.4f}")
        return ",".join(chain)
    else:
        return f"atempo={speed:.4f}"


def generate_speed_ramp_command(
    input_path: Path,
    output_path: Path,
    segments: list[SpeedSegment],
    video_codec: str = "libx264",
    audio_codec: str = "aac",
    video_bitrate: str = "4M",
    audio_bitrate: str = "128k",
    include_audio: bool = True
) -> list[str]:
    """
    生成分段变速命令

    Args:
        input_path: 输入视频路径
        output_path: 输出视频路径
        segments: 变速片段列表
        video_codec: 视频编码器
        audio_codec: 音频编码器
        video_bitrate: 视频码率
        audio_bitrate: 音频码率
        include_audio: 是否包含音频

    Returns:
        FFmpeg 命令参数列表
    """
    video_filter = generate_speed_segment_filter(segments)

    if include_audio:
        audio_filter = generate_audio_speed_filter(segments)
        full_filter = f"{video_filter};{audio_filter}"
        map_args = ["-map", "[vout]", "-map", "[aout]"]
    else:
        full_filter = video_filter
        map_args = ["-map", "[vout]"]

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-filter_complex", full_filter
    ] + map_args + [
        "-c:v", video_codec,
        "-c:a", audio_codec,
        "-b:v", video_bitrate,
        "-b:a", audio_bitrate,
        str(output_path)
    ]

    return cmd


def process_single_clip(
    clip: ClipEdit,
    output_dir: Path,
    video_codec: str = "libx264",
    audio_codec: str = "aac",
    video_bitrate: str = "4M",
    audio_bitrate: str = "128k",
    progress_callback: Optional[Callable[[str], None]] = None
) -> Path:
    """
    处理单个片段

    Args:
        clip: 片段剪辑参数
        output_dir: 输出目录
        video_codec: 视频编码器
        audio_codec: 音频编码器
        video_bitrate: 视频码率
        audio_bitrate: 音频码率
        progress_callback: 进度回调函数

    Returns:
        输出文件路径
    """
    input_path = Path(clip.filepath)
    output_path = output_dir / f"segment_{clip.order:03d}.mp4"

    if progress_callback:
        progress_callback(f"处理片段 {clip.order}: {clip.filename}")

    if clip.has_speed_change:
        # 有变速，使用 filter_complex
        cmd = generate_speed_ramp_command(
            input_path, output_path, clip.speed_segments,
            video_codec, audio_codec, video_bitrate, audio_bitrate
        )
    else:
        # 无变速，简单裁剪
        cmd = generate_trim_command(
            input_path, output_path,
            clip.trim_start_ms, clip.trim_end_ms,
            video_codec, audio_codec, video_bitrate, audio_bitrate
        )

    # 执行命令
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg 错误: {result.stderr}")

    return output_path


def concat_clips(
    clip_paths: list[Path],
    output_path: Path,
    video_codec: str = "libx264",
    audio_codec: str = "aac",
    video_bitrate: str = "4M",
    audio_bitrate: str = "128k",
    progress_callback: Optional[Callable[[str], None]] = None
) -> Path:
    """
    拼接多个片段

    Args:
        clip_paths: 片段路径列表
        output_path: 输出路径
        video_codec: 视频编码器
        audio_codec: 音频编码器
        video_bitrate: 视频码率
        audio_bitrate: 音频码率
        progress_callback: 进度回调

    Returns:
        输出文件路径
    """
    if progress_callback:
        progress_callback("拼接所有片段...")

    # 创建文件列表
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.txt', delete=False, encoding='utf-8'
    ) as f:
        for path in clip_paths:
            # 使用正斜杠，FFmpeg 在 Windows 上也能识别
            f.write(f"file '{str(path).replace(os.sep, '/')}'\n")
        filelist_path = f.name

    try:
        # 尝试 stream copy（如果编码相同）
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", filelist_path,
            "-c", "copy",
            str(output_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            # stream copy 失败，重新编码
            if progress_callback:
                progress_callback("需要重新编码，可能需要更长时间...")

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", filelist_path,
                "-c:v", video_codec,
                "-c:a", audio_codec,
                "-b:v", video_bitrate,
                "-b:a", audio_bitrate,
                str(output_path)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg 拼接错误: {result.stderr}")

    finally:
        # 清理临时文件
        os.unlink(filelist_path)

    return output_path


def execute_edit_plan(
    edit_plan: dict,
    video_dir: Path,
    output_path: Path,
    preset: str = "douyin",
    progress_callback: Optional[Callable[[str], None]] = None
) -> Path:
    """
    执行完整的剪辑方案

    Args:
        edit_plan: 剪辑方案（edit_plan_v2.json 格式）
        video_dir: 视频目录
        output_path: 最终输出路径
        preset: 输出预设名称
        progress_callback: 进度回调

    Returns:
        最终输出文件路径
    """
    if not check_ffmpeg():
        raise RuntimeError("FFmpeg 未安装或不在 PATH 中")

    # 从预设获取编码参数（这里使用默认值，实际应从 config 读取）
    video_codec = "libx264"
    audio_codec = "aac"
    video_bitrate = "4M"
    audio_bitrate = "128k"

    # 创建临时目录
    temp_dir = video_dir / ".ai-editor-temp"
    temp_dir.mkdir(exist_ok=True)

    try:
        # 解析剪辑序列
        clips = []
        for item in edit_plan.get("clip_sequence", []):
            phase2 = item.get("phase2", {})
            trim = phase2.get("trim", {})
            speed_segments = []

            for seg in phase2.get("speed_segments", []):
                speed_segments.append(SpeedSegment(
                    start_ms=seg["start_ms"],
                    end_ms=seg["end_ms"],
                    speed=seg.get("speed", 1.0)
                ))

            # 如果没有 speed_segments，创建一个默认的
            if not speed_segments and trim:
                speed_segments = [SpeedSegment(
                    start_ms=trim.get("start_ms", 0),
                    end_ms=trim.get("end_ms", 0),
                    speed=1.0
                )]

            clip = ClipEdit(
                filename=item.get("filename"),
                filepath=str(video_dir / item.get("filename")),
                trim_start_ms=trim.get("start_ms", 0),
                trim_end_ms=trim.get("end_ms", 0),
                speed_segments=speed_segments,
                order=item.get("order", 0),
                role=item.get("role", ""),
                transition=item.get("transition_to_next", "cut")
            )
            clips.append(clip)

        if not clips:
            raise ValueError("剪辑方案中没有有效的片段")

        # 处理每个片段
        processed_paths = []
        total = len(clips)

        for i, clip in enumerate(clips, 1):
            if progress_callback:
                progress_callback(f"处理片段 [{i}/{total}]: {clip.filename}")

            segment_path = process_single_clip(
                clip, temp_dir,
                video_codec, audio_codec, video_bitrate, audio_bitrate,
                progress_callback
            )
            processed_paths.append(segment_path)

        # 拼接所有片段
        if progress_callback:
            progress_callback("拼接最终视频...")

        final_path = concat_clips(
            processed_paths, output_path,
            video_codec, audio_codec, video_bitrate, audio_bitrate,
            progress_callback
        )

        if progress_callback:
            progress_callback(f"完成！输出文件: {final_path}")

        return final_path

    finally:
        # 清理临时目录
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    """测试入口"""
    import argparse

    parser = argparse.ArgumentParser(description="FFmpeg 执行器测试")
    parser.add_argument("video_dir", help="视频目录")
    parser.add_argument("--plan", required=True, help="剪辑方案 JSON 文件")
    parser.add_argument("-o", "--output", default="output.mp4", help="输出文件名")

    args = parser.parse_args()

    video_dir = Path(args.video_dir)
    plan_path = Path(args.plan)

    if not video_dir.exists():
        print(f"错误: 目录不存在: {video_dir}")
        return

    if not plan_path.exists():
        print(f"错误: 方案文件不存在: {plan_path}")
        return

    with open(plan_path, 'r', encoding='utf-8') as f:
        edit_plan = json.load(f)

    output_path = video_dir / args.output

    def progress(msg):
        print(f"  {msg}")

    try:
        result = execute_edit_plan(
            edit_plan, video_dir, output_path,
            progress_callback=progress
        )
        print(f"\n输出文件: {result}")
    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    main()
