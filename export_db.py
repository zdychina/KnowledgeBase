"""
CoreMasterKB 数据库导出脚本
- 读取 .env 中的 PG 连接信息
- 将所有业务表的数据导出为 INSERT SQL 文件
- 不导出建表语句（由 reset_db.py 负责）

用法：python export_db.py [输出文件]
默认输出：backups/export_<日期时间>.sql
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

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

# ── 表顺序（共享定义） ────────────────────────────────────────
from db_tables import EXPORT_TABLES, OPTIONAL_TABLES


def table_exists(cur, table: str) -> bool:
    """表是否存在（to_regclass 对不存在的表返回 NULL，不会抛异常）"""
    cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
    return cur.fetchone()[0] is not None


def escape_sql(value):
    """将 Python 值转为 SQL 字面量，dict/list 用 json.dumps 保证合法 JSON"""
    import json
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (dict, list)):
        s = json.dumps(value, ensure_ascii=False).replace("'", "''")
        return f"'{s}'"
    # str, datetime, uuid, bytes 等
    s = str(value).replace("'", "''")
    return f"'{s}'"


def export_table(cur, table: str, out) -> int:
    """导出单张表的数据为 INSERT 语句，返回行数"""
    cur.execute(f"SELECT * FROM {table} ORDER BY 1")
    rows = cur.fetchall()
    if not rows:
        out.write(f"-- {table}: 0 rows (empty)\n\n")
        return 0

    cols = [desc[0] for desc in cur.description]
    col_list = ", ".join(cols)
    count = 0

    for row in rows:
        values = ", ".join(escape_sql(v) for v in row)
        out.write(f"INSERT INTO {table} ({col_list}) VALUES ({values});\n")
        count += 1

    out.write(f"\n-- {table}: {count} rows\n\n")
    return count


def main():
    try:
        import psycopg
    except ImportError:
        print("[ERROR] psycopg is required. Install with: pip install psycopg[binary]")
        sys.exit(1)

    # 确定输出文件
    backup_dir = REPO_ROOT / "backups"
    backup_dir.mkdir(exist_ok=True)

    if len(sys.argv) > 1:
        output_path = Path(sys.argv[1])
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = backup_dir / f"export_{ts}.sql"

    print(f"Connecting to: {PG_HOST}:{PG_PORT}/{PG_DBNAME}")

    with psycopg.connect(CONNINFO, autocommit=True) as conn:
        with conn.cursor() as cur:
            with open(output_path, "w", encoding="utf-8") as out:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                out.write(f"-- CoreMasterKB Data Export\n")
                out.write(f"-- Generated: {ts}\n")
                out.write(f"-- Database:  {PG_DBNAME}@{PG_HOST}:{PG_PORT}\n")
                out.write(f"-- \n")
                out.write(f"-- Import with: python import_db.py {output_path.name}\n")
                out.write(f"-- \n\n")
                out.write(f"\n")

                total = 0
                for table in EXPORT_TABLES:
                    if table in OPTIONAL_TABLES and not table_exists(cur, table):
                        out.write(f"-- {table}: skipped (table not found)\n\n")
                        print(f"  {table}: skipped (not found)")
                        continue
                    count = export_table(cur, table, out)
                    total += count
                    print(f"  {table}: {count} rows")

                out.write(f"\n")
                out.write(f"-- Total: {total} rows\n")

    print(f"\nExported {total} rows to: {output_path}")


if __name__ == "__main__":
    main()
