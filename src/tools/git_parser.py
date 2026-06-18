"""
Git diff 解析工具

解析 Git diff 输出，提取变更信息供 Agent 审查。
"""

import subprocess
from pathlib import Path


class GitParser:
    """Git 操作解析器。

    从 Git 仓库中提取 diff 信息，供 Agent 进行增量审查。
    """

    @staticmethod
    def get_diff(
        repo_path: str | None = None,
        staged: bool = True,
        target_branch: str | None = None,
    ) -> dict:
        """获取 Git diff。

        Args:
            repo_path: 仓库路径，None 使用当前目录。
            staged: True 获取已暂存的 diff，False 获取未暂存的 diff。
            target_branch: 比较的目标分支，如 "main"。

        Returns:
            {"success": bool, "diff": str, "summary": str, "error": str | None}
        """
        cwd = str(Path(repo_path).resolve()) if repo_path else None
        try:
            if target_branch:
                # 与目标分支比较
                cmd = ["git", "diff", target_branch, "--", "."]
            elif staged:
                cmd = ["git", "diff", "--cached"]
            else:
                cmd = ["git", "diff"]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=30,
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "diff": "",
                    "summary": "",
                    "error": f"Git 命令失败:\n{result.stderr}",
                }

            diff_text = result.stdout
            if not diff_text.strip():
                return {
                    "success": True,
                    "diff": "",
                    "summary": "无变更",
                    "error": None,
                }

            summary = GitParser._summarize_diff(diff_text)

            return {
                "success": True,
                "diff": diff_text,
                "summary": summary,
                "error": None,
            }
        except FileNotFoundError:
            return {
                "success": False,
                "diff": "",
                "summary": "",
                "error": "未找到 Git 命令。请确认已安装 Git。",
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "diff": "",
                "summary": "",
                "error": "Git diff 操作超时。",
            }
        except Exception as e:
            return {
                "success": False,
                "diff": "",
                "summary": "",
                "error": f"Git 操作异常: {e}",
            }

    @staticmethod
    def _summarize_diff(diff_text: str) -> str:
        """从 diff 文本中提取摘要。"""
        files_changed: list[str] = []
        additions = 0
        deletions = 0

        for line in diff_text.splitlines():
            if line.startswith("+++ "):
                file_path = line[6:]
                if file_path != "/dev/null":
                    files_changed.append(file_path)
            elif line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1

        return (
            f"变更文件数: {len(files_changed)}\n"
            f"新增行: +{additions}\n"
            f"删除行: -{deletions}\n"
            f"涉及文件: {', '.join(files_changed[:10])}"
            + ("..." if len(files_changed) > 10 else "")
        )

    @staticmethod
    def is_git_repo(repo_path: str | None = None) -> bool:
        """检查是否为 Git 仓库。"""
        cwd = str(Path(repo_path).resolve()) if repo_path else None
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                capture_output=True,
                cwd=cwd,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False
