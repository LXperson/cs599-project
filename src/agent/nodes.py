"""
LangGraph 节点实现 - CodeSage Agent
"""

import logging
import re
from pathlib import Path

from langchain_core.messages import AIMessage

from src.agent.state import AgentState
from src.config.prompts import (
    FIX_BUG_PROMPT,
    GENERATE_TEST_PROMPT,
    INTERACTIVE_QUERY_PROMPT,
    REVIEW_DIFF_PROMPT,
)
from src.review.reviewer import Reviewer
from src.tools.file_reader import FileReader

logger = logging.getLogger("codesage")


# ============================================================
# 节点 1: 解析输入
# ============================================================

def parse_input_node(state: AgentState) -> dict:
    messages = state.get("messages", [])
    if not messages:
        return {"done": True, "error": "无输入消息。", "target_type": "unknown"}
    last_msg = messages[-1]
    content = last_msg.content.strip() if hasattr(last_msg, "content") else str(last_msg).strip()

    preset = state.get("target_type", "review_file")
    if preset not in ("", "review_file"):
        return {"target": content, "target_type": preset, "done": False, "error": ""}

    if content.lower().startswith(("fix", "修复")):
        target_type = "fix"
    elif content.lower().startswith(("test", "单测", "测试")):
        target_type = "test"
    elif "diff" in content.lower():
        target_type = "review_diff"
    elif "追问" in content or "question" in content.lower():
        target_type = "query"
    else:
        target_type = "review_file"

    return {"target": content, "target_type": target_type, "done": False, "error": ""}


# ============================================================
# 节点 2: 收集文件
# ============================================================

def collect_files_node(state: AgentState) -> dict:
    target_type = state.get("target_type", "review_file")
    target = state.get("target", "")

    if target_type in ("fix", "test"):
        parts = target.split(None, 1)
        file_target = parts[1] if len(parts) > 1 else ""
        if not file_target:
            return {"error": "请提供文件路径。例如: fix src/main.py", "done": True}
        try:
            result = FileReader.read_file(file_target)
            if result["success"]:
                return {"current_file": file_target, "files_processed": [file_target],
                        "target": file_target, "original_code": result["content"]}
            return {"error": result.get("error", "无法读取文件"), "done": True}
        except Exception as e:
            return {"error": str(e), "done": True}

    if target_type == "review_file":
        try:
            result = FileReader.read_file(target)
            if result["success"]:
                return {"current_file": target, "files_processed": [target]}
            return {"error": result.get("error", "无法读取文件"), "done": True}
        except Exception as e:
            return {"error": str(e), "done": True}

    if target_type == "review_diff":
        from src.tools.git_parser import GitParser
        repo_path = str(Path(target).resolve().parent) if target else "."
        if not GitParser.is_git_repo(repo_path):
            return {"error": f"不是 Git 仓库: {repo_path}。请在有 .git 的目录下使用 diff 命令。", "done": True}
        diff_result = GitParser.get_diff(repo_path)
        if diff_result["success"]:
            return {"current_file": "", "files_processed": [],
                    "diff_content": diff_result.get("diff", ""),
                    "diff_summary": diff_result.get("summary", "")}
        return {"error": diff_result.get("error", "无变更可审查"), "done": True}

    return {"done": True, "error": f"未知目标类型: {target_type}"}


# ============================================================
# 节点 3a: 审查单文件（供 CLI 逐文件调用）
# ============================================================

def review_file_node(state: AgentState) -> dict:
    current_file = state.get("current_file", "")
    if not current_file:
        return {"done": True, "error": "没有文件可审查。", "issues": [], "llm_review_text": ""}
    try:
        result = FileReader.read_file(current_file)
    except Exception as e:
        return _err(current_file, str(e), "critical")
    if not result["success"]:
        return _err(current_file, result.get("error", ""), "warning")

    code = result["content"]
    language = result["language"]
    reviewer = Reviewer()
    rule_issues = reviewer.rule_review(code, language, current_file)

    llm_text = ""
    if len(code) < 8000 and language not in ("unknown", "markdown", "json", "yaml"):
        try:
            llm_text, _ = reviewer.llm_review(code, language, current_file)
        except Exception:
            pass

    score = reviewer.calculate_score(rule_issues)
    return {"issues": _ser(rule_issues), "llm_review_text": llm_text,
            "score": score, "error": ""}


