"""
CoreMasterKB 数据库导入脚本
- 读取 .env 中的 PG 连接信息
- 执行 export_db.py 导出的 INSERT SQL 文件
- 要求目标表已存在（由 reset_db.py 创建）
- 导入前自动 TRUNCATE 所有表（反序，处理外键）

用法：python import_db.py [SQL文件]
默认：backups/ 目录下最新的 export_*.sql
"""
from __future__ import annotations

import sys
from pathlib import Path

# ── 表顺序（共享定义） ────────────────────────────────────────
from db_tables import EXPORT_TABLES, OPTIONAL_TABLES

# ── 加载 .env ──────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent
ENV_FILE = REPO_ROOT / ".env"

if not ENV_FILE.exists():
    print(f"[ERROR] .env not found: {ENV_FILE}")
    sys.exit(1)

_env = {}
for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    if "=" in line:
        k, v = line.split("=", 1)
        _env[k.strip()] = v.strip()

PG_HOST = _env.get("PG_HOST", "")
PG_PORT = _env.get("PG_PORT", "5432")
PG_DBNAME = _env.get("PG_DBNAME", "")
PG_USER = _env.get("PG_USER", "")
PG_PASSWORD = _env.get("PG_PASSWORD", "")
PG_SSLMODE = _env.get("PG_SSLMODE", "disable")
PG_GSSENCMODE = _env.get("PG_GSSENCMODE", "disable")

if not all([PG_HOST, PG_DBNAME, PG_USER]):
    print("[ERROR] PG_HOST / PG_DBNAME / PG_USER must be set in .env")
    sys.exit(1)

CONNINFO = (
    f"host={PG_HOST} port={PG_PORT} dbname={PG_DBNAME} "
    f"user={PG_USER} password={PG_PASSWORD} "
    f"sslmode={PG_SSLMODE} gssencmode={PG_GSSENCMODE}"
)


def find_latest_backup() -> Path | None:
    backup_dir = REPO_ROOT / "backups"
    if not backup_dir.exists():
        return None
    files = sorted(backup_dir.glob("export_*.sql"), reverse=True)
    return files[0] if files else None


def table_exists(cur, table: str) -> bool:
    """表是否存在（to_regclass 对不存在的表返回 NULL，不会抛异常）"""
    cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
    return cur.fetchone()[0] is not None


def parse_statements(sql: str) -> list[str]:
    """从 SQL 文本中提取独立语句，跳过注释、空行、BEGIN/COMMIT"""
    stmts = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if stripped.upper() in ("BEGIN;", "COMMIT;"):
            continue
        stmts.append(stripped)
    return stmts


def main():
    try:
        import psycopg
    except ImportError:
        print("[ERROR] psycopg is required. Install with: pip install psycopg[binary]")
        sys.exit(1)

    # 确定输入文件
    if len(sys.argv) > 1:
        sql_path = Path(sys.argv[1])
    else:
        sql_path = find_latest_backup()
        if not sql_path:
            print("[ERROR] No export file found in backups/. Usage: python import_db.py <file.sql>")
            sys.exit(1)

    if not sql_path.exists():
        print(f"[ERROR] File not found: {sql_path}")
        sys.exit(1)

    print(f"File:    {sql_path}")
    print(f"Size:    {sql_path.stat().st_size / 1024:.1f} KB")
    print(f"Target:  {PG_HOST}:{PG_PORT}/{PG_DBNAME}")
    print(f"\nWARNING: This will TRUNCATE all tables and INSERT data!")
    confirm = input("Type 'YES' to proceed: ")
    if confirm != "YES":
        print("Aborted.")
        sys.exit(0)

    sql = sql_path.read_text(encoding="utf-8")
    stmts = parse_statements(sql)
    insert_stmts = [s for s in stmts if s.upper().startswith("INSERT")]
    print(f"Statements to execute: {len(insert_stmts)}")

    with psycopg.connect(CONNINFO) as conn:
        with conn.cursor() as cur:
            # 1. TRUNCATE 所有表（反序，先清子表）
            #    可选表若不存在则跳过——TRUNCATE 是单条语句，缺一张表整条都会失败。
            present = [
                t for t in EXPORT_TABLES
                if t not in OPTIONAL_TABLES or table_exists(cur, t)
            ]
            for t in EXPORT_TABLES:
                if t not in present:
                    print(f"  {t}: skipped (not found)")
            truncate_sql = ", ".join(reversed(present))
            cur.execute(f"TRUNCATE TABLE {truncate_sql} CASCADE;")
            print("Tables truncated.")

            # 2. 逐条执行 INSERT，便于定位错误
            ok = 0
            for i, stmt in enumerate(insert_stmts, 1):
                try:
                    cur.execute(stmt)
                    ok += 1
                except Exception as e:
                    # 提取表名用于定位
                    table = stmt.split()[2] if len(stmt.split()) > 2 else "?"
                    print(f"[ERROR] Statement {i} (table={table}): {e}")
                    conn.rollback()
                    print(f"Rolled back. {ok} rows succeeded before failure.")
                    sys.exit(1)

        conn.commit()

    print(f"Import complete. {ok} rows inserted.")


if __name__ == "__main__":
    main()
