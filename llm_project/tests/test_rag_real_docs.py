import os
import unittest

from autofpga.rag import build_text_chunks, file_sha256, retrieve_context


class RealDocsCollection:
    def __init__(self, root, relative_paths):
        self.ids = []
        self.documents = []
        self.metadatas = []
        for relpath in relative_paths:
            path = os.path.join(root, relpath)
            if not os.path.exists(path):
                continue
            source_group = "knowledge_base" if relpath.startswith("knowledge_base") else "datasheets"
            texts, metas, ids = build_text_chunks(path, relpath.replace("\\", "/"), source_group, file_sha256(path))
            self.ids.extend(ids)
            self.documents.extend(texts)
            self.metadatas.extend(metas)

    def get(self, include=None):
        return {"ids": self.ids, "documents": self.documents, "metadatas": self.metadatas}


class RagRealDocsRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = os.path.dirname(os.path.dirname(__file__))
        cls.collection = RealDocsCollection(
            cls.root,
            [
                "knowledge_base/xilinx_skill/xdc_constraints_notes.md",
                "knowledge_base/xilinx_skill/vivado_flow_notes.md",
                "knowledge_base/xilinx_skill/tcl_commands_notes.md",
                "knowledge_base/coding_style.txt",
                "knowledge_base/board_constraints.txt",
                "datasheets/Xilinx_7Series_Config_Guide.txt",
            ],
        )

    def setUp(self):
        import autofpga.rag as rag

        self.rag = rag
        self.old_get_embedding = rag.get_embedding
        rag.get_embedding = lambda query: []

    def tearDown(self):
        self.rag.get_embedding = self.old_get_embedding

    def assertTopContains(self, query, expected_source, top_k=5, skill_type="CONCEPT"):
        retrieved = retrieve_context(self.collection, query, skill_type=skill_type, top_k=top_k)
        sources = [item["source"] for item in retrieved]

        self.assertTrue(any(expected_source in source for source in sources), f"query={query!r}, sources={sources}")

    def test_xdc_create_clock_query_hits_xdc_notes(self):
        self.assertTopContains("create_clock PACKAGE_PIN IOSTANDARD XDC", "xdc_constraints_notes.md")

    def test_vivado_flow_query_hits_vivado_notes(self):
        self.assertTopContains("synth_design place_design route_design write_bitstream", "vivado_flow_notes.md")

    def test_tcl_command_query_hits_tcl_notes(self):
        self.assertTopContains("Vivado Tcl command report_timing_summary", "tcl_commands_notes.md")

    def test_board_pin_query_hits_board_constraints(self):
        self.assertTopContains("board pin mapping rst_n led_out PACKAGE_PIN", "board_constraints.txt")

    def test_config_voltage_query_hits_config_guide(self):
        self.assertTopContains("CFGBVS CONFIG_VOLTAGE configuration bank voltage", "Xilinx_7Series_Config_Guide.txt")


if __name__ == "__main__":
    unittest.main()
