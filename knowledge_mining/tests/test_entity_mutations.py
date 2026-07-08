"""实体 mutation（合并/改类型/删除）+ scoped 取数的 store 层测试。连真实 PG。"""
from __future__ import annotations

import uuid
from knowledge_mining.mining.infra.ontology_store import OntologyStore, GraphStore

DOMAIN = "cloud_core_network"


def _nid() -> str:
    return uuid.uuid4().hex


def _seed_entity(gs: GraphStore, name: str, node_type: str = "concept_x") -> str:
    eid = _nid()
    gs._execute(
        "INSERT INTO ontology_entities (id, domain_id, canonical_name, node_type, layer) "
        "VALUES (%s, %s, %s, %s, 'concept')",
        (eid, DOMAIN, name, node_type),
    )
    return eid


def _seed_snapshot_segment(gs: GraphStore) -> tuple[str, str]:
    """建一份最小的快照+段落，满足 mention 的外键。返回 (snapshot_id, segment_id)。

    asset_segment_entity_mentions 只外键依赖 asset_document_snapshots 和 asset_raw_segments，
    无需 asset_source_batches / asset_documents。
    """
    snap, seg = _nid(), _nid()
    gs._execute(
        "INSERT INTO asset_document_snapshots "
        "(id, normalized_content_hash, raw_content_hash, mime_type, created_at) "
        "VALUES (%s, %s, %s, 'text/plain', now()::text)",
        (snap, snap + "_n", snap + "_r"),
    )
    gs._execute(
        "INSERT INTO asset_raw_segments "
        "(id, document_snapshot_id, segment_key, segment_index, "
        " raw_text, normalized_text, content_hash, normalized_hash) "
        "VALUES (%s, %s, %s, 0, %s, %s, %s, %s)",
        (seg, snap, seg + "_k", "网络切片由 UPF 承载",
         "网络切片由 UPF 承载", seg + "_c", seg + "_nh"),
    )
    return snap, seg


def _seed_mention(gs: GraphStore, *, snap: str, seg: str, entity_id: str, name: str) -> None:
    gs._execute(
        "INSERT INTO asset_segment_entity_mentions "
        "(id, document_snapshot_id, segment_id, node_type, mention_text, canonical_name, "
        " resolved_entity_id, resolve_status) "
        "VALUES (%s, %s, %s, 'concept_x', %s, %s, %s, 'human')",
        (_nid(), snap, seg, name, name, entity_id),
    )


def test_mentions_around_entities_pulls_cooccurring(asset_db) -> None:
    gs = GraphStore(asset_db.pool)
    a = _seed_entity(gs, "网络切片")
    b = _seed_entity(gs, "UPF")
    c = _seed_entity(gs, "无关实体")
    snap, seg = _seed_snapshot_segment(gs)
    _seed_mention(gs, snap=snap, seg=seg, entity_id=a, name="网络切片")
    _seed_mention(gs, snap=snap, seg=seg, entity_id=b, name="UPF")
    # c 在另一段，不与 a 同段
    snap2, seg2 = _seed_snapshot_segment(gs)
    _seed_mention(gs, snap=snap2, seg=seg2, entity_id=c, name="无关实体")
    asset_db.commit()

    rows = gs.resolved_mentions_around_entities(DOMAIN, [a])
    ids = {r["entity_id"] for r in rows}
    assert a in ids and b in ids        # a 及其同段邻居 b 被带出
    assert c not in ids                  # 不同段的 c 不在范围内
    r0 = next(r for r in rows if r["entity_id"] == a)
    assert set(r0.keys()) >= {"document_snapshot_id", "segment_id", "entity_id",
                              "node_type", "canonical_name", "quote"}


def _seed_edge(gs: GraphStore, h: str, t: str) -> None:
    gs._execute(
        "INSERT INTO ontology_entity_relations "
        "(id, domain_id, head_entity_id, tail_entity_id, relation_type, source_refs_json) "
        "VALUES (%s, %s, %s, %s, 'rel', '[\"x\"]'::jsonb)",
        (_nid(), DOMAIN, h, t),
    )


