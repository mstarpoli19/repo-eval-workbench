import json
import unittest

from repo_eval_workbench.reporting import render_report


def report():
    return {
        "schema_version": "1.0",
        "files_scanned": 2,
        "files_skipped": 1,
        "findings": [
            {
                "rule_id": "bare-except",
                "severity": "warning",
                "path": "a.py",
                "line": 3,
                "message": "Review this handler",
            }
        ],
        "checks": [],
    }


class ReportingTests(unittest.TestCase):
    def test_json_roundtrip(self):
        self.assertEqual(json.loads(render_report(report())), report())

    def test_deterministic(self):
        for format in ("json", "markdown", "html"):
            self.assertEqual(render_report(report(), format), render_report(report(), format))

    def test_html_escapes_untrusted_text(self):
        value = report()
        value["findings"][0]["path"] = '<script>alert("x")</script>'
        rendered = render_report(value, "html")
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("default-src 'none'", rendered)
        self.assertNotIn("<script ", rendered)

    def test_markdown_table_cells(self):
        value = report()
        value["findings"][0]["message"] = "a|b\nc"
        self.assertIn("a\\|b c", render_report(value, "markdown"))

    def test_evaluation_report(self):
        value = {
            "schema_version": "1.0",
            "score": 0.5,
            "metrics": {"micro_f1": 0.5, "task_coverage": 1.0},
            "tasks": [
                {
                    "id": "example",
                    "status": "evaluated",
                    "score": 0.5,
                    "true_positives": [{"rule_id": "bare-except", "line": 3}],
                    "false_positives": [],
                    "false_negatives": [],
                }
            ],
        }
        for format in ("markdown", "html"):
            self.assertIn("0.500", render_report(value, format))
            self.assertIn("bare-except:3", render_report(value, format))

    def test_unknown_format_rejected(self):
        with self.assertRaises(ValueError):
            render_report(report(), "xml")


if __name__ == "__main__":
    unittest.main()
