
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'agent-plugins/data_agent/src'))

try:
    from data_agent.agents.python import get_python_agent_graph
    from data_agent.agents.visualizer import get_visualizer_agent_graph
    from data_agent.graph import get_data_deep_agent_graph
    # Assuming report agent also exists or is part of data agent
    # from data_agent.agents.report import get_report_agent_graph 
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

def check_orphans():
    print("Checking for Orphan Nodes (Duplicate Node Names)...")
    
    # Get graphs
    try:
        py_graph = get_python_agent_graph()
        viz_graph = get_visualizer_agent_graph()
        # report_graph = get_report_agent_graph()
        
        # We can also check data agent composite graph
        data_graph = get_data_deep_agent_graph()
        
    except Exception as e:
        print(f"Error compiling graphs: {e}")
        # If compilation fails due to duplicate nodes, we catch it here mostly.
        sys.exit(1)

    print("Successfully imported agent graphs.")

    # Inspect nodes - access internal graph structure if possible, or just rely on compilation success
    # LangGraph raises ValueError on compile if duplicates exist in certain structures, 
    # but here we also want to verify the names are distinct manually if possible.
    
    py_nodes = set(py_graph.get_graph().nodes.keys())
    viz_nodes = set(viz_graph.get_graph().nodes.keys())
    
    print(f"Python Agent Nodes: {py_nodes}")
    print(f"Visualizer Agent Nodes: {viz_nodes}")
    
    # Check intersection (excluding common system nodes like '__start__', '__end__' if any)
    intersection = py_nodes.intersection(viz_nodes)
    reserved = {'__start__', '__end__'}
    duplicates = intersection - reserved
    
    if duplicates:
        print(f"FAIL: Duplicate node names found: {duplicates}")
        sys.exit(1)
    else:
        print("PASS: No duplicate node names found.")

if __name__ == "__main__":
    check_orphans()
