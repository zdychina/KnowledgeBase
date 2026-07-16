"""Upload configuration — all values from .env via pydantic-settings."""
from __future__ import annotations

from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings

_REPO_ROOT = Path(__file__).resolve().parents[3]  # knowledge_mining/mining/infra/ -> CoreMasterKB/


class UploadConfig(BaseSettings):
    """Upload limits and storage configuration.

    Env vars:
        UPLOAD_ROOT:                    base directory for uploads (default: ./uploads)
        UPLOAD_MAX_FILE_SIZE:           max single regular file size in bytes (default: 100MB)
        UPLOAD_MAX_ARCHIVE_SIZE:        max archive file size in bytes (default: 500MB)
        UPLOAD_MAX_FILES_PER_REQUEST:   max files per upload request (default: 100)
        UPLOAD_DISK_RESERVE_BYTES:      minimum free disk space to keep (default: 1GB)
        UPLOAD_ARCHIVE_EXTENSIONS:      comma-separated archive extensions (default: .zip,.rar)
    """

    upload_root: str = "./uploads"
    upload_max_file_size: int = 100 * 1024 * 1024          # 100MB
    upload_max_archive_size: int = 500 * 1024 * 1024       # 500MB
    upload_max_files_per_request: int = 100
    upload_disk_reserve_bytes: int = 1024 * 1024 * 1024    # 1GB
    upload_archive_extensions: str = ".zip"

    model_config = {
        "env_prefix": "",
        "env_file": str(_REPO_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @computed_field
    @property
    def archive_exts_set(self) -> frozenset[str]:
        """Extensions that will be auto-extracted after upload (ZIP only — pure Python)."""
        return frozenset(e.strip().lower() for e in self.upload_archive_extensions.split(",") if e.strip())

    @computed_field
    @property
    def max_file_size_mb(self) -> int:
        return self.upload_max_file_size // (1024 * 1024)

    @computed_field
    @property
    def max_archive_size_mb(self) -> int:
        return self.upload_max_archive_size // (1024 * 1024)

    @computed_field
    @property
    def upload_root_path(self) -> Path:
        return Path(self.upload_root).resolve()
