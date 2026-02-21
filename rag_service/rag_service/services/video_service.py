"""
视频处理服务 - 视频理解与分析

策略：
1. 优先检测 VLM 是否支持原生视频输入
2. 支持则直接使用 VLM 分析
3. 不支持则降级为抽帧 + 音轨转写模式
"""

import logging
import tempfile
import subprocess
from pathlib import Path
from typing import List, Optional, Union, Tuple
from dataclasses import dataclass

from ..config import settings
from .vlm_service import vlm_service
from .speech_service import speech_service

logger = logging.getLogger(__name__)


@dataclass
class VideoInfo:
    """视频信息"""
    duration: float       # 时长 (秒)
    width: int
    height: int
    fps: float
    codec: str
    has_audio: bool


@dataclass
class VideoAnalysisResult:
    """视频分析结果"""
    summary: str                        # 视频内容摘要
    transcript: Optional[str]           # 音频转写文本
    key_points: List[str]               # 关键要点
    frame_descriptions: List[str]       # 关键帧描述 (降级模式)
    timestamps: List[Tuple[float, str]] # (时间戳, 描述) 列表


class VideoService:
    """视频处理服务"""
    
    def __init__(self):
        self.supported_types = set(settings.supported_video_types.split(','))
        self.sample_interval = settings.video_sample_interval
        self.max_frames = settings.video_max_frames
        self._vlm_video_support = None
        
        logger.info(f"Initialized video service: interval={self.sample_interval}s, max_frames={self.max_frames}")
    
    def is_supported(self, filename: str) -> bool:
        """检查文件类型是否支持"""
        ext = Path(filename).suffix.lower()
        return ext in self.supported_types
    
    async def check_vlm_video_support(self) -> bool:
        """
        检测 VLM 是否支持原生视频输入
        
        Returns:
            True 如果支持，False 否则
        """
        if self._vlm_video_support is None:
            self._vlm_video_support = await vlm_service.check_video_support()
        return self._vlm_video_support
    
    def get_video_info(self, video_path: str) -> VideoInfo:
        """
        获取视频基本信息
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            VideoInfo 视频信息
        """
        try:
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                video_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            import json
            data = json.loads(result.stdout)
            
            # 查找视频流
            video_stream = None
            audio_stream = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video" and video_stream is None:
                    video_stream = stream
                elif stream.get("codec_type") == "audio" and audio_stream is None:
                    audio_stream = stream
            
            if not video_stream:
                raise ValueError("No video stream found")
            
            # 解析帧率
            fps_str = video_stream.get("r_frame_rate", "30/1")
            if "/" in fps_str:
                num, den = fps_str.split("/")
                fps = float(num) / float(den)
            else:
                fps = float(fps_str)
            
            return VideoInfo(
                duration=float(data.get("format", {}).get("duration", 0)),
                width=int(video_stream.get("width", 0)),
                height=int(video_stream.get("height", 0)),
                fps=fps,
                codec=video_stream.get("codec_name", "unknown"),
                has_audio=audio_stream is not None
            )
            
        except subprocess.CalledProcessError as e:
            logger.error(f"FFprobe failed: {e.stderr}")
            raise RuntimeError(f"Failed to get video info: {e.stderr}")
        except FileNotFoundError:
            raise RuntimeError("FFprobe not installed. Run: apt install ffmpeg")
    
    def extract_keyframes(
        self,
        video_path: str,
        interval: Optional[float] = None,
        max_frames: Optional[int] = None
    ) -> List[Tuple[float, bytes]]:
        """
        抽取视频关键帧
        
        Args:
            video_path: 视频文件路径
            interval: 抽帧间隔 (秒)
            max_frames: 最大帧数
            
        Returns:
            (时间戳, 帧图像数据) 列表
        """
        interval = interval or self.sample_interval
        max_frames = max_frames or self.max_frames
        
        # 获取视频时长
        info = self.get_video_info(video_path)
        duration = info.duration
        
        # 计算实际抽帧数量
        num_frames = min(int(duration / interval) + 1, max_frames)
        
        frames = []
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(num_frames):
                timestamp = i * interval
                if timestamp > duration:
                    break
                
                output_path = Path(tmpdir) / f"frame_{i:04d}.jpg"
                
                try:
                    cmd = [
                        "ffmpeg", "-y",
                        "-ss", str(timestamp),
                        "-i", video_path,
                        "-vframes", "1",
                        "-q:v", "2",
                        str(output_path)
                    ]
                    
                    subprocess.run(cmd, capture_output=True, check=True)
                    
                    if output_path.exists():
                        frame_data = output_path.read_bytes()
                        frames.append((timestamp, frame_data))
                        
                except subprocess.CalledProcessError as e:
                    logger.warning(f"Failed to extract frame at {timestamp}s: {e}")
        
        logger.info(f"Extracted {len(frames)} keyframes from {video_path}")
        return frames
    
    async def analyze(
        self,
        video: Union[bytes, str, Path],
        include_transcript: bool = True
    ) -> VideoAnalysisResult:
        """
        分析视频内容
        
        自适应策略：
        - 如果 VLM 支持原生视频：直接分析
        - 如果不支持：使用抽帧 + 音轨转写模式
        
        Args:
            video: 视频数据或路径
            include_transcript: 是否包含音频转写
            
        Returns:
            VideoAnalysisResult 分析结果
        """
        # 确保视频是文件路径
        if isinstance(video, bytes):
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(video)
                video_path = f.name
            cleanup = True
        else:
            video_path = str(video)
            cleanup = False
        
        try:
            # 检查 VLM 原生视频支持
            if await self.check_vlm_video_support():
                return await self._analyze_native(video_path, include_transcript)
            else:
                return await self._analyze_fallback(video_path, include_transcript)
        finally:
            if cleanup:
                Path(video_path).unlink(missing_ok=True)
    
    async def _analyze_native(
        self,
        video_path: str,
        include_transcript: bool
    ) -> VideoAnalysisResult:
        """
        使用 VLM 原生视频能力分析 (通过高密度抽帧模拟原生理解)
        """
        logger.info(f"Executing native video analysis for {Path(video_path).name}")
        
        # 获取视频信息
        info = self.get_video_info(video_path)
        
        # 1. 提取音频并转写 (辅助理解)
        transcript = None
        if include_transcript and info.has_audio:
            try:
                audio_path = speech_service.extract_audio_from_video(video_path)
                result = await speech_service.transcribe(audio_path)
                transcript = result.text
                Path(audio_path).unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Audio transcription failed: {e}")
        
        # 2. 抽取关键帧 (使用配置的高密度采样)
        frames = self.extract_keyframes(video_path)
        timestamps = [t for t, _ in frames]
        frame_data = [d for _, d in frames]
        
        if not frames:
            raise ValueError("Failed to extract validation frames from video")

        logger.info(f"Analyzing {len(frames)} frames with VLM (Native Mode)")

        # 3. 使用 VLM 分析
        # 提示词可以稍微调整，强调视频流理解
        response = await vlm_service.analyze_video_frames(
            frames=frame_data,
            timestamps=timestamps,
            audio_transcript=transcript,
            prompt="请分析这段视频。作为全能多模态助手，请捕捉视频中的视觉细节、动作流、物体位置关系以及音频内容(如果有)。提供全面、精准的视频内容总结。"
        )
        
        summary = response.content
        
        # 4. 提取要点
        key_points = []
        for line in summary.split('\n'):
            line = line.strip()
            if line.startswith(('-', '•', '*', '1', '2', '3', '4', '5')):
                key_points.append(line.lstrip('-•*0123456789. '))
        
        return VideoAnalysisResult(
            summary=summary,
            transcript=transcript,
            key_points=key_points[:10],
            frame_descriptions=[], 
            timestamps=[(t, "") for t in timestamps]
        )
    
    async def _analyze_fallback(
        self,
        video_path: str,
        include_transcript: bool
    ) -> VideoAnalysisResult:
        """
        降级模式：抽帧 + 音轨转写
        """
        # 获取视频信息
        info = self.get_video_info(video_path)
        
        # 提取音频并转写 (如果有音轨且需要)
        transcript = None
        if include_transcript and info.has_audio:
            try:
                audio_path = speech_service.extract_audio_from_video(video_path)
                result = await speech_service.transcribe(audio_path)
                transcript = result.text
                Path(audio_path).unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Audio transcription failed: {e}")
        
        # 抽取关键帧
        frames = self.extract_keyframes(video_path)
        timestamps = [t for t, _ in frames]
        frame_data = [d for _, d in frames]
        
        # 使用 VLM 分析帧序列
        response = await vlm_service.analyze_video_frames(
            frames=frame_data,
            timestamps=timestamps,
            audio_transcript=transcript
        )
        
        # 解析分析结果
        summary = response.content
        
        # 提取关键要点 (简单解析)
        key_points = []
        for line in summary.split('\n'):
            line = line.strip()
            if line.startswith(('-', '•', '*', '1', '2', '3', '4', '5')):
                key_points.append(line.lstrip('-•*0123456789. '))
        
        return VideoAnalysisResult(
            summary=summary,
            transcript=transcript,
            key_points=key_points[:10],  # 最多 10 个要点
            frame_descriptions=[],  # 简化，不单独描述每帧
            timestamps=[(t, "") for t in timestamps]
        )
    
    async def summarize(self, video: Union[bytes, str, Path]) -> str:
        """
        生成视频摘要
        
        Args:
            video: 视频数据或路径
            
        Returns:
            视频内容摘要
        """
        result = await self.analyze(video, include_transcript=True)
        return result.summary


# 单例
video_service = VideoService()
