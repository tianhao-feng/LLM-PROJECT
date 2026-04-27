import os
import unittest
import uuid

from autofpga.rag import (
    answer_has_source_citation,
    build_or_load_vector_db,
    build_in_memory_collection,
    build_pdf_chunks,
    build_pdf_chunks_with_pdftotext,
    build_text_chunks,
    bm25_scores,
    embed_chunks,
    extract_query_terms,
    extract_answer_technical_terms,
    find_ungrounded_answer_terms,
    format_citation_warning,
    format_dry_run_report,
    format_index_summary,
    format_grounding_warning,
    InMemoryCollection,
    iter_knowledge_files,
    lexical_hash_embedding,
    retrieve_context,
    summarize_index,
)


class RagKnowledgeFileTests(unittest.TestCase):
    def test_iter_knowledge_files_scans_datasheets_and_knowledge_base_recursively(self):
        root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"rag_{uuid.uuid4().hex}")
        datasheets = os.path.join(root, "datasheets")
        kb = os.path.join(root, "knowledge_base")
        nested = os.path.join(kb, "xilinx_skill")
        os.makedirs(datasheets)
        os.makedirs(nested)
        with open(os.path.join(datasheets, "device.md"), "w", encoding="utf-8") as f:
            f.write("# Device")
        with open(os.path.join(nested, "xdc_constraints_notes.md"), "w", encoding="utf-8") as f:
            f.write("# XDC")
        with open(os.path.join(nested, "ignore.json"), "w", encoding="utf-8") as f:
            f.write("{}")

        class Ctx:
            pass

        ctx = Ctx()
        ctx.script_dir = root
        ctx.datasheet_dir = datasheets
        ctx.kb_dir = kb

        source_ids = sorted(source_id for _, source_id, _ in iter_knowledge_files(ctx))

        self.assertEqual(source_ids, ["datasheets/device.md", "knowledge_base/xilinx_skill/xdc_constraints_notes.md"])

    def test_build_text_chunks_uses_markdown_headings_and_hash_metadata(self):
        root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"rag_chunks_{uuid.uuid4().hex}")
        os.makedirs(root)
        path = os.path.join(root, "notes.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# XDC\n\ncreate_clock defines clock timing.\n\n## Pins\n\nPACKAGE_PIN maps ports to pins.\n")

        texts, metas, ids = build_text_chunks(path, "knowledge_base/notes.md", "knowledge_base", "abc123")

        self.assertTrue(any("create_clock" in text for text in texts))
        self.assertTrue(any(meta["heading"] == "XDC" for meta in metas))
        self.assertTrue(all(meta["content_hash"] == "abc123" for meta in metas))
        self.assertTrue(all(meta["source_group"] == "knowledge_base" for meta in metas))
        self.assertTrue(all(id_.startswith("knowledge_base/notes.md_chunk_") for id_ in ids))

    def test_build_pdf_chunks_emits_separate_table_chunks(self):
        import autofpga.rag as rag

        class FakePage:
            def extract_text(self):
                return "Configuration voltage page text for CFGBVS settings."

            def extract_tables(self, settings):
                return [[["Pin", "Voltage"], ["CFGBVS", "CONFIG_VOLTAGE"]]]

        class FakePdf:
            pages = [FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"rag_pdf_{uuid.uuid4().hex}")
        os.makedirs(root)
        path = os.path.join(root, "device.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF-test")

        old_has_pdf = rag.HAS_PDF_PLUMBER
        old_pdfplumber = getattr(rag, "pdfplumber", None)
        try:
            rag.HAS_PDF_PLUMBER = True
            rag.pdfplumber = type("FakePdfPlumber", (), {"open": staticmethod(lambda path: FakePdf())})
            texts, metas, ids = build_pdf_chunks(path, "datasheets/device.pdf", "datasheets", "hash")
        finally:
            rag.HAS_PDF_PLUMBER = old_has_pdf
            if old_pdfplumber is None:
                delattr(rag, "pdfplumber")
            else:
                rag.pdfplumber = old_pdfplumber

        self.assertTrue(any(meta["chunk_type"] == "pdf_table" for meta in metas))
        self.assertTrue(any("| Pin | Voltage |" in text for text in texts))
        self.assertTrue(any("table_0" in id_ for id_ in ids))

    def test_build_pdf_chunks_with_pdftotext_fallback(self):
        import autofpga.rag as rag

        root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"rag_pdftotext_{uuid.uuid4().hex}")
        os.makedirs(root)
        path = os.path.join(root, "device.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF-test")

        class FakeResult:
            returncode = 0
            stdout = "BUFR regional clock buffer for FPGA clocking resources with enough extracted text to index.\fSecond page"
            stderr = ""

        old_which = rag.shutil.which
        old_run = rag.subprocess.run
        try:
            rag.shutil.which = lambda name: "pdftotext"
            rag.subprocess.run = lambda *args, **kwargs: FakeResult()
            texts, metas, ids = build_pdf_chunks_with_pdftotext(path, "datasheets/device.pdf", "datasheets", "hash")
        finally:
            rag.shutil.which = old_which
            rag.subprocess.run = old_run

        self.assertTrue(any("BUFR" in text for text in texts))
        self.assertEqual(metas[0]["chunk_type"], "pdf_page_text")
        self.assertIn("_p1_", ids[0])

    def test_embed_chunks_skips_failed_embeddings(self):
        texts = ["valid first", "failed second", "valid third"]
        metas = [{"source_id": "a"}, {"source_id": "b"}, {"source_id": "c"}]
        ids = ["a_0", "b_0", "c_0"]

        def fake_embedding(text):
            if "failed" in text:
                return []
            return [1.0, 0.0, 0.5]

        embeddings, valid_texts, valid_metas, valid_ids, skipped = embed_chunks(
            texts, metas, ids, embedding_fn=fake_embedding
        )

        self.assertEqual(skipped, 1)
        self.assertEqual(len(embeddings), 3)
        self.assertEqual(embeddings[0], [1.0, 0.0, 0.5])
        self.assertEqual(embeddings[2], [1.0, 0.0, 0.5])
        self.assertEqual(valid_texts, texts)
        self.assertEqual(valid_metas, metas)
        self.assertEqual(valid_ids, ids)

    def test_lexical_hash_embedding_is_stable_for_embedding_fallback(self):
        first = lexical_hash_embedding("create_clock PACKAGE_PIN", dims=16)
        second = lexical_hash_embedding("create_clock PACKAGE_PIN", dims=16)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)
        self.assertGreater(sum(abs(value) for value in first), 0.0)

    def test_retrieve_context_uses_keyword_fallback_when_embedding_fails(self):
        class FakeCollection:
            def get(self, include=None):
                return {
                    "ids": ["a", "b"],
                    "documents": [
                        "Vivado implementation command is route_design.",
                        "Use create_clock and PACKAGE_PIN in XDC constraints.",
                    ],
                    "metadatas": [
                        {"source_id": "knowledge_base/vivado.md", "page": "N/A", "chunk_index": "0", "heading": "Flow"},
                        {"source_id": "knowledge_base/xdc.md", "page": "N/A", "chunk_index": "1", "heading": "XDC"},
                    ],
                }

        import autofpga.rag as rag

        old_get_embedding = rag.get_embedding
        try:
            rag.get_embedding = lambda query: []
            retrieved = retrieve_context(FakeCollection(), "How to use create_clock PACKAGE_PIN?", top_k=1)
        finally:
            rag.get_embedding = old_get_embedding

        self.assertEqual(len(retrieved), 1)
        self.assertIn("xdc.md", retrieved[0]["source"])
        self.assertIn("create_clock", retrieved[0]["text"])

    def test_retrieve_context_handles_missing_collection_ids(self):
        class FakeCollection:
            def get(self, include=None):
                return {
                    "documents": ["NSTD-1 means unspecified IO standard."],
                    "metadatas": [{"source_id": "knowledge_base/errors.md", "page": "N/A", "chunk_index": "0"}],
                }

        import autofpga.rag as rag

        old_get_embedding = rag.get_embedding
        try:
            rag.get_embedding = lambda query: []
            retrieved = retrieve_context(FakeCollection(), "NSTD-1", top_k=1)
        finally:
            rag.get_embedding = old_get_embedding

        self.assertEqual(retrieved[0]["id"], "keyword_0")
        self.assertIn("NSTD-1", retrieved[0]["text"])

    def test_extract_query_terms_filters_common_stopwords_but_keeps_technical_terms(self):
        terms = extract_query_terms("How to use UCIO-1 and create_clock in XDC?")

        self.assertNotIn("how", terms)
        self.assertNotIn("to", terms)
        self.assertNotIn("use", terms)
        self.assertIn("ucio-1", terms)
        self.assertIn("create_clock", terms)
        self.assertIn("xdc", terms)

    def test_extract_query_terms_keeps_ascii_term_from_mixed_chinese_query(self):
        terms = extract_query_terms("讲一下BUFR")

        self.assertIn("bufr", terms)
        self.assertNotIn("一下", terms)

    def test_bm25_prefers_focused_repeated_terms_over_long_generic_text(self):
        docs = [
            "create_clock create_clock PACKAGE_PIN",
            "generic Vivado documentation " * 80 + "create_clock",
        ]
        scores = bm25_scores(docs, {"create_clock", "package_pin"})

        self.assertGreater(scores[0], scores[1])

    def test_format_dry_run_report_includes_sources_and_trimmed_chunks(self):
        retrieved = [
            {
                "source": "knowledge_base/xdc.md | XDC | chunk 0",
                "score": 1.2345,
                "text": "create_clock " + ("x" * 100),
            }
        ]

        report = format_dry_run_report(retrieved, max_chars=40)

        self.assertIn("Sources:", report)
        self.assertIn("knowledge_base/xdc.md", report)
        self.assertIn("score=1.234", report)
        self.assertIn("...", report)

    def test_answer_source_citation_detection(self):
        self.assertTrue(answer_has_source_citation("Use create_clock [1].", 2))
        self.assertTrue(answer_has_source_citation("See Source 2 for PACKAGE_PIN.", 2))
        self.assertTrue(answer_has_source_citation("参考来源 1。", 2))
        self.assertFalse(answer_has_source_citation("Use create_clock.", 2))

    def test_format_citation_warning_lists_sources(self):
        warning = format_citation_warning(
            [{"source": "knowledge_base/xdc.md | chunk 0", "score": 1.0, "text": "create_clock"}]
        )

        self.assertIn("WARNING", warning)
        self.assertIn("knowledge_base/xdc.md", warning)

    def test_answer_grounding_detects_technical_terms_missing_from_chunks(self):
        retrieved = [{"text": "create_clock and PACKAGE_PIN are XDC constraints."}]
        answer = "Use create_clock [1], then run UNKNOWN_PRIMITIVE."

        self.assertIn("unknown_primitive", extract_answer_technical_terms(answer))
        self.assertEqual(find_ungrounded_answer_terms(answer, retrieved), ["unknown_primitive"])
        self.assertIn("UNKNOWN_PRIMITIVE".lower(), format_grounding_warning(["unknown_primitive"]).lower())

    def test_index_summary_groups_chunks_by_source(self):
        class FakeCollection:
            def get(self, include=None):
                return {
                    "metadatas": [
                        {
                            "source_id": "knowledge_base/xdc.md",
                            "source_group": "knowledge_base",
                            "file_type": "md",
                            "content_hash": "abcdef1234567890",
                            "mtime": "100",
                        },
                        {
                            "source_id": "knowledge_base/xdc.md",
                            "source_group": "knowledge_base",
                            "file_type": "md",
                            "content_hash": "abcdef1234567890",
                            "mtime": "100",
                        },
                    ]
                }

        summary = summarize_index(FakeCollection())
        report = format_index_summary(summary)

        self.assertEqual(summary[0]["chunks"], 2)
        self.assertIn("knowledge_base/xdc.md", report)
        self.assertIn("chunks=2", report)
        self.assertIn("abcdef123456", report)

    def test_build_or_load_vector_db_reindexes_changed_files_and_removes_deleted_files(self):
        root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"rag_index_{uuid.uuid4().hex}")
        datasheets = os.path.join(root, "datasheets")
        kb = os.path.join(root, "knowledge_base")
        os.makedirs(datasheets)
        os.makedirs(kb)
        changed = os.path.join(kb, "changed.md")
        with open(changed, "w", encoding="utf-8") as f:
            f.write("# Changed\n\ncreate_clock updated guidance for tests.\n")

        class Ctx:
            script_dir = root
            datasheet_dir = datasheets
            kb_dir = kb
            vector_db_dir = os.path.join(root, "runs", "vector_db")
            rag_sources = ["knowledge_base"]
            rag_reindex = False
            rag_clear_index = False

        class FakeCollection:
            def __init__(self):
                self.deleted = []
                self.added = []

            def get(self, include=None):
                return {
                    "ids": ["old_changed", "old_deleted"],
                    "metadatas": [
                        {"source_id": "knowledge_base/changed.md", "content_hash": "old_hash"},
                        {"source_id": "knowledge_base/deleted.md", "content_hash": "deleted_hash"},
                    ],
                }

            def delete(self, ids):
                self.deleted.extend(ids)

            def add(self, embeddings, documents, metadatas, ids):
                self.added.append({"embeddings": embeddings, "documents": documents, "metadatas": metadatas, "ids": ids})

        class FakeClient:
            def __init__(self, path):
                self.collection = fake_collection

            def get_or_create_collection(self, name, metadata=None):
                return self.collection

        import autofpga.rag as rag

        fake_collection = FakeCollection()
        old_has_chroma = rag.HAS_CHROMA
        old_chromadb = getattr(rag, "chromadb", None)
        old_get_embedding = rag.get_embedding
        try:
            rag.HAS_CHROMA = True
            rag.chromadb = type("FakeChroma", (), {"PersistentClient": FakeClient})
            rag.get_embedding = lambda text: [0.1, 0.2, 0.3]
            collection = build_or_load_vector_db(Ctx())
        finally:
            rag.HAS_CHROMA = old_has_chroma
            if old_chromadb is None:
                delattr(rag, "chromadb")
            else:
                rag.chromadb = old_chromadb
            rag.get_embedding = old_get_embedding

        self.assertIs(collection, fake_collection)
        self.assertIn("old_changed", fake_collection.deleted)
        self.assertIn("old_deleted", fake_collection.deleted)
        self.assertEqual(len(fake_collection.added), 1)
        added = fake_collection.added[0]
        self.assertTrue(any("create_clock" in doc for doc in added["documents"]))
        self.assertTrue(all(meta["source_id"] == "knowledge_base/changed.md" for meta in added["metadatas"]))

    def test_in_memory_collection_supports_keyword_retrieval(self):
        collection = InMemoryCollection()
        collection.add(
            embeddings=[lexical_hash_embedding("create_clock PACKAGE_PIN")],
            documents=["create_clock and PACKAGE_PIN are XDC constraints."],
            metadatas=[{"source_id": "knowledge_base/xdc.md", "page": "N/A", "chunk_index": "0"}],
            ids=["xdc"],
        )

        retrieved = retrieve_context(collection, "create_clock PACKAGE_PIN", top_k=1)

        self.assertEqual(collection.count(), 1)
        self.assertIn("xdc.md", retrieved[0]["source"])


if __name__ == "__main__":
    unittest.main()
