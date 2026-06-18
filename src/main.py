"""
CodeSage — 智能代码工程师 Agent (Claude Code Style CLI)

核心能力：
  review  - 代码审查（规则引擎 + LLM 双引擎）
  fix     - Bug 分析 → LLM 修复 → 自动写回源文件
  test    - LLM 生成高质量单元测试
  diff    - Git 变更审查
  interactive - 交互式 REPL（支持模糊路径、文件操作）
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Sequence

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.rule import Rule
from langchain_core.messages import HumanMessage

console = Console()

# ============================================================
# 启动横幅
# ============================================================

BANNER = r"""[bold cyan]╔══════════════════════════════════════════════════╗[/]
[bold cyan]║[/]  [bold white on cyan] CodeSage [/]  [dim]|[/]  [white]智能代码工程师 Agent[/]     [bold cyan]║[/]
[bold cyan]╠══════════════════════════════════════════════════╣[/]
[bold cyan]║[/]  [dim]review · fix · test · diff · interactive[/]         [bold cyan]║[/]
[bold cyan]║[/]  [dim]CS599 企业级应用软件设计与开发 · 期末项目[/]        [bold cyan]║[/]
[bold cyan]╚══════════════════════════════════════════════════╝[/]"""


def print_banner() -> None:
    console.print()
    console.print(BANNER)
    cwd = os.getcwd()
    console.print(f"[dim]版本 v1.1.0  |  LangGraph  |  DeepSeek LLM[/dim]")
    console.print(f"[dim]工作目录: [bright_black]{cwd}[/][/dim]")
    console.print(Rule(style="cyan"))
    console.print()


def print_help_panel() -> None:
    print_banner()
    console.print("[bold white]用法[/]: [cyan]codesage[/] <命令> [选项]\n")
    console.print("[dim]CodeSage 是一个 AI 驱动的软件工程师 Agent，[/dim]")
    console.print("[dim]提供 代码审查 · Bug 修复 · 单元测试生成 三大核心能力。[/dim]")
    console.print()

    cmd_table = Table(show_header=True, header_style="bold white", border_style="dim",
                      padding=(1, 2), expand=False, box=None)
    cmd_table.add_column("命令", style="bold cyan", width=14, no_wrap=True)
    cmd_table.add_column("别名", style="dim", width=6, no_wrap=True)
    cmd_table.add_column("说明", style="white")

    for cmd, alias, desc in [
        ("review", "r",   "审查单个文件或整个目录"),
        ("fix",    "",    "分析 Bug → LLM 修复 → [green]自动写回文件[/]"),
        ("test",   "",    "为文件生成单元测试"),
        ("diff",   "d",   "审查当前 Git 仓库变更"),
        ("interactive", "i", "交互式 REPL (支持模糊路径)"),
        ("rules",  "",    "列出所有内建审查规则"),
        ("version","v",   "显示版本信息"),
    ]:
        alias_str = f"[dim]{alias}[/]" if alias else ""
        cmd_table.add_row(cmd, alias_str, desc)

    console.print("[bold white]可用命令[/]")
    console.print(cmd_table)
    console.print()

    ex_table = Table(show_header=False, border_style="dim", padding=(0, 2),
                     expand=False, box=None)
    ex_table.add_column("", style="dim")
    ex_table.add_column("")

    for row in [
        "$ [cyan]codesage review[/] [white]src/main.py[/]         # 审查文件",
        "$ [cyan]codesage review[/] [white]src/ -o report.md[/]   # 审查目录并导出",
        "$ [cyan]codesage fix[/] [white]src/buggy.py[/]           # 修复 Bug → 写回文件",
        "$ [cyan]codesage test[/] [white]src/utils.py[/]          # 生成单测",
        "$ [cyan]codesage diff[/]                                 # 审查 Git 变更",
        "$ [cyan]codesage interactive[/]                          # 交互模式",
        "$ [cyan]python src/main.py review[/] [white]test.py[/]   # 直接运行",
    ]:
        ex_table.add_row("", row)

    console.print("[bold white]使用示例[/]")
    console.print(ex_table)
    console.print()

    install_box = Panel(
        "[dim]首次使用请先配置 API Key：\n"
        "  1. cp .env.example .env\n"
        "  2. 编辑 .env 填入 DEEPSEEK_API_KEY\n\n"
        "安装方式：pip install -e .\n"
        "直接运行：python src/main.py <命令> ...[/dim]",
        title="[bold]快速开始[/]", border_style="cyan", padding=(1, 3),
    )
    console.print(install_box)


# ============================================================
# 进度指示器
# ============================================================

def show_progress(message: str) -> Progress:
    return Progress(
        SpinnerColumn(spinner_name="dots", finished_text="[green]✓[/]"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=20, complete_style="cyan", finished_style="bright_green"),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    )


# ============================================================
# 配置校验
# ============================================================

def _validate_config() -> bool:
    try:
        from src.config.settings import settings
        settings.validate()
        return True
    except ValueError as e:
        console.print(Panel(
            f"[red]✗ 配置错误[/]\n{e}",
            title="[bold red]启动失败[/]", border_style="red", padding=(1, 3),
        ))
        console.print("\n[yellow]提示：复制 .env.example 为 .env 并填入 API Key[/yellow]")
        return False


def _build_initial_state(target: str, target_type: str) -> dict:
    return {
        "messages": [HumanMessage(content=target)],
        "target": target, "target_type": target_type,
        "issues": [], "llm_review_text": "",
        "diff_content": "", "diff_summary": "",
        "current_file": "", "files_processed": [],
        "fixed_code": "", "original_code": "",
        "backup_path": "", "fix_instruction": "",
        "score": 100.0, "memory_summary": "",
        "done": False, "error": "",
    }


# ============================================================
# 模糊路径解析
# ============================================================

def _rel_path(base: Path, target: str) -> str:
    """将绝对路径转为相对于 base 的展示路径（跨磁盘时回退到绝对路径）。"""
    try:
        return str(Path(target).relative_to(base))
    except ValueError:
        return target


def _resolve_target_with_fuzzy(target: str) -> str | None:
    """模糊解析用户输入的路径，找不到时交互式让用户选择。

    Returns:
        解析后的精确路径，或 None 表示用户放弃。
    """
    target_path = Path(target)
    if target_path.exists():
        return target

    # 不在当前目录，尝试追加 src/ 前缀（常见于只输入 main.py 等）
    cwd = Path().resolve()
    alt1 = cwd / "src" / target
    if alt1.exists():
        return str(alt1)

    # 模糊搜索
    from src.tools.file_reader import FileReader
    result = FileReader.fuzzy_find(target, str(cwd))

    if result["success"] and result["items"]:
        items = result["items"]
        # items 已经是绝对路径，直接使用
        if len(items) == 1:
            resolved = items[0]
            rel = _rel_path(cwd, resolved)
            console.print(f"[dim]→ 自动匹配: [white]{rel}[/][/dim]")
            return resolved

        # 多个候选项，交互选择
        if len(items) > 1:
            console.print(f"\n[yellow]路径 `{target}` 不存在，找到以下匹配项：[/]\n")
            table = Table(show_header=False, border_style="dim", box=None, padding=(0, 2))
            table.add_column("序号", style="bold cyan", width=5)
            table.add_column("路径", style="white")
            for idx, item in enumerate(items[:10], 1):
                table.add_row(str(idx), _rel_path(cwd, item))
            console.print(table)

            try:
                choice = console.input(
                    f"\n[bold]选择序号 (1-{min(len(items), 10)}, Enter=取消):[/] "
                ).strip()
                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < min(len(items), 10):
                        resolved = items[idx]
                        console.print(
                            f"[dim]→ 已选择: [white]{_rel_path(cwd, resolved)}[/][/dim]"
                        )
                        return resolved
            except (EOFError, KeyboardInterrupt):
                pass
            console.print("[dim]已取消。[/dim]")
            return None

    console.print(f"[yellow]未找到匹配的路径: {target}[/yellow]")
    # 列出当前目录内容
    _print_directory_contents(cwd)
    return None


def _print_directory_contents(path: Path) -> None:
    """打印目录内容摘要。"""
    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        entries = [e for e in entries if not e.name.startswith(".")]
        source_exts = {".py", ".java", ".js", ".ts", ".go", ".rs", ".cpp", ".c",
                       ".h", ".hpp", ".cs"}
        items = []
        for e in entries[:30]:
            marker = "📁" if e.is_dir() else "📄"
            if e.suffix.lower() in source_exts:
                marker = "[cyan]📄[/]"
            items.append(f"  {marker} {e.name}")
        if items:
            console.print("\n[dim]当前目录内容：[/dim]")
            console.print("\n".join(items))
    except Exception:
        pass


# ============================================================
# 核心执行引擎
# ============================================================

def run_agent(target: str, target_type: str, output: str | None = None,
              label: str = "处理中", fix_instruction: str = "") -> int:
    """统一 Agent 执行入口。Returns 0/1/2 exit code."""
    from src.agent.graph import graph

    config = {"configurable": {"thread_id": f"cs-{int(time.time())}"}}
    state = _build_initial_state(target, target_type)
    if fix_instruction:
        state["fix_instruction"] = fix_instruction

    with Live(console=console, refresh_per_second=4) as live:
        progress = show_progress(label)
        task_id = progress.add_task(label, total=None)
        live.update(Group(progress))
        start_time = time.time()
        try:
            result = graph.invoke(state, config)
            elapsed = time.time() - start_time
        except ValueError as e:
            live.stop()
            _print_error(str(e), "配置错误")
            return 2
        except Exception as e:
            live.stop()
            console.print(f"\n[red][异常][/red] {e}")
            if "--debug" in sys.argv:
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
            return 2
        progress.update(task_id, completed=1, total=1,
                       description=f"{label}完成 ({elapsed:.1f}s)")
        live.refresh()

    # 智能输出
    _smart_output(result, target_type)
    if output:
        _export(result, output)

    if target_type.startswith("review"):
        crit = sum(1 for i in result.get("issues", []) if i.get("severity") == "critical")
        if crit > 0:
            console.print("\n[red]发现严重问题，建议优先处理。[/red]")
            return 1
    return 0


def _smart_output(result: dict, target_type: str) -> None:
    """根据操作类型和结果智能选择输出格式，避免冗余。"""
    issues = result.get("issues", [])
    error_msg = result.get("error", "")
    llm_text = result.get("llm_review_text", "")

    # fix / test 操作：只输出分析部分，剥离代码块
    if target_type in ("fix", "test"):
        if llm_text.strip():
            clean = _strip_code_blocks(llm_text)
            console.print()
            console.print(Markdown(clean))
            console.print()
        _print_write_results(result)
        if error_msg and not error_msg.startswith("LLM"):
            console.print(f"\n[yellow]⚠ {error_msg}[/yellow]")
        return

    # review 操作：有实质输出才展示
    if target_type.startswith("review"):
        has_issues = bool(issues)
        has_llm = bool(llm_text.strip())
        has_report = bool(result.get("messages"))

        error_is_noop = error_msg and ("无实质变更" in error_msg or "无变更" in error_msg)

        if error_is_noop:
            console.print("\n[dim]无变更可审查。[/]")
            return

        # 有 m次essages（LangGraph 报告）且没有问题 → 只给摘要
        if has_report and not has_issues and not has_llm and not error_msg:
            # 单文件审查无问题
            console.print()
            console.print("[green]✅ 规则检查未发现问题。[/]")
            console.print()
            _print_stats(result)
            return

        # 输出报告内容
        for msg in result.get("messages", []):
            if hasattr(msg, "content") and msg.content:
                console.print()
                console.print(Markdown(msg.content))
                console.print()

        _print_stats(result)

        if error_msg:
            console.print(f"\n[yellow]⚠ {error_msg}[/yellow]")
        return

    # 其他类型：直接输出消息
    for msg in result.get("messages", []):
        if hasattr(msg, "content") and msg.content:
            console.print()
            console.print(Markdown(msg.content))
    if error_msg:
        console.print(f"\n[yellow]⚠ {error_msg}[/yellow]")


def _print_write_results(result: dict) -> None:
    write_result = result.get("_write_result")
    backup_path = result.get("backup_path", "")
    if write_result:
        if write_result["success"]:
            console.print(f"\n[green]✅ 文件已修复并写入：{result.get('current_file', '')}[/green]")
        else:
            console.print(f"\n[red]❌ 写入失败：{write_result.get('error')}[/red]")
    if backup_path:
        console.print(f"[dim]💾 备份: {backup_path}[/dim]")

    test_write = result.get("_test_write_result")
    test_path = result.get("_test_file_path", "")
    if test_write:
        if test_write["success"]:
            console.print(f"\n[green]✅ 测试文件：[bold]{test_path}[/bold]"
                          f" ({test_write['written_bytes']} bytes)[/green]")
        else:
            console.print(f"\n[red]❌ 测试写入失败：{test_write.get('error')}[/red]")


def _print_stats(result: dict) -> None:
    from src.review.reporter import Reporter
    issues = result.get("issues", [])
    score = result.get("score", 100.0)
    crit = sum(1 for i in issues if i.get("severity") == "critical")
    warn = sum(1 for i in issues if i.get("severity") == "warning")
    sugg = sum(1 for i in issues if i.get("severity") == "suggestion")
    stat_table = Table(show_header=False, border_style="cyan", padding=(0, 3), box=None)
    stat_table.add_column("指标", style="bold white", width=12)
    stat_table.add_column("值")
    stat_table.add_row("综合评分", f"{score:.1f}/100  {Reporter.get_score_grade(score)}")
    stat_table.add_row("问题总数", f"{len(issues)}")
    stat_table.add_row("🔴 严重", f"{crit}")
    stat_table.add_row("🟡 警告", f"{warn}")
    stat_table.add_row("🔵 建议", f"{sugg}")
    console.print(Panel(stat_table, title="[bold]审查统计[/]", border_style="cyan"))


def _export(result: dict, output_path: str) -> None:
    try:
        from src.review.reviewer import ReviewIssue, Severity as S, Category as C
        from src.review.reporter import Reporter
        issue_objs = [
            ReviewIssue(
                severity=S(i["severity"]) if i.get("severity") else S.SUGGESTION,
                category=C(i["category"]) if i.get("category") else C.QUALITY,
                rule_id=i.get("rule_id", "?"), file_path=i.get("file_path", ""),
                line=i.get("line"), title=i.get("title", ""),
                description=i.get("description", ""),
                suggestion=i.get("suggestion", ""),
                source=i.get("source", "rule"))
            for i in result.get("issues", [])
        ]
        report = Reporter.build_report(
            rule_issues=issue_objs,
            files=result.get("files_processed", []),
            llm_text=result.get("llm_review_text", ""))
        path = Reporter.save_report(report, output_path)
        console.print(f"\n[green]✓ 报告：[bold]{path}[/][/green]")
    except Exception as e:
        console.print(f"\n[red]导出失败：{e}[/red]")


def _print_error(msg: str, title: str = "错误") -> None:
    console.print(Panel(msg, title=f"[bold red]{title}[/]",
                        border_style="red", padding=(1, 3)))


# ============================================================
# 目录审查（CLI 层循环，逐文件输出）
# ============================================================

def _strip_code_blocks(text: str) -> str:
    """移除 Markdown 代码块内容，只保留分析和说明。
    将 ```...``` 块替换为 [代码块已省略]。
    """
    import re as _re
    # 替换代码块为占位符
    result = _re.sub(r'```[\w]*\n.*?```', '\n_[代码已写入文件]_\n', text, flags=_re.DOTALL)
    return result

def _max_dir_files() -> int:
    """从环境变量获取目录审查文件上限，提供默认值 10。"""
    try:
        from src.config.settings import settings
        return settings.MAX_DIR_FILES
    except Exception:
        return 10


def _scan_dir_sources(directory: str) -> list[str]:
    """递归扫描目录中的源文件。"""
    from src.tools.file_reader import SOURCE_EXTS
    dir_path = Path(directory).resolve()
    all_files: list[str] = []
    limit = _max_dir_files()

    for p in sorted(dir_path.rglob("*")):
        if p.is_file() and p.suffix.lower() in SOURCE_EXTS:
            if not any(part.startswith(".") for part in p.parts):
                all_files.append(str(p))
        if len(all_files) >= limit:
            break

    total = len(all_files)
    return all_files[:limit], total


def _review_single_file(file_path: str) -> dict:
    """对单个文件执行规则引擎审查，不调用 LLM。返回 issue dicts。"""
    from src.review.reviewer import Reviewer
    from src.tools.file_reader import FileReader
    try:
        r = FileReader.read_file(file_path)
        if not r["success"]:
            return {"issues": [], "score": 100.0, "file": file_path,
                    "error": r.get("error", "")}
        reviewer = Reviewer()
        rule_issues = reviewer.rule_review(r["content"], r["language"], file_path)
        score = reviewer.calculate_score(rule_issues)
        issue_dicts = [
            {"severity": i.severity.value, "category": i.category.value,
             "rule_id": i.rule_id, "file_path": i.file_path,
             "line": i.line, "title": i.title,
             "description": i.description, "suggestion": i.suggestion,
             "source": i.source}
            for i in rule_issues
        ]
        return {"issues": issue_dicts, "score": score, "file": file_path, "error": ""}
    except Exception as e:
        return {"issues": [], "score": 100.0, "file": file_path, "error": str(e)}


def run_directory_review(directory: str, output: str | None = None) -> int:
    """递归审查目录，逐文件展示问题。"""
    from src.review.reviewer import Reviewer
    from src.review.reporter import Reporter

    files, total_count = _scan_dir_sources(directory)
    trunc_note = ""
    limit = _max_dir_files()
    if total_count > limit:
        trunc_note = f" (共 {total_count} 个源文件，受限于上限审查前 {limit} 个)"

    console.print(Rule(title=f"[bold cyan]目录审查: {directory}[/]", style="cyan"))
    console.print(f"[dim]发现 {len(files)} 个源文件{trunc_note}[/dim]\n")

    if not files:
        _print_error("目录中无源代码文件", "无文件")
        return 2

    all_issues: list[dict] = []
    files_with_issues: list[str] = []
    total_score = 0.0

    for idx, file_path in enumerate(files, 1):
        rel = _rel_path(Path(directory), file_path)
        console.print(f"[bold]📄 [{idx}/{len(files)}][/] [white]{rel}[/]")
        result = _review_single_file(file_path)

        if result.get("error"):
            console.print(f"  [yellow]⚠ {result['error']}[/yellow]")
            continue

        issues = result["issues"]
        score = result["score"]
        total_score += score

        if not issues:
            console.print("  [green]✅ 无问题[/green] (score: {:.0f})".format(score))
        else:
            console.print("  [yellow]发现 {} 个问题[/yellow] (score: {:.0f})".format(
                len(issues), score))
            for issue in issues:
                sev = issue.get("severity", "suggestion")
                emoji = {"critical": "🔴", "warning": "🟡", "suggestion": "🔵"}.get(sev, "⚪")
                li = f"L{issue['line']}" if issue.get("line") else "—"
                console.print(
                    f"    {emoji} `{issue.get('rule_id','?')}` {issue.get('title','')} ({li})"
                )
            files_with_issues.append(file_path)
            all_issues.extend(issues)

        console.print()

    # 汇总
    avg_score = total_score / len(files) if files else 100.0
    crit = sum(1 for i in all_issues if i.get("severity") == "critical")
    warn = sum(1 for i in all_issues if i.get("severity") == "warning")
    sugg = sum(1 for i in all_issues if i.get("severity") == "suggestion")

    stat_table = Table(show_header=False, border_style="cyan", padding=(0, 3), box=None)
    stat_table.add_column("指标", style="bold white", width=14)
    stat_table.add_column("值")
    stat_table.add_row("审查文件数", f"{len(files)}{trunc_note}")
    stat_table.add_row("问题总数", f"{len(all_issues)}")
    stat_table.add_row("综合评分", f"{avg_score:.1f}/100  {Reporter.get_score_grade(avg_score)}")
    stat_table.add_row("🔴 严重", f"{crit}")
    stat_table.add_row("🟡 警告", f"{warn}")
    stat_table.add_row("🔵 建议", f"{sugg}")
    console.print(Panel(stat_table, title="[bold]审查汇总[/]", border_style="cyan"))

    # 导出
    if output:
        from src.review.reviewer import ReviewIssue, Severity as S, Category as C
        issue_objs = [
            ReviewIssue(
                severity=S(i["severity"]) if i.get("severity") else S.SUGGESTION,
                category=C(i["category"]) if i.get("category") else C.QUALITY,
                rule_id=i.get("rule_id", "?"), file_path=i.get("file_path", ""),
                line=i.get("line"), title=i.get("title", ""),
                description=i.get("description", ""),
                suggestion=i.get("suggestion", ""),
                source=i.get("source", "rule"))
            for i in all_issues
        ]
        report = Reporter.build_report(
            rule_issues=issue_objs, files=list(files),
            llm_text=f"目录审查: {directory}\n审查 {len(files)}/{total_count} 个文件，"
                     f"发现 {len(all_issues)} 个问题。")
        path = Reporter.save_report(report, output)
        console.print(f"\n[green]✓ 报告：[bold]{path}[/][/green]")

    # 询问是否修复
    if files_with_issues and sys.stdin.isatty():
        console.print()
        try:
            ans = console.input(
                f"[yellow]发现 {len(files_with_issues)} 个文件存在问题，是否修复？[/] "
                f"[dim](y/n/s: 选择文件)[/] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"

        if ans == "y":
            for fp in files_with_issues:
                console.print(f"\n[dim]▸ 修复 [white]{_rel_path(Path(directory), fp)}[/]...[/dim]")
                run_agent(f"fix {fp}", "fix", label="Bug 修复")
        elif ans == "s":
            _interactive_fix_select(files_with_issues, directory)

    return 1 if crit > 0 else 0


def _interactive_fix_select(files_with_issues: list[str], base_dir: str) -> None:
    """交互式选择要修复的文件。"""
    table = Table(show_header=False, border_style="dim", box=None, padding=(0, 2))
    table.add_column("序号", style="bold cyan", width=5)
    table.add_column("文件", style="white")
    for idx, fp in enumerate(files_with_issues, 1):
        table.add_row(str(idx), _rel_path(Path(base_dir), fp))
    console.print(table)
    try:
        choice = console.input(
            f"[bold]选择要修复的文件 (1-{len(files_with_issues)}, 逗号分隔, Enter=取消):[/] "
        ).strip()
        if choice:
            indices = [int(c.strip()) - 1 for c in choice.split(",") if c.strip().isdigit()]
            for i in indices:
                if 0 <= i < len(files_with_issues):
                    fp = files_with_issues[i]
                    console.print(f"\n[dim]▸ 修复 [white]{_rel_path(Path(base_dir), fp)}[/]...[/dim]")
                    run_agent(f"fix {fp}", "fix", label="Bug 修复")
    except (EOFError, KeyboardInterrupt, ValueError):
        pass


# ============================================================
# 子命令
# ============================================================

def cmd_review(args: argparse.Namespace) -> int:
    target = _resolve_target_with_fuzzy(args.target)
    if target is None:
        return 2
    target_path = Path(target)
    if target_path.is_dir():
        return run_directory_review(str(target_path.resolve()), output=args.output)
    console.print(f"[dim]▸ 目标：[/][white]{target}[/] ([cyan]审查文件[/])\n")
    return run_agent(target, "review_file", output=args.output, label="审查文件")


def cmd_diff(args: argparse.Namespace) -> int:
    from src.tools.git_parser import GitParser
    repo = args.repo or "."
    console.print(f"[dim]▸ 目标：[/][white]{repo}[/] ([cyan]git diff[/])\n")
    if not GitParser.is_git_repo(repo):
        _print_error(f"不是 Git 仓库：{repo}", "无效仓库")
        return 2
    return run_agent("diff", "review_diff", output=args.output, label="审查变更")


def cmd_fix(args: argparse.Namespace) -> int:
    """fix 命令：分析 Bug → LLM 修复 → 自动写回文件。"""
    target = _resolve_target_with_fuzzy(args.target)
    if target is None:
        return 2

    target_path = Path(target)
    if target_path.is_dir():
        _print_error(f"fix 需要文件，不是目录: {target}", "参数错误")
        return 2

    console.print(f"[dim]▸ 目标：[/][white]{target}[/] ([cyan]Bug 修复[/])\n")
    return run_agent(f"fix {target}", "fix", output=args.output, label="Bug 修复")


def cmd_test(args: argparse.Namespace) -> int:
    target = _resolve_target_with_fuzzy(args.target)
    if target is None:
        return 2

    target_path = Path(target)
    if target_path.is_dir():
        _print_error(f"test 需要文件，不是目录: {target}", "参数错误")
        return 2

    console.print(f"[dim]▸ 目标：[/][white]{target}[/] ([cyan]单测生成[/])\n")
    return run_agent(f"test {target}", "test", output=args.output, label="单测生成")


def cmd_interactive(args: argparse.Namespace) -> int:
    """交互模式 - Claude Code 风格。

    纯自然语言为主：输入任意文本，LLM 路由器自动判断意图并执行。
    / 开头的命令作为快捷补充。
    """
    from src.memory.memory_manager import ConversationMemory

    cwd = Path.cwd()
    mem = ConversationMemory.load_from_disk()
    _print_interactive_welcome(cwd)

    while True:
        try:
            prompt = f"[dim]{cwd.name}[/] [bold cyan]❯[/] "
            user_input = console.input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            mem.save_to_disk()
            console.print("\n[dim]再见。[/dim]")
            break

        if not user_input:
            continue

        lower = user_input.lower()

        # 退出
        if lower in (":q", ":quit", "exit", "quit"):
            mem.save_to_disk()
            console.print("[dim]再见。[/dim]")
            break

        # 斜杠命令：快捷补充（含 LLM 混合解析）
        if lower.startswith("/"):
            cwd = _handle_slash_command(user_input, cwd, mem, args=args)
            mem.save_to_disk()
            continue

        # help 关键词
        if lower in ("help", "帮助", "?"):
            _print_help_text()
            continue

        # ---- LLM 意图路由 ----
        _process_natural_input(user_input, cwd, mem, args)
        mem.save_to_disk()
        console.print()

    return 0


def _process_natural_input(user_input: str, cwd: Path,
                           mem, args: argparse.Namespace) -> None:
    """LLM 路由器：分析用户输入 → 判断意图 → 执行操作。"""
    from src.config.prompts import AGENT_ROUTER_PROMPT, CONVERSATION_PROMPT
    from src.config.settings import settings
    from langchain_openai import ChatOpenAI

    mem.add_user_turn(user_input)
    context = mem.context_for_llm()

    # 1. LLM 路由（带 loading）
    router_prompt = AGENT_ROUTER_PROMPT.format(context=context, user_input=user_input)
    try:
        with console.status("[bold cyan]分析中...[/]", spinner="dots"):
            llm = ChatOpenAI(
                model=settings.LLM_MODEL, api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL, temperature=0, max_tokens=256,
            )
            response = llm.invoke(router_prompt)
            intent = _parse_router_json(response.content)
    except Exception:
        if Path(user_input).exists():
            intent = {"action": "review", "file": user_input, "instruction": ""}
        else:
            _chat_fallback(user_input, mem)
            return

    action = intent.get("action", "chat")
    file = intent.get("file", "").strip()
    instruction = intent.get("instruction", "").strip()

    # 2. 分发
    if action == "review":
        _do_review(file, instruction, cwd, mem, args)
    elif action == "fix":
        _do_fix(file, instruction, cwd, mem, args)
    elif action == "test":
        _do_test(file, cwd, mem, args)
    elif action == "diff":
        console.print("[dim]▸ 审查 Git 变更...[/]\n")
        run_agent("diff", "review_diff", output=args.output, label="审查变更")
        mem.add_agent_turn("已完成 Git diff 审查。", "diff")
    elif action == "refactor":
        _do_refactor(file, cwd, mem)
    elif action == "stats":
        target = file or str(cwd)
        run_stats(target)
        mem.add_agent_turn("已完成目录统计。", "stats")
    elif action == "undo":
        _do_undo_nl(file, cwd, mem)
    else:
        _chat_fallback(user_input, mem)


def _parse_router_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON。容错中文引号、markdown 包裹。"""
    import json as _json
    text = text.strip().replace('\u201c', '"').replace('\u201d', '"')
    try:
        return _json.loads(text)
    except Exception:
        pass
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            return _json.loads(m.group(1))
        except Exception:
            pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return _json.loads(m.group(0))
        except Exception:
            pass
    return {"action": "chat", "file": "", "instruction": ""}


