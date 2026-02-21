from langchain_core.tools import tool

@tool
def my_tool(query: str) -> str:
    """Tool my-tool created via CLI"""
    # TODO: Implement tool logic
    return f"Executed my_tool with query: {query}"