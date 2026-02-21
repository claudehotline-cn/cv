import sys
import agent_core
import agent_core.decorators
print(f"sys.path: {sys.path}")
try:
    print(f"agent_core: {agent_core.__file__}")
    print(f"decorators: {agent_core.decorators.__file__}")
except Exception as e:
    print(f"Error: {e}")
