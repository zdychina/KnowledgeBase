"""服务日志读取。

日志由 supervisor 按服务写在 /app/logs 下（见 docker/supervisord.conf），
单文件上限 50MB、保留 5 份轮转。本模块只读，负责：

  * 列出有哪些服务日志、各自多大、最后写入时间
  * 从文件**尾部**读取若干行（50MB 的文件不能整体读进内存）

安全边界：服务名一律按 LOG_DIR 下的实际文件校验，解析后必须仍位于
LOG_DIR 内，杜绝 `../` 路径穿越。main_control_service 的 IP 白名单中间件
（main.py 里 add_middleware(IpWhitelistMiddleware)）对本模块的端点同样生效。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# 容器内默认 /app/logs；本地开发时回落到仓库根的 logs/。
_DEFAULT_LOG_DIR = Path("/app/logs")
_REPO_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

# 一次最多返回多少行，防止前端拉爆。
MAX_LINES = 5000
DEFAULT_LINES = 200

# 带过滤条件时最多从尾部扫描多少字节。50MB 的文件全扫会拖死请求，
# 因此限定窗口，并在结果里如实标记 truncated。
MAX_SCAN_BYTES = 8 * 1024 * 1024

# 不带过滤时，按每行约 400 字节估算需要读取的窗口。
_BYTES_PER_LINE_ESTIMATE = 400

_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")


def log_dir() -> Path:
    """日志目录：CMKB_LOG_DIR > /app/logs > 仓库根 logs/。"""
    env = os.environ.get("CMKB_LOG_DIR")
    if env:
        return Path(env)
    if _DEFAULT_LOG_DIR.is_dir():
        return _DEFAULT_LOG_DIR
    return _REPO_LOG_DIR


@dataclass(slots=True)
class LogFileInfo:
    name: str
    size_bytes: int
    modified_at: str | None
    rotated_count: int


@dataclass(slots=True)
class LogContent:
    name: str
    lines: list[str]
    returned_lines: int
    size_bytes: int
    truncated: bool          # 是否因扫描窗口上限而未覆盖整个文件
    filtered: bool


def list_logs() -> list[LogFileInfo]:
    """列出当前日志文件（不含 .log.1 之类的轮转备份，它们计入 rotated_count）。"""
    directory = log_dir()
    if not directory.is_dir():
        return []

    result: list[LogFileInfo] = []
    for path in sorted(directory.glob("*.log")):
        if not path.is_file():
            continue
        stat = path.stat()
        rotated = sum(
            1 for _ in directory.glob(f"{path.name}.*")
        )
        result.append(
            LogFileInfo(
                name=path.name,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                rotated_count=rotated,
            )
        )
    return result


def resolve_log_path(name: str) -> Path | None:
    """把服务名解析成 LOG_DIR 内的真实路径；越界或不存在一律返回 None。"""
    if not name or not _SAFE_NAME.match(name):
        return None

    directory = log_dir()
    if not directory.is_dir():
        return None

    candidate = (directory / name).resolve()
    root = directory.resolve()

    # 解析后必须仍在 LOG_DIR 内（挡住 ../ 与指向外部的符号链接）
    if root != candidate.parent and root not in candidate.parents:
        return None
    if not candidate.is_file():
        return None
    return candidate


def tail_log(
    name: str,
    lines: int = DEFAULT_LINES,
    keyword: str | None = None,
    level: str | None = None,
) -> LogContent | None:
    """从文件尾部读取若干行，可按关键字/级别过滤。

    过滤只作用于扫描窗口内的内容（见 MAX_SCAN_BYTES）；窗口没覆盖到整个
    文件时 truncated=True，前端据此提示"仅搜索了最近 N MB"。
    """
    path = resolve_log_path(name)
    if path is None:
        return None

    lines = max(1, min(int(lines), MAX_LINES))
    keyword_lower = keyword.lower() if keyword else None
    level_upper = level.upper() if level else None
    filtered = bool(keyword_lower or level_upper)

    size = path.stat().st_size
    if filtered:
        window = min(size, MAX_SCAN_BYTES)
    else:
        window = min(size, max(lines * _BYTES_PER_LINE_ESTIMATE, 64 * 1024))

    with path.open("rb") as handle:
        if window < size:
            handle.seek(size - window)
        raw = handle.read()

    text = raw.decode("utf-8", errors="replace")
    collected = text.splitlines()

    # 窗口不是从文件头开始时，第一行大概率被截断，丢掉
    if window < size and collected:
        collected = collected[1:]

    if keyword_lower:
        collected = [ln for ln in collected if keyword_lower in ln.lower()]
    if level_upper:
        collected = [ln for ln in collected if _matches_level(ln, level_upper)]

    return LogContent(
        name=path.name,
        lines=collected[-lines:],
        returned_lines=min(len(collected), lines),
        size_bytes=size,
        truncated=window < size,
        filtered=filtered,
    )


def _matches_level(line: str, level: str) -> bool:
    """按级别过滤：选中某级别时，同时包含比它更严重的级别。

    日志格式是 `%(asctime)s %(levelname)s %(name)s %(message)s`，
    级别名以独立单词出现，用词边界匹配避免命中正文里的同名单词。
    """
    try:
        threshold = _LEVELS.index(level)
    except ValueError:
        return True
    wanted = _LEVELS[threshold:]
    return any(re.search(rf"\b{lv}\b", line) for lv in wanted)
