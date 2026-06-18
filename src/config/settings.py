"""
CodeSage 配置模块

所有配置通过环境变量注入，严禁硬编码 API Key。
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class Settings:
    """全局配置单例。"""

    # ---- 项目路径 ----
    PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
    CODESAGE_DIR: Path = PROJECT_ROOT / ".codesage"
    MEMORY_FILE: Path = CODESAGE_DIR / "memory.json"
    BACKUP_DIR: Path = CODESAGE_DIR / "backups"

    # ---- LLM 配置 ----
    LLM_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    LLM_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "4096"))

    # ---- LangSmith 可观测性 ----
    LANGSMITH_API_KEY: str = os.getenv("LANGSMITH_API_KEY", "")
    LANGSMITH_PROJECT: str = os.getenv("LANGSMITH_PROJECT", "cs599-project")

    # ---- Agent 配置 ----
    MAX_RECURSION: int = int(os.getenv("MAX_RECURSION", "15"))
    MAX_MEMORY_TOKENS: int = int(os.getenv("MAX_MEMORY_TOKENS", "8000"))

    # ---- 审查配置 ----
    MAX_FILE_SIZE_BYTES: int = int(os.getenv("MAX_FILE_SIZE_KB", "500")) * 1024
    MAX_DIR_FILES: int = int(os.getenv("MAX_DIR_FILES", "10"))

    # ---- LLM 调用配置 ----
    LLM_RETRIES: int = int(os.getenv("LLM_RETRIES", "3"))
    LLM_REQUEST_TIMEOUT: int = int(os.getenv("LLM_REQUEST_TIMEOUT", "120"))

    # ---- 记忆配置 ----
    MEMORY_MAX_TURNS: int = int(os.getenv("MEMORY_MAX_TURNS", "30"))
    MEMORY_MAX_FILE_OPS: int = int(os.getenv("MEMORY_MAX_FILE_OPS", "50"))

    @classmethod
    def ensure_dirs(cls) -> None:
        """确保 .codesage 相关目录存在。"""
        cls.CODESAGE_DIR.mkdir(parents=True, exist_ok=True)
        cls.BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def validate(cls) -> None:
        """校验必要配置是否存在。"""
        if not cls.LLM_API_KEY:
            raise ValueError(
                "DEEPSEEK_API_KEY 未设置。请复制 .env.example 为 .env 并填入 API Key。"
            )

    @classmethod
    def setup_langsmith(cls) -> None:
        """配置 LangSmith 可观测性（可选）。"""
        if cls.LANGSMITH_API_KEY:
            os.environ["LANGSMITH_API_KEY"] = cls.LANGSMITH_API_KEY
            os.environ["LANGSMITH_PROJECT"] = cls.LANGSMITH_PROJECT
            os.environ["LANGSMITH_TRACING"] = "true"


settings = Settings()
