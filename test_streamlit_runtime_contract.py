import inspect
import unittest

import streamlit as st


class StreamlitRuntimeContractTests(unittest.TestCase):
    def test_pinned_streamlit_supports_atomic_fragments(self):
        self.assertTrue(callable(st.fragment))

    def test_spinner_supports_visible_elapsed_time(self):
        self.assertIn("show_time", inspect.signature(st.spinner).parameters)


if __name__ == "__main__":
    unittest.main()
