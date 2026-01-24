from typing import Optional, Type, Any
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

class SideEffectInput(BaseModel):
    dry_run: bool = Field(
        default=False, 
        description="If True, verify parameters and return predicted impact without executing actions."
    )

class BaseSideEffectTool(BaseTool):
    """
    Base class for tools that have side effects (Delete, Write, Execute).
    Enforces 'dry_run' support.
    """
    
    def _run(self, *args: Any, **kwargs: Any) -> Any:
        # Pre-process dry_run
        dry_run = kwargs.pop("dry_run", False)
        
        if dry_run:
            return self._dry_run(*args, **kwargs)
            
        return self._execute(*args, **kwargs)
        
    def _dry_run(self, *args: Any, **kwargs: Any) -> str:
        """
        Return a description of what WOULD happen.
        Must be implemented by subclasses.
        """
        raise NotImplementedError("Tool must implement _dry_run logic")
        
    def _execute(self, *args: Any, **kwargs: Any) -> Any:
        """
        Perform actual execution.
        Must be implemented by subclasses.
        """
        raise NotImplementedError("Tool must implement _execute logic")
