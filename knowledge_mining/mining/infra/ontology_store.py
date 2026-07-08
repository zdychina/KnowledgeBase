"""本体存储薄接口（OntologyStore / GraphStore）。对应实现设计 L2 §10。

两个适配器与 AssetCoreDB / MiningRuntimeDB 共用同一连接池（同一 PG 库）：
- OntologyStore：规则层读写（版本 / 点类型 / 边类型 / 别名词典）。
- GraphStore：事实层 + 出处读写（canonical 对象 / 事实边 / evidence / mention / 邻域）。

业务代码（抽取轨、检索侧）只调这两个接口，不写裸 SQL。后期迁图库 = 换实现 + ETL，
不动业务（迁图风险见 L2 §10.1）。所以图遍历（neighbors）也收敛在这里，绝不外泄。
"""
from __future__ import annotations

import logging
from typing import Any

from knowledge_mining.mining.infra.db import _DB, _json_dumps, _new_id

logger = logging.getLogger(__name__)


# 哨兵类型：本体外但被确认为"重要、暂无类型"的实体（L1 §12 / L2 §15.2）。
# 这类实体先经 Gate2 人工确认，再由 ontology_induction（LLM 调用 2）归纳出正式类型，
# Gate1 通过后回贴正式类型名（见 N5）。用哨兵字符串、零 DDL（L2 §15.5 决策①）。
UNTYPED_NODE_TYPE = "__untyped__"


def _norm_type_name(s: str) -> str:
    """判重用归一化：去全部空白 + 小写。"""
    return "".join((s or "").split()).lower()


def find_duplicate_type(proposed_name: str, existing_types: list[dict[str, Any]]) -> str | None:
    """判断提议的点类型名是否与现有类型重复，命中返回现有类型名，否则 None。

    点类型无别名字段，以"示例"代偿。规则（任一命中即重复）：
    1. 归一化后与现有 name 完全相同；
    2. 提议名与现有 name 双向子串包含（"切片类"含"切片"）；
    3. 提议名命中现有类型的某个 example。

    existing_types：每项含 "name"（必需）和可选 "examples": list[str]。
    """
    p = _norm_type_name(proposed_name)
    if not p:
        return None
    for t in existing_types:
        name = t.get("name") or ""
        n = _norm_type_name(name)
        if not n:
            continue
        if p == n or p in n or n in p:
            return name
        for ex in (t.get("examples") or []):
            if _norm_type_name(str(ex)) == p:
                return name
    return None


# ===================================================================
# OntologyStore — 规则层（TBox）
# ===================================================================

