# Agent Development Guide

This guide covers the end-to-end workflow for developing, testing, and managing agents on the Agent Platform.

## 1. Agent CLI (`agent-cli`)

The `agent-cli` is your primary tool for scaffolding and managing agents.

### Installation
Ensure the `agent-cli` package is in your PYTHONPATH or installed.

```bash
# In development environment
export PYTHONPATH=$PYTHONPATH:$(pwd)/agent-cli
```

### Commands

#### Create a New Agent
Scaffold a new agent project structure.
```bash
python -m agent_cli.main create <agent_name> --type [basic|deep]
# Example
python -m agent_cli.main create my-agent
```

#### Add Components
Add tools or skills to an existing agent.
```bash
python -m agent_cli.main add tool <tool_name> --agent-dir agent-plugins/my_agent
```

#### Check Structure
Validate that your agent adheres to platform standards.
```bash
python -m agent_cli.main check agent-plugins/my_agent
```

#### Run Tests
Run the agent's test suite (using `agent-test`).
```bash
python -m agent_cli.main test agent-plugins/my_agent
```

#### Interactive Chat
Run a local interactive chat session for debugging.
```bash
python -m agent_cli.main test agent-plugins/my_agent --interactive
```

---

## 2. Test Framework (`agent-test`)

The `agent-test` package provides utilities for robust testing of LangGraph agents.

### Writing Tests

New agents created with `agent-cli` come with a pre-configured `tests/test_core.py`.

#### Unit Tests (Mocked)
Use `mock_chat_model` to simulate LLM responses without network calls.

```python
from agent_test import mock_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from my_agent.graph import get_graph

def test_basic_flow():
    # Mock LLM response
    model = mock_chat_model(["Hello world"]) 
    # Inject model into agent (if your agent supports injection) or just test graph logic
    
    checkpointer = InMemorySaver()
    graph = get_graph(checkpointer=checkpointer)
    
    result = graph.invoke(...)
    assert result["messages"][-1].content == "Hello world"
```

#### Integration Tests (Record & Replay)
Use standard `pytest` markers or VCR to record real interactions.

```bash
# Run tests
pytest
```

If configured with `pytest-recording`, network calls will be saved to cassettes.

### Evaluators
Use `evaluators` to assess agent performance.

```python
from agent_test.evaluators import get_trajectory_match_evaluator

def test_trajectory():
    evaluator = get_trajectory_match_evaluator(mode="strict")
    # compare output vs reference...
```

---

## 3. Directory Structure

Standard agent structure:

```
agent-plugins/
  my_agent/
    __init__.py
    agent.py       # Main entry point (extends BaseAgent)
    config.py      # Configuration
    graph.py       # LangGraph definition
    tools/         # Tool definitions
    tests/         # Tests
```