# ---- Action helpers ----

def _do_review(file: str, instruction: str,
              cwd: Path, mem, args: argparse.Namespace) -> None:
    if not file or file == ".":
        file = str(cwd)
    resolved = _resolve_target_with_fuzzy(file) or str(cwd)
    resolved_path = Path(resolved)
    if resolved_path.is_dir():
        console.print(f"[dim]▸ 审查 [white]{_rel_path(cwd, resolved)}[/]...[/]\n")
        run_directory_review(str(resolved_path.resolve()), output=args.output)
        files, _ = _scan_dir_sources(str(resolved_path.resolve()))
        mem.record_review_result(str(resolved_path.resolve()), files, 0, 100.0)
        mem.add_agent_turn(f"已审查目录 {_rel_path(cwd, resolved)}", "review")
    else:
        console.print(f"[dim]▸ 审查 [white]{_rel_path(cwd, resolved)}[/]...[/]\n")
        run_agent(resolved, "review_file", output=args.output, label="审查文件")
        mem.last_review_files = [resolved]
        mem.add_agent_turn(f"已审查 {_rel_path(cwd, resolved)}", "review")


def _do_fix(file: str, instruction: str,
           cwd: Path, mem, args: argparse.Namespace) -> None:
    if not file:
        recent = mem.last_review_files
        if recent and len(recent) == 1:
            file = recent[0]
        else:
            console.print("[yellow]请指定要修复的文件。[/yellow]")
            return
    resolved = _resolve_target_with_fuzzy(file)
    if resolved is None:
        console.print(f"[yellow]未找到: {file}[/yellow]")
        return
    if Path(resolved).is_dir():
        console.print(f"[red]需要文件，不是目录: {_rel_path(cwd, resolved)}[/red]")
        return
    if instruction:
        console.print(f"[dim]▸ 指令: [white]{instruction}[/][/dim]")
    console.print(f"[dim]▸ 修复 [white]{_rel_path(cwd, resolved)}[/]...[/]\n")
    run_agent(f"fix {resolved}", "fix", output=args.output, label="Bug 修复",
              fix_instruction=instruction if instruction else "")
    mem.record_file_op("fix", str(Path(resolved).resolve()))
    mem.add_agent_turn(f"已修复 {_rel_path(cwd, resolved)}", "fix")


