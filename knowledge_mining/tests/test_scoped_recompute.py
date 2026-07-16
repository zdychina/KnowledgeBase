"""scoped 重算编排：取受影响子图 mention → 删旧边 → 重算 NPMI → 落边。连真实 PG。"""
from __future__ import annotations
import uuid
from knowledge_mining.mining.infra.ontology_store import OntologyStore, GraphStore
from knowledge_mining.mining.stages.graph_write import scoped_recompute

DOMAIN = "cloud_core_network"


def _nid() -> str:
    return uuid.uuid4().hex


def test_scoped_recompute_runs_without_active_ontology(asset_db) -> None:
    """无 active 本体时安静返回 0（不抛、不阻断）——与 graph_write_final 同样的容错。"""
    gs = GraphStore(asset_db.pool)
    eid = _nid()
    gs._execute(
        "INSERT INTO ontology_entities (id, domain_id, canonical_name, node_type, layer) "
        "VALUES (%s, %s, '网络切片', 'concept_x', 'concept')", (eid, DOMAIN))
    asset_db.commit()
    n = scoped_recompute(asset_db.pool, DOMAIN, [eid])
    assert n == 0
