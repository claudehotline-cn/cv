
async def _describe_image_with_vlm(image_bytes: bytes) -> str:
    """Use VLM to generate a detailed description of the image."""
    try:
        # Build LLM (Settings will determine provider, e.g. Gemini/OpenAI)
        # Note: Ensure the model supports Vision! 
        # For simplicity, we assume the default M8/M12 model (Gemini) supports vision.
        llm = build_chat_llm(task_name="ingest_vlm")
        
        # Prepare content
        # LangChain standard for image support
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        
        message = HumanMessage(
            content=[
                {"type": "text", "text": "Please provide a detailed visual description of this image. Identify key elements, text, charts, or people suitable for use in an article."},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                },
            ]
        )
        
        # Invoke
        response = await llm.ainvoke([message])
        return extract_text_content(response)
        
    except Exception as e:
        _LOGGER.warning(f"Error in VLM call: {e}")
        return ""