def _do_test(file: str, cwd: Path, mem, args: argparse.Namespace) -> None:
    if not file:
        recent = mem.last_review_files
        if recent and len(recent) == 1:
            file = recent[0]
        else:
            console.print("[yellow]请指定要生成测试的文件。[/yellow]")
            return
    resolved = _resolve_target_with_fuzzy(file)
    if resolved is None or Path(resolved).is_dir():
        console.print("[yellow]请指定具体的文件。[/yellow]")
        return
    console.print(f"[dim]▸ 单测 [white]{_rel_path(cwd, resolved)}[/]...[/]\n")
    run_agent(f"test {resolved}", "test", output=args.output, label="单测生成")
    mem.add_agent_turn(f"已生成测试 {_rel_path(cwd, resolved)}", "test")


def _do_refactor(file: str, cwd: Path, mem) -> None:
    if not file:
        recent = mem.last_review_files
        file = recent[0] if recent else ""
        if not file:
            console.print("[yellow]请指定要重构的文件。[/yellow]")
            return
    resolved = _resolve_target_with_fuzzy(file)
    if resolved is None:
        return
    console.print(f"[dim]▸ 重构 [white]{_rel_path(cwd, resolved)}[/]...[/]\n")
    run_refactor(resolved)
    mem.add_agent_turn(f"已分析 {_rel_path(cwd, resolved)}", "refactor")


