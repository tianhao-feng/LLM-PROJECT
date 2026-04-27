import os
import unittest
import uuid

from autofpga.config import build_context
from autofpga.rag import build_or_load_vector_db, retrieve_context


@unittest.skipUnless(os.getenv("AUTOFPGARAG_CHROMA_SMOKE") == "1", "set AUTOFPGARAG_CHROMA_SMOKE=1 to run")
class RagChromaSmokeTests(unittest.TestCase):
    def test_chroma_index_and_keyword_retrieval_smoke(self):
        import autofpga.rag as rag

        if not rag.HAS_CHROMA:
            self.skipTest("chromadb is not installed")

        root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"chroma_{uuid.uuid4().hex}")
        ctx = build_context(script_dir=root, project_name="demo", auto_timestamp=False)
        ctx.rag_sources = ["knowledge_base"]
        ctx.rag_reindex = True
        ctx.rag_clear_index = True
        os.makedirs(ctx.kb_dir, exist_ok=True)
        with open(os.path.join(ctx.kb_dir, "xdc.md"), "w", encoding="utf-8") as f:
            f.write("# XDC\n\ncreate_clock and PACKAGE_PIN are XDC constraints.\n")

        old_get_embedding = rag.get_embedding
        try:
            rag.get_embedding = lambda text: [0.1, 0.2, 0.3, 0.4]
            collection = build_or_load_vector_db(ctx)
            retrieved = retrieve_context(collection, "create_clock PACKAGE_PIN", top_k=1)
        finally:
            rag.get_embedding = old_get_embedding

        self.assertTrue(retrieved)
        self.assertIn("xdc.md", retrieved[0]["source"])


if __name__ == "__main__":
    unittest.main()
