import subprocess
import tempfile
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parent / ".github" / "workflows" / "update-data.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")


def _step_block(name):
    start = TEXT.index(f"- name: {name}")
    end = TEXT.find("\n      - name:", start + 1)
    return TEXT[start:] if end == -1 else TEXT[start:end]


def _run_script(name):
    block = _step_block(name).splitlines()
    index = next(i for i, line in enumerate(block) if line.strip() == "run: |")
    body = [line[10:] for line in block[index + 1 :]]
    return "\n".join(body) + "\n"


class UpdateDataWorkflowTests(unittest.TestCase):
    def test_not_triggered_by_push(self):
        triggers = TEXT.split("\non:", 1)[1].split("\npermissions:", 1)[0]
        self.assertNotIn("push:", triggers)

    def test_db_apply_step_has_id_and_secret_env(self):
        block = _step_block("Apply snapshot to database (skips when DATABASE_URL is not set)")
        self.assertIn("id: db_apply", block)
        self.assertIn("DATABASE_URL: ${{ secrets.DATABASE_URL }}", block)

    def _summary(self, outcome):
        script = _run_script("Write failure summary")
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            subprocess.run(
                ["bash", "-c", script],
                check=True,
                env={"DB_APPLY_OUTCOME": outcome, "GITHUB_STEP_SUMMARY": str(summary), "PATH": "/usr/bin:/bin"},
            )
            return summary.read_text(encoding="utf-8")

    def test_summary_when_database_write_failed(self):
        text = self._summary("failure")
        self.assertIn("committed, but applying it to the database failed", text)
        self.assertNotIn("No snapshot was published", text)

    def test_summary_when_snapshot_not_published(self):
        for outcome in ("", "skipped"):
            text = self._summary(outcome)
            self.assertIn("No snapshot was published", text)


if __name__ == "__main__":
    unittest.main()