def _do_undo_nl(file: str, cwd: Path, mem) -> None:
    """自然语言 undo：从记忆推测文件，或直接回退。"""
    from src.tools.file_reader import FileReader

    # 未指定文件 → 从记忆中最最后修改的文件
    if not file:
        mod_files = mem.last_modified_files()
        if mod_files:
            file = mod_files[0]
            console.print(f"[dim]→ 最近修改: [white]{_rel_path(cwd, file)}[/][/dim]")
        else:
            console.print("[yellow]没有可回退的文件。请指定文件路径。[/yellow]")
            return

    resolved = _resolve_target_with_fuzzy(file) if file else None
    if not resolved:
        console.print(f"[yellow]未找到: {file}[/yellow]")
        return

    backups = FileReader.list_backups(resolved)
    items = backups.get("backups", [])
    if not items:
        console.print(f"[yellow]{_rel_path(cwd, resolved)} 没有 CodeSage 备份。[/yellow]")
        console.print("[dim]备份在 fix 操作时自动创建，存储于 .codesage/backups/[/]")
        return

    # 单备份直接恢复
    if len(items) == 1:
        r = FileReader.restore_from_backup(resolved, items[0]["path"])
        if r["success"]:
            console.print(f"[green]✅ 已恢复: {_rel_path(cwd, resolved)}[/green]")
            mem.record_file_op("undo", str(Path(resolved).resolve()), items[0]["path"])
            mem.add_agent_turn(f"已回退 {_rel_path(cwd, resolved)}", "undo")
        else:
            console.print(f"[red]恢复失败: {r['error']}[/red]")
    else:
        # 多备份 → 显示列表交互选择
        table = Table(show_header=False, border_style="dim", box=None, padding=(0, 2))
        table.add_column("序号", style="bold cyan", width=5)
        table.add_column("时间", width=18)
        for idx, b in enumerate(items[:10], 1):
            table.add_row(str(idx), b["timestamp"])
        console.print(f"\n[bold]{_rel_path(cwd, resolved)}[/] 的备份：")
        console.print(table)
        try:
            choice = console.input(
                f"\n[bold]选择恢复版本 (1-{min(len(items), 10)}, Enter=取消):[/] "
            ).strip()
            if choice.isdigit():
                i = int(choice) - 1
                if 0 <= i < min(len(items), 10):
                    r = FileReader.restore_from_backup(resolved, items[i]["path"])
                    if r["success"]:
                        console.print(f"[green]✅ 已恢复[/green]")
                        mem.record_file_op("undo", str(Path(resolved).resolve()),
                                          items[i]["path"])
                        mem.add_agent_turn(f"已回退 {_rel_path(cwd, resolved)}", "undo")
        except (EOFError, KeyboardInterrupt):
            pass


