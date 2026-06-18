"""
Agent 状态定义
"""
from typing import Annotated, Any, TypedDict
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list[Any], add_messages]
    target: str
    target_type: str
    issues: list[dict]
    llm_review_text: str
    diff_content: str       # git diff 文本
    diff_summary: str       # git diff 摘要
    current_file: str
    files_processed: list[str]
    fixed_code: str
    original_code: str
    backup_path: str
    fix_instruction: str
    score: float
    memory_summary: str
    done: bool
    error: str
