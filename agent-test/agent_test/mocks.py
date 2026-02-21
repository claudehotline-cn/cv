from typing import List, Union, Iterator
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

def mock_chat_model(responses: List[Union[str, BaseMessage]]) -> GenericFakeChatModel:
    """
    Create a GenericFakeChatModel that returns a sequence of responses.
    
    Args:
        responses: List of strings or AIMessages to return in order.
    
    Returns:
        GenericFakeChatModel: A fake chat model for testing.
    """
    processed_responses = []
    for resp in responses:
        if isinstance(resp, str):
            processed_responses.append(AIMessage(content=resp))
        else:
            processed_responses.append(resp)
            
    return GenericFakeChatModel(messages=iter(processed_responses))