def test_delete_edges_among_only_inside_set(asset_db) -> None:
    gs = GraphStore(asset_db.pool)
    a, b, c = _seed_entity(gs, "A"), _seed_entity(gs, "B"), _seed_entity(gs, "C")
    _seed_edge(gs, a, b)   # 两端都在 {a,b} → 应删
    _seed_edge(gs, b, c)   # 一端 c 在集合外 → 应保留
    asset_db.commit()

    n = gs.delete_edges_among(DOMAIN, [a, b])
    asset_db.commit()
    assert n == 1
    remain = gs._fetchall(
        "SELECT head_entity_id, tail_entity_id FROM ontology_entity_relations WHERE domain_id=%s",
        (DOMAIN,))
    assert len(remain) == 1
    assert {remain[0]["head_entity_id"], remain[0]["tail_entity_id"]} == {b, c}


def test_merge_entities_repoints_and_drops(asset_db) -> None:
    gs = GraphStore(asset_db.pool)
    prim = _seed_entity(gs, "UPF")
    dup = _seed_entity(gs, "用户面功能")
    snap, seg = _seed_snapshot_segment(gs)
    _seed_mention(gs, snap=snap, seg=seg, entity_id=dup, name="用户面功能")
    asset_db.commit()

    affected = gs.merge_entities(DOMAIN, prim, [dup])
    asset_db.commit()

    # 被并实体没了
    assert gs._fetchone("SELECT 1 FROM ontology_entities WHERE id=%s", (dup,)) is None
    # 它的提及改指主实体
    m = gs._fetchall(
        "SELECT resolved_entity_id FROM asset_segment_entity_mentions WHERE segment_id=%s", (seg,))
    assert all(r["resolved_entity_id"] == prim for r in m)
    # 返回的受影响集合含主实体
    assert prim in affected


def test_retype_entity_simple(asset_db) -> None:
    gs = GraphStore(asset_db.pool)
    eid = _seed_entity(gs, "S-NSSAI", node_type="__untyped__")
    asset_db.commit()
    affected = gs.retype_entity(DOMAIN, eid, "identifier")
    asset_db.commit()
    row = gs._fetchone("SELECT node_type FROM ontology_entities WHERE id=%s", (eid,))
    assert row["node_type"] == "identifier"
    assert eid in affected


def test_retype_entity_name_conflict_merges(asset_db) -> None:
    gs = GraphStore(asset_db.pool)
    target = _seed_entity(gs, "网元", node_type="network_function")
    moving = _seed_entity(gs, "网元", node_type="__untyped__")  # 同名不同类型
    snap, seg = _seed_snapshot_segment(gs)
    _seed_mention(gs, snap=snap, seg=seg, entity_id=moving, name="网元")
    asset_db.commit()

    affected = gs.retype_entity(DOMAIN, moving, "network_function")  # 撞 (network_function,网元)
    asset_db.commit()
    # moving 被并入 target
    assert gs._fetchone("SELECT 1 FROM ontology_entities WHERE id=%s", (moving,)) is None
    m = gs._fetchall(
        "SELECT resolved_entity_id FROM asset_segment_entity_mentions WHERE segment_id=%s", (seg,))
    assert all(r["resolved_entity_id"] == target for r in m)
    assert target in affected


def test_delete_entity_removes_entity_mentions_edges(asset_db) -> None:
    gs = GraphStore(asset_db.pool)
    a, b = _seed_entity(gs, "垃圾实体"), _seed_entity(gs, "邻居")
    snap, seg = _seed_snapshot_segment(gs)
    _seed_mention(gs, snap=snap, seg=seg, entity_id=a, name="垃圾实体")
    _seed_edge(gs, a, b)
    asset_db.commit()

    gs.delete_entity(DOMAIN, a)
    asset_db.commit()
    assert gs._fetchone("SELECT 1 FROM ontology_entities WHERE id=%s", (a,)) is None
    assert gs._fetchall(
        "SELECT 1 FROM asset_segment_entity_mentions WHERE resolved_entity_id=%s", (a,)) == []
    assert gs._fetchall(
        "SELECT 1 FROM ontology_entity_relations WHERE head_entity_id=%s OR tail_entity_id=%s",
        (a, a)) == []
    # 邻居还在
    assert gs._fetchone("SELECT 1 FROM ontology_entities WHERE id=%s", (b,)) is not None
