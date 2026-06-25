"""
Runner: extract Functional Testing PDF → per-family Excel + report.

Usage:
    python run_functional.py [pdf] [output_dir]          # full pipeline (Gemini)
    python run_functional.py --reprocess [output_dir]   # offline: reload saved JSON, no API

Defaults:
    pdf        = "source/FUnctional Testing WI_Five series.pdf"
    output_dir = outputs/functional
"""

import argparse
import logging
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

from services.functional_extractor import extract_all, reprocess_from_cache


def main():
    parser = argparse.ArgumentParser(
        description="Functional Testing PDF extractor (v3)"
    )
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="Skip Gemini calls; reload raw/*.json and re-run parsing+integrity+report",
    )
    parser.add_argument(
        "pdf_or_output",
        nargs="?",
        help=(
            "Full mode: path to PDF. "
            "Reprocess mode: output directory (default: outputs/functional)"
        ),
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        help="Output directory (full mode only; default: outputs/functional)",
    )
    args = parser.parse_args()

    if args.reprocess:
        output_dir = Path(args.pdf_or_output or "outputs/functional")
        print(f"[REPROCESS] output_dir: {output_dir}")
        print(f"[REPROCESS] loading raw JSON from: {output_dir / 'raw'}")
        print()
        report = reprocess_from_cache(output_dir)
        report_path = output_dir / "extraction_report.md"
        report_path.write_text(report, encoding="utf-8")
        print("\n" + "=" * 60)
        print(report)
        print("=" * 60)
        print(f"\nReport saved: {report_path}")
    else:
        pdf_path = Path(args.pdf_or_output or "source/FUnctional Testing WI_Five series.pdf")
        output_dir = Path(args.output_dir or "outputs/functional")

        if not pdf_path.exists():
            print(f"ERROR: PDF not found: {pdf_path}")
            sys.exit(1)

        print(f"PDF:        {pdf_path}")
        print(f"Output dir: {output_dir}")
        print()

        report = extract_all(pdf_path, output_dir)
        report_path = output_dir / "extraction_report.md"
        report_path.write_text(report, encoding="utf-8")
        print("\n" + "=" * 60)
        print(report)
        print("=" * 60)
        print(f"\nReport saved: {report_path}")
        print(f"Audit crops: {output_dir / 'audit_crops'}/")


if __name__ == "__main__":
    main()
