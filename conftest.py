import os
import sys


def _add_repo_packages_to_sys_path() -> None:
    """Make in-repo packages importable for pytest runs.

    This mirrors the container setup (see docker/agent-test/Dockerfile) where
    PYTHONPATH includes /workspace/agent-test, etc.
    """

    repo_root = os.path.dirname(__file__)
    agent_test_root = os.path.join(repo_root, "agent-test")
    if os.path.isdir(agent_test_root) and agent_test_root not in sys.path:
        sys.path.insert(0, agent_test_root)


_add_repo_packages_to_sys_path()

