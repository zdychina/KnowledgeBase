"""GitHub Archive API 代码同步服务。

从 https://github.com/fzl194/KnowledgeBase/archive/refs/heads/master.tar.gz
下载最新 tarball，只解压白名单目录到 /app/。
"""
from __future__ import annotations

import logging
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://github.com/fzl194/KnowledgeBase/archive/refs/heads/master.tar.gz"

# 白名单：只覆盖这些目录
SYNC_DIRS = {"knowledge_mining", "llm_service", "main_control_service", "mcp_server"}

# 排除的子目录（即使是白名单目录内也不覆盖）
EXCLUDE_SUBDIRS = {"main_control_service/config"}

DOWNLOAD_TIMEOUT = 60


@dataclass(slots=True)
class CodeSyncResult:
    ok: bool
    updated_dirs: list[str]
    file_count: int
    error: str | None = None


def sync_from_github(app_dir: Path | None = None) -> CodeSyncResult:
    """从 GitHub 下载最新 tarball 并解压白名单目录。

    Args:
        app_dir: 目标根目录，默认 /app
    """
    target_root = app_dir or Path("/app")
    tmp_path = Path(tempfile.gettempdir()) / f"cmkb-sync-{int(time.time())}.tar.gz"

    # 1. 下载
    try:
        logger.info("Downloading %s", ARCHIVE_URL)
        urllib.request.urlretrieve(ARCHIVE_URL, tmp_path)
        logger.info("Downloaded to %s (%.1f KB)", tmp_path, tmp_path.stat().st_size / 1024)
    except Exception as e:
        logger.error("Download failed: %s", e)
        if tmp_path.exists():
            tmp_path.unlink()
        return CodeSyncResult(ok=False, updated_dirs=[], file_count=0, error=f"下载失败: {e}")

    # 2. 解压
    updated_dirs: set[str] = set()
    file_count = 0

    try:
        with tarfile.open(tmp_path, "r:gz") as tar:
            for member in tar.getmembers():
                # 路径遍历检查
                if ".." in member.name:
                    continue

                # tarball 路径格式: KnowledgeBase-master/{dir}/...
                parts = Path(member.name).parts
                if len(parts) < 3:
                    continue  # 根目录或单层文件

                # parts[0] = "KnowledgeBase-master", parts[1] = dir name
                dir_name = parts[1]

                if dir_name not in SYNC_DIRS:
                    continue

                # 排除检查: main_control_service/config/...
                rel_after_dir = "/".join(parts[2:])
                first_segment = rel_after_dir.split("/")[0] if "/" in rel_after_dir else ""
                exclude_key = f"{dir_name}/{first_segment}" if first_segment else ""
                if exclude_key in EXCLUDE_SUBDIRS:
                    continue

                # 只处理文件（跳过目录条目）
                if not member.isfile():
                    continue

                # 提取到目标目录
                dest = target_root / dir_name / rel_after_dir
                dest.parent.mkdir(parents=True, exist_ok=True)

                with tar.extractfile(member) as src:
                    if src:
                        dest.write_bytes(src.read())

                updated_dirs.add(dir_name)
                file_count += 1

    except Exception as e:
        logger.error("Extract failed: %s", e)
        return CodeSyncResult(ok=False, updated_dirs=list(updated_dirs), file_count=file_count, error=f"解压失败: {e}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    logger.info("Sync complete: %d files in %s", file_count, updated_dirs)
    return CodeSyncResult(ok=True, updated_dirs=sorted(updated_dirs), file_count=file_count)