def _chat_fallback(user_input: str, mem) -> None:
    """纯对话：LLM 自然语言响应，带记忆（带 loading）。"""
    from src.config.prompts import CONVERSATION_PROMPT
    from src.config.settings import settings
    from langchain_openai import ChatOpenAI

    context = mem.context_for_llm()
    prompt = CONVERSATION_PROMPT.format(context=context, user_input=user_input)
    try:
        with console.status("[bold cyan]思考中...[/]", spinner="dots"):
            llm = ChatOpenAI(
                model=settings.LLM_MODEL, api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL, temperature=0.7, max_tokens=512,
            )
            response = llm.invoke(prompt)
            text = response.content.strip()
        console.print(Markdown(text))
        mem.add_agent_turn(text, "chat")
    except Exception:
        console.print("[dim]💬 试试输入 /help 查看可用命令。[/]")


def _print_interactive_welcome(cwd: Path) -> None:
    """打印简洁的交互模式欢迎信息（Claude Code 风格）。"""
    welcome = (
        f"[dim]工作目录: [white]{cwd}[/][/dim]\n"
        "[dim]输入 [cyan]/help[/] 查看可用命令[/dim]"
    )
    console.print(Panel(welcome, title="[bold cyan]CodeSage[/]",
                        border_style="cyan", padding=(1, 3)))
    console.print()


