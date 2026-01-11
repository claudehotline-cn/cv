"""
Pydantic schemas for structured output of all agent tools.
Ensures consistent JSON format for frontend parsing.
"""
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


# ============================================================================
# SQL Tool Output Schema
# ============================================================================
class SQLResultSchema(BaseModel):
    """Structured output for SQL query results."""
    success: bool = Field(description="Whether query succeeded")
    columns: List[str] = Field(default=[], description="Column names")
    rows: List[List[Any]] = Field(default=[], description="Query result rows (first 50)")
    total_rows: int = Field(default=0, description="Total number of rows returned")
    error: Optional[str] = Field(default=None, description="Error message if query failed")
    suggestion: Optional[str] = Field(default=None, description="Suggestion for fixing errors")


# ============================================================================
# Python Execute Tool Output Schema
# ============================================================================
class PythonResultSchema(BaseModel):
    """Structured output for Python code execution."""
    success: bool = Field(description="Whether execution succeeded")
    stdout: str = Field(default="", description="Standard output from execution")
    stderr: str = Field(default="", description="Standard error from execution")
    result_type: Optional[str] = Field(default=None, description="Type of result variable (e.g., DataFrame)")
    result_shape: Optional[str] = Field(default=None, description="Shape of result if DataFrame")
    result_columns: Optional[List[str]] = Field(default=None, description="Columns of result if DataFrame")
    result_preview: Optional[List[Dict[str, Any]]] = Field(default=None, description="Preview of result data (first rows)")
    saved_chart: Optional[str] = Field(default=None, description="Path to saved chart JSON file")
    saved_dataframes: Optional[List[str]] = Field(default=None, description="Paths to saved DataFrame files")
    error: Optional[str] = Field(default=None, description="Error message if execution failed")
    suggestion: Optional[str] = Field(default=None, description="Suggestion for fixing errors")
    note: Optional[str] = Field(default=None, description="Additional notes")


# ============================================================================
# Chart Tool Output Schema
# ============================================================================
class ChartResultSchema(BaseModel):
    """Structured output for ECharts chart generation."""
    success: bool = Field(default=True, description="Whether chart generation succeeded")
    chart_type: str = Field(description="Type of chart (line, bar, pie, heatmap)")
    title: str = Field(description="Chart title")
    option: Dict[str, Any] = Field(description="Complete ECharts option configuration")
    error: Optional[str] = Field(default=None, description="Error message if generation failed")
    suggestion: Optional[str] = Field(default=None, description="Suggestion for fixing errors")


# ============================================================================
# Validation Tool Output Schema
# ============================================================================
class ValidationResultSchema(BaseModel):
    """Structured output for data validation."""
    valid: bool = Field(description="Whether data is valid for visualization")
    data_source: str = Field(description="Name of the validated DataFrame")
    row_count: int = Field(default=0, description="Number of rows in data")
    columns: List[str] = Field(default=[], description="Column names")
    warnings: List[str] = Field(default=[], description="Validation warnings (non-critical)")
    error: Optional[str] = Field(default=None, description="Error message if validation failed")
    suggestion: Optional[str] = Field(default=None, description="Suggestion for fixing issues")


# ============================================================================
# Main Agent Output Schema
# ============================================================================
class MainAgentOutput(BaseModel):
    """Structured output for the Main Agent's final response."""
    summary: str = Field(description="给用户的最终总结（可读文本）")
    actions: List[str] = Field(default=[], description="下一步可执行动作列表")
    confidence: str = Field(description="主结论把握度 (low/medium/high)")
    citations: Optional[List[str]] = Field(default=None, description="引用/证据来源（可选）")
    chart: Optional[Dict[str, Any]] = Field(default=None, description="ECharts 图表配置 (可选)")

    def __str__(self):
        """Override string representation to return valid JSON.
        This ensures LangGraph streams valid JSON instead of Python object repr.
        """
        try:
            return self.model_dump_json(exclude_none=True)
        except Exception:
            return super().__str__()

