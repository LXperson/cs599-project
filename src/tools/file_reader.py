"""
文件读取工具

提供文件系统访问能力，支持安全读取、目录列举、模糊搜索和集中备份。
"""

import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.config.settings import settings

SOURCE_EXTS = {".py", ".java", ".js", ".ts", ".go", ".rs", ".cpp", ".c",
               ".h", ".hpp", ".cs", ".vue", ".swift", ".kt", ".rb", ".php",
               ".sh", ".sql", ".r", ".scala", ".dart"}
TZ = timezone(timedelta(hours=8))


def _get_backup_dir() -> Path:
    from src.config.settings import settings
    backup_dir = settings.BACKUP_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _collect_candidates(search_dir: Path, query: str, recursive: bool = False) -> list[Path]:
    if not search_dir.is_dir():
        return []
    q = query.lower()
    candidates: list[tuple[int, Path]] = []
    iterator = search_dir.rglob("*") if recursive else search_dir.iterdir()
    for p in iterator:
        if p.name.startswith("."):
            continue
        pname = p.name.lower()
        if pname.startswith(q):
            candidates.append((0, p))
        elif q in pname:
            candidates.append((1, p))
    candidates.sort(key=lambda x: x[0])
    return [c[1] for c in candidates]


class FileReader:
    EXTENSION_LANGUAGE: dict[str, str] = {
        ".py": "python", ".java": "java", ".js": "javascript",
        ".ts": "typescript", ".go": "go", ".rs": "rust",
        ".cpp": "cpp", ".c": "c", ".h": "c", ".hpp": "cpp",
        ".cs": "csharp", ".rb": "ruby", ".php": "php",
        ".sh": "bash", ".yaml": "yaml", ".yml": "yaml",
        ".json": "json", ".xml": "xml", ".sql": "sql",
        ".r": "r", ".kt": "kotlin", ".swift": "swift",
        ".md": "markdown", ".vue": "vue",
    }

    # ---- 文件读取 ----
    @staticmethod
    def read_file(file_path: str, max_lines: int | None = None) -> dict:
        path = Path(file_path).resolve()
        try:
            if not path.exists():
                return {"success": False, "content": "", "language": "unknown",
                        "line_count": 0, "error": f"文件不存在: {file_path}"}
            if not path.is_file():
                return {"success": False, "content": "", "language": "unknown",
                        "line_count": 0, "error": f"路径不是文件: {file_path}"}
            file_size = path.stat().st_size
            if file_size > settings.MAX_FILE_SIZE_BYTES:
                return {"success": False, "content": "", "language": "unknown",
                        "line_count": 0,
                        "error": f"文件过大: {file_size/1024:.0f}KB "
                                 f"(限制 {settings.MAX_FILE_SIZE_BYTES/1024:.0f}KB)"}
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            truncated = bool(max_lines and len(lines) > max_lines)
            if truncated:
                lines = lines[:max_lines]
            content = "".join(lines)
            language = FileReader.EXTENSION_LANGUAGE.get(
                path.suffix.lower(), path.suffix.lstrip("."))
            return {"success": True, "content": content, "language": language,
                    "line_count": len(lines), "truncated": truncated, "error": None}
        except PermissionError:
            return {"success": False, "content": "", "language": "unknown",
                    "line_count": 0, "error": f"无读取权限: {file_path}"}
        except Exception as e:
            return {"success": False, "content": "", "language": "unknown",
                    "line_count": 0, "error": f"读取失败: {e}"}

    # ---- 文件写入 ----
    @staticmethod
    def write_file(file_path: str, content: str) -> dict:
        path = Path(file_path).resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return {"success": True, "written_bytes": len(content.encode("utf-8")),
                    "error": None}
        except PermissionError:
            return {"success": False, "written_bytes": 0,
                    "error": f"无写入权限: {file_path}"}
        except Exception as e:
            return {"success": False, "written_bytes": 0,
                    "error": f"写入失败: {e}"}

    # ---- 集中备份 ----
    @staticmethod
    def backup_file(file_path: str) -> dict:
        """备份文件到项目根 .codesage/backups/<filename>.<timestamp>.bak"""
        path = Path(file_path).resolve()
        if not path.is_file():
            return {"success": False, "backup_path": "",
                    "error": f"文件不存在: {file_path}"}
        try:
            backup_dir = _get_backup_dir()
            ts = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
            backup_name = f"{path.name}.{ts}.bak"
            backup_path = backup_dir / backup_name
            shutil.copy2(path, backup_path)
            return {"success": True, "backup_path": str(backup_path), "error": None}
        except Exception as e:
            return {"success": False, "backup_path": "", "error": f"备份失败: {e}"}

    @staticmethod
    def restore_from_backup(file_path: str, backup_path: str) -> dict:
        """从备份恢复文件到指定路径。"""
        try:
            shutil.copy2(backup_path, file_path)
            return {"success": True, "error": None}
        except Exception as e:
            return {"success": False, "error": f"恢复失败: {e}"}

    @staticmethod
    def list_backups(file_path: str) -> dict:
        """列出某个文件的所有备份（集中目录）。"""
        path = Path(file_path).resolve()
        backup_dir = _get_backup_dir()
        if not backup_dir.is_dir():
            return {"success": True, "backups": [], "error": None}
        try:
            prefix = f"{path.name}."
            items = []
            for b in sorted(backup_dir.glob(f"{prefix}*"), reverse=True)[:20]:
                ts_str = b.stem.replace(f"{path.name}.", "").replace(".bak", "")
                items.append({"path": str(b), "timestamp": ts_str})
            return {"success": True, "backups": items, "error": None}
        except Exception as e:
            return {"success": False, "backups": [], "error": str(e)}

    # ---- 目录列举 ----
    @staticmethod
    def list_directory(directory: str, pattern: str = "*",
                       recursive: bool = False) -> dict:
        path = Path(directory).resolve()
        try:
            if not path.exists() or not path.is_dir():
                return {"success": False, "files": [],
                        "error": f"目录不存在: {directory}"}
            glob_func = path.rglob if recursive else path.glob
            files = [str(p) for p in glob_func(pattern) if p.is_file()]
            files = [f for f in files
                     if not any(part.startswith(".") for part in Path(f).parts)]
            binary_exts = {".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".o", ".obj"}
            files = [f for f in files if Path(f).suffix.lower() not in binary_exts]
            return {"success": True, "files": files, "error": None}
        except PermissionError:
            return {"success": False, "files": [],
                    "error": f"无访问权限: {directory}"}
        except Exception as e:
            return {"success": False, "files": [], "error": f"列举失败: {e}"}

    # ---- 模糊搜索 ----
    @staticmethod
    def fuzzy_find(
        target: str, base_dir: str = ".",
        max_results: int = 30, recursive: bool = True,
    ) -> dict:
        base = Path(base_dir).resolve()
        target_path = Path(target)
        if target_path.is_absolute():
            exact = target_path
            search_parent = target_path.parent
        else:
            exact = base / target
            search_parent = exact.parent
        if exact.exists():
            if exact.is_dir():
                py_files = list(exact.glob("*.py"))
                candidates = py_files if py_files else list(exact.glob("*"))
                items = sorted(str(p.resolve()) for p in candidates if p.is_file())
                return {"success": True, "items": items[:max_results],
                        "search_dir": str(exact), "is_dir": True,
                        "resolved_path": str(exact), "error": None}
            return {"success": True, "items": [str(exact.resolve())],
                    "search_dir": str(search_parent), "is_dir": False,
                    "resolved_path": str(exact.resolve()), "error": None}
        name = target_path.name if target_path.name else target
        if search_parent.is_dir():
            candidates = _collect_candidates(search_parent, name, recursive=True)
            if candidates:
                items = [str(p.resolve()) for p in candidates[:max_results]]
                return {"success": True, "items": items,
                        "search_dir": str(search_parent),
                        "is_dir": None, "resolved_path": None, "error": None}
        qname = target.lstrip("./\\")
        candidates = _collect_candidates(base, qname, recursive=True)
        if candidates:
            items = [str(p.resolve()) for p in candidates[:max_results]]
            return {"success": True, "items": items,
                    "search_dir": str(base),
                    "is_dir": None, "resolved_path": None, "error": None}
        return {"success": True, "items": [], "search_dir": str(base),
                "is_dir": None, "resolved_path": None,
                "error": f"未找到匹配: {target}"}