def _handle_slash_command(cmd: str, cwd: Path,
                            mem=None, args=None, **kwargs) -> Path:
    """处理斜杠快捷命令。

    对于含自然语言的 undo/backups，先用 LLM 提取文件路径。
    """
    lower = cmd.lower().lstrip("/").strip()
    parts = lower.split(None, 1) if lower else []
    verb = parts[0] if parts else ""
    arg = parts[1] if len(parts) > 1 else ""

    if verb in ("ls",):
        _cmd_ls(cwd)

    elif verb in ("pwd",):
        console.print(f"[dim]工作目录: [/][white]{cwd}[/white]")
        console.print(f"[dim]项目根: [/][white]{_PROJECT_ROOT}[/white]")

    elif verb == "cd":
        new_path = (cwd / arg).resolve() if arg else _PROJECT_ROOT
        if new_path.is_dir():
            os.chdir(new_path)
            cwd = Path.cwd()
            console.print(f"[dim]→ [white]{cwd}[/white][/dim]")
        else:
            console.print(f"[yellow]目录不存在: {arg}[/yellow]")

    elif verb in ("help", "?"):
        _print_help_text()

    elif verb in ("clear", "clc", "cls"):
        console.clear()

    elif verb in ("undo", "rollback", "回退"):
        # arg 含自然语言 → LLM 提取文件路径
        if arg and not Path(arg).exists():
            arg = _extract_file_path_from_text(arg, mem)
        _cmd_undo(arg, cwd, mem)

    elif verb in ("backups", "备份"):
        if arg and not Path(arg).exists():
            arg = _extract_file_path_from_text(arg, mem)
        _cmd_list_backups(arg, cwd)

    elif verb in ("stats", "统计"):
        target = arg or "."
        resolved = _resolve_target_with_fuzzy(target) if target else str(cwd)
        if resolved:
            run_stats(resolved)

    elif verb in ("lint",):
        resolved = _resolve_target_with_fuzzy(arg) if arg else None
        if resolved:
            run_lint(resolved)

    else:
        # 未知的 / 命令 → 用自然语言路由器处理
        if args is not None and mem is not None:
            _process_natural_input(cmd.lstrip("/"), cwd, mem, args)
        else:
            console.print(f"[dim]未知命令: {verb}（输入 /help 查看帮助）[/dim]")

    return cwd


def _extract_file_path_from_text(text: str, mem=None) -> str:
    """用 LLM 从自然语言中提取文件路径。

    例如: "D:\...\src目录下的App文件" → "D:\...\src\App.vue"
    """
    from src.config.settings import settings
    from langchain_openai import ChatOpenAI

    context = ""
    if mem:
        context = mem.context_for_llm()

    prompt = f"""从用户输入中提取文件路径。只输出绝对路径或相对路径，不输出其他文字。

上下文：
{context}

用户输入：{text}

路径："""

    try:
        with console.status("[bold cyan]理解中...[/]", spinner="dots"):
            llm = ChatOpenAI(
                model=settings.LLM_MODEL, api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL, temperature=0, max_tokens=128,
            )
            response = llm.invoke(prompt)
            extracted = response.content.strip()
            # 清理常见多余的引号
            extracted = extracted.strip('\'"`')
            if extracted and len(extracted) > 2:
                console.print(f"[dim]→ 理解为: [white]{extracted}[/][/dim]")
                return extracted
    except Exception:
        pass
    return text