# ============================================================
# 节点 3d: Diff 审查
# ============================================================

def review_diff_node(state: AgentState) -> dict:
    """审查 Git diff 变更：LLM 深度分析 + 规则引擎辅助。"""
    diff_content = state.get("diff_content", "")
    diff_summary = state.get("diff_summary", "")

    if not diff_content.strip():
        return {"done": True, "error": "无实质变更可审查。",
                "issues": [], "llm_review_text": ""}

    reviewer = Reviewer()

    # LLM 审查 diff
    prompt = REVIEW_DIFF_PROMPT.format(
        summary=diff_summary, diff_content=diff_content[:8000],
    )
    try:
        llm_text, success = reviewer.call_llm_with_retry(prompt)
    except Exception as e:
        logger.error("Diff 审查 LLM 调用失败: %s", e)
        llm_text, success = f"LLM 调用失败: {e}", False

    # 对 diff 中涉及的文件执行规则审查（简易版）
    rules_issues: list = []
    changed_files = _extract_diff_files(diff_content)
    for file_path in changed_files[:5]:  # 最多审查 5 个变更文件
        try:
            r = FileReader.read_file(file_path)
            if r["success"]:
                parsed = reviewer.rule_review(r["content"], r["language"], file_path)
                rules_issues.extend(_ser(parsed))
        except Exception:
            pass

    # 计算评分
    score = 100.0
    for i in rules_issues:
        sev = i.get("severity", "")
        if sev == "critical":
            score -= 15
        elif sev == "warning":
            score -= 5
        elif sev == "suggestion":
            score -= 1
    score = max(0.0, min(100.0, score))

    return {"issues": rules_issues, "llm_review_text": llm_text,
            "score": score,
            "error": "" if success else "LLM 调用未完全成功。"}


def _extract_diff_files(diff_text: str) -> list[str]:
    """从 diff 文本中提取涉及的文件路径列表。"""
    files: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            f = line[6:].strip()
            if f != "/dev/null":
                files.append(f)
    return files


# ============================================================
# 节点 3b: Bug 修复（先备份，再写回）
# ============================================================

def fix_file_node(state: AgentState) -> dict:
    current_file = state.get("current_file", "")
    if not current_file:
        return {"done": True, "error": "请指定需要修复的文件。", "issues": [], "llm_review_text": ""}
    try:
        result = FileReader.read_file(current_file)
    except Exception as e:
        return {"done": True, "error": str(e), "issues": [], "llm_review_text": ""}
    if not result["success"]:
        return {"done": True, "error": result.get("error", "读取失败"),
                "issues": [], "llm_review_text": ""}

    code = result["content"]
    language = result["language"]
    reviewer = Reviewer()

    rule_issues = reviewer.rule_review(code, language, current_file)
    issue_descriptions = "\n".join(
        f"- [{i.severity.value.upper()}] {i.rule_id}: {i.description}"
        for i in rule_issues[:10]) or "无规则引擎发现的问题"

    # 自然语言指令注入
    instruction = state.get("fix_instruction", "")
    if instruction:
        issue_descriptions = f"【用户指令】{instruction}\n\n{issue_descriptions}"

    prompt = FIX_BUG_PROMPT.format(
        file_path=current_file, language=language,
        issue_description=issue_descriptions, code=code,
    )

    try:
        llm_text, success = reviewer.call_llm_with_retry(prompt)
    except Exception as e:
        logger.error("Bug 修复 LLM 调用失败: %s", e)
        llm_text, success = f"LLM 调用失败: {e}", False

    fixed_code = _extract_code(llm_text, language)

    # 先备份原文件
    backup_result = FileReader.backup_file(current_file)
    backup_path = backup_result.get("backup_path", "") if backup_result["success"] else ""

    # 写回修复代码
    write_result = None
    if success and fixed_code and len(fixed_code) > 20:
        write_result = FileReader.write_file(current_file, fixed_code)

    return {
        "issues": _ser(rule_issues),
        "llm_review_text": llm_text,
        "fixed_code": fixed_code or "",
        "original_code": state.get("original_code", code),
        "backup_path": backup_path,
        "score": reviewer.calculate_score(rule_issues),
        "error": "" if success else "LLM 调用未完全成功。",
        "_write_result": write_result,
    }


