"""Test ingestion: folder scan with md/txt/html/pdf/docx, skip manifest.jsonl."""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from knowledge_mining.mining.ingestion import ingest_directory
from knowledge_mining.mining.models import BatchParams


def _write_files(tmp: Path, files: dict[str, str | bytes]) -> None:
    for name, content in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")


class TestIngestMarkdown:
    def test_discovers_md_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {
                "doc1.md": "# Hello\n\nWorld",
                "sub/doc2.md": "# Sub\n\nContent",
            })
            docs, summary = ingest_directory(tmp)
            assert len(docs) == 2
            assert summary["discovered_documents"] == 2
            assert summary["parsed_documents"] == 2

    def test_inherits_batch_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"doc.md": "# Title"})
            bp = BatchParams(
                default_source_type="api_import",
                default_document_type="command",
                batch_scope={"product": "5G"},
                tags=["v1"],
            )
            docs, _ = ingest_directory(tmp, bp)
            assert len(docs) == 1
            assert docs[0].source_type == "api_import"
            assert docs[0].document_type == "command"
            assert docs[0].scope_json == {"product": "5G"}
            assert docs[0].tags_json == ["v1"]

    def test_title_from_h1(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"doc.md": "# My Title\n\nContent"})
            docs, _ = ingest_directory(tmp)
            assert docs[0].title == "My Title"

    def test_title_from_filename_when_no_h1(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"readme.md": "No heading here"})
            docs, _ = ingest_directory(tmp)
            assert docs[0].title == "readme"

    def test_content_hash_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            content = "# Hello\n\nWorld"
            _write_files(tmp, {"doc.md": content})
            docs, _ = ingest_directory(tmp)
            # Hash is computed from file bytes, verify it's a valid sha256 hex
            assert len(docs[0].content_hash) == 64
            # Also verify determinism: same content → same hash
            _write_files(tmp, {"doc2.md": content})
            docs2, _ = ingest_directory(tmp)
            assert docs[0].content_hash == docs2[1].content_hash

    def test_structure_quality_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"doc.md": "# Test"})
            docs, _ = ingest_directory(tmp)
            assert docs[0].structure_quality == "markdown_native"

    def test_file_type_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {
                "a.md": "# A",
                "b.markdown": "# B",
            })
            docs, _ = ingest_directory(tmp)
            assert all(d.file_type == "markdown" for d in docs)

    def test_relative_path_forward_slashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"sub/dir/doc.md": "# Test"})
            docs, _ = ingest_directory(tmp)
            assert "\\" not in docs[0].relative_path
            assert docs[0].relative_path == "sub/dir/doc.md"


class TestIngestTxt:
    def test_discovers_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"data.txt": "Plain text content"})
            docs, summary = ingest_directory(tmp)
            assert len(docs) == 1
            assert docs[0].file_type == "txt"
            assert summary["parsed_documents"] == 1

    def test_structure_quality_plain(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"data.txt": "content"})
            docs, _ = ingest_directory(tmp)
            assert docs[0].structure_quality == "plain_text_only"


class TestIngestHtmlPdfDocx:
    def test_html_registered_but_empty_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"page.html": "<html><body>Hello</body></html>"})
            docs, summary = ingest_directory(tmp)
            assert len(docs) == 1
            assert docs[0].file_type == "html"
            assert docs[0].content == ""
            assert summary["unparsed_documents"] == 1
            assert summary["parsed_documents"] == 0

    def test_htm_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"page.htm": "<html><body>Hi</body></html>"})
            docs, _ = ingest_directory(tmp)
            assert docs[0].file_type == "html"

    def test_pdf_binary_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"doc.pdf": b"%PDF-1.4 fake content"})
            docs, summary = ingest_directory(tmp)
            assert len(docs) == 1
            assert docs[0].file_type == "pdf"
            assert docs[0].content == ""
            assert summary["unparsed_documents"] == 1

    def test_docx_binary_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"doc.docx": b"PK\x03\x04 fake docx"})
            docs, summary = ingest_directory(tmp)
            assert len(docs) == 1
            assert docs[0].file_type == "docx"
            assert docs[0].content == ""

    def test_doc_binary_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"doc.doc": b"\xd0\xcf\x11\xe0 fake doc"})
            docs, summary = ingest_directory(tmp)
            assert len(docs) == 1
            assert docs[0].file_type == "doc"

    def test_html_structure_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {"page.html": "<html></html>"})
            docs, _ = ingest_directory(tmp)
            assert docs[0].structure_quality == "full_html"


class TestIngestSkipFiles:
    def test_skip_manifest_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {
                "doc.md": "# Hello",
                "manifest.jsonl": '{"doc_id":"x"}\n',
            })
            docs, summary = ingest_directory(tmp)
            assert len(docs) == 1
            assert summary["skipped_files"] == 1

    def test_skip_manifest_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {
                "doc.md": "# Hello",
                "manifest.json": "[]",
            })
            docs, summary = ingest_directory(tmp)
            assert summary["skipped_files"] == 1

    def test_skip_system_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {
                "doc.md": "# Hello",
                ".DS_Store": "fake",
                "Thumbs.db": "fake",
                ".gitkeep": "",
            })
            docs, summary = ingest_directory(tmp)
            assert len(docs) == 1
            assert summary["skipped_files"] == 3

    def test_skip_unrecognized_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {
                "doc.md": "# Hello",
                "image.png": b"\x89PNG",
                "data.csv": "a,b,c",
            })
            docs, summary = ingest_directory(tmp)
            assert len(docs) == 1
            assert summary["skipped_files"] == 2


class TestIngestMixed:
    def test_mixed_file_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {
                "readme.md": "# Readme\n\nContent",
                "notes.txt": "Some plain text",
                "page.html": "<html></html>",
                "doc.pdf": b"%PDF fake",
                "doc.docx": b"PK fake",
            })
            docs, summary = ingest_directory(tmp)
            assert len(docs) == 5
            assert summary["discovered_documents"] == 5
            assert summary["parsed_documents"] == 2  # md + txt
            assert summary["unparsed_documents"] == 3  # html + pdf + docx

    def test_recursive_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_files(tmp, {
                "root.md": "# Root",
                "sub/deep/nested.md": "# Nested",
            })
            docs, _ = ingest_directory(tmp)
            assert len(docs) == 2


class TestIngestEmpty:
    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs, summary = ingest_directory(Path(tmp))
            assert docs == []
            assert summary["discovered_documents"] == 0
