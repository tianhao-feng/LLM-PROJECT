import unittest

from autofpga.rag import retrieve_context


class FakeRetrievalCollection:
    def get(self, include=None):
        return {
            "ids": [
                "xdc_clock",
                "vivado_flow",
                "verilog_style",
                "vivado_drc",
                "config_voltage",
                "board_pins",
            ],
            "documents": [
                "Use create_clock -period 20.000 on the top-level clock port. PACKAGE_PIN and IOSTANDARD belong in XDC constraints.",
                "Vivado build flow runs synth_design, opt_design, place_design, route_design, report_timing_summary, and write_bitstream.",
                "Verilog-2001 code must not use SystemVerilog logic, always_ff, always_comb, typedef, enum, or for (integer i = ...).",
                "Vivado DRC UCIO-1 reports unconstrained logical ports. NSTD-1 reports unspecified I/O standard.",
                "7 Series configuration requires correct CFGBVS and CONFIG_VOLTAGE settings for the configuration bank voltage.",
                "Do not let the LLM invent pins. AutoFPGA must read board_pins.json and map physical board ports from verified constraints.",
            ],
            "metadatas": [
                {"source_id": "knowledge_base/xilinx_skill/xdc_constraints_notes.md", "heading": "create_clock", "page": "N/A", "chunk_index": "0"},
                {"source_id": "knowledge_base/xilinx_skill/vivado_flow_notes.md", "heading": "Vivado Flow", "page": "N/A", "chunk_index": "0"},
                {"source_id": "knowledge_base/coding_style.txt", "heading": "Verilog-2001", "page": "N/A", "chunk_index": "0"},
                {"source_id": "knowledge_base/xilinx_skill/diagnostics_notes.md", "heading": "DRC", "page": "N/A", "chunk_index": "0"},
                {"source_id": "datasheets/Xilinx_7Series_Config_Guide.txt", "heading": "Configuration Voltage", "page": "42", "chunk_index": "0"},
                {"source_id": "knowledge_base/board_constraints.txt", "heading": "Board Pins", "page": "N/A", "chunk_index": "0"},
            ],
        }


class RagRetrievalQualityTests(unittest.TestCase):
    def setUp(self):
        import autofpga.rag as rag

        self.rag = rag
        self.old_get_embedding = rag.get_embedding
        rag.get_embedding = lambda query: []
        self.collection = FakeRetrievalCollection()

    def tearDown(self):
        self.rag.get_embedding = self.old_get_embedding

    def assertTopSource(self, query, expected_source, skill_type="CONCEPT"):
        retrieved = retrieve_context(self.collection, query, skill_type=skill_type, top_k=3)

        self.assertTrue(retrieved, query)
        self.assertIn(expected_source, retrieved[0]["source"], f"query={query!r}, retrieved={retrieved}")

    def test_exact_xdc_terms_find_xdc_notes(self):
        self.assertTopSource("How should create_clock and PACKAGE_PIN be written?", "xdc_constraints_notes.md")

    def test_vivado_flow_terms_find_vivado_notes(self):
        self.assertTopSource("Vivado route_design write_bitstream build flow", "vivado_flow_notes.md")

    def test_verilog_2001_terms_find_coding_style(self):
        self.assertTopSource("Why is always_ff logic forbidden in Verilog-2001?", "coding_style.txt")

    def test_drc_error_codes_find_diagnostics(self):
        self.assertTopSource("What do UCIO-1 and NSTD-1 mean?", "diagnostics_notes.md")

    def test_configuration_voltage_terms_find_datasheet(self):
        self.assertTopSource("Explain CFGBVS CONFIG_VOLTAGE for 7 Series", "Xilinx_7Series_Config_Guide.txt")

    def test_pin_invention_question_finds_board_constraints(self):
        self.assertTopSource("Why should the LLM not invent pins and use board_pins.json?", "board_constraints.txt")

    def test_table_queries_boost_table_like_chunks(self):
        class TableCollection(FakeRetrievalCollection):
            def get(self, include=None):
                data = super().get(include)
                data["ids"].append("table")
                data["documents"].append("| Pin | Voltage |\n|---|---|\n| CFGBVS | CONFIG_VOLTAGE |")
                data["metadatas"].append(
                    {
                        "source_id": "datasheets/config_table.md",
                        "heading": "Configuration Table",
                        "page": "10",
                        "chunk_index": "0",
                    }
                )
                return data

        retrieved = retrieve_context(TableCollection(), "CFGBVS CONFIG_VOLTAGE table", skill_type="TABLE", top_k=1)

        self.assertIn("config_table.md", retrieved[0]["source"])


if __name__ == "__main__":
    unittest.main()