# ============================================================
# 节点 3c: 单测生成
# ============================================================

def test_file_node(state: AgentState) -> dict:
    current_file = state.get("current_file", "")
    if not current_file:
        return {"done": True, "error": "请指定文件。", "issues": [], "llm_review_text": ""}
    try:
        result = FileReader.read_file(current_file)
    except Exception as e:
        return {"done": True, "error": str(e), "issues": [], "llm_review_text": ""}
    if not result["success"]:
        return {"done": True, "error": result.get("error", "读取失败"),
                "issues": [], "llm_review_text": ""}

    code = result["content"]
    language = result["language"]
    prompt = GENERATE_TEST_PROMPT.format(
        file_path=current_file, language=language, code=code)
    reviewer = Reviewer()
    try:
        llm_text, success = reviewer.call_llm_with_retry(prompt)
    except Exception as e:
        llm_text, success = f"LLM 调用失败: {e}", False

    test_code = _extract_code(llm_text, language)
    write_result = None
    test_file_path = ""
    if test_code and len(test_code) > 20:
        src_path = Path(current_file).resolve()
        stem, suffix = src_path.stem, src_path.suffix
        if language == "python":
            test_file_path = str(src_path.parent / f"test_{stem}{suffix}")
        else:
            test_file_path = str(src_path.parent / f"{stem}.test{suffix}")
        write_result = FileReader.write_file(test_file_path, test_code)

    return {"issues": [], "llm_review_text": llm_text, "score": 100.0,
            "error": "" if success else "LLM 调用未完全成功。",
            "_test_write_result": write_result, "_test_file_path": test_file_path}


# ============================================================
# 节点 4: 生成报告
# ============================================================

def generate_report_node(state: AgentState) -> dict:
    issues_data = state.get("issues", [])
    files = state.get("files_processed", [])
    error_msg = state.get("error", "")
    llm_text = state.get("llm_review_text", "")
    score = state.get("score", 100.0)
    target_type = state.get("target_type", "review_file")
    write_result = state.get("_write_result")
    test_write = state.get("_test_write_result")
    test_path = state.get("_test_file_path", "")
    backup_path = state.get("backup_path", "")

    labels = {
        "fix": ("# CodeSage — Bug 修复报告\n", "## 🤖 AI 修复建议"),
        "test": ("# CodeSage — 单元测试生成报告\n", "## 🧪 生成的测试代码"),
        "review_file": ("# CodeSage 代码审查报告\n", "## 🤖 AI 深度分析"),
        "review_dir": ("# CodeSage 代码审查报告\n", "## 🤖 AI 深度分析"),
        "review_diff": ("# CodeSage 代码审查报告\n", "## 🤖 AI 深度分析"),
    }
    header, ai_label = labels.get(target_type, ("# CodeSage 报告\n", "## 🤖 AI 分析"))

    lines = [header,
             f"## 📊 概览",
             f"- 处理文件数: {len(files) if files else 1}",
             f"- 问题总数: {len(issues_data)}",
             f"- **综合评分: {score:.1f}/100**\n"]

    crit = sum(1 for i in issues_data if i.get("severity") == "critical")
    warn = sum(1 for i in issues_data if i.get("severity") == "warning")
    sugg = sum(1 for i in issues_data if i.get("severity") == "suggestion")
    lines.append("| 级别 | 数量 |")
    lines.append("|------|------|")
    lines.append(f"| 🔴 严重 | {crit} |")
    lines.append(f"| 🟡 警告 | {warn} |")
    lines.append(f"| 🔵 建议 | {sugg} |\n")

    if error_msg:
        lines.append(f"> ⚠️ {error_msg}\n")

    if target_type == "fix" and write_result:
        status = "已写入" if write_result["success"] else "写入失败"
        lines.append(f"> ✅ **文件{status}**：`{files[0] if files else '?'}`"
                     f" ({write_result.get('written_bytes',0)} bytes)\n")
        if backup_path:
            lines.append(f"> 💾 备份: `{backup_path}`\n")

    if target_type == "test" and test_write:
        status = "已生成" if test_write["success"] else "写入失败"
        lines.append(f"> ✅ **测试文件{status}**：`{test_path}`"
                     f" ({test_write.get('written_bytes',0)} bytes)\n")

    if target_type.startswith("review") and issues_data:
        lines.append("## 🔍 规则检查问题\n")
        sev_order = {"critical": 0, "warning": 1, "suggestion": 2}
        sorted_issues = sorted(
            issues_data,
            key=lambda i: sev_order.get(i.get("severity", "suggestion"), 2))
        emoji_map = {"critical": "🔴", "warning": "🟡", "suggestion": "🔵"}
        for issue in sorted_issues:
            sev = issue.get("severity", "suggestion")
            e = emoji_map.get(sev, "⚪")
            li = f"L{issue['line']}" if issue.get("line") else "—"
            lines.append(
                f"- **{e} [{sev.upper()}]** `{issue.get('rule_id', '?')}` "
                f"— **{issue.get('title', '')}**\n"
                f"  - 📄 `{issue['file_path']}` ({li})\n"
                f"  - ❓ {issue.get('description', '')}\n"
                f"  - 💡 {issue.get('suggestion', '')}\n"
            )
    elif target_type.startswith("review") and not issues_data:
        lines.append("## ✅ 规则检查未发现问题。\n")

    if llm_text.strip():
        lines.append("\n---\n")
        lines.append(ai_label + "\n")
        lines.append(llm_text)

    return {"done": True, "messages": [AIMessage(content="\n".join(lines))]}


