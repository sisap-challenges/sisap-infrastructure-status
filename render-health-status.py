#!/usr/bin/env python3

import argparse
import html
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml


ROOT = Path(__file__).parent
DEFAULT_HEALTH_DATA = ROOT / "data" / "health-monitoring.jsonl"
DEFAULT_TEST_MATRIX = ROOT / "test-matrix.yml"
DEFAULT_OUTPUT = ROOT / "index.html"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Render the SISAP 2026 infrastructure status page."
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="HTML output file (default: index.html)",
    )
    parser.add_argument(
        "--health-data",
        type=Path,
        default=DEFAULT_HEALTH_DATA,
        help="JSONL health-monitoring input",
    )
    parser.add_argument(
        "--test-matrix",
        type=Path,
        default=DEFAULT_TEST_MATRIX,
        help="YAML test matrix input",
    )
    return parser.parse_args()


def load_jsonl(path):
    records = []
    with path.open(encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON in {path}:{line_number}: {error}") from error
    return records


def load_matrix(path):
    with path.open(encoding="utf-8") as input_file:
        matrix = yaml.safe_load(input_file)

    if not isinstance(matrix, dict) or not isinstance(matrix.get("systems"), dict):
        raise ValueError(f"{path} must contain a 'systems' mapping")
    return matrix


def test_name(system, dataset):
    return f"run-{system}-{dataset}"


def configured_rows(matrix):
    rows_by_task = {task: [] for task in range(1, 4)}
    for system, configuration in matrix["systems"].items():
        datasets = configuration.get("datasets", [])
        if not isinstance(datasets, list):
            raise ValueError(f"{system!r} must configure a list of datasets")

        seen_datasets = set()
        for dataset in datasets:
            if dataset in seen_datasets:
                raise ValueError(
                    f"{system!r} configures dataset {dataset!r} more than once"
                )
            seen_datasets.add(dataset)

            task_match = re.match(r"^task-([1-3])(?:-|$)", dataset)
            if task_match is None:
                raise ValueError(
                    f"Cannot assign dataset {dataset!r} to SISAP 2026 task 1, 2, or 3"
                )
            task = int(task_match.group(1))
            rows_by_task[task].append(
                {
                    "system": system,
                    "dataset": dataset,
                    "test_name": test_name(system, dataset),
                }
            )
    return rows_by_task


def health_history(records, expected_test_names):
    history = defaultdict(dict)
    timestamps = set()

    for record in records:
        name = record.get("name")
        timestamp = record.get("timestamp")
        if name not in expected_test_names or not timestamp:
            continue
        history[name][timestamp] = record
        timestamps.add(timestamp)

    return history, sorted(timestamps)


def format_timestamp(timestamp):
    try:
        return datetime.fromisoformat(timestamp).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return timestamp


def format_number(value, digits=3):
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value:.{digits}f}"


def result_cell(record):
    if record is None:
        return '<td class="missing" title="No result recorded">—</td>'
    if record.get("status") == "failed":
        return '<td class="failed">Failed</td>'

    evaluation = record.get("evaluation")
    if not isinstance(evaluation, dict):
        return '<td class="failed">No evaluation</td>'

    recall = format_number(evaluation.get("Recall"))
    return f"<td>{html.escape(recall)}</td>"


def render_results_table(rows, history, timestamps):
    timestamp_headers = "".join(
        f"<th scope=\"col\">{html.escape(format_timestamp(timestamp))}</th>"
        for timestamp in timestamps
    )
    if not timestamps:
        timestamp_headers = '<th scope="col">No health checks recorded</th>'

    body = []
    for row in rows:
        cells = [
            "<tr>",
            f'<th class="system-column" scope="row">{html.escape(row["system"])}</th>',
            f'<td class="dataset-column"><code>{html.escape(row["dataset"])}</code></td>',
        ]
        if timestamps:
            cells.extend(
                result_cell(history[row["test_name"]].get(timestamp))
                for timestamp in timestamps
            )
        else:
            cells.append('<td class="missing">—</td>')
        cells.append("</tr>")
        body.append("".join(cells))

    return f"""
      <div class="table-wrap" tabindex="0" aria-label="Submission health over time">
        <table>
          <thead>
            <tr>
              <th class="system-column" scope="col">Submission</th>
              <th class="dataset-column" scope="col">Health-check dataset</th>
              {timestamp_headers}
            </tr>
          </thead>
          <tbody>
            {''.join(body)}
          </tbody>
        </table>
      </div>
    """


