"""
审查报告生成器

将审查问题汇总为结构化报告，支持 Markdown 输出和文件导出。
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.review.reviewer import ReviewIssue, ReviewReport, Reviewer, Severity


class Reporter:
    """审查报告生成器。"""

    @staticmethod
    def build_report(
        rule_issues: list[ReviewIssue],
        files: list[str],
        llm_text: str = "",
        highlights: list[str] | None = None,
    ) -> ReviewReport:
        """汇总审查结果生成报告。

        Args:
            rule_issues: 规则引擎发现的问题列表。
            files: 被审查的文件列表。
            llm_text: LLM 自然语言审查文本。
            highlights: 代码亮点（可选）。

        Returns:
            ReviewReport 实例。
        """
        crit = sum(1 for i in rule_issues if i.severity == Severity.CRITICAL)
        warn = sum(1 for i in rule_issues if i.severity == Severity.WARNING)
        sugg = sum(1 for i in rule_issues if i.severity == Severity.SUGGESTION)

        reviewer = Reviewer()
        score = reviewer.calculate_score(rule_issues)

        return ReviewReport(
            file_count=len(files),
            total_issues=len(rule_issues),
            critical=crit,
            warning=warn,
            suggestion=sugg,
            issues=rule_issues,
            highlights=highlights or [],
            llm_review_text=llm_text,
            score=score,
        )

    @staticmethod
    def save_report(report: ReviewReport, output_path: str) -> str:
        """保存报告到文件。

        Args:
            report: 审查报告。
            output_path: 输出路径。

        Returns:
            输出文件的绝对路径。
        """
        tz = timezone(timedelta(hours=8))
        header = f"<!-- 生成时间: {datetime.now(tz).isoformat()} -->\n\n"
        content = header + report.to_markdown()

        path = Path(output_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path)

    @staticmethod
    def format_issues_for_display(issues: list[ReviewIssue]) -> str:
        """格式化为 CLI 友好的展示文本。

        Args:
            issues: 问题列表。

        Returns:
            格式化的文本。
        """
        if not issues:
            return "✅ 规则检查未发现任何问题。"

        lines = [f"共发现 {len(issues)} 个规则检查问题：\n"]
        for issue in issues:
            lines.append(issue.to_markdown())
        return "\n".join(lines)

    @staticmethod
    def get_score_grade(score: float) -> str:
        """根据评分返回等级标签。"""
        if score >= 90:
            return "[green]优秀[/green]"
        elif score >= 70:
            return "[yellow]良好[/yellow]"
        elif score >= 50:
            return "[orange1]及格[/orange1]"
        else:
            return "[red]需改进[/red]"