# ============================================================
# 节点 5: 交互追问
# ============================================================

def interactive_node(state: AgentState) -> dict:
    from src.config.settings import settings
    from langchain_openai import ChatOpenAI

    messages = state.get("messages", [])
    user_query = ""
    for m in reversed(messages):
        if hasattr(m, "type") and m.type == "human":
            user_query = m.content
            break
    issues = state.get("issues", [])
    review_context = ""
    if issues:
        categories = set(i.get("category", "") for i in issues)
        review_context = (f"之前审查发现 {len(issues)} 个问题，"
                          f"主要集中在: {', '.join(categories)} 方面。")
    prompt = INTERACTIVE_QUERY_PROMPT.format(
        user_query=user_query, review_context=review_context)
    try:
        llm = ChatOpenAI(
            model=settings.LLM_MODEL, api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL, temperature=0.3, max_tokens=1024)
        response = llm.invoke(prompt)
        return {"done": True, "messages": [AIMessage(content=response.content)]}
    except Exception as e:
        return {"done": True, "messages": [AIMessage(content=f"[LLM 调用失败] {e}")]}


# ============================================================
# 路由
# ============================================================

def should_continue(state: AgentState) -> str:
    if state.get("error"):
        return "generate_report"
    tt = state.get("target_type", "")
    if tt == "query":
        return "interactive"
    if tt == "fix":
        return "fix_file"
    if tt == "test":
        return "test_file"
    if tt in ("review_diff",):
        return "review_diff"
    return "review_file"


# ============================================================
# 辅助
# ============================================================

def _ser(issues: list) -> list[dict]:
    return [
        {"severity": i.severity.value, "category": i.category.value,
         "rule_id": i.rule_id, "file_path": i.file_path,
         "line": i.line, "title": i.title,
         "description": i.description, "suggestion": i.suggestion,
         "source": i.source}
        for i in issues
    ]


def _err(file_path: str, msg: str, severity: str) -> dict:
    return {"issues": [{"severity": severity, "category": "quality",
                        "rule_id": "IO-ERR", "file_path": file_path,
                        "line": None, "title": "文件读取失败",
                        "description": msg,
                        "suggestion": "请检查文件路径和权限。",
                        "source": "system"}],
            "llm_review_text": "", "error": ""}


def _extract_code(text: str, language: str) -> str:
    # 找 "修复后代码" / "📝" / "fixed code" 后的代码块
    for marker in [r"修复后[代码\s]*\n", r"#+\s*修复后",
                   r"Fixed\s+code", r"#+\s*Fixed",
                   r"修复后[的\s]*代码", r"📝"]:
        idx = re.search(marker, text, re.IGNORECASE)
        if idx:
            cm = re.search(r"```[\w]*\n(.*?)```", text[idx.end():], re.DOTALL)
            if cm:
                return cm.group(1).rstrip() + "\n"
    # 最后手段：取最后一个代码块
    blocks = re.findall(r"```[\w]*\n(.*?)```", text, re.DOTALL)
    return (blocks[-1].rstrip() + "\n") if blocks else ""