def render_page(matrix, records):
    rows_by_task = configured_rows(matrix)
    all_rows = [row for rows in rows_by_task.values() for row in rows]
    history, timestamps = health_history(
        records, {row["test_name"] for row in all_rows}
    )
    generated_at = (
        format_timestamp(max(timestamps)) if timestamps else "No health checks recorded"
    )

    sections = []
    for task, rows in rows_by_task.items():
        task_timestamps = sorted(
            {
                timestamp
                for row in rows
                for timestamp in history[row["test_name"]]
            }
        )
        if rows:
            content = render_results_table(rows, history, task_timestamps)
        else:
            content = '<p class="in-progress">No submissions are configured yet.</p>'
        sections.append(
            f"""
    <section>
      <h2>Submissions 2026 Task {task}</h2>
      {content}
    </section>
            """
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SISAP 2026 Infrastructure Status</title>
  <style>
    :root {{
      color-scheme: light dark;
      font-family: system-ui, sans-serif;
      line-height: 1.5;
    }}
    body {{
      max-width: 90rem;
      margin: 0 auto;
      padding: 2rem;
    }}
    header, section {{
      margin-bottom: 2.5rem;
    }}
    .in-progress {{
      border-left: 0.35rem solid #bf8700;
      padding: 0.75rem 1rem;
      background: color-mix(in srgb, #bf8700 12%, transparent);
    }}
    .table-wrap {{
      --system-column-width: 18rem;
      position: relative;
      overflow-x: auto;
      max-width: 100%;
      isolation: isolate;
      scrollbar-gutter: stable;
      overscroll-behavior-x: contain;
    }}
    table {{
      border-collapse: separate;
      border-spacing: 0;
      min-width: 100%;
      font-size: 0.9rem;
      border-top: 1px solid #8c959f;
    }}
    th, td {{
      box-sizing: border-box;
      border-right: 1px solid #8c959f;
      border-bottom: 1px solid #8c959f;
      padding: 0.55rem 0.7rem;
      text-align: left;
      vertical-align: top;
      white-space: nowrap;
    }}
    thead th {{
      background: color-mix(in srgb, Canvas 92%, CanvasText 8%);
    }}
    .system-column, .dataset-column {{
      position: -webkit-sticky;
      position: sticky;
      background: Canvas;
      white-space: normal;
      overflow-wrap: anywhere;
    }}
    .system-column {{
      left: 0;
      width: 18rem;
      min-width: 18rem;
      max-width: 18rem;
      border-left: 1px solid #8c959f;
      z-index: 2;
    }}
    .dataset-column {{
      left: var(--system-column-width);
      width: 22rem;
      min-width: 22rem;
      max-width: 22rem;
      z-index: 2;
    }}
    thead .system-column, thead .dataset-column {{
      background: color-mix(in srgb, Canvas 92%, CanvasText 8%);
      z-index: 3;
    }}
    td > span {{
      display: block;
    }}
    .failed {{
      color: #cf222e;
      font-weight: 700;
    }}
    .missing {{
      color: #6e7781;
      text-align: center;
    }}
    .updated {{
      color: #6e7781;
    }}
  </style>
</head>
<body>
  <header>
    <h1>SISAP 2026 Infrastructure Status</h1>
    <p class="updated">Latest recorded health check: {html.escape(generated_at)}</p>
    <p>
      Automated spot checks for configured
      <a href="https://github.com/sisap-challenges/sisap-infrastructure-status">SISAP 2026 submissions</a>.
      Each result reports the recall of the system on the spot-check datasets. Please note that the recall scores on the spot-check dataset are not meaningful, the CI tests here are only intended to ensure that the systems run and produce the same (or a similar) output, i.e., "success" here is when the recall value stays the same over time but the individual recall score is not meaningful.
    </p>
  </header>

  <main>
    {''.join(sections)}
  </main>
  <script>
    const positionTablesAtLatestResult = () => {{
      document.querySelectorAll(".table-wrap").forEach((container) => {{
        const systemColumn = container.querySelector("thead .system-column");
        if (systemColumn) {{
          container.style.setProperty(
            "--system-column-width",
            `${{systemColumn.getBoundingClientRect().width}}px`,
          );
        }}
        container.scrollLeft = container.scrollWidth - container.clientWidth;
      }});
    }};

    window.addEventListener("load", () => {{
      requestAnimationFrame(() => {{
        requestAnimationFrame(positionTablesAtLatestResult);
      }});
      document.fonts?.ready.then(positionTablesAtLatestResult);
    }});
    window.addEventListener("resize", positionTablesAtLatestResult);
  </script>
</body>
</html>
"""


def main():
    args = parse_args()
    matrix = load_matrix(args.test_matrix)
    records = load_jsonl(args.health_data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_page(matrix, records), encoding="utf-8")


if __name__ == "__main__":
    main()