def _cmd_ls(cwd: Path) -> None:
    entries = sorted(cwd.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    entries = [e for e in entries if not e.name.startswith(".")]
    if not entries:
        console.print("[dim](空目录)[/dim]")
        return
    table = Table(show_header=False, border_style="dim", box=None, padding=(0, 1))
    table.add_column("", width=3)
    table.add_column("")
    for e in entries[:40]:
        icon = "[cyan]📁[/]" if e.is_dir() else "[white]📄[/]"
        table.add_row(icon, e.name)
    console.print(table)


def _cmd_undo(arg: str, cwd: Path, mem=None) -> None:
    """回退文件到 CodeSage 备份。无参数时显示最近修改的文件。"""
    from src.tools.file_reader import FileReader

    # 无参数：显示最近修改的文件供选择
    target = arg.strip() if arg else ""
    if not target:
        if mem:
            mod_files = mem.last_modified_files()
            if mod_files:
                console.print("[bold]最近修改的文件：[/]")
                table = Table(show_header=False, border_style="dim", box=None, padding=(0, 2))
                table.add_column("序号", style="bold cyan", width=5)
                table.add_column("文件", style="white")
                for idx, fp in enumerate(mod_files[:10], 1):
                    table.add_row(str(idx), _rel_path(cwd, fp))
                console.print(table)
                try:
                    choice = console.input(
                        f"\n[bold]选择要回退的文件 (1-{min(len(mod_files), 10)}, Enter=取消):[/] "
                    ).strip()
                    if choice.isdigit():
                        i = int(choice) - 1
                        if 0 <= i < min(len(mod_files), 10):
                            target = mod_files[i]
                except (EOFError, KeyboardInterrupt):
                    target = ""
            if not target:
                console.print("[yellow]请指定文件。例如: /undo src/main.py[/yellow]")
                console.print("[dim]提示: 如果没有文件被修改过，输入文件路径来检查是否有备份。[/]")
                return

    resolved = _resolve_target_with_fuzzy(target) if target else None
    if not resolved:
        console.print(f"[yellow]未找到文件: {target}[/yellow]")
        return

    backups = FileReader.list_backups(resolved)
    items = backups.get("backups", [])
    if not items:
        console.print(f"[yellow]{_rel_path(cwd, resolved)} 没有 CodeSage 备份。[/yellow]")
        console.print("[dim]备份在 fix 操作时自动创建，存储于 .codesage/backups/[/]")
        return

    # 只有一个备份 → 直接恢复
    if len(items) == 1:
        r = FileReader.restore_from_backup(resolved, items[0]["path"])
        if r["success"]:
            console.print(f"[green]✅ 已恢复: {_rel_path(cwd, resolved)}[/green]"
                          f" [dim]({items[0]['timestamp']})[/]")
            if mem:
                mem.record_file_op("undo", str(Path(resolved).resolve()),
                                   items[0]["path"])
        else:
            console.print(f"[red]恢复失败: {r['error']}[/red]")
        return

    # 多个备份 → 交互选择
    table = Table(show_header=False, border_style="dim", box=None, padding=(0, 2))
    table.add_column("序号", style="bold cyan", width=5)
    table.add_column("时间", width=18)
    for idx, b in enumerate(items[:15], 1):
        table.add_row(str(idx), b["timestamp"])
    console.print(f"\n[bold]{_rel_path(cwd, resolved)}[/] 的备份：")
    console.print(table)
    try:
        choice = console.input(
            f"\n[bold]选择要恢复的版本 (1-{min(len(items), 15)}, Enter=取消):[/] "
        ).strip()
        if choice.isdigit():
            i = int(choice) - 1
            if 0 <= i < min(len(items), 15):
                r = FileReader.restore_from_backup(resolved, items[i]["path"])
                if r["success"]:
                    console.print(f"[green]✅ 已恢复 ({items[i]['timestamp']})[/green]")
                    if mem:
                        mem.record_file_op("undo", str(Path(resolved).resolve()),
                                          items[i]["path"])
                else:
                    console.print(f"[red]恢复失败: {r['error']}[/red]")
    except (EOFError, KeyboardInterrupt):
        pass


def _cmd_list_backups(arg: str, cwd: Path) -> None:
    """列出备份文件。"""
    from src.tools.file_reader import FileReader
    target = arg or "."
    resolved = _resolve_target_with_fuzzy(target) if target else None
    if not resolved:
        console.print("[yellow]请指定文件。例如: /backups src/main.py[/yellow]")
        return
    backups = FileReader.list_backups(resolved)
    items = backups.get("backups", [])
    if not items:
        console.print(f"[yellow]{_rel_path(cwd, resolved)} 没有备份。[/yellow]")
        return
    table = Table(show_header=False, border_style="dim", box=None, padding=(0, 2))
    table.add_column("序号", style="bold cyan", width=5)
    table.add_column("时间")
    for idx, b in enumerate(items[:20], 1):
        table.add_row(str(idx), b["timestamp"])
    console.print(f"\n[bold]{_rel_path(cwd, resolved)}[/] 的备份 ({len(items)} 个)：")
    console.print(table)


def _print_help_text() -> None:
    console.print("[bold]CodeSage 交互帮助[/]\n")
    console.print("[bold white]自然语言（直接输入即可）[/]")
    console.print("  [cyan]审查这个项目[/]         — 审查当前目录")
    console.print("  [cyan]看看 src/main.py[/]     — 审查文件")
    console.print("  [cyan]修复 src/main.py[/]     — Bug 修复（自动备份）")
    console.print("  [cyan]帮我修复刚审查的文件[/] — 基于记忆修复最近操作的对象")
    console.print("  [cyan]给 utils.py 生成测试[/] — 自动生成并写入 test_ 文件")
    console.print("  [cyan]重构 main.py[/]         — 代码重构建议")
    console.print("  [cyan]看下变更[/]             — Git diff 审查")
    console.print("  [cyan]统计一下[/]             — 目录统计（文件/行数/语言）")
    console.print("  [cyan]你好[/]                 — 闲谈对话")
    console.print()
    console.print("[bold white]快捷命令[/]")
    console.print("  [cyan]/review <path>[/]  — 审查指定文件或目录（模糊匹配）")
    console.print("  [cyan]/fix <path>[/]     — 修复指定文件 Bug（先备份再写入）")
    console.print("  [cyan]/test <path>[/]    — 为文件生成单元测试")
    console.print("  [cyan]/stats <dir>[/]    — 统计目录（文件数/行数/语言分布）")
    console.print("  [cyan]/lint <file>[/]    — 快速规则扫描（仅规则引擎，秒出）")
    console.print("  [cyan]/ls[/]             — 列出当前目录文件")
    console.print("  [cyan]/pwd[/]            — 显示工作目录和项目根")
    console.print("  [cyan]/cd <dir>[/]       — 切换工作目录")
    console.print("  [cyan]/undo <file>[/]    — 回退文件到上一份 CodeSage 备份")
    console.print("  [cyan]/backups <file>[/] — 查看文件的所有 CodeSage 备份")
    console.print("  [cyan]/clear[/]          — 清屏")
    console.print("  [cyan]:q[/]              — 退出")


# ============================================================
# 文件统计
# ============================================================

def run_stats(directory: str) -> None:
    """统计目录中的文件数、行数、语言分布。"""
    from src.tools.file_reader import SOURCE_EXTS, FileReader
    dir_path = Path(directory).resolve()
    console.print(Rule(title=f"[bold cyan]目录统计: {directory}[/]", style="cyan"))

    lang_files: dict[str, list[str]] = {}
    total_lines = 0
    total_files = 0

    for p in sorted(dir_path.rglob("*")):
        if p.is_file() and p.suffix.lower() in SOURCE_EXTS:
            if any(part.startswith(".") for part in p.parts):
                continue
            lang = p.suffix.lstrip(".") or "other"
            try:
                line_count = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
            except Exception:
                line_count = 0
            lang_files.setdefault(lang, []).append(str(p))
            total_lines += line_count
            total_files += 1
        if total_files >= 50:
            break

    # 汇总表
    table = Table(show_header=True, header_style="bold white", border_style="dim", padding=(0, 2))
    table.add_column("语言", style="bold cyan")
    table.add_column("文件数", justify="right")
    table.add_column("比例", justify="right")
    for lang in sorted(lang_files, key=lambda k: -len(lang_files[k])):
        cnt = len(lang_files[lang])
        table.add_row(lang, str(cnt), f"{cnt/total_files*100:.0f}%" if total_files else "-")
    console.print(table)

    console.print(f"\n[bold]总计:[/] {total_files} 文件, {total_lines} 行")
    if total_files > 50:
        console.print("[dim]（仅统计前 50 个源文件）[/dim]")

    # 最大的文件
    console.print("\n[bold white]最大的文件 (行数)[/]")
    file_sizes = []
    for lang, files in lang_files.items():
        for f in files:
            try:
                lc = len(Path(f).read_text(encoding="utf-8", errors="replace").splitlines())
                file_sizes.append((lc, _rel_path(dir_path, f)))
            except Exception:
                pass
    file_sizes.sort(key=lambda x: -x[0])
    for lc, fp in file_sizes[:10]:
        console.print(f"  {lc:>5}  {fp}")


def run_lint(file_path: str) -> None:
    """对单个文件执行快速规则扫描。"""
    from src.review.reviewer import Reviewer
    from src.tools.file_reader import FileReader
    r = FileReader.read_file(file_path)
    if not r["success"]:
        _print_error(r.get("error", "读取失败"), "Lint 错误")
        return
    reviewer = Reviewer()
    issues = reviewer.rule_review(r["content"], r["language"], file_path)
    console.print(Rule(title=f"[bold cyan]Lint: {_rel_path(Path.cwd(), file_path)}[/]", style="cyan"))
    if not issues:
        console.print("[green]✅ 无规则问题[/green]")
        return
    from rich.table import Table as T
    table = T(show_header=True, header_style="bold white", border_style="dim", padding=(0, 1))
    table.add_column("级别", width=8)
    table.add_column("规则", style="bold cyan", width=10)
    table.add_column("行", width=5)
    table.add_column("问题")
    emoji = {"critical": "[red]🔴[/]", "warning": "[yellow]🟡[/]", "suggestion": "[blue]🔵[/]"}
    for i in issues:
        table.add_row(
            emoji.get(i.severity.value, "⚪"),
            i.rule_id,
            str(i.line) if i.line else "—",
            i.title)
    console.print(table)


def run_refactor(file_path: str) -> int:
    """对文件提出重构建议（LLM 深度分析）。"""
    from src.review.reviewer import Reviewer
    from src.tools.file_reader import FileReader
    try:
        r = FileReader.read_file(file_path)
        if not r["success"]:
            _print_error(r.get("error", "读取失败"), "Refactor 错误")
            return 2
        reviewer = Reviewer()
        prompt = f"""你是一名资深代码重构专家。请分析以下代码，提出具体的重构建议。

**文件**: {file_path}
**语言**: {r['language']}

```{r['language']}
{r['content'][:6000]}
```

请输出：
1. 代码异味识别
2. 设计模式改进建议
3. SOLID 原则分析
4. 可读性改进点
5. 如果有改进空间，给出重构后的代码示例

如果没有明显改进空间，输出 "✅ 代码结构良好"。"""
        llm_text, _ = reviewer.call_llm_with_retry(prompt)
        console.print(Markdown(llm_text))
    except Exception as e:
        _print_error(str(e), "LLM 错误")
        return 2
    return 0


def cmd_rules(args: argparse.Namespace) -> int:
    from src.review.rules import BUILTIN_RULES
    table = Table(title=f"内建审查规则 ({len(BUILTIN_RULES)} 条)",
                  show_header=True, header_style="bold white", border_style="dim",
                  padding=(0, 2))
    table.add_column("ID", style="bold cyan", width=10)
    table.add_column("级别", width=10)
    table.add_column("类别", width=10)
    table.add_column("名称", style="bold white")
    table.add_column("描述", max_width=45)

    sev_styles = {
        "critical": "[red]🔴 CRITICAL[/]",
        "warning": "[yellow]🟡 WARNING[/]",
        "suggestion": "[blue]🔵 SUGGESTION[/]",
    }
    for r in BUILTIN_RULES:
        table.add_row(
            r.rule_id, sev_styles.get(r.severity.value, r.severity.value),
            r.category.value, r.title, r.description[:45],
        )
    console.print(table)
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    info_table = Table(show_header=False, border_style="cyan", box=None, padding=(0, 2))
    info_table.add_column("字段", style="bold white", width=16)
    info_table.add_column("值")
    for k, v in [
        ("产品名称", "CodeSage — 智能代码工程师 Agent"),
        ("版本号", "v1.1.0"),
        ("核心能力", "代码审查 · Bug 修复(自动写回) · 单测生成"),
        ("交互模式", "Claude Code 风格 REPL · 模糊路径匹配"),
        ("技术方向", "Agentic AI 原生开发"),
        ("课程", "CS599 企业级应用软件设计与开发"),
        ("Agent 框架", "LangGraph (ReAct 状态机)"),
        ("LLM 后端", "DeepSeek API (OpenAI 兼容)"),
        ("审查引擎", "双引擎：规则 + LLM"),
        ("CLI 渲染", "Rich Terminal UI"),
    ]:
        info_table.add_row(k, v)
    console.print(Panel(info_table, title="CodeSage v1.1.0",
                        border_style="cyan", padding=(1, 3)))
    return 0


# ============================================================
# CLI 解析器
# ============================================================

class HelpAction(argparse.Action):
    def __init__(self, option_strings, dest=argparse.SUPPRESS,
                 default=argparse.SUPPRESS, **kwargs):
        super().__init__(option_strings, dest=dest, default=default, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        print_help_panel()
        parser.exit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codesage",
        description="CodeSage — 基于 AI Agent 的智能代码工程师助手",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action=HelpAction)
    parser.add_argument("--version", "-V", action="version", version="%(prog)s v1.1.0")

    sub = parser.add_subparsers(dest="command", title="命令")

    p = sub.add_parser("review", aliases=["r"], add_help=False,
                       description="审查单个文件或整个目录 (支持模糊路径)")
    p.add_argument("target", help="文件或目录路径")
    p.add_argument("-o", "--output", metavar="FILE", default=None,
                   help="导出报告到指定文件 (.md)")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("fix", add_help=False,
                       description="分析 Bug → LLM 修复 → 自动写回文件")
    p.add_argument("target", help="需要修复的源代码文件")
    p.add_argument("-o", "--output", metavar="FILE", default=None,
                   help="导出修复报告 (.md)")
    p.set_defaults(func=cmd_fix)

    p = sub.add_parser("test", add_help=False,
                       description="为文件生成单元测试")
    p.add_argument("target", help="源代码文件路径")
    p.add_argument("-o", "--output", metavar="FILE", default=None,
                   help="导出测试报告 (.md)")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("diff", aliases=["d"], add_help=False,
                       description="审查当前 Git 仓库变更")
    p.add_argument("--repo", metavar="PATH", default=None)
    p.add_argument("-o", "--output", metavar="FILE", default=None)
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("interactive", aliases=["i"], add_help=False,
                       description="交互式 REPL (模糊路径 + 文件操作)")
    p.add_argument("-o", "--output", metavar="FILE", default=None)
    p.set_defaults(func=cmd_interactive)

    p = sub.add_parser("rules", add_help=False, description="列出内建审查规则")
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("version", aliases=["v"], add_help=False,
                       description="显示版本信息")
    p.set_defaults(func=cmd_version)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        print_help_panel()
        sys.exit(0)

    print_banner()

    if not _validate_config():
        sys.exit(1)

    try:
        from src.config.settings import settings
        settings.setup_langsmith()
    except Exception:
        pass

    try:
        exit_code = args.func(args)
    except Exception as e:
        _print_error(f"{e}\n{''.join(traceback.format_exc())}", "运行异常")
        exit_code = 2

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
