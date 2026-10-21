"""Deterministic JSON, Markdown, and self-contained HTML reports."""

from __future__ import annotations

import html
import json


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _finding_text(items: list[dict]) -> str:
    return ", ".join(f"{item['rule_id']}:{item['line']}" for item in items) or "—"


def _view(report: dict) -> tuple[str, list[tuple[str, str]], list[str], list[list[str]]]:
    if "tasks" in report:
        cards = [("Macro F1 score", f"{report['score']:.3f}")]
        cards += [
            (name.replace("_", " ").title(), f"{value:.3f}")
            for name, value in report["metrics"].items()
        ]
        headers = ["Task", "Status", "F1", "Correct", "False positives", "Missed"]
        rows = [
            [
                item["id"],
                item["status"],
                f"{item['score']:.3f}",
                _finding_text(item["true_positives"]),
                _finding_text(item["false_positives"]),
                _finding_text(item["false_negatives"]),
            ]
            for item in report["tasks"]
        ]
        return "Code review evaluation", cards, headers, rows
    cards = [
        ("Python files scanned", str(report["files_scanned"])),
        ("Files skipped", str(report["files_skipped"])),
        ("Findings", str(len(report["findings"]))),
    ]
    headers = ["Rule", "Severity", "Path", "Line", "Evidence"]
    rows = [
        [item["rule_id"], item["severity"], item["path"], str(item["line"]), item["message"]]
        for item in report["findings"]
    ]
    return "Repository audit", cards, headers, rows


def render_report(report: dict, format: str = "json") -> str:
    if format == "json":
        return json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    title, cards, headers, rows = _view(report)
    disclaimer = (
        "Static heuristics and a small public synthetic benchmark are not a security "
        "certification or evidence of real-world model performance."
    )
    if format == "markdown":
        lines = [f"# {title}", "", disclaimer, ""]
        lines.extend(f"- {label}: {value}" for label, value in cards)
        lines.extend(
            [
                "",
                "| " + " | ".join(headers) + " |",
                "| " + " | ".join("---" for _ in headers) + " |",
            ]
        )
        lines.extend("| " + " | ".join(_markdown_cell(cell) for cell in row) + " |" for row in rows)
        if "checks" in report:
            lines += ["", "## Repository metadata", ""]
            lines.extend(
                f"- {'Present' if check['passed'] else 'Not found'}: "
                f"{_markdown_cell(check['name'])} — {_markdown_cell(check['detail'])}"
                for check in report["checks"]
            )
        return "\n".join(lines) + "\n"
    if format != "html":
        raise ValueError(f"unsupported report format: {format}")

    def escape(value: object) -> str:
        return html.escape(str(value), quote=True)

    card_html = "".join(
        f'<div class="card"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in cards
    )
    table_html = "<tr>" + "".join(f'<th scope="col">{escape(h)}</th>' for h in headers) + "</tr>"
    table_html += "".join(
        "<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>" for row in rows
    )
    checks_html = ""
    if "checks" in report:
        checks_html = (
            "<h2>Repository metadata</h2><ul>"
            + "".join(
                f"<li>{'Present' if c['passed'] else 'Not found'}: {escape(c['name'])} — "
                f"{escape(c['detail'])}</li>"
                for c in report["checks"]
            )
            + "</ul>"
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>{escape(title)} · Repo Eval Workbench</title>
<style>
:root{{color-scheme:light}}*{{box-sizing:border-box}}body{{margin:0;background:#f2f5fa;color:#15253c;font:15px/1.55 system-ui,sans-serif}}
main{{max-width:1240px;margin:0 auto;padding:48px 28px}}.eyebrow{{color:#17636b;font-weight:700;letter-spacing:.12em;font-size:12px}}
h1{{font-size:34px;letter-spacing:-.035em;margin:8px 0}}.note{{max-width:800px;color:#536075}}.cards{{display:flex;gap:14px;flex-wrap:wrap;margin:28px 0}}
.card{{background:white;border:1px solid #dbe2ed;border-radius:10px;min-width:170px;padding:18px;flex:1}}.card span{{display:block;color:#536075;font-size:13px}}
.card strong{{display:block;font-size:30px;margin-top:4px;font-variant-numeric:tabular-nums}}.table-wrap{{overflow-x:auto;background:white;border:1px solid #dbe2ed;border-radius:10px}}
table{{width:100%;border-collapse:collapse;text-align:left;font-size:13px}}th,td{{padding:13px 16px;border-bottom:1px solid #e6eaf1;vertical-align:top;overflow-wrap:anywhere}}th{{background:#e9eef6;color:#304664}}tr:last-child td{{border-bottom:0}}
footer{{margin-top:24px;color:#637085;font-size:12px}}@media(max-width:600px){{main{{padding:24px 16px}}h1{{font-size:27px}}}}
</style></head><body><main><div class="eyebrow">REPO EVAL WORKBENCH / OFFLINE REPORT</div>
<h1>{escape(title)}</h1><p class="note">{escape(disclaimer)}</p><section class="cards" aria-label="Summary">{card_html}</section>
<div class="table-wrap"><table aria-label="Detailed results"><thead>{table_html.split("</tr>", 1)[0]}</tr></thead><tbody>{table_html.split("</tr>", 1)[1]}</tbody></table></div>
{checks_html}<footer>Schema {escape(report.get("schema_version", "1.0"))} · Deterministic output · No external assets or scripts</footer>
</main></body></html>\n"""
