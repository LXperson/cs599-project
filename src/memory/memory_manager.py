"""
记忆管理模块

ConversationMemory：会话级结构化记忆，贯穿交互生命周期。
支持 JSON 持久化到 .codesage/memory.json，重启恢复。
追踪审查历史、文件操作、对话轮次，为 LLM 提供上下文。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

TZ = timezone(timedelta(hours=8))


@dataclass
class FileOp:
    """记录对文件的操作。"""
    action: str         # "fix" | "review" | "test" | "backup" | "undo"
    file_path: str      # 绝对路径
    backup_path: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(TZ).strftime("%Y%m%d_%H%M%S"))


@dataclass
class ConversationTurn:
    role: str
    content: str
    action: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationMemory:
    """交互会话记忆。支持序列化到磁盘。"""

    history: list[ConversationTurn] = field(default_factory=list)
    file_ops: list[FileOp] = field(default_factory=list)

    last_review_dir: str = ""
    last_review_files: list[str] = field(default_factory=list)
    last_review_issues: int = 0
    last_review_score: float = 100.0

    @property
    def max_turns(self) -> int:
        try:
            from src.config.settings import settings
            return settings.MEMORY_MAX_TURNS
        except Exception:
            return 30

    @property
    def max_file_ops(self) -> int:
        try:
            from src.config.settings import settings
            return settings.MEMORY_MAX_FILE_OPS
        except Exception:
            return 50

    # ---- 对话 ----
    def add_user_turn(self, content: str) -> None:
        self.history.append(ConversationTurn(role="user", content=content))
        self._trim()

    def add_agent_turn(self, content: str, action: str = "",
                       meta: dict[str, Any] | None = None) -> None:
        self.history.append(ConversationTurn(
            role="agent", content=content, action=action, meta=meta or {}))
        self._trim()

    # ---- 文件操作追踪 ----
    def record_file_op(self, action: str, file_path: str,
                       backup_path: str = "") -> None:
        self.file_ops.append(FileOp(
            action=action, file_path=file_path, backup_path=backup_path))
        limit = self.max_file_ops
        if len(self.file_ops) > limit:
            self.file_ops = self.file_ops[-limit:]

    def recent_file_ops(self, n: int = 10) -> list[FileOp]:
        return self.file_ops[-n:]

    def find_ops_for_file(self, file_path: str) -> list[FileOp]:
        path = str(Path(file_path).resolve()) if file_path else ""
        return [op for op in self.file_ops if op.file_path == path]

    def last_modified_files(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for op in reversed(self.file_ops):
            if op.action == "fix" and op.file_path not in seen:
                seen.add(op.file_path)
                result.append(op.file_path)
        return result

    # ---- 审查 ----
    def record_review_result(self, directory: str, files: list[str],
                             issues: int, score: float) -> None:
        self.last_review_dir = directory
        self.last_review_files = files
        self.last_review_issues = issues
        self.last_review_score = score

    # ---- 持久化 ----
    def save_to_disk(self) -> None:
        """保存记忆到 .codesage/memory.json。"""
        from src.config.settings import settings
        settings.ensure_dirs()
        data = {
            "last_review_dir": self.last_review_dir,
            "last_review_files": self.last_review_files,
            "last_review_issues": self.last_review_issues,
            "last_review_score": self.last_review_score,
            "file_ops": [
                {"action": o.action, "file_path": o.file_path,
                 "backup_path": o.backup_path, "timestamp": o.timestamp}
                for o in self.file_ops[-20:]  # 只保留最近 20 条
            ],
            "history": [
                {"role": t.role, "content": t.content[:200],
                 "action": t.action, "meta": t.meta}
                for t in self.history[-20:]  # 只保留最近 20 轮
            ],
        }
        try:
            settings.MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            settings.MEMORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
        except Exception:
            pass

    @classmethod
    def load_from_disk(cls) -> ConversationMemory:
        """从 .codesage/memory.json 恢复记忆。"""
        mem = cls()
        from src.config.settings import settings
        if not settings.MEMORY_FILE.exists():
            return mem
        try:
            data = json.loads(settings.MEMORY_FILE.read_text(encoding="utf-8"))
            mem.last_review_dir = data.get("last_review_dir", "")
            mem.last_review_files = data.get("last_review_files", [])
            mem.last_review_issues = data.get("last_review_issues", 0)
            mem.last_review_score = data.get("last_review_score", 100.0)
            for op_data in data.get("file_ops", []):
                mem.file_ops.append(FileOp(
                    action=op_data.get("action", ""),
                    file_path=op_data.get("file_path", ""),
                    backup_path=op_data.get("backup_path", ""),
                    timestamp=op_data.get("timestamp", ""),
                ))
            for turn_data in data.get("history", []):
                mem.history.append(ConversationTurn(
                    role=turn_data.get("role", ""),
                    content=turn_data.get("content", ""),
                    action=turn_data.get("action", ""),
                    meta=turn_data.get("meta", {}),
                ))
        except Exception:
            pass
        return mem

    # ---- 上下文生成 ----
    def context_for_llm(self) -> str:
        parts: list[str] = []
        if self.last_review_dir:
            parts.append(
                f"最近审查目录: {self.last_review_dir}"
                f"（{len(self.last_review_files)} 文件，"
                f"{self.last_review_issues} 问题，评分 {self.last_review_score:.0f}/100）"
            )
            if self.last_review_files:
                parts.append("涉及文件: " + ", ".join(self.last_review_files[:5])
                             + ("..." if len(self.last_review_files) > 5 else ""))
        recent_ops = self.file_ops[-5:]
        if recent_ops:
            parts.append("最近文件操作：")
            for op in recent_ops:
                parts.append(f"  [{op.action}] {Path(op.file_path).name} @ {op.timestamp}")
                if op.backup_path:
                    parts.append(f"    备份: {op.backup_path}")
        recent = self.history[-8:]
        if recent:
            parts.append("近期对话：")
            for t in recent:
                label = "用户" if t.role == "user" else "CodeSage"
                parts.append(f"  [{label}]{'(' + t.action + ')' if t.action else ''} "
                             f"{t.content[:100]}")
        return "\n".join(parts) if parts else "（新会话，无历史上下文）"

    def _trim(self) -> None:
        if len(self.history) > self.max_turns:
            self.history = self.history[-self.max_turns:]

    def clear(self) -> None:
        self.history.clear()
        self.file_ops.clear()
        self.last_review_dir = ""
        self.last_review_files = []
        self.last_review_issues = 0
        self.last_review_score = 100.0


class MemoryManager:
    """LangGraph Checkpoint 持久化（保留原接口兼容）。"""

    def __init__(self, max_tokens: int = 8000) -> None:
        self._checkpointer: MemorySaver = MemorySaver()
        self._session_memory: dict[str, Any] = {}
        self._max_tokens = max_tokens

    @property
    def checkpointer(self) -> MemorySaver:
        return self._checkpointer

    def store_context(self, key: str, value: Any) -> None:
        self._session_memory[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        return self._session_memory.get(key, default)

    def clear_session(self) -> None:
        self._session_memory.clear()

    def summarize_for_context(self, text: str, max_chars: int = 4000) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n... (内容已截断)"
