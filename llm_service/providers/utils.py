"""Shared provider utilities."""


def extract_doc_text(doc) -> str:
    """Normalize rerank document field: str | dict | None → str.

    External API returns:  {"document": "some text"}
    Internal API returns:  {"document": {"text": "some text", "multi_modal": null}}
    """
    if doc is None:
        return ""
    if isinstance(doc, dict):
        return doc.get("text", "")
    return str(doc)
