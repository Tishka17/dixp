from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .api.app import App, Blueprint
from .inspection.graph import BundleGraphDiff, DoctorReport


def _load_reference(spec: str) -> Any:
    module_name, separator, attr_path = spec.partition(":")
    if not separator or not module_name or not attr_path:
        raise ValueError(f"Reference {spec!r} must look like 'package.module:object'")
    module = importlib.import_module(module_name)
    current: Any = module
    for part in attr_path.split("."):
        try:
            current = getattr(current, part)
        except AttributeError as exc:
            raise ValueError(f"Reference {spec!r} does not define attribute {part!r}") from exc
    return current


def _resolve_target(candidate: Any) -> Any:
    if isinstance(candidate, (App, Blueprint)):
        return candidate
    if inspect.isroutine(candidate):
        try:
            signature = inspect.signature(candidate)
        except (TypeError, ValueError) as exc:
            raise TypeError("Doctor target factory must expose an inspectable zero-argument signature") from exc
        if signature.parameters:
            raise TypeError("Doctor target factory must be callable without arguments")
        return _resolve_target(candidate())
    if hasattr(candidate, "doctor") and callable(candidate.doctor):
        return candidate
    raise TypeError(
        "Doctor target must be an App, Blueprint, object with doctor(...), or a zero-argument factory returning one"
    )


def _load_roots(specs: Sequence[str]) -> tuple[Any, ...]:
    return tuple(_load_reference(spec) for spec in specs)


def _write_output(path: str | None, content: str) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content + ("" if content.endswith("\n") else "\n"), encoding="utf-8")


def _render_output(report: DoctorReport, diff: BundleGraphDiff | None, output_format: str) -> str:
    if output_format == "json":
        payload: dict[str, Any]
        if diff is None:
            payload = report.bundle_graph_dict()
        else:
            payload = {
                "report": report.bundle_graph_dict(),
                "diff": diff.to_dict(),
            }
        return json.dumps(payload, indent=2, sort_keys=True)
    if output_format == "mermaid":
        if diff is None:
            return report.bundle_graph_mermaid()
        status = "detected" if diff.drift else "none"
        return "\n".join((f"%% bundle graph drift: {status}", report.bundle_graph_mermaid()))
    if diff is None:
        return str(report)
    return f"{report}\n{diff}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m dixp.doctor",
        description="Run dixp doctor for an App or Blueprint reference and optionally export the bundle graph.",
    )
    parser.add_argument("target", help="Python reference in the form package.module:object")
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        metavar="REF",
        help="Optional root service references in the same package.module:object form",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json", "mermaid"),
        default="text",
        help="What to print to stdout",
    )
    parser.add_argument(
        "--baseline-json",
        metavar="PATH",
        help="Compare the current bundle graph against a saved bundle-graph.json baseline",
    )
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="Return exit code 1 when the bundle graph differs from the baseline",
    )
    parser.add_argument("--json-out", metavar="PATH", help="Write bundle graph JSON to a file")
    parser.add_argument("--mermaid-out", metavar="PATH", help="Write bundle graph Mermaid to a file")
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        target = _resolve_target(_load_reference(args.target))
        roots = _load_roots(args.root)
        report = target.doctor(*roots)
        if not isinstance(report, DoctorReport):
            raise TypeError(f"doctor(...) for {args.target!r} did not return DoctorReport")
        diff = None
        if args.baseline_json is not None:
            diff = report.diff_bundle_graph(Path(args.baseline_json).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        parser.exit(2, f"dixp doctor: {exc}\n")

    _write_output(args.json_out, report.bundle_graph_json())
    _write_output(args.mermaid_out, report.bundle_graph_mermaid())
    sys.stdout.write(_render_output(report, diff, args.format) + "\n")

    if not report.ok:
        return 1
    if diff is not None and args.fail_on_drift and diff.drift:
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
