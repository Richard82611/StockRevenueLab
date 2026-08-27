import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
UI_FILES = (ROOT / "app.py", ROOT / "pages/probability.py", ROOT / "pages/timing_lab.py")


class UiSourceContractTests(unittest.TestCase):
    def test_no_streamlit_table_relies_on_pandas_styler(self):
        for path in UI_FILES:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn(".style.", source, path.name)
            self.assertNotIn("background_gradient", source, path.name)

    def test_detail_filters_and_results_share_one_fragment(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn("@st.fragment\ndef render_detail_explorer", source)
        self.assertIn("render_detail_explorer(target_year", source)

    def test_free_text_search_is_bound_not_interpolated(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        timing_source = (ROOT / "pages/timing_lab.py").read_text(encoding="utf-8")

        self.assertIn("LOWER(:search_keyword)", app_source)
        self.assertNotIn("%{search_keyword}%", app_source)
        self.assertIn("LOWER(:keyword)", timing_source)
        self.assertNotIn("%{keyword}%", timing_source)


if __name__ == "__main__":
    unittest.main()
