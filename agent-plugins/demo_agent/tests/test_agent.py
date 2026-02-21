import pytest
from ..agent import DemoAgent

def test_agent_graph_compile():
    agent = DemoAgent()
    graph = agent.get_graph()
    assert graph is not None

def test_agent_config():
    agent = DemoAgent()
    config = agent.get_config()
    assert config["key"] == "demo_agent"