import typer
import os
import shutil
from pathlib import Path
from typing import Optional
from typing_extensions import Annotated
from rich.console import Console
from rich.panel import Panel
from jinja2 import Environment, FileSystemLoader

app = typer.Typer(help="Agent Platform CLI - Scaffolding and Management Tool")
console = Console()

TEMPLATE_DIR = Path(__file__).parent / "templates"

def _render_template(template_name: str, context: dict, output_path: Path):
    """Render a directory of templates to an output path."""
    src_dir = TEMPLATE_DIR / template_name
    if not src_dir.exists():
        console.print(f"[bold red]Error:[/bold red] Template '{template_name}' not found at {src_dir}")
        raise typer.Exit(code=1)

    # Initialize Jinja2 environment
    env = Environment(loader=FileSystemLoader(str(src_dir)))

    for root, dirs, files in os.walk(src_dir):
        rel_root = Path(root).relative_to(src_dir)
        target_root = output_path / rel_root
        
        # Create directories
        target_root.mkdir(parents=True, exist_ok=True)
        
        for file in files:
            if file.endswith(".pyc") or file == "__pycache__":
                continue
                
            # Handle template files
            if file.endswith(".j2"):
                target_filename = file[:-3] # remove .j2
                template = env.get_template(str(rel_root / file))
                content = template.render(**context)
                
                target_file = target_root / target_filename
                target_file.write_text(content, encoding="utf-8")
                console.print(f"  Created: {target_file.relative_to(output_path.parent)}")
            else:
                # Copy static files directly
                shutil.copy2(root + "/" + file, target_root / file)
                console.print(f"  Copied: {target_root.relative_to(output_path.parent)}/{file}")


@app.command()
def create(
    name: Annotated[str, typer.Argument(help="Name of the agent (e.g., marketing_agent)")],
    type: Annotated[str, typer.Option(help="Type of agent template [basic|react|deep]")] = "basic",
    output_dir: Annotated[str, typer.Option(help="Output directory for plugins")] = "./agent-plugins"
):
    """
    Create a new agent plugin from a template.
    """
    # Normalize naming
    agent_key = name.lower().replace("-", "_")
    class_name = "".join(x.title() for x in agent_key.split("_"))
    
    output_path = Path(output_dir) / agent_key
    
    if output_path.exists():
        console.print(f"[bold red]Error:[/bold red] Directory {output_path} already exists.")
        raise typer.Exit(code=1)
        
    console.print(Panel(f"[bold blue]Creating Agent Plugin[/bold blue]\nName: {name}\nType: {type}\nPath: {output_path}"))
    
    context = {
        "agent_name": name,
        "agent_key": agent_key,
        "class_name": class_name,
        "agent_description": f"{name} created via Agent CLI"
    }
    
    try:
        _render_template(type, context, output_path)
        console.print(f"\n[bold green]Success![/bold green] Agent created at {output_path}")
        console.print(f"Next steps:\n  cd {output_path}\n  # Edit graph.py to define your workflow")
    except Exception as e:
        console.print(f"[bold red]Failed to create agent:[/bold red] {e}")
        # cleanup
        if output_path.exists():
            shutil.rmtree(output_path)
        raise typer.Exit(code=1)

@app.command()
def add(
    component: Annotated[str, typer.Argument(help="Component type [tool|skill]")],
    name: Annotated[str, typer.Argument(help="Name of the component")],
    agent_dir: Annotated[str, typer.Option(help="Path to agent directory")] = "."
):
    """
    Add a component (tool, skill) to an existing agent.
    """
    agent_path = Path(agent_dir).resolve()
    if not (agent_path / "agent.py").exists():
        console.print(f"[bold red]Error:[/bold red] {agent_path} does not look like a valid agent directory (missing agent.py)")
        raise typer.Exit(code=1)
        
    name_clean = name.lower().replace("-", "_")
    
    if component == "tool":
        tools_dir = agent_path / "tools"
        tools_dir.mkdir(exist_ok=True)
        
        target_file = tools_dir / f"{name_clean}.py"
        if target_file.exists():
            console.print(f"[bold red]Error:[/bold red] Tool {target_file} already exists.")
            raise typer.Exit(code=1)
            
        template_path = TEMPLATE_DIR / "components/tool/tool.py.j2"
        if not template_path.exists():
             console.print(f"[bold red]Error:[/bold red] Tool template not found at {template_path}")
             raise typer.Exit(code=1)
             
        env = Environment(loader=FileSystemLoader(str(template_path.parent)))
        template = env.get_template(template_path.name)
        content = template.render(tool_name=name_clean, tool_description=f"Tool {name} created via CLI")
        
        target_file.write_text(content, encoding="utf-8")
        console.print(f"[bold green]Success![/bold green] Created tool: {target_file.relative_to(agent_path)}")
        console.print(f"Remember to export it in {tools_dir / '__init__.py'}")
        
    elif component == "skill":
        console.print("[yellow]Skill generation not yet implemented[/yellow]")
    else:
        console.print(f"[bold red]Error:[/bold red] Unknown component type: {component}")
        raise typer.Exit(code=1)

