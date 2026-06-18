"""
静态分析工具

集成外部静态分析器（pylint, ruff, mypy 等），
自动对文件进行分析并将结果结构化返回给 Agent。
"""

import subprocess
from pathlib import Path


class StaticAnalyzer:
    """代码静态分析器。

    作为 Agent 工具，对指定文件执行静态分析，
    返回结构化的分析结果。
    """

    SUPPORTED_TOOLS: dict[str, dict] = {
        "ruff": {
            "extensions": {".py"},
            "cmd": ["ruff", "check", "--output-format", "text", "{file}"],
            "description": "Python 快速 linter & 修复工具",
        },
    }

    @classmethod
    def analyze(cls, file_path: str, tool: str = "ruff") -> dict:
        """对指定文件执行静态分析。

        Args:
            file_path: 要分析的文件路径。
            tool: 静态分析工具名称。

        Returns:
            {"success": bool, "tool": str, "issues": list[dict], "error": str | None}
        """
        path = Path(file_path).resolve()
        if not path.exists() or not path.is_file():
            return {
                "success": False,
                "tool": tool,
                "issues": [],
                "error": f"文件不存在: {file_path}",
            }

        tool_config = cls.SUPPORTED_TOOLS.get(tool)
        if tool_config is None:
            return {
                "success": False,
                "tool": tool,
                "issues": [],
                "error": f"不支持的工具: {tool}",
            }

        suffix = path.suffix.lower()
        if suffix not in tool_config["extensions"]:
            return {
                "success": True,
                "tool": tool,
                "issues": [],
                "error": None,
            }

        try:
            cmd = [arg.replace("{file}", str(path)) for arg in tool_config["cmd"]]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            issues = cls._parse_ruff_output(result.stdout, result.stderr)

            return {
                "success": True,
                "tool": tool,
                "issues": issues,
                "error": None,
            }
        except FileNotFoundError:
            return {
                "success": False,
                "tool": tool,
                "issues": [],
                "error": f"未安装 {tool}。请运行: pip install {tool}",
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "tool": tool,
                "issues": [],
                "error": f"分析超时: {file_path}",
            }
        except Exception as e:
            return {
                "success": False,
                "tool": tool,
                "issues": [],
                "error": f"分析异常: {e}",
            }

    @staticmethod
    def _parse_ruff_output(stdout: str, stderr: str) -> list[dict]:
        """解析 ruff/类似工具的输出行。

        格式：file:line:col: CODE message
        """
        issues = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # ruff format: file:line:col: CODE description
            parts = line.split(":", 3)
            if len(parts) >= 4:
                issues.append(
                    {
                        "line": parts[1].strip(),
                        "column": parts[2].strip(),
                        "code": parts[3].split()[0] if parts[3].strip() else "UNKNOWN",
                        "message": parts[3].strip(),
                    }
                )
            else:
                issues.append({"line": "?", "column": "?", "code": "PARSE", "message": line})
        if stderr.strip():
            issues.append({"line": "?", "column": "?", "code": "STDERR", "message": stderr.strip()})
        return issues
