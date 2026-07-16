"""草稿编辑器后端单测：OntologyStore 草稿原语（纯逻辑 + 假 store，无需 DB）。

覆盖：
- get_draft_version / node_types_for_version / relation_types_for_version / delete_version_types：SQL 拼装与参数；
- replace_draft：无 draft → 新建 draft 版本 + 写类型；有 draft → 先删旧类型再重写；
- publish_draft：有 draft → 调 activate_version；无 draft → 返回 None。
"""
from __future__ import annotations

from contextlib import contextmanager

from knowledge_mining.mining.infra.ontology_store import OntologyStore


# ---- 读/删原语：校验 SQL 拼装 ----

class _FakeQueryOnto(OntologyStore):
    """记录 _fetchall/_fetchone/_execute 的 SQL+params，校验草稿读/删 SQL。"""

    def __init__(self) -> None:
        self.queries: list[tuple[str, tuple]] = []
        self.executed: list[tuple[str, tuple]] = []

    def _fetchall(self, sql, params=()):  # type: ignore[override]
        self.queries.append((sql, tuple(params)))
        return []

    def _fetchone(self, sql, params=()):  # type: ignore[override]
        self.queries.append((sql, tuple(params)))
        return None

    def _execute(self, sql, params=()):  # type: ignore[override]
        self.executed.append((sql, tuple(params)))


def test_get_draft_version_filters_status_draft() -> None:
    g = _FakeQueryOnto()
    g.get_draft_version("dom")
    sql, params = g.queries[0]
    assert "ontology_versions" in sql and "status = 'draft'" in sql
    assert "domain_id = %s" in sql
    assert params == ("dom",)


def test_node_types_for_version_filters_by_version_id() -> None:
    g = _FakeQueryOnto()
    g.node_types_for_version("v1")
    sql, params = g.queries[0]
    assert "ontology_node_types" in sql and "ontology_version_id = %s" in sql
    assert params == ("v1",)


def test_relation_types_for_version_filters_by_version_id() -> None:
    g = _FakeQueryOnto()
    g.relation_types_for_version("v1")
    sql, params = g.queries[0]
    assert "ontology_relation_types" in sql and "ontology_version_id = %s" in sql
    assert params == ("v1",)


def test_delete_version_types_deletes_both_tables() -> None:
    g = _FakeQueryOnto()
    g.delete_version_types("v1")
    assert len(g.executed) == 2
    assert all("DELETE" in s for s, _ in g.executed)
    assert any("ontology_node_types" in s for s, _ in g.executed)
    assert any("ontology_relation_types" in s for s, _ in g.executed)
    assert all(p == ("v1",) for _, p in g.executed)


# ---- replace_draft / publish_draft：编排逻辑 ----

class _FakeReplaceOnto(OntologyStore):
    """覆盖 transaction + 被 replace_draft/publish_draft 调用的高层方法，记录调用序列。"""

    def __init__(self, *, draft=None, version_no=5) -> None:
        self.calls: list[tuple] = []
        self._draft = draft
        self._version_no = version_no

    @contextmanager
    def transaction(self):  # type: ignore[override]
        self.calls.append(("transaction",))
        yield

    def get_draft_version(self, domain_id):  # type: ignore[override]
        return self._draft

    def next_version_no(self, domain_id):  # type: ignore[override]
        return self._version_no

    def create_version(self, domain_id, *, version_no, status="draft",
                       source="human_review", created_by=None, note=None):  # type: ignore[override]
        self.calls.append(("create_version", domain_id, version_no, status, source))
        return "new-draft-vid"

    def delete_version_types(self, version_id):  # type: ignore[override]
        self.calls.append(("delete_version_types", version_id))

    def add_node_type(self, version_id, **kw):  # type: ignore[override]
        self.calls.append(("add_node_type", version_id, kw["name"]))
        return "n"

    def add_relation_type(self, version_id, **kw):  # type: ignore[override]
        self.calls.append(("add_relation_type", version_id, kw["name"]))
        return "r"

    def activate_version(self, version_id, domain_id):  # type: ignore[override]
        self.calls.append(("activate_version", version_id, domain_id))


_NODES = [{"name": "feature", "layer": "concept", "is_strong": True,
           "definition": "d", "examples": ["x"]}]
_RELS = [{"name": "triggers", "layer": "concept", "is_directed": True,
          "inverse_name": None, "allowed_pairs": [{"head": "alarm", "tail": "feature"}],
          "definition": None}]


def test_replace_draft_creates_when_no_draft() -> None:
    store = _FakeReplaceOnto(draft=None, version_no=7)
    vid = store.replace_draft("dom", _NODES, _RELS, created_by="tester")
    assert vid == "new-draft-vid"
    kinds = [c[0] for c in store.calls]
    # 无 draft：先建 draft 版本，再写点/边类型；不调 delete_version_types
    assert kinds[0] == "transaction"
    assert ("create_version", "dom", 7, "draft", "human_edit") in store.calls
    assert "delete_version_types" not in kinds
    assert ("add_node_type", "new-draft-vid", "feature") in store.calls
    assert ("add_relation_type", "new-draft-vid", "triggers") in store.calls


def test_replace_draft_clears_then_rewrites_when_draft_exists() -> None:
    store = _FakeReplaceOnto(draft={"id": "old-draft"}, version_no=7)
    vid = store.replace_draft("dom", _NODES, _RELS)
    assert vid == "old-draft"
    kinds = [c[0] for c in store.calls]
    # 有 draft：不新建版本，先删旧类型再重写
    assert "create_version" not in kinds
    assert ("delete_version_types", "old-draft") in store.calls
    assert kinds.index("delete_version_types") < kinds.index("add_node_type")
    assert ("add_node_type", "old-draft", "feature") in store.calls
    assert ("add_relation_type", "old-draft", "triggers") in store.calls


def test_publish_draft_activates_existing_draft() -> None:
    store = _FakeReplaceOnto(draft={"id": "draft-1"})
    out = store.publish_draft("dom")
    assert out == "draft-1"
    assert ("activate_version", "draft-1", "dom") in store.calls


def test_publish_draft_none_when_no_draft() -> None:
    store = _FakeReplaceOnto(draft=None)
    assert store.publish_draft("dom") is None
    assert all(c[0] != "activate_version" for c in store.calls)
