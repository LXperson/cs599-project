"""
审查引擎

协调 LLM 审查与基于规则的审查，生成综合审查结果。
设计原则：规则引擎产出结构化 Issue，LLM 产出自然语言审查文本，
两者在报告层合并展示。
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_openai import ChatOpenAI

from src.config.prompts import REVIEW_FILE_PROMPT
from src.config.settings import settings
from src.review.rules import (
    BUILTIN_RULES,
    Category,
    Severity,
)

logger = logging.getLogger("codesage")


# ---- 严重级别显示映射 ----
SEVERITY_EMOJI: dict[Severity, str] = {
    Severity.CRITICAL: "🔴",
    Severity.WARNING: "🟡",
    Severity.SUGGESTION: "🔵",
}

# 严重级别权重（用于评分计算）
SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.CRITICAL: -15.0,
    Severity.WARNING: -5.0,
    Severity.SUGGESTION: -1.0,
}


@dataclass
class ReviewIssue:
    """单条规则引擎发现的审查问题。"""

    severity: Severity
    category: Category
    rule_id: str
    file_path: str
    line: int | None
    title: str
    description: str
    suggestion: str
    source: str = "rule"

    def to_markdown(self) -> str:
        emoji = SEVERITY_EMOJI.get(self.severity, "⚪")
        line_info = f"第 {self.line} 行" if self.line else "—"
        return (
            f"- **{emoji} [{self.severity.value.upper()}]** `{self.rule_id}` — {self.title}\n"
            f"  - 文件: `{self.file_path}` ({line_info})\n"
            f"  - 问题: {self.description}\n"
            f"  - 建议: {self.suggestion}\n"
        )


@dataclass
class ReviewReport:
    """完整审查报告。"""

    file_count: int
    total_issues: int
    critical: int
    warning: int
    suggestion: int
    issues: list[ReviewIssue] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    # LLM 自然语言审查文本（原始输出）
    llm_review_text: str = ""
    # 综合评分 (0-100)
    score: float = 100.0

    def summary(self) -> str:
        return (
            f"审查 {self.file_count} 个文件，发现 {self.total_issues} 个问题 "
            f"(🔴{self.critical} / 🟡{self.warning} / 🔵{self.suggestion}) | "
            f"综合评分: {self.score:.1f}/100"
        )

    def to_markdown(self) -> str:
        lines = [
            "# CodeSage 代码审查报告\n",
            "## 📊 概览",
            f"- 审查文件数: {self.file_count}",
            f"- 发现问题总数: {self.total_issues}",
            f"  - 🔴 严重: {self.critical}",
            f"  - 🟡 警告: {self.warning}",
            f"  - 🔵 建议: {self.suggestion}",
            f"- **综合评分: {self.score:.1f}/100**\n",
        ]

        if self.issues:
            lines.append("## 🔍 规则检查问题\n")
            sorted_issues = sorted(
                self.issues,
                key=lambda i: (
                    {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.SUGGESTION: 2}[i.severity]
                ),
            )
            for issue in sorted_issues:
                lines.append(issue.to_markdown())

        if not self.issues:
            lines.append("## ✅ 规则检查未发现问题。\n")

        if self.llm_review_text:
            lines.append("## 🤖 AI 深度分析")
            lines.append(self.llm_review_text)

        if self.highlights:
            lines.append("\n## 💡 代码亮点\n")
            for h in self.highlights:
                lines.append(f"- {h}")

        return "\n".join(lines)


class Reviewer:
    """代码审查引擎。

    双引擎架构：
    - rule_review: 基于内建正则规则的快速结构化审查
    - llm_review: 基于大模型的自然语言深度语义审查（返回原始文本）

    健壮性设计：
    - LLM 调用自动重试（次数由 LLM_RETRIES 环境变量控制）
    - 降级策略：LLM 失败时仅输出规则引擎结果
    """

    def __init__(self) -> None:
        self._llm: ChatOpenAI | None = None

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
            )
        return self._llm

    def call_llm_with_retry(self, prompt: str, retries: int = -1) -> tuple[str, bool]:
        """带重试和指数退避的 LLM 调用（公开接口，供 agent 节点调用）。

        Args:
            prompt: 完整的提示词。
            retries: 最大重试次数。默认从 LLM_RETRIES 环境变量读取。
        """
        import time as _time
        if retries < 0:
            retries = max(1, int(settings.LLM_RETRIES))

        for attempt in range(1, retries + 1):
            try:
                logger.debug("LLM 调用 (尝试 %d/%d)", attempt, retries)
                response = self.llm.invoke(prompt)
                text = response.content.strip() if response.content else ""
                if not text:
                    continue
                logger.info("LLM 返回 %d 字符", len(text))
                return text, True
            except Exception as e:
                logger.warning(
                    "LLM 调用失败 (尝试 %d/%d): %s", attempt, retries, e
                )
                if attempt < retries:
                    wait = min(2 ** attempt, 10)  # 指数退避，最大 10s
                    _time.sleep(wait)

        error_msg = f"LLM 调用在 {retries} 次尝试后均失败"
        logger.error(error_msg)
        return f"[{error_msg}]，已降级为规则引擎审查。", False

    def rule_review(self, code: str, language: str, file_path: str) -> list[ReviewIssue]:
        """基于内建规则进行快速审查，不调用 LLM。

        Args:
            code: 源代码内容。
            language: 语言标识。
            file_path: 文件路径。

        Returns:
            结构化的问题列表。
        """
        issues: list[ReviewIssue] = []
        lines = code.splitlines()

        for rule in BUILTIN_RULES:
            pattern = rule.patterns.get(language)
            if not pattern:
                continue

            try:
                for i, line in enumerate(lines, start=1):
                    if re.search(pattern, line, re.IGNORECASE):
                        issues.append(
                            ReviewIssue(
                                severity=rule.severity,
                                category=rule.category,
                                rule_id=rule.rule_id,
                                file_path=file_path,
                                line=i,
                                title=rule.title,
                                description=rule.description,
                                suggestion=rule.suggestion,
                                source="rule",
                            )
                        )
            except re.error:
                continue

        # 函数长度检查
        if language in ("python",):
            issues.extend(self._check_function_length(lines, file_path))

        return issues

    def llm_review(
        self, code: str, language: str, file_path: str, max_code_len: int = 8000
    ) -> tuple[str, bool]:
        """使用 LLM 进行深度语义审查（带重试和降级）。

        Returns:
            (review_text, success): LLM 返回的原始 Markdown 审查文本和是否成功。
        """
        if len(code) > max_code_len:
            code = code[:max_code_len] + "\n\n# ... (代码已截断)"

        prompt = REVIEW_FILE_PROMPT.format(
            file_path=file_path, language=language, code=code
        )

        return self.call_llm_with_retry(prompt)

    def combined_review(
        self, code: str, language: str, file_path: str
    ) -> tuple[list[ReviewIssue], str]:
        """组合审查：规则 + LLM 双引擎（LLM 失败时自动降级）。

        Returns:
            (rule_issues, llm_text): 规则引擎的结构化问题和 LLM 的自然语言文本。
        """
        rule_issues = self.rule_review(code, language, file_path)

        llm_text = ""
        if len(code) < 8000 and language not in ("unknown", "markdown", "json", "yaml"):
            try:
                llm_text, _success = self.llm_review(code, language, file_path)
                if not _success:
                    logger.warning("LLM 审查降级：仅输出规则引擎结果")
            except Exception as e:
                logger.error("LLM 审查异常，已跳过: %s", e)

        return rule_issues, llm_text

    def calculate_score(self, issues: list[ReviewIssue]) -> float:
        """基于问题列表计算代码质量评分 (0-100)。"""
        score = 100.0
        for issue in issues:
            w = SEVERITY_WEIGHT.get(issue.severity, 0)
            score += w
        return max(0.0, min(100.0, round(score, 1)))

    # ---- 私有方法 ----

    @staticmethod
    def _check_function_length(
        lines: list[str], file_path: str, language: str
    ) -> list[ReviewIssue]:
        """检查 Python 函数行数。"""
        issues = []
        func_start = 0
        func_depth = 0
        in_function = False
        func_name = ""

        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if not in_function and stripped.startswith("def "):
                in_function = True
                func_start = i
                func_depth = 0
                func_name = stripped.split("(")[0].replace("def ", "").strip()
            elif in_function:
                if "(" in stripped:
                    func_depth += stripped.count("(")
                if ")" in stripped:
                    func_depth -= stripped.count(")")

                if func_depth <= 0 and (
                    stripped.startswith("def ") or stripped.startswith("class ")
                    or i == len(lines)
                    or (stripped and not stripped.startswith((" ", "\t", "(", ")", "@")))
                ):
                    func_length = i - func_start
                    if func_length > 50:
                        issues.append(
                            ReviewIssue(
                                severity=Severity.SUGGESTION,
                                category=Category.QUALITY,
                                rule_id="QUAL-001",
                                file_path=file_path,
                                line=func_start,
                                title="函数过长",
                                description=f"函数 `{func_name}()` 约 {func_length} 行，建议拆分。",
                                suggestion="将长函数拆分为多个短小的函数。",
                                source="rule",
                            )
                        )
                    in_function = False
                    if stripped.startswith("def "):
                        in_function = True
                        func_start = i
                        func_depth = 0
                        func_name = (
                            stripped.split("(")[0].replace("def ", "").strip()
                        )

        return issues
