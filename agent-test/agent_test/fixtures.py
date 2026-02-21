import pytest
import os
from langgraph.checkpoint.memory import InMemorySaver

@pytest.fixture
def memory_saver():
    """
    Fixture to provide a fresh InMemorySaver for each test.
    """
    return InMemorySaver()

@pytest.fixture(scope="module")
def vcr_config():
    """
    Configure pytest-recording (VCR.py).
    Masks sensitive headers.
    """
    return {
        "filter_headers": [
            ("authorization", "XXXX"),
            ("x-api-key", "XXXX"),
            ("openai-api-key", "XXXX"),
            ("anthropic-api-key", "XXXX"),
        ],
        "filter_query_parameters": [
            ("api_key", "XXXX"),
            ("key", "XXXX"),
        ],
    }
