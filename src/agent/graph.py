"""
LangGraph 状态图 - CodeSage Agent
"""

from langgraph.graph import END, StateGraph

from src.agent.nodes import (
    collect_files_node,
    fix_file_node,
    generate_report_node,
    interactive_node,
    parse_input_node,
    review_diff_node,
    review_file_node,
    should_continue,
    test_file_node,
)
from src.agent.state import AgentState


def build_graph() -> StateGraph:
    workflow = StateGraph(AgentState)

    workflow.add_node("parse_input", parse_input_node)
    workflow.add_node("collect_files", collect_files_node)
    workflow.add_node("review_file", review_file_node)
    workflow.add_node("review_diff", review_diff_node)
    workflow.add_node("fix_file", fix_file_node)
    workflow.add_node("test_file", test_file_node)
    workflow.add_node("generate_report", generate_report_node)
    workflow.add_node("interactive", interactive_node)

    workflow.set_entry_point("parse_input")
    workflow.add_edge("parse_input", "collect_files")

    workflow.add_conditional_edges(
        "collect_files",
        should_continue,
        {"review_file": "review_file",
         "review_diff": "review_diff",
         "fix_file": "fix_file",
         "test_file": "test_file",
         "interactive": "interactive",
         "generate_report": "generate_report"},
    )

    workflow.add_edge("review_file", "generate_report")
    workflow.add_edge("review_diff", "generate_report")
    workflow.add_edge("fix_file", "generate_report")
    workflow.add_edge("test_file", "generate_report")
    workflow.add_edge("generate_report", END)
    workflow.add_edge("interactive", END)

    return workflow.compile()


graph = build_graph()
