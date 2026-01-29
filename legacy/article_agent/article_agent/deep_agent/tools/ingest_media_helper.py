"""Media file analysis helper for ingest_documents_tool."""

import logging
import json

from langchain_core.messages import HumanMessage

from ...config.llm_runtime import build_chat_llm, extract_text_content

_LOGGER = logging.getLogger(__name__)


async def _describe_media_file_with_vlm(
    local_file_path: str, 
    media_type: str, 
    article_id: str, 
    doc_id: str,
    filename: str
) -> str:
    """Use VLM to analyze Video or Audio files served via rag-service.
    
    Args:
        local_file_path: Absolute path to the file (for fallback/logging)
        media_type: 'video' or 'audio'
        article_id: Article ID
        doc_id: Document/Corpus ID
        filename: Filename in the corpus directory
    
    Returns:
        JSON string with summary and description.
    """
    try:
        # Construct internal URL accessible by vLLM container
        # Pattern: http://rag-service:8200/api/artifacts/article_{id}/corpus/{doc_id}/{filename}
        internal_url = f"http://rag-service:8200/api/artifacts/article_{article_id}/corpus/{doc_id}/{filename}"
        _LOGGER.info(f"Generated internal media URL for VLM: {internal_url}")
        
        # Build LLM
        llm = build_chat_llm(task_name="ingest_vlm")
        
        prompt_text = ""
        content_payload = []
        
        if media_type == "video":
            prompt_text = """请观看这段视频并返回 JSON 格式分析：
{
  "summary": "视频摘要（200-300字）：包含主要事件、人物动作、关键视觉信息",
  "transcription": "（可选）如果视频有对话，请简要概括对话内容",
  "technical_details": "视频中的任何技术细节、图表或演示内容的说明"
}
仅返回 JSON。"""
            content_payload = [
                {"type": "text", "text": prompt_text},
                {"type": "video_url", "video_url": {"url": internal_url}},
            ]
        elif media_type == "audio":
             prompt_text = """请收听这段音频并返回 JSON 格式分析：
{
  "summary": "音频摘要（200-300字）：包含主要话题、结论",
  "transcription": "详细的音频内容转录或要点总结",
  "speakers": "区分不同的说话人（如有）"
}
仅返回 JSON。"""
             content_payload = [
                {"type": "text", "text": prompt_text},
                {"type": "audio_url", "audio_url": {"url": internal_url}},
            ]
            
        message = HumanMessage(content=content_payload)
        
        # Invoke
        _LOGGER.info(f"Calling VLM for {media_type} analysis...")
        response = await llm.ainvoke([message])
        result = extract_text_content(response)
        
        # Parse JSON
        import re
        import json
        code_block_pattern = r'```(?:json)?\s*(\{[\s\S]*?\})\s*```'
        code_matches = re.findall(code_block_pattern, result)
        
        final_json = result
        if code_matches:
             final_json = code_matches[0]
        else:
            # Try finding first { and last }
            start = result.find('{')
            end = result.rfind('}')
            if start != -1 and end != -1:
                final_json = result[start:end+1]
        
        return final_json
        
    except Exception as e:
        _LOGGER.error(f"VLM Media Analysis failed: {e}")
        return json.dumps({"description": f"Analysis failed: {str(e)}", "summary": "Analysis failed"})