@app.command()
def check(
    agent_dir: Annotated[str, typer.Argument(help="Path to agent directory")] = "."
):
    """
    Validate agent structure and configuration.
    """
    agent_path = Path(agent_dir).resolve()
    console.print(Panel(f"[bold blue]Checking Agent Plugin[/bold blue]\nPath: {agent_path}"))
    
    # 1. Structural Checks
    required_files = ["__init__.py", "agent.py", "config.py", "graph.py"]
    missing = [f for f in required_files if not (agent_path / f).exists()]
    
    if missing:
        console.print(f"[bold red]FAIL:[/bold red] Missing required files: {', '.join(missing)}")
        raise typer.Exit(code=1)
        
    console.print("[green]PASS:[/green] Directory structure is valid")
    
    # 2. Logic Checks (Import)
    try:
        import sys
        sys.path.insert(0, str(agent_path.parent))
        
        module_name = agent_path.name
        agent_module = __import__(module_name, fromlist=["*"])
        
        # Check Agent Class
        agent_class = None
        from agent_core.base import BaseAgent
        
        for attr_name in dir(agent_module):
            attr = getattr(agent_module, attr_name)
            if isinstance(attr, type) and issubclass(attr, BaseAgent) and attr is not BaseAgent:
                agent_class = attr
                break
                
        if not agent_class:
            console.print(f"[bold red]FAIL:[/bold red] No BaseAgent subclass found in {module_name}")
            raise typer.Exit(code=1)
            
        console.print(f"[green]PASS:[/green] Found Agent class: {agent_class.__name__}")
        
        # Check Graph Compilation
        try:
            agent = agent_class()
            graph = agent.get_graph()
            console.print("[green]PASS:[/green] Graph compiled successfully")
        except Exception as e:
            console.print(f"[bold red]FAIL:[/bold red] Graph compilation failed: {e}")
            raise typer.Exit(code=1)
            
        console.print("\n[bold green]All checks passed![/bold green]")
        
    except Exception as e:
        console.print(f"[bold red]FAIL:[/bold red] Import/Runtime check failed: {e}")
        raise typer.Exit(code=1)

@app.command()
def test(
    agent_dir: Annotated[str, typer.Argument(help="Path to agent directory")] = ".",
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Run interactive chat")
):
    """
    Test the agent (dry run or interactive).
    """
    if not interactive:
        # Run pytest
        import subprocess
        agent_path = Path(agent_dir).resolve()
        tests_dir = agent_path / "tests"
        if not tests_dir.exists():
             console.print(f"[bold red]Error:[/bold red] Tests directory not found at {tests_dir}")
             raise typer.Exit(code=1)
             
        try:
             console.print(f"[bold blue]Running Tests:[/bold blue] {tests_dir}")
             # Ensure current project root is in PYTHONPATH so agent-test and agent-plugins can be found
             env = os.environ.copy()
             root_dir = Path.cwd()
             pythonpath = env.get("PYTHONPATH", "")
             # Add current dir, agent-test, agent-core, and agent-plugins parent
             # Assuming we run from project root:
             # agent-test is at ./agent-test
             # agent-core is at ./agent-core
             # agent-plugins is at ./agent-plugins
             paths_to_add = [
                 str(root_dir / "agent-test"),
                 str(root_dir / "agent-core"),
                 str(root_dir / "agent-plugins"),
                 str(root_dir)
             ]
             env["PYTHONPATH"] = ":".join(paths_to_add) + ":" + pythonpath
             
             subprocess.run(["pytest", str(tests_dir)], check=True, env=env)
        except subprocess.CalledProcessError:
             console.print("[bold red]Tests Failed[/bold red]")
             raise typer.Exit(code=1)
        return

    agent_path = Path(agent_dir).resolve()
    import sys
    sys.path.insert(0, str(agent_path.parent))
    
    try:
        module_name = agent_path.name
        agent_module = __import__(module_name, fromlist=["*"])
        
        # Find Agent Class (simplified logic from check)
        from agent_core.base import BaseAgent
        agent_class = next(
            (attr for attr in (getattr(agent_module, n) for n in dir(agent_module)) 
             if isinstance(attr, type) and issubclass(attr, BaseAgent) and attr is not BaseAgent), 
            None
        )
        
        if not agent_class:
            console.print("[bold red]Error:[/bold red] Agent class not found")
            raise typer.Exit(code=1)
            
        agent = agent_class()
        graph = agent.get_graph()
        
        console.print(Panel(f"[bold green]Starting Interactive Session[/bold green]\nAgent: {agent_class.__name__}\nType 'exit' to quit."))
        
        import asyncio
        async def run_chat():
            config = {"configurable": {"thread_id": "cli-test"}}
            while True:
                user_input = console.input("[bold blue]You:[/bold blue] ")
                if user_input.lower() in ("exit", "quit"):
                    break
                    
                inputs = {"messages": [("user", user_input)]}
                console.print("[dim]Thinking...[/dim]")
                
                async for event in graph.astream(inputs, config=config):
                    # Simple output handling
                    for key, value in event.items():
                        if key == "messages":
                            # LangGraph may yield partial updates or final state
                            pass
                        elif isinstance(value, dict) and "messages" in value:
                            # Node output
                            last_msg = value["messages"][-1]
                            console.print(f"[bold green]Agent:[/bold green] {last_msg.content}")

        asyncio.run(run_chat())

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