class OntologyStore(_DB):
    """本体规则层适配器：版本治理 + 点/边类型 + 别名词典。"""

    # -- 版本 --

    def active_version(self, domain_id: str) -> dict[str, Any] | None:
        """返回该领域当前 active 的本体版本（无则 None）。抽取轨永远读这一版。"""
        return self._fetchone(
            "SELECT * FROM ontology_versions WHERE domain_id = %s AND status = 'active'",
            (domain_id,),
        )

    def list_versions(self, domain_id: str) -> list[dict[str, Any]]:
        return self._fetchall(
            "SELECT * FROM ontology_versions WHERE domain_id = %s ORDER BY version_no DESC",
            (domain_id,),
        )

    def next_version_no(self, domain_id: str) -> int:
        row = self._fetchone(
            "SELECT COALESCE(MAX(version_no), 0) AS m FROM ontology_versions WHERE domain_id = %s",
            (domain_id,),
        )
        return int(row["m"]) + 1 if row else 1

    def create_version(
        self,
        domain_id: str,
        *,
        version_no: int,
        status: str = "draft",
        source: str = "human_review",
        created_by: str | None = None,
        note: str | None = None,
    ) -> str:
        """新建一个本体版本记录，返回其 id。"""
        vid = _new_id()
        self._execute(
            """INSERT INTO ontology_versions
                   (id, domain_id, version_no, status, source, created_by, note)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (vid, domain_id, version_no, status, source, created_by, note),
        )
        return vid

    def activate_version(self, version_id: str, domain_id: str) -> None:
        """把指定版本置为 active，同时把该领域旧的 active 降级为 superseded。

        靠 DDL 的 partial unique index 保证"同领域同时只一个 active"。
        """
        self._execute(
            "UPDATE ontology_versions SET status = 'superseded' "
            "WHERE domain_id = %s AND status = 'active' AND id <> %s",
            (domain_id, version_id),
        )
        self._execute(
            "UPDATE ontology_versions SET status = 'active' WHERE id = %s",
            (version_id,),
        )

    # -- 点类型 / 边类型 --

    def add_node_type(
        self,
        version_id: str,
        *,
        name: str,
        layer: str = "concept",
        is_strong: bool = False,
        definition: str | None = None,
        examples: list | None = None,
    ) -> str:
        nid = _new_id()
        self._execute(
            """INSERT INTO ontology_node_types
                   (id, ontology_version_id, name, layer, is_strong, definition, examples_json)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (ontology_version_id, name) DO UPDATE SET
                   is_strong = excluded.is_strong,
                   definition = excluded.definition,
                   examples_json = excluded.examples_json""",
            (nid, version_id, name, layer, is_strong, definition, _json_dumps(examples or [])),
        )
        return nid

    def add_relation_type(
        self,
        version_id: str,
        *,
        name: str,
        layer: str = "concept",
        is_directed: bool = True,
        inverse_name: str | None = None,
        allowed_pairs: list | None = None,
        definition: str | None = None,
    ) -> str:
        rid = _new_id()
        self._execute(
            """INSERT INTO ontology_relation_types
                   (id, ontology_version_id, name, layer, is_directed, inverse_name,
                    allowed_pairs_json, definition)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (ontology_version_id, name) DO UPDATE SET
                   is_directed = excluded.is_directed,
                   inverse_name = excluded.inverse_name,
                   allowed_pairs_json = excluded.allowed_pairs_json,
                   definition = excluded.definition""",
            (rid, version_id, name, layer, is_directed, inverse_name,
             _json_dumps(allowed_pairs or []), definition),
        )
        return rid

    def active_node_types(self, domain_id: str) -> list[dict[str, Any]]:
        """active 版本下的全部点类型（B2 enrich 读这个当抽取约束）。"""
        return self._fetchall(
            """SELECT nt.* FROM ontology_node_types nt
               JOIN ontology_versions v ON v.id = nt.ontology_version_id
               WHERE v.domain_id = %s AND v.status = 'active'
               ORDER BY nt.name""",
            (domain_id,),
        )

    def active_relation_types(self, domain_id: str) -> list[dict[str, Any]]:
        """active 版本下的全部边类型（B4 entity_relations 读这个拿 allowed_pairs）。"""
        return self._fetchall(
            """SELECT rt.* FROM ontology_relation_types rt
               JOIN ontology_versions v ON v.id = rt.ontology_version_id
               WHERE v.domain_id = %s AND v.status = 'active'
               ORDER BY rt.name""",
            (domain_id,),
        )

    # -- 草稿版本（人工编辑器）--

    def get_draft_version(self, domain_id: str) -> dict[str, Any] | None:
        """取该领域 status='draft' 的本体版本（约定每领域至多一个 draft，取最新）。"""
        return self._fetchone(
            "SELECT * FROM ontology_versions WHERE domain_id = %s AND status = 'draft' "
            "ORDER BY version_no DESC LIMIT 1",
            (domain_id,),
        )

    def node_types_for_version(self, version_id: str) -> list[dict[str, Any]]:
        """按 version_id 读点类型（active_node_types 只按 active 读，这里补按 id 读）。"""
        return self._fetchall(
            "SELECT * FROM ontology_node_types WHERE ontology_version_id = %s ORDER BY name",
            (version_id,),
        )

    def relation_types_for_version(self, version_id: str) -> list[dict[str, Any]]:
        """按 version_id 读边类型。"""
        return self._fetchall(
            "SELECT * FROM ontology_relation_types WHERE ontology_version_id = %s ORDER BY name",
            (version_id,),
        )

    def delete_version_types(self, version_id: str) -> None:
        """删一个版本名下的全部点/边类型（供 replace_draft 的"清空+重写"复用）。"""
        self._execute(
            "DELETE FROM ontology_node_types WHERE ontology_version_id = %s", (version_id,))
        self._execute(
            "DELETE FROM ontology_relation_types WHERE ontology_version_id = %s", (version_id,))

    def replace_draft(
        self,
        domain_id: str,
        node_types: list[dict[str, Any]],
        relation_types: list[dict[str, Any]],
        *,
        created_by: str | None = None,
    ) -> str:
        """整份覆盖式保存草稿：事务内 get-or-create draft → 清空旧类型 → 按提交内容重写。

        node_types 每项键：name, layer, is_strong, definition, examples（list）。
        relation_types 每项键：name, layer, is_directed, inverse_name, allowed_pairs（list[{head,tail}]）, definition。
        返回 draft 版本 id。
        """
        with self.transaction():
            draft = self.get_draft_version(domain_id)
            if draft is None:
                vid = self.create_version(
                    domain_id, version_no=self.next_version_no(domain_id),
                    status="draft", source="human_edit", created_by=created_by,
                )
            else:
                vid = draft["id"]
                self.delete_version_types(vid)
            for nt in node_types:
                self.add_node_type(
                    vid, name=nt["name"], layer=nt.get("layer", "concept"),
                    is_strong=nt.get("is_strong", False), definition=nt.get("definition"),
                    examples=nt.get("examples") or [],
                )
            for rt in relation_types:
                self.add_relation_type(
                    vid, name=rt["name"], layer=rt.get("layer", "concept"),
                    is_directed=rt.get("is_directed", True),
                    inverse_name=rt.get("inverse_name"),
                    allowed_pairs=rt.get("allowed_pairs") or [],
                    definition=rt.get("definition"),
                )
            return vid

    def publish_draft(self, domain_id: str) -> str | None:
        """发布：把该领域 draft 激活为新 active（旧 active 自动转 superseded）。

        无 draft → 返回 None（路由转 400）。
        """
        draft = self.get_draft_version(domain_id)
        if draft is None:
            return None
        self.activate_version(draft["id"], domain_id)
        return draft["id"]

    # -- 别名词典 --

    def upsert_alias(
        self,
        domain_id: str,
        *,
        alias_normalized: str,
        canonical_name: str,
        node_type: str | None = None,
        source: str = "seed",
    ) -> str:
        aid = _new_id()
        self._execute(
            """INSERT INTO ontology_alias_dictionary
                   (id, domain_id, alias_normalized, canonical_name, node_type, source)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (domain_id, alias_normalized) DO UPDATE SET
                   canonical_name = excluded.canonical_name,
                   node_type = excluded.node_type,
                   source = excluded.source""",
            (aid, domain_id, alias_normalized, canonical_name, node_type, source),
        )
        return aid

    def lookup_alias(self, domain_id: str, alias_normalized: str) -> dict[str, Any] | None:
        return self._fetchone(
            "SELECT * FROM ontology_alias_dictionary WHERE domain_id = %s AND alias_normalized = %s",
            (domain_id, alias_normalized),
        )

    def all_aliases(self, domain_id: str) -> list[dict[str, Any]]:
        """该领域全部别名行（B3 resolve 一次性拉来在内存建归一索引，避免逐 mention 查库）。"""
        return self._fetchall(
            "SELECT alias_normalized, canonical_name, node_type FROM ontology_alias_dictionary WHERE domain_id = %s",
            (domain_id,),
        )

    # -- 本体候选（逃生口 / off-schema 关系 → Gate1 人审）--

    def upsert_candidate(
        self,
        domain_id: str,
        *,
        kind: str,
        proposed_name: str,
        payload: dict[str, Any] | None = None,
        source: str = "escape_hatch",
        evidence: list | None = None,
        score: float | None = None,
        layer: str = "concept",
    ) -> str:
        """写/更新一条本体候选（kind: node_type|relation_type）。

        按 (domain, kind, proposed_name) 去重——同名候选重跑 build 只更新打分/证据，
        不堆重复，保证 B5 幂等。已被人审 accepted/rejected 的候选不回退 status。
        """
        existing = self._fetchone(
            "SELECT id, status FROM ontology_candidates "
            "WHERE domain_id = %s AND kind = %s AND proposed_name = %s",
            (domain_id, kind, proposed_name),
        )
        if existing is not None:
            self._execute(
                "UPDATE ontology_candidates SET payload_json = %s, evidence_json = %s, "
                "score = %s, source = %s WHERE id = %s",
                (_json_dumps(payload or {}), _json_dumps(evidence or []),
                 score, source, existing["id"]),
            )
            return existing["id"]
        cid = _new_id()
        self._execute(
            """INSERT INTO ontology_candidates
                   (id, domain_id, kind, layer, proposed_name, payload_json,
                    source, evidence_json, score, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'proposed')""",
            (cid, domain_id, kind, layer, proposed_name, _json_dumps(payload or {}),
             source, _json_dumps(evidence or []), score),
        )
        return cid

    def list_candidates(self, domain_id: str, *, status: str = "proposed") -> list[dict[str, Any]]:
        """Gate1 评审页用：列某状态的候选。"""
        return self._fetchall(
            "SELECT * FROM ontology_candidates WHERE domain_id = %s AND status = %s "
            "ORDER BY score DESC NULLS LAST, created_at",
            (domain_id, status),
        )

    def accepted_node_type_members(self, domain_id: str) -> list[tuple[str, str]]:
        """N5 回贴输入：已 accepted 的 node_type 候选 → [(member_entity_id, 批准的类型名)]。

        归纳候选（source='global_induction'）的 payload 里存了 member_entity_ids；Gate1 通过、
        升版后用这份名单把成员实体的 __untyped__ 回贴成 proposed_name（可能被人改过名）。
        """
        rows = self._fetchall(
            "SELECT proposed_name, payload_json FROM ontology_candidates "
            "WHERE domain_id = %s AND kind = 'node_type' AND status = 'accepted'",
            (domain_id,),
        )
        out: list[tuple[str, str]] = []
        for r in rows:
            payload = r.get("payload_json") or {}
            for eid in payload.get("member_entity_ids", []) or []:
                if eid:
                    out.append((eid, r["proposed_name"]))
        return out

    def count_proposed_candidates(self, domain_id: str) -> int:
        """Gate1 触发判定：还有多少条待审本体候选（B6 暂停检查）。"""
        row = self._fetchone(
            "SELECT COUNT(*) AS n FROM ontology_candidates "
            "WHERE domain_id = %s AND status = 'proposed'",
            (domain_id,),
        )
        return int(row["n"]) if row else 0

    def review_candidate(
        self, candidate_id: str, *, action: str,
        new_name: str | None = None, note: str | None = None,
    ) -> None:
        """Gate1 单条裁决（不升版，只标状态）。action: accept | reject。

        - accept：标 status='accepted'，可顺带改名（new_name 写回 proposed_name），
          稍后 promote_accepted_candidates 统一并入新版本；
        - reject：标 status='rejected'。
        升版动作单独走 promote_accepted_candidates，便于"逐条审完一把提交"。
        """
        if action not in ("accept", "reject"):
            raise ValueError(f"unknown review action: {action!r}")
        # 幂等保护：已裁决（accepted/rejected）的候选不允许重复操作——防前端误点或并发重复提交。
        cur = self._fetchone(
            "SELECT status FROM ontology_candidates WHERE id = %s", (candidate_id,))
        if cur is None:
            raise ValueError(f"candidate {candidate_id} not found")
        if cur["status"] != "proposed":
            raise ValueError(f"candidate {candidate_id} already {cur['status']}, cannot review again")
        status = "accepted" if action == "accept" else "rejected"
        parts = ["status = %s"]
        params: list[Any] = [status]
        if new_name is not None:
            parts.append("proposed_name = %s")
            params.append(new_name)
        if note is not None:
            parts.append("review_note = %s")
            params.append(note)
        params.append(candidate_id)
        self._execute(
            f"UPDATE ontology_candidates SET {', '.join(parts)} WHERE id = %s", tuple(params))

    def promote_accepted_candidates(
        self, domain_id: str, *, created_by: str | None = None, note: str | None = None,
    ) -> str | None:
        """把全部 accepted 候选并入一个新 active 本体版本（克隆旧版类型 + 追加新类型）。

        无 accepted 候选 → 返回 None（自动放行，不升版）。流程：
          1) 读旧 active 版本的全部点/边类型；
          2) 建新 draft 版本，克隆旧类型，追加 accepted 候选转出的新类型；
          3) 激活新版本（旧版自动降为 superseded）。
        node_type 候选 → 新节点类型；relation_type 候选 → 新边类型
        （allowed_pairs 取候选 payload 的 head_type/tail_type）。
        """
        accepted = self._fetchall(
            "SELECT * FROM ontology_candidates WHERE domain_id = %s AND status = 'accepted'",
            (domain_id,),
        )
        if not accepted:
            return None

        old_node_types = self.active_node_types(domain_id)
        old_rel_types = self.active_relation_types(domain_id)

        new_vid = self.create_version(
            domain_id, version_no=self.next_version_no(domain_id),
            status="draft", source="human_review", created_by=created_by, note=note,
        )

        for nt in old_node_types:
            self.add_node_type(
                new_vid, name=nt["name"], layer=nt.get("layer", "concept"),
                is_strong=nt.get("is_strong", False), definition=nt.get("definition"),
                examples=nt.get("examples_json") or [],
            )
        for rt in old_rel_types:
            self.add_relation_type(
                new_vid, name=rt["name"], layer=rt.get("layer", "concept"),
                is_directed=rt.get("is_directed", True), inverse_name=rt.get("inverse_name"),
                allowed_pairs=rt.get("allowed_pairs_json") or [], definition=rt.get("definition"),
            )

        for c in accepted:
            payload = c.get("payload_json") or {}
            if c["kind"] == "node_type":
                # 归纳候选 payload 里带 definition/layer/examples（N3），升版时一并保留。
                self.add_node_type(
                    new_vid, name=c["proposed_name"],
                    layer=payload.get("layer") or "concept",
                    definition=payload.get("definition"),
                    examples=payload.get("examples") or [],
                )
            else:
                head, tail = payload.get("head_type"), payload.get("tail_type")
                pairs = [{"head": head, "tail": tail}] if head and tail else []
                self.add_relation_type(new_vid, name=c["proposed_name"], allowed_pairs=pairs)

        self.activate_version(new_vid, domain_id)
        return new_vid


# ===================================================================
# GraphStore — 事实层（ABox）+ 出处
# ===================================================================

class GraphStore(_DB):
    """事实层适配器：canonical 对象 / 事实边 / 出处 / mention / 邻域遍历。

    出处强约束在两处兜底：DB CHECK(source_refs 非空) + 本类 upsert_relation 校验，
    迁图后 CHECK 失效仍由代码侧保住（L2 §10.1-④）。
    """

    # -- canonical 对象 --

    def upsert_entity(
        self,
        domain_id: str,
        *,
        canonical_name: str,
        node_type: str,
        layer: str = "concept",
        aliases: list | None = None,
        attributes: dict | None = None,
        first_ontology_version_id: str | None = None,
    ) -> str:
        """按 (domain, node_type, canonical_name) 聚合 upsert，返回 entity id。"""
        eid = _new_id()
        self._execute(
            """INSERT INTO ontology_entities
                   (id, domain_id, canonical_name, node_type, layer, aliases_json,
                    attributes_json, first_ontology_version_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (domain_id, node_type, canonical_name) DO UPDATE SET
                   aliases_json = excluded.aliases_json,
                   attributes_json = excluded.attributes_json""",
            (eid, domain_id, canonical_name, node_type, layer,
             _json_dumps(aliases or []), _json_dumps(attributes or {}),
             first_ontology_version_id),
        )
        row = self._fetchone(
            "SELECT id FROM ontology_entities WHERE domain_id = %s AND node_type = %s AND canonical_name = %s",
            (domain_id, node_type, canonical_name),
        )
        return row["id"] if row else eid

    def bump_entity_counts(self, entity_id: str, *, mention_delta: int = 0, document_delta: int = 0) -> None:
        self._execute(
            "UPDATE ontology_entities SET mention_count = mention_count + %s, "
            "document_count = document_count + %s WHERE id = %s",
            (mention_delta, document_delta, entity_id),
        )

    def set_entity_counts(self, entity_id: str, *, mention_count: int, document_count: int) -> None:
        """直接置（非累加）计数，供 B5 全局重算——重跑同 build 幂等不翻倍。"""
        self._execute(
            "UPDATE ontology_entities SET mention_count = %s, document_count = %s WHERE id = %s",
            (mention_count, document_count, entity_id),
        )

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        return self._fetchone("SELECT * FROM ontology_entities WHERE id = %s", (entity_id,))

    def list_entities(
        self,
        domain_id: str,
        *,
        node_type: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """对象检索（图谱浏览页用）：按领域过滤，可选 node_type 与 canonical_name 模糊匹配。"""
        conds = ["domain_id = %s"]
        params: list[Any] = [domain_id]
        if node_type:
            conds.append("node_type = %s")
            params.append(node_type)
        if q:
            conds.append("canonical_name ILIKE %s")
            params.append(f"%{q}%")
        where = " AND ".join(conds)
        params.extend([limit, offset])
        return self._fetchall(
            f"SELECT * FROM ontology_entities WHERE {where} "
            f"ORDER BY mention_count DESC NULLS LAST, canonical_name LIMIT %s OFFSET %s",
            tuple(params),
        )

    def count_entities(
        self, domain_id: str, *, node_type: str | None = None, q: str | None = None,
    ) -> int:
        conds = ["domain_id = %s"]
        params: list[Any] = [domain_id]
        if node_type:
            conds.append("node_type = %s")
            params.append(node_type)
        if q:
            conds.append("canonical_name ILIKE %s")
            params.append(f"%{q}%")
        row = self._fetchone(
            f"SELECT COUNT(*) AS n FROM ontology_entities WHERE {' AND '.join(conds)}",
            tuple(params),
        )
        return int(row["n"]) if row else 0

    def get_entities_by_ids(self, entity_ids: list[str]) -> list[dict[str, Any]]:
        """批量取对象（邻域图渲染时按边里的 head/tail id 一次性取名字）。"""
        if not entity_ids:
            return []
        placeholders = ",".join(["%s"] * len(entity_ids))
        return self._fetchall(
            f"SELECT * FROM ontology_entities WHERE id IN ({placeholders})",
            tuple(entity_ids),
        )

    def confirmed_untyped_entities(
        self, domain_id: str, *, limit: int = 500,
    ) -> list[dict[str, Any]]:
        """N3 归纳输入：本领域已人确认（存在于 ontology_entities）的 __untyped__ 实体。

        Gate2 里人对"暂无类型"提及点"新建对象"，就落成一条 node_type='__untyped__' 的
        canonical 实体。这里把这批干净实体连同成员 mention 的 proposed_type 提示、原文引用
        一并捞出，喂给 ontology_induction（LLM 调用 2）聚类/命名/定义新类型。

        members 每项含 mention_text / proposed_type / segment_id / quote（原文截断 300 字）。
        """
        return self._fetchall(
            """SELECT e.id, e.canonical_name, e.mention_count, e.document_count,
                      COALESCE(json_agg(json_build_object(
                          'mention_text', m.mention_text,
                          'proposed_type', m.metadata_json->>'proposed_type',
                          'segment_id', m.segment_id,
                          'quote', LEFT(s.raw_text, 300)
                      ) ORDER BY m.id) FILTER (WHERE m.id IS NOT NULL), '[]') AS members
               FROM ontology_entities e
               LEFT JOIN asset_segment_entity_mentions m ON m.resolved_entity_id = e.id
               LEFT JOIN asset_raw_segments s ON s.id = m.segment_id
               WHERE e.domain_id = %s AND e.node_type = %s
               GROUP BY e.id, e.canonical_name, e.mention_count, e.document_count
               ORDER BY e.mention_count DESC NULLS LAST
               LIMIT %s""",
            (domain_id, UNTYPED_NODE_TYPE, limit),
        )

    def member_quotes(
        self, entity_ids: list[str], *, window: int = 80,
    ) -> dict[str, dict[str, str]]:
        """为每个成员实体取一条"包含该实体提及"的原文片段（围绕提及位置开窗）。

        本体确认页按实体展示各自的原文摘录。早先的实现给每个实体取它首条提及所在 segment 的
        前 300 字，多个实体若首次共现在同一段（如开头的列举句），摘录就完全一样。这里改成：
        优先选 raw_text 中确实出现该实体 mention_text 的片段，再以提及位置为中心开窗截取，
        于是即便共用一段，各实体也会落在自己提及附近的不同窗口上，互不相同。

        返回 {entity_id: {"quote": 片段, "mention": 提及原文}}；mention 供前端在片段中加粗。
        """
        if not entity_ids:
            return {}
        uniq = list(dict.fromkeys(e for e in entity_ids if e))
        if not uniq:
            return {}
        placeholders = ",".join(["%s"] * len(uniq))
        rows = self._fetchall(
            f"""SELECT DISTINCT ON (m.resolved_entity_id)
                       m.resolved_entity_id AS entity_id,
                       m.mention_text       AS mention,
                       s.raw_text           AS raw_text,
                       POSITION(m.mention_text IN s.raw_text) AS pos
                FROM asset_segment_entity_mentions m
                JOIN asset_raw_segments s ON s.id = m.segment_id
                WHERE m.resolved_entity_id IN ({placeholders})
                  AND COALESCE(m.mention_text, '') <> ''
                  AND COALESCE(s.raw_text, '') <> ''
                ORDER BY m.resolved_entity_id,
                         (POSITION(m.mention_text IN s.raw_text) > 0) DESC,
                         LENGTH(s.raw_text) ASC""",
            tuple(uniq),
        )
        out: dict[str, dict[str, str]] = {}
        for r in rows:
            text = r.get("raw_text") or ""
            mention = r.get("mention") or ""
            pos = int(r.get("pos") or 0) - 1  # POSITION 1-based；0=未找到 → -1
            if pos < 0:
                quote = text[: window * 2]
            else:
                start = max(0, pos - window)
                end = min(len(text), pos + len(mention) + window)
                quote = text[start:end]
                if start > 0:
                    quote = "…" + quote
                if end < len(text):
                    quote = quote + "…"
            out[r["entity_id"]] = {"quote": quote.strip(), "mention": mention}
        return out

    # -- 事实边（出处强制非空）--

    def upsert_relation(
        self,
        domain_id: str,
        *,
        head_entity_id: str,
        tail_entity_id: str,
        relation_type: str,
        source_refs: list,
        confidence: float = 0.7,
        ontology_version_id: str | None = None,
        has_conflict: bool = False,
    ) -> str:
        """落一条事实边。出处强制：source_refs 为空直接拒绝（不依赖 DB CHECK）。"""
        if not source_refs:
            raise ValueError(
                f"refused to upsert relation {head_entity_id}-{relation_type}->{tail_entity_id}: "
                "source_refs must be non-empty (出处强约束)"
            )
        if head_entity_id == tail_entity_id:
            raise ValueError("refused self-loop relation (head == tail)")
        rid = _new_id()
        self._execute(
            """INSERT INTO ontology_entity_relations
                   (id, domain_id, head_entity_id, tail_entity_id, relation_type,
                    confidence, source_refs_json, ontology_version_id, has_conflict)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (domain_id, head_entity_id, tail_entity_id, relation_type) DO UPDATE SET
                   confidence = excluded.confidence,
                   source_refs_json = excluded.source_refs_json,
                   has_conflict = excluded.has_conflict""",
            (rid, domain_id, head_entity_id, tail_entity_id, relation_type,
             confidence, _json_dumps(source_refs), ontology_version_id, has_conflict),
        )
        row = self._fetchone(
            """SELECT id FROM ontology_entity_relations
               WHERE domain_id = %s AND head_entity_id = %s AND tail_entity_id = %s AND relation_type = %s""",
            (domain_id, head_entity_id, tail_entity_id, relation_type),
        )
        return row["id"] if row else rid

    # -- 出处 --

    def add_evidence(
        self,
        domain_id: str,
        *,
        document_snapshot_id: str,
        segment_id: str,
        target_kind: str,
        target_id: str,
        quote: str | None = None,
    ) -> str:
        """挂一条出处（target_kind: entity|relation|mention），返回 evidence id。"""
        ev_id = _new_id()
        self._execute(
            """INSERT INTO ontology_evidence_nodes
                   (id, domain_id, document_snapshot_id, segment_id, quote, target_kind, target_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (ev_id, domain_id, document_snapshot_id, segment_id, quote, target_kind, target_id),
        )
        return ev_id

    def get_evidence(self, target_kind: str, target_id: str) -> list[dict[str, Any]]:
        """某对象/边/mention 的全部出处（检索侧出处回链用）。"""
        return self._fetchall(
            "SELECT * FROM ontology_evidence_nodes WHERE target_kind = %s AND target_id = %s ORDER BY created_at",
            (target_kind, target_id),
        )

    def evidence_for_target(self, target_id: str) -> list[dict[str, Any]]:
        """按 target_id 取全部出处（不限 kind）。出处回链页只拿到一个 id 时用。

        顺带 JOIN 片段拿原文引用，给前端直接展示"这条知识来自哪段原文"。
        """
        return self._fetchall(
            """SELECT e.*, s.raw_text AS segment_text, s.section_title AS segment_section
               FROM ontology_evidence_nodes e
               LEFT JOIN asset_raw_segments s ON s.id = e.segment_id
               WHERE e.target_id = %s ORDER BY e.created_at""",
            (target_id,),
        )

    def delete_snapshot_artifacts(self, document_snapshot_id: str) -> None:
        """删一份快照名下的 mention + evidence，供 B5 全局阶段"删后重写"实现幂等。

        ontology_entities / relations 是跨 build 累积的（不按 snapshot 删）；mention/evidence
        是 snapshot 域的，重跑同一文档时先清掉旧的再写，避免重复堆叠。
        """
        self._execute(
            "DELETE FROM ontology_evidence_nodes WHERE document_snapshot_id = %s", (document_snapshot_id,))
        self._execute(
            "DELETE FROM asset_segment_entity_mentions WHERE document_snapshot_id = %s",
            (document_snapshot_id,))

    # -- mention（文章级）--

    def add_mention(
        self,
        *,
        document_snapshot_id: str,
        segment_id: str,
        node_type: str,
        mention_text: str,
        canonical_name: str | None = None,
        resolved_entity_id: str | None = None,
        resolve_status: str = "pending",
        confidence: float = 1.0,
        metadata: dict | None = None,
    ) -> str:
        mid = _new_id()
        self._execute(
            """INSERT INTO asset_segment_entity_mentions
                   (id, document_snapshot_id, segment_id, node_type, mention_text,
                    canonical_name, resolved_entity_id, resolve_status, confidence, metadata_json)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (mid, document_snapshot_id, segment_id, node_type, mention_text,
             canonical_name, resolved_entity_id, resolve_status, confidence,
             _json_dumps(metadata or {})),
        )
        return mid

    # mention 列表统一带出所在 segment 的原文（§14.2：评审时可看上下文）
    _PENDING_SELECT = (
        "SELECT m.*, s.raw_text AS segment_text, s.section_title AS segment_section "
        "FROM asset_segment_entity_mentions m "
        "LEFT JOIN asset_raw_segments s ON s.id = m.segment_id "
    )

    def pending_mentions(self, document_snapshot_id: str | None = None) -> list[dict[str, Any]]:
        """待人审（Gate2）的 mention 列表（带 segment 原文）。"""
        if document_snapshot_id:
            return self._fetchall(
                self._PENDING_SELECT
                + "WHERE m.resolve_status = 'pending' AND m.document_snapshot_id = %s",
                (document_snapshot_id,),
            )
        return self._fetchall(
            self._PENDING_SELECT + "WHERE m.resolve_status = 'pending'",
        )

    def get_mention(self, mention_id: str) -> dict[str, Any] | None:
        return self._fetchone(
            "SELECT * FROM asset_segment_entity_mentions WHERE id = %s", (mention_id,))

    def pending_mentions_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Gate2 评审页：某 run 处理的快照下全部待审 mention（mention 无 run_id，经
        mining_run_documents 的 document_snapshot_id 关联）。"""
        return self._fetchall(
            """SELECT m.*, s.raw_text AS segment_text, s.section_title AS segment_section
               FROM asset_segment_entity_mentions m
               JOIN mining_run_documents d ON d.document_snapshot_id = m.document_snapshot_id
               LEFT JOIN asset_raw_segments s ON s.id = m.segment_id
               WHERE d.run_id = %s AND m.resolve_status = 'pending'
               ORDER BY m.id""",
            (run_id,),
        )

    def resolved_mentions_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """终态建边输入（N4/N5）：某 run 快照下全部已确认 mention，连到其归一实体的
        **当前** node_type / canonical_name（实体可能已被 N5 回贴成正式类型）+ 所在段原文。

        只取 resolve_status in (auto, human) 且已绑实体的——pending/rejected 不建边。
        """
        return self._fetchall(
            """SELECT m.document_snapshot_id, m.segment_id,
                      e.id AS entity_id, e.node_type AS node_type,
                      e.canonical_name AS canonical_name,
                      s.raw_text AS quote
               FROM asset_segment_entity_mentions m
               JOIN mining_run_documents d ON d.document_snapshot_id = m.document_snapshot_id
               JOIN ontology_entities e ON e.id = m.resolved_entity_id
               LEFT JOIN asset_raw_segments s ON s.id = m.segment_id
               WHERE d.run_id = %s AND m.resolved_entity_id IS NOT NULL
                     AND m.resolve_status IN ('auto', 'human')
               ORDER BY m.document_snapshot_id, m.segment_id""",
            (run_id,),
        )

    def resolved_mentions_around_entities(
        self, domain_id: str, entity_ids: list[str],
    ) -> list[dict[str, Any]]:
        """scoped 重算取数：给定一组实体，返回它们**所在段落**里的全部已确认 mention，
        连到各自归一实体的当前 node_type/canonical_name + 段落原文。

        形状与 resolved_mentions_for_run 一致（供 reaggregate_edges 直接消费）。
        邻居实体由"同段共现"自然带出——这正是 NPMI 需要重算的范围。
        """
        if not entity_ids:
            return []
        return self._fetchall(
            """SELECT m.document_snapshot_id, m.segment_id,
                      e.id AS entity_id, e.node_type AS node_type,
                      e.canonical_name AS canonical_name,
                      s.raw_text AS quote
               FROM asset_segment_entity_mentions m
               JOIN ontology_entities e ON e.id = m.resolved_entity_id
               LEFT JOIN asset_raw_segments s ON s.id = m.segment_id
               WHERE e.domain_id = %s
                 AND m.resolve_status IN ('auto', 'human')
                 AND m.segment_id IN (
                     SELECT DISTINCT m2.segment_id
                     FROM asset_segment_entity_mentions m2
                     WHERE m2.resolved_entity_id = ANY(%s)
                 )
               ORDER BY m.document_snapshot_id, m.segment_id""",
            (domain_id, list(entity_ids)),
        )

    def rebind_untyped_entities(
        self, domain_id: str, members: list[tuple[str, str]],
    ) -> int:
        """N5：Gate1 通过后把成员实体的 node_type 从 __untyped__ 改成新批准类型名。

        members 为 [(entity_id, new_type_name), ...]。带 node_type='__untyped__' 守卫保证幂等
        （已回贴过的实体不再动）。同名冲突（新类型下已存在同名实体）时跳过该条、记日志，
        避免撞唯一键 (domain, node_type, canonical_name)。返回成功回贴条数。
        """
        n = 0
        for entity_id, new_type in members:
            if not entity_id or not new_type or new_type == UNTYPED_NODE_TYPE:
                continue
            try:
                self._execute(
                    "UPDATE ontology_entities SET node_type = %s "
                    "WHERE id = %s AND domain_id = %s AND node_type = %s",
                    (new_type, entity_id, domain_id, UNTYPED_NODE_TYPE),
                )
                n += 1
            except Exception:
                logger.warning("rebind entity %s -> %s failed (name conflict?); skip",
                               entity_id, new_type, exc_info=True)
        return n

    def count_pending_mentions_for_run(self, run_id: str) -> int:
        """Gate2 触发判定：某 run 还有多少待人审 mention（B6 暂停检查）。"""
        row = self._fetchone(
            """SELECT COUNT(*) AS n FROM asset_segment_entity_mentions m
               JOIN mining_run_documents d ON d.document_snapshot_id = m.document_snapshot_id
               WHERE d.run_id = %s AND m.resolve_status = 'pending'""",
            (run_id,),
        )
        return int(row["n"]) if row else 0

    def resolve_mention(
        self, mention_id: str, *, action: str,
        entity_id: str | None = None, domain_id: str | None = None,
        canonical_name: str | None = None, node_type: str | None = None,
        first_ontology_version_id: str | None = None,
    ) -> str | None:
        """Gate2 单条裁决。action: merge | new | reject。返回归一到的 entity_id（reject→None）。

        - merge：mention 指向已有 canonical 对象（entity_id），status='human'；
        - new：按 mention 自身新建一个 domain_entity，再指过去；
        - reject：标 resolve_status='rejected'（非实体，丢弃）。
        """
        if action == "reject":
            self._execute(
                "UPDATE asset_segment_entity_mentions SET resolve_status = 'rejected' WHERE id = %s",
                (mention_id,))
            return None

        m = self.get_mention(mention_id)
        if m is None:
            raise ValueError(f"mention not found: {mention_id}")

        if action == "merge":
            if not entity_id:
                raise ValueError("merge 需要 entity_id")
            ent = self.get_entity(entity_id)
            canon = ent["canonical_name"] if ent else canonical_name
            ev_domain = domain_id or (ent.get("domain_id") if ent else None)
        elif action == "new":
            did = domain_id or m.get("metadata_json", {}).get("domain_id")
            if not did:
                raise ValueError("new 需要 domain_id")
            canon = canonical_name or m["mention_text"]
            entity_id = self.upsert_entity(
                did, canonical_name=canon, node_type=node_type or m["node_type"],
                first_ontology_version_id=first_ontology_version_id,
            )
            ev_domain = did
        else:
            raise ValueError(f"unknown resolve action: {action!r}")

        self._execute(
            "UPDATE asset_segment_entity_mentions SET resolved_entity_id = %s, "
            "canonical_name = %s, resolve_status = 'human' WHERE id = %s",
            (entity_id, canon, mention_id))

        # 人审激活了这条原 pending 提及 → 给目标实体 mention_count 即时 +1（Gate2 列表/推荐
        # 立刻反映人确认的热度）。document_count 因要按文档去重不在此即时算，连同 mention_count
        # 的权威值由收尾 _finalize_graph 从全部已确认 mention set 重算矫正（以重算为准）。
        if entity_id:
            self.bump_entity_counts(entity_id, mention_delta=1)

        # 出处强制（L1 §7 / L4 §14.5）：人工确认实体时，把这条提及的 segment 作为该实体的
        # 权威出处写进 ontology_evidence_nodes —— 修复 Gate2 确认实体不写出处、导致"实体连不到原文"的漏洞。
        # 同一实体的多个段落自然落成多行（target_id=实体id 重复，segment_id 不同）。
        seg_id = m.get("segment_id")
        snap_id = m.get("document_snapshot_id")
        if entity_id and seg_id and snap_id and ev_domain:
            self.add_evidence(
                ev_domain, document_snapshot_id=snap_id, segment_id=seg_id,
                target_kind="entity", target_id=entity_id, quote=m.get("mention_text"))
        return entity_id

    def resolve_mentions_batch(
        self, mention_ids: list[str], *, action: str,
        entity_id: str | None = None, domain_id: str | None = None,
        node_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Gate2 批量裁决：对一批 mention 套用同一 action（reject / new / merge）。

        - reject：全部丢弃；
        - new：每条按自身新建对象（upsert_entity 按 canonical_name 聚合，同名自动并）；
        - merge：全部并到同一个已有对象（entity_id）。

        复用单条 resolve_mention 循环，逐条返回结果；**单条失败不阻断其余**
        （每条 _execute 各自 auto-commit，与单条裁决一致）。
        """
        results: list[dict[str, Any]] = []
        for mid in mention_ids:
            try:
                eid = self.resolve_mention(
                    mid, action=action, entity_id=entity_id,
                    domain_id=domain_id, node_type=node_type,
                )
                results.append({"mention_id": mid, "resolved_entity_id": eid, "ok": True})
            except Exception as e:  # noqa: BLE001
                results.append({"mention_id": mid, "error": str(e), "ok": False})
        return results

    def suggest_entities_for_mention(
        self, domain_id: str, *, mention_text: str, node_type: str, limit: int = 5,
    ) -> list[dict[str, Any]]:
        """§14.3：Gate2 实时推荐——同 node_type 下、名字与提及**双向包含**的已有对象，
        按提及数降序取 top-N。双向包含让"SMF会话"能命中已有"SMF"（实体名含提及，或提及含实体名）。

        局限（TODO）：纯字面匹配，"会话管理功能↔SMF"这类语义异形抓不到；后续接别名词典
        （ontology_alias_dictionary）或向量相似度增强。
        """
        if not mention_text or not node_type:
            return []
        like = f"%{mention_text}%"
        return self._fetchall(
            """SELECT * FROM ontology_entities
               WHERE domain_id = %s AND node_type = %s
                 AND (canonical_name ILIKE %s OR %s ILIKE '%%' || canonical_name || '%%')
               ORDER BY mention_count DESC
               LIMIT %s""",
            (domain_id, node_type, like, mention_text, limit),
        )

    # -- scoped 重算辅助 --

    def delete_edges_among(self, domain_id: str, entity_ids: list[str]) -> int:
        """删除两端点都在 entity_ids 内的事实边（scoped 重算前清旧边，无损）。返回删除条数。"""
        if not entity_ids:
            return 0
        ids = list(entity_ids)
        row = self._fetchone(
            """WITH del AS (
                   DELETE FROM ontology_entity_relations
                   WHERE domain_id = %s
                     AND head_entity_id = ANY(%s) AND tail_entity_id = ANY(%s)
                   RETURNING 1
               ) SELECT count(*) AS n FROM del""",
            (domain_id, ids, ids),
        )
        return int(row["n"]) if row else 0

    # -- 邻域遍历（递归 CTE，迁图时只换这里）--

    def neighbors(self, entity_id: str, *, hops: int = 1) -> list[dict[str, Any]]:
        """返回 entity 的 hops 跳邻域内的边（无向遍历）。

        迁 NebulaGraph 时本方法重写为 nGQL GO/MATCH，调用方零改动（L2 §10.1-①）。
        """
        if hops < 1:
            return []
        return self._fetchall(
            """WITH RECURSIVE reach(entity_id, depth) AS (
                   SELECT %s::text, 0
                 UNION
                   SELECT CASE WHEN r.head_entity_id = reach.entity_id
                               THEN r.tail_entity_id ELSE r.head_entity_id END,
                          reach.depth + 1
                   FROM reach
                   JOIN ontology_entity_relations r
                     ON (r.head_entity_id = reach.entity_id OR r.tail_entity_id = reach.entity_id)
                   WHERE reach.depth < %s
               )
               SELECT DISTINCT r.*
               FROM ontology_entity_relations r
               WHERE r.head_entity_id IN (SELECT entity_id FROM reach)
                  OR r.tail_entity_id IN (SELECT entity_id FROM reach)""",
            (entity_id, hops),
        )

    # -- 实体合并 --

    def merge_entities(
        self, domain_id: str, primary_id: str, drop_ids: list[str],
    ) -> list[str]:
        """把 drop_ids 的提及全部改指 primary_id，删除 drop 实体，重算 primary 计数。
        返回受影响实体 id 列表（含 primary）——供 scoped_recompute 使用。
        """
        drops = [d for d in drop_ids if d and d != primary_id]
        if not drops:
            return [primary_id]
        # 多步写入放进同一事务，半路出错整体回滚，避免「提及搬走但实体没删」的半合并脏态。
        with self.transaction():
            # 1) 提及改指主实体
            self._execute(
                "UPDATE asset_segment_entity_mentions SET resolved_entity_id = %s "
                "WHERE resolved_entity_id = ANY(%s)",
                (primary_id, drops),
            )
            # 1b) 出处证据也改指主实体（保留 provenance，不留悬空 target_id）
            self._execute(
                "UPDATE ontology_evidence_nodes SET target_id = %s "
                "WHERE target_kind = 'entity' AND target_id = ANY(%s)",
                (primary_id, drops),
            )
            # 2) 删被并实体的事实边与实体本身（提及已搬走）
            self._execute(
                "DELETE FROM ontology_entity_relations "
                "WHERE head_entity_id = ANY(%s) OR tail_entity_id = ANY(%s)",
                (drops, drops),
            )
            self._execute(
                "DELETE FROM ontology_entities WHERE id = ANY(%s) AND domain_id = %s",
                (drops, domain_id),
            )
            # 3) 重算主实体计数（提及行数 / 去重文档数）
            self._recount_one(domain_id, primary_id)
        return [primary_id]

    def retype_entity(self, domain_id: str, entity_id: str, new_type: str) -> list[str]:
        """改实体 node_type。若新 (node_type, canonical_name) 已有实体 → 并入它（撞唯一键即合并）。
        返回受影响实体 id 列表（普通改类型为 [entity_id]；撞名合并为 [target_id]）。
        """
        # 取数 + 撞名合并 + 改类型放进同一事务（嵌套调用 merge_entities 复用本事务，不另起 BEGIN）。
        with self.transaction():
            ent = self._fetchone(
                "SELECT canonical_name, node_type FROM ontology_entities WHERE id=%s AND domain_id=%s",
                (entity_id, domain_id))
            if ent is None or ent["node_type"] == new_type:
                return [entity_id]
            existing = self._fetchone(
                "SELECT id FROM ontology_entities "
                "WHERE domain_id=%s AND node_type=%s AND canonical_name=%s",
                (domain_id, new_type, ent["canonical_name"]))
            if existing and existing["id"] != entity_id:
                return self.merge_entities(domain_id, existing["id"], [entity_id])
            self._execute(
                "UPDATE ontology_entities SET node_type=%s WHERE id=%s AND domain_id=%s",
                (new_type, entity_id, domain_id))
            return [entity_id]

    def delete_entity(self, domain_id: str, entity_id: str) -> None:
        """删除实体及其提及、出处证据、相连事实边。纯减法——不改变其它实体对的共现，无需重算。"""
        with self.transaction():
            self._execute(
                "DELETE FROM ontology_entity_relations "
                "WHERE head_entity_id=%s OR tail_entity_id=%s", (entity_id, entity_id))
            self._execute(
                "DELETE FROM asset_segment_entity_mentions WHERE resolved_entity_id=%s", (entity_id,))
            self._execute(
                "DELETE FROM ontology_evidence_nodes "
                "WHERE target_kind='entity' AND target_id=%s", (entity_id,))
            self._execute(
                "DELETE FROM ontology_entities WHERE id=%s AND domain_id=%s", (entity_id, domain_id))

    def _recount_one(self, domain_id: str, entity_id: str) -> None:
        """按已确认 mention 重算单个实体的 mention_count / document_count，set 置准。"""
        self._execute(
            """UPDATE ontology_entities e SET
                   mention_count = sub.mc, document_count = sub.dc
               FROM (
                   SELECT count(*) AS mc, count(DISTINCT document_snapshot_id) AS dc
                   FROM asset_segment_entity_mentions
                   WHERE resolved_entity_id = %s AND resolve_status IN ('auto','human')
               ) sub
               WHERE e.id = %s AND e.domain_id = %s""",
            (entity_id, entity_id, domain_id),
        )
