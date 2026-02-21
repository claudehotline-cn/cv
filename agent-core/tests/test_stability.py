import pytest
from pydantic import BaseModel, Field
from typing import Optional, Type
from agent_core.tool_patterns import BaseSideEffectTool, SideEffectInput

# Define a Concrete SideEffect Tool
class FileDeleteInput(SideEffectInput):
    path: str = Field(description="File to delete")

class FileDeleteTool(BaseSideEffectTool):
    name: str = "delete_file"
    description: str = "Deletes a file."
    args_schema: Type[BaseModel] = FileDeleteInput
    
    def _dry_run(self, path: str) -> str:
        return f"[DRY RUN] Would delete file: {path}"
        
    def _execute(self, path: str) -> str:
        return f"File deleted: {path}"

def test_dry_run_execution():
    """Test that dry_run=True invokes _dry_run."""
    tool = FileDeleteTool()
    
    # 1. Dry Run
    result = tool.invoke({"path": "/tmp/a.txt", "dry_run": True})
    assert "Would delete" in result
    
    # 2. Real Execution
    result = tool.invoke({"path": "/tmp/a.txt", "dry_run": False})
    assert "File deleted" in result
    
    # 3. Default (False)
    result = tool.invoke({"path": "/tmp/a.txt"})
    assert "File deleted" in result
