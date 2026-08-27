import unittest

import numpy as np
import pandas as pd

from table_display import (
    TableDisplayContractError,
    numeric_column_formats,
    streamlit_display_frame,
)


class StreamlitDisplayFrameTests(unittest.TestCase):
    def test_formats_numeric_values_and_replaces_every_missing_value(self):
        source = pd.DataFrame(
            {
                "報酬%": [12.34, None, np.inf],
                "備註": [None, "正常", np.nan],
            }
        )

        display = streamlit_display_frame(source, {"報酬%": "{:.1f}%"})

        self.assertEqual(display["報酬%"].tolist(), ["12.3%", "—", "∞"])
        self.assertEqual(display["備註"].tolist(), ["—", "正常", "—"])
        self.assertFalse(display.isna().any().any())
        self.assertTrue(pd.isna(source.loc[0, "備註"]))

    def test_rejects_non_numeric_value_in_declared_numeric_column(self):
        source = pd.DataFrame({"報酬%": [1, "壞資料"]})

        with self.assertRaisesRegex(TableDisplayContractError, "報酬%"):
            streamlit_display_frame(source, {"報酬%": "{:.1f}%"})

    def test_builds_formats_only_for_numeric_columns(self):
        frame = pd.DataFrame({"代號": [1], "名稱": ["台積電"], "值": [2.0]})

        self.assertEqual(
            numeric_column_formats(frame, "{:.1f}", exclude=("代號",)),
            {"值": "{:.1f}"},
        )


if __name__ == "__main__":
    unittest.main()
