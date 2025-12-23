"""
语音处理服务 - 基于 faster-whisper 的语音转写

功能：
- 语音转文字 (多语言)
- 带时间戳的转写
- 从视频提取音轨
"""

import logging
import tempfile
import subprocess
from pathlib import Path
from typing import List, Optional, Union
from dataclasses import dataclass

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionSegment:
    """转写片段"""
    start: float  # 开始时间 (秒)
    end: float    # 结束时间 (秒)
    text: str     # 转写文本


@dataclass
class TranscriptionResult:
    """转写结果"""
    text: str                           # 完整文本
    language: str                       # 检测到的语言
    segments: List[TranscriptionSegment]  # 分段列表
    duration: float                     # 音频时长 (秒)


class SpeechService:
    """语音处理服务 (使用 faster-whisper 本地推理)"""
    
    def __init__(self):
        self.model_name = settings.whisper_model
        self.device = settings.whisper_device
        self.supported_types = set(settings.supported_audio_types.split(','))
        self._model = None
        
        logger.info(f"Initialized speech service: {self.model_name} on {self.device}")
    
    @property
    def model(self):
        """懒加载 Whisper 模型"""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type="float16" if self.device == "cuda" else "int8"
                )
                logger.info(f"Loaded Whisper model: {self.model_name}")
            except ImportError:
                logger.error("faster-whisper not installed. Run: pip install faster-whisper")
                raise
        return self._model
    
    def is_supported(self, filename: str) -> bool:
        """检查文件类型是否支持"""
        ext = Path(filename).suffix.lower()
        return ext in self.supported_types
    
    async def transcribe(
        self,
        audio: Union[bytes, str, Path],
        language: str = "auto",
    ) -> TranscriptionResult:
        """
        语音转文字
        
        Args:
            audio: 音频数据 (bytes 或文件路径)
            language: 语言代码 (auto 自动检测)
            
        Returns:
            TranscriptionResult 转写结果
        """
        # 处理音频输入
        if isinstance(audio, bytes):
            # 保存临时文件
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio)
                audio_path = f.name
        else:
            audio_path = str(audio)
        
        try:
            # 执行转写
            segments_iter, info = self.model.transcribe(
                audio_path,
                language=None if language == "auto" else language,
                beam_size=5,
                vad_filter=True,
            )
            
            segments = []
            full_text_parts = []
            
            for segment in segments_iter:
                seg = TranscriptionSegment(
                    start=segment.start,
                    end=segment.end,
                    text=segment.text.strip()
                )
                segments.append(seg)
                full_text_parts.append(seg.text)
            
            return TranscriptionResult(
                text=" ".join(full_text_parts),
                language=info.language,
                segments=segments,
                duration=info.duration
            )
            
        finally:
            # 清理临时文件
            if isinstance(audio, bytes):
                Path(audio_path).unlink(missing_ok=True)
    
    async def transcribe_with_timestamps(
        self,
        audio: Union[bytes, str, Path],
    ) -> List[TranscriptionSegment]:
        """
        带时间戳的转写
        
        Args:
            audio: 音频数据
            
        Returns:
            TranscriptionSegment 列表
        """
        result = await self.transcribe(audio)
        return result.segments
    
    def extract_audio_from_video(
        self,
        video_path: str,
        output_path: Optional[str] = None
    ) -> str:
        """
        从视频提取音轨
        
        Args:
            video_path: 视频文件路径
            output_path: 输出音频路径 (可选，默认临时文件)
            
        Returns:
            提取的音频文件路径
        """
        if output_path is None:
            output_path = tempfile.mktemp(suffix=".wav")
        
        try:
            # 使用 ffmpeg 提取音轨
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-vn",                    # 不包含视频
                "-acodec", "pcm_s16le",   # WAV PCM 格式
                "-ar", "16000",           # 16kHz 采样率
                "-ac", "1",               # 单声道
                output_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info(f"Extracted audio from {video_path} to {output_path}")
            return output_path
            
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg failed: {e.stderr}")
            raise RuntimeError(f"Failed to extract audio: {e.stderr}")
        except FileNotFoundError:
            logger.error("FFmpeg not found. Please install FFmpeg.")
            raise RuntimeError("FFmpeg not installed. Run: apt install ffmpeg")
    
    def format_srt(self, segments: List[TranscriptionSegment]) -> str:
        """
        将转写结果格式化为 SRT 字幕格式
        
        Args:
            segments: 转写片段列表
            
        Returns:
            SRT 格式字符串
        """
        def format_time(seconds: float) -> str:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            millis = int((seconds % 1) * 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
        
        lines = []
        for i, seg in enumerate(segments, 1):
            lines.append(str(i))
            lines.append(f"{format_time(seg.start)} --> {format_time(seg.end)}")
            lines.append(seg.text)
            lines.append("")
        
        return "\n".join(lines)


# 单例
speech_service = SpeechService()
