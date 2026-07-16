"""草稿编辑器路由契约测试：3 个新路由已注册、HTTP 方法正确。

不连 DB、不起服务——只导入 APIRouter 检查 route 表。业务逻辑由 test_ontology_draft.py 覆盖。
"""
from __future__ import annotations

from knowledge_mining.mining.api.routes.ontology import router


def _route_methods() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for r in router.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if path and methods:
            out.setdefault(path, set()).update(methods)
    return out


def test_draft_get_and_put_registered() -> None:
    rm = _route_methods()
    assert "/api/ontology/draft" in rm
    assert "GET" in rm["/api/ontology/draft"]
    assert "PUT" in rm["/api/ontology/draft"]


def test_draft_publish_registered() -> None:
    rm = _route_methods()
    assert "/api/ontology/draft/publish" in rm
    assert "POST" in rm["/api/ontology/draft/publish"]
