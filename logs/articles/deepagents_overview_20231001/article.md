# Deep Agents overview

Deep agents is a standalone library for building agents that can tackle complex, multi-step tasks. Built on LangGraph and inspired by applications like Claude Code, Deep Research, and Manus, deep agents come with planning capabilities, file systems for context management, and the ability to spawn subagents.

## When to use deep agents

Use deep agents when you need agents that can:
- Handle complex, multi-step tasks that require planning and decomposition
- Manage large amounts of context through file system tools
- Delegate work to specialized subagents for context isolation
- Persist memory across conversations and threads

For simpler use cases, consider using LangChain’s `create_agent` or building a custom `LangGraph` workflow.

## Core capabilities

### Planning and task decomposition
Deep agents include a built-in `write_todos` tool that enables agents to break down complex tasks into discrete steps, track progress, and adapt plans as new information emerges.

### Context management
File system tools (`ls`, `read_file`, `write_file`, `edit_file`) allow agents to offload large context to memory, preventing context window overflow and enabling work with variable-length tool results.

### Subagent spawning
A built-in `task` tool enables agents to spawn specialized subagents for context isolation and task delegation.

![Light Logo](https://mintcdn.com/langchain-5e9cc07a/Xbr8HuVd9jPi6qTU/images/brand/langchain-docs-teal.svg?fit=max&auto=format&n=Xbr8HuVd9jPi6qTU&q=85&s=16111530672bf976cb54ef2143478342)

![Dark Logo](https://mintcdn.com/langchain-5e9cc07a/Xbr8HuVd9jPi6qTU/images/brand/langchain-docs-lilac.svg?fit=max&auto=format&n=Xbr8HuVd9jPi6qTU&q=85&s=b70fb1a2208670492ef94aef14b680be)