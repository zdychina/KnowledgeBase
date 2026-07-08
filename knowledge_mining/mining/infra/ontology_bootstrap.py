"""本体冷启动引种（seed 文件 → 本体 v1）。对应实现设计 L2 §4。

不进逐文档流水线，是一次性 idempotent 操作：读种子目录下所有 *.yaml，
建 active 版本 + 点类型 + 边类型 + 别名词典。引种后真相源转移到 DB，
运行期抽取读 active 版本（OntologyStore.active_*），不再读种子文件或 domain.yaml。

入口：kb-ui 设置页"引种本体"按钮，或 CLI（见 run_bootstrap）。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from knowledge_mining.mining.infra.ontology_store import OntologyStore

logger = logging.getLogger(__name__)


def _normalize_alias(text: str) -> str:
    """归一化别名：转小写 + 合并空白。与 ontology_alias_dictionary.alias_normalized 对齐。"""
    return re.sub(r"\s+", " ", text.strip()).lower()


def _load_seed_docs(seed_source: str | Path) -> list[tuple[str, dict[str, Any]]]:
    """把种子来源读成 [(文件名, 解析后的 dict)]。

    seed_source 可以是单个 *.yaml 文件（= 人工上传的那一个文件），也可以是目录
    （目录下所有 *.yaml，对应"一层一个文件"的多层场景）。
    """
    path = Path(seed_source)
    if path.is_dir():
        files = sorted(path.glob("*.yaml"))
        if not files:
            raise FileNotFoundError(f"no *.yaml seed found under {path}")
    elif path.is_file():
        files = [path]
    else:
        raise FileNotFoundError(f"seed source not found: {path}")
    return [(f.name, yaml.safe_load(f.read_text(encoding="utf-8")) or {}) for f in files]


def _apply_seed_doc(
    store: OntologyStore, version_id: str, domain_id: str, data: dict[str, Any],
) -> tuple[int, int, int]:
    """把一份解析后的种子文档灌进指定本体版本。返回 (点类型数, 边类型数, 别名数)。"""
    default_layer = data.get("layer", "concept")
    n = r = a = 0

    for nt in data.get("node_types", []) or []:
        store.add_node_type(
            version_id,
            name=nt["name"],
            layer=nt.get("layer", default_layer),
            is_strong=bool(nt.get("is_strong", False)),
            definition=nt.get("definition"),
            examples=nt.get("examples", []),
        )
        n += 1

    for rt in data.get("relation_types", []) or []:
        store.add_relation_type(
            version_id,
            name=rt["name"],
            layer=rt.get("layer", default_layer),
            is_directed=bool(rt.get("is_directed", True)),
            inverse_name=rt.get("inverse_name"),
            allowed_pairs=rt.get("patterns", []),
            definition=rt.get("definition"),
        )
        r += 1

    # aliases: {canonical_name: [alias, ...]}
    for canonical, alias_list in (data.get("aliases", {}) or {}).items():
        for alias in alias_list or []:
            store.upsert_alias(
                domain_id,
                alias_normalized=_normalize_alias(alias),
                canonical_name=canonical,
                source="seed",
            )
            a += 1

    return n, r, a


def bootstrap_ontology(
    store: OntologyStore,
    *,
    domain_id: str = "cloud_core_network",
    seed_source: str | Path,
) -> dict[str, Any]:
    """从种子文件/目录引种本体 v1（幂等）。

    seed_source 既可以是单个上传文件（模拟其他场景冷启动：人工上传一个本体文档），
    也可以是目录（多层一层一个文件）。

    若该 domain 已有 active 版本 → 跳过并返回 {'skipped': True, ...}。
    否则建 version_no=1 / status='active' / source='bootstrap_yaml'，灌入类型与别名。
    """
    existing = store.active_version(domain_id)
    if existing is not None:
        logger.info("ontology already active for %s (v%s), skip bootstrap",
                    domain_id, existing["version_no"])
        return {"skipped": True, "version_id": existing["id"], "version_no": existing["version_no"]}

    docs = _load_seed_docs(seed_source)
    version_no = store.next_version_no(domain_id)
    version_id = store.create_version(
        domain_id,
        version_no=version_no,
        status="active",
        source="bootstrap_yaml",
        note="引种自 " + ",".join(name for name, _ in docs),
    )

    node_count = rel_count = alias_count = 0
    for _name, data in docs:
        n, r, a = _apply_seed_doc(store, version_id, domain_id, data)
        node_count += n
        rel_count += r
        alias_count += a

    logger.info("bootstrapped ontology %s v%d: %d node_types, %d relation_types, %d aliases",
                domain_id, version_no, node_count, rel_count, alias_count)
    return {
        "skipped": False,
        "version_id": version_id,
        "version_no": version_no,
        "node_types": node_count,
        "relation_types": rel_count,
        "aliases": alias_count,
    }


def bootstrap_ontology_from_text(
    store: OntologyStore,
    *,
    domain_id: str = "cloud_core_network",
    yaml_text: str,
    source_name: str = "uploaded.yaml",
) -> dict[str, Any]:
    """上传入口：直接吃一段 YAML 文本（= 用户上传的文件内容）引种本体 v1（幂等）。

    将来 kb-ui 的"上传本体文档"按钮把文件内容传到后端，后端调本函数即可——
    与本地 bootstrap_ontology 走同一条引种逻辑。
    """
    existing = store.active_version(domain_id)
    if existing is not None:
        return {"skipped": True, "version_id": existing["id"], "version_no": existing["version_no"]}

    data = yaml.safe_load(yaml_text) or {}
    version_no = store.next_version_no(domain_id)
    version_id = store.create_version(
        domain_id,
        version_no=version_no,
        status="active",
        source="bootstrap_yaml",
        note=f"引种自上传文件 {source_name}",
    )
    node_count, rel_count, alias_count = _apply_seed_doc(store, version_id, domain_id, data)
    logger.info("bootstrapped ontology %s v%d from upload %s: %d/%d/%d",
                domain_id, version_no, source_name, node_count, rel_count, alias_count)
    return {
        "skipped": False,
        "version_id": version_id,
        "version_no": version_no,
        "node_types": node_count,
        "relation_types": rel_count,
        "aliases": alias_count,
    }


def run_bootstrap(
    conninfo: str,
    *,
    domain_id: str = "cloud_core_network",
    seed_source: str | Path,
) -> dict[str, Any]:
    """CLI/服务层入口：自建连接池 → 引种 → 关池。

    注意：会向目标库写入 ontology_* 数据，对共享远程库执行前需确认（见 L2 风险）。
    """
    from psycopg_pool import ConnectionPool
    from psycopg.rows import dict_row

    pool = ConnectionPool(
        conninfo, min_size=1, max_size=4, open=True,
        check=ConnectionPool.check_connection, max_idle=300.0,
        kwargs={"row_factory": dict_row},
    )
    try:
        store = OntologyStore(pool)
        return bootstrap_ontology(store, domain_id=domain_id, seed_source=seed_source)
    finally:
        pool.close()
