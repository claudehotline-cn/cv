Skip to main content
🚀
Share how you're building agents
for a chance to win LangChain swag!
Docs by LangChain
home page
LangChain + LangGraph
Search...
⌘
K
Ask AI
GitHub
Try LangSmith
Try LangSmith
Search...
Navigation
Deep Agents overview
LangChain
LangGraph
Deep Agents
Integrations
Learn
Reference
Contribute
Python
Overview
Get started
Quickstart
Customization
Core capabilities
Agent harness
Backends
Subagents
Human-in-the-loop
Long-term memory
Middleware
Command line interface
Use the CLI
On this page
When to use deep agents
Core capabilities
Relationship to the LangChain ecosystem
Get started
Deep Agents overview
Copy page
Build agents that can plan, use subagents, and leverage file systems for complex tasks
Copy page
deepagents
is a standalone library for building agents that can tackle complex, multi-step tasks. Built on LangGraph and inspired by applications like Claude Code, Deep Research, and Manus, deep agents come with planning capabilities, file systems for context management, and the ability to spawn subagents.
​
When to use deep agents
Use deep agents when you need agents that can:
Handle complex, multi-step tasks
that require planning and decomposition
Manage large amounts of context
through file system tools
Delegate work
to specialized subagents for context isolation
Persist memory
across conversations and threads
For simpler use cases, consider using LangChain’s
create_agent
or building a custom
LangGraph
workflow.
​
Core capabilities
Planning and task decomposition
Deep agents include a built-in
write_todos
tool that enables agents to break down complex tasks into discrete steps, track progress, and adapt plans as new information emerges.
Context management
File system tools (
ls
,
read_file
,
write_file
,
edit_file
) allow agents to offload large context to memory, preventing context window overflow and enabling work with variable-length tool results.
Subagent spawning
A built-in
task
tool enables agents to spawn specialized subagents for context isolation. This keeps the main agent’s context clean while still going deep on specific subtasks.
Long-term memory
Extend agents with persistent memory across threads using LangGraph’s Store. Agents can save and retrieve information from previous conversations.
​
Relationship to the LangChain ecosystem
Deep agents is built on top of:
LangGraph
- Provides the underlying graph execution and state management
LangChain
- Tools and model integrations work seamlessly with deep agents
LangSmith
- Observability, evaluation, and deployment
Deep agents applications can be deployed via
LangSmith Deployment
and monitored with
LangSmith Observability
.
​
Get started
Quickstart
Build your first deep agent
Customization
Learn about customization options
Middleware
Understand the middleware architecture
Reference
See the
deepagents
API reference
Edit the source of this page on GitHub.
Connect these docs programmatically
to Claude, VSCode, and more via MCP for real-time answers.
Was this page helpful?