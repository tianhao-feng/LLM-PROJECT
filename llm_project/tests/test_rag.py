import os
import unittest
import uuid

from autofpga.rag import embed_chunks, iter_knowledge_files


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

        source_ids = sorted(source_id for _, source_id in iter_knowledge_files(ctx))

        self.assertEqual(source_ids, ["datasheets/device.md", "knowledge_base/xilinx_skill/xdc_constraints_notes.md"])

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
        self.assertEqual(embeddings, [[1.0, 0.0, 0.5], [1.0, 0.0, 0.5]])
        self.assertEqual(valid_texts, ["valid first", "valid third"])
        self.assertEqual(valid_metas, [{"source_id": "a"}, {"source_id": "c"}])
        self.assertEqual(valid_ids, ["a_0", "c_0"])


if __name__ == "__main__":
    unittest.main()
