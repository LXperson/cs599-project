"""
审查规则定义

定义结构化的代码审查规则，涵盖安全、质量、最佳实践等维度。
每条规则包含：ID、类别、严重级别、匹配条件、描述、建议。
"""

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    """严重级别。"""

    CRITICAL = "critical"    # 🔴 严重
    WARNING = "warning"      # 🟡 警告
    SUGGESTION = "suggestion"  # 🔵 建议


class Category(str, Enum):
    """规则类别。"""

    SECURITY = "security"
    QUALITY = "quality"
    BEST_PRACTICE = "best_practice"
    PERFORMANCE = "performance"
    STYLE = "style"


@dataclass
class ReviewRule:
    """单条审查规则定义。"""

    rule_id: str
    category: Category
    severity: Severity
    title: str
    description: str
    suggestion: str
    # 匹配正则（按语言维度区分）
    patterns: dict[str, str] = field(default_factory=dict)


# ---- 内建审查规则 ----

BUILTIN_RULES: list[ReviewRule] = [
    ReviewRule(
        rule_id="SEC-001",
        category=Category.SECURITY,
        severity=Severity.CRITICAL,
        title="硬编码密钥/密码",
        description="代码中包含硬编码的密码、API Key、Token 等敏感信息。",
        suggestion="将敏感信息存放在环境变量或密钥管理服务中，通过 os.getenv() 等方式读取。",
        patterns={
            "python": r"(password|secret|api_key|apikey|token)\s*=\s*['\"][^'\"]+['\"]",
            "java": r"(password|secret|apiKey|token)\s*=\s*\"[^\"]+\"",
        },
    ),
    ReviewRule(
        rule_id="SEC-002",
        category=Category.SECURITY,
        severity=Severity.WARNING,
        title="SQL 拼接风险",
        description="使用字符串拼接构造 SQL 查询，存在 SQL 注入风险。",
        suggestion="使用参数化查询（PreparedStatement / cursor.execute(query, params)）。",
        patterns={
            "python": r"""["']\s*SELECT\s.*\s*["'].*\+|f".*SELECT.*\{""",
            "java": r'"SELECT.*" *\+',
        },
    ),
    ReviewRule(
        rule_id="SEC-003",
        category=Category.SECURITY,
        severity=Severity.WARNING,
        title="调试代码未移除",
        description="提交中包含 print/console.log 等调试输出。",
        suggestion="移除调试代码，或使用 logging 框架的 DEBUG 级别替代。",
        patterns={
            "python": r"^\s*print\(",
            "java": r"System\.out\.print",
            "javascript": r"console\.(log|debug)\(",
        },
    ),
    ReviewRule(
        rule_id="QUAL-001",
        category=Category.QUALITY,
        severity=Severity.SUGGESTION,
        title="函数过长",
        description="函数/方法行数超过 50 行（不含空行和注释），影响可读性。",
        suggestion="将长函数拆分为多个短小的函数，每个函数只做一件事。",
        patterns={},
    ),
    ReviewRule(
        rule_id="QUAL-002",
        category=Category.QUALITY,
        severity=Severity.SUGGESTION,
        title="魔法数字",
        description="代码中存在未命名的数字字面量（0 和 1 除外）。",
        suggestion="将魔法数字提取为命名常量，提升代码可读性。",
        patterns={
            "python": r"(?<!\d)(?!0\b|1\b)[2-9]\d*(?!\s*[:=]\s*[\"'])(?![\d.])",
        },
    ),
    ReviewRule(
        rule_id="QUAL-003",
        category=Category.QUALITY,
        severity=Severity.WARNING,
        title="异常处理过于宽泛",
        description="使用裸露的 except: 或 except Exception: 捕获所有异常。",
        suggestion="仅捕获预期异常类型，并记录异常详情以便排查。",
        patterns={
            "python": r"^\s*except\s*(Exception)?\s*:\s*$",
            "java": r"catch\s*\(\s*Exception\s+\w+\s*\)",
        },
    ),
    ReviewRule(
        rule_id="BEST-001",
        category=Category.BEST_PRACTICE,
        severity=Severity.SUGGESTION,
        title="类 / 函数缺少文档字符串",
        description="公开类或函数缺少 docstring / Javadoc。",
        suggestion="为公开接口添加简洁的文档注释，说明功能、参数和返回值。",
        patterns={},
    ),
    ReviewRule(
        rule_id="PERF-001",
        category=Category.PERFORMANCE,
        severity=Severity.WARNING,
        title="循环内 I/O 操作",
        description="在循环内进行文件读取、网络请求、数据库查询等 I/O 操作。",
        suggestion="尽量批量操作，将 I/O 移出循环，或使用缓存/连接池。",
        patterns={
            "python": r"for\s+.+:\s*\n\s+(open|requests|urllib|cursor\.execute)",
        },
    ),
    ReviewRule(
        rule_id="PERF-002",
        category=Category.PERFORMANCE,
        severity=Severity.SUGGESTION,
        title="列表拼接性能问题",
        description="在循环中使用 + 拼接字符串或列表。",
        suggestion="使用 ''.join() 或列表推导式替代。",
        patterns={
            "python": r"\w+\s*=\s*\w+\s*\+\s*\w+\s*(#.*)?\n",
        },
    ),
]

# 按类别和严重级别建立索引
RULES_BY_CATEGORY: dict[Category, list[ReviewRule]] = {}
for _rule in BUILTIN_RULES:
    RULES_BY_CATEGORY.setdefault(_rule.category, []).append(_rule)
