"""OCR for scanned PDFs (M13): detect image-only/low-text PDFs, run local
ocrmypdf (Tesseract backend) to produce a searchable sidecar, then ingest that.

This is an optional dependency: `pip install 'research-cockpit[ocr]'`. When the
binary is missing, detection still works but OCR raises a clear error message.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class OCRUnavailableError(Exception):
    pass


def is_scanned_pdf(path: Path, sample_pages: int = 5, chars_threshold: int = 50) -> bool:
    """Heuristic: sample up to `sample_pages` pages; if the average text chars
    per page is below `chars_threshold`, the PDF is likely image-only/scanned."""
    import fitz

    with fitz.open(path) as doc:
        pages_to_check = min(len(doc), sample_pages)
        if pages_to_check == 0:
            return False
        total_chars = 0
        for i in range(pages_to_check):
            text = doc[i].get_text("text")
            total_chars += len(text.strip())
        avg_chars = total_chars / pages_to_check
    return avg_chars < chars_threshold


def ocr_available() -> bool:
    """Check if ocrmypdf CLI is available on PATH."""
    return shutil.which("ocrmypdf") is not None


def run_ocr(input_path: Path, output_path: Path, language: str = "eng") -> Path:
    """Run ocrmypdf (Tesseract) to produce a searchable PDF at output_path.

    Raises OCRUnavailableError if the binary is missing, RuntimeError on failure.
    """
    if not ocr_available():
        raise OCRUnavailableError(
            "ocrmypdf is not installed. Install it with:\n"
            "  pip install 'research-cockpit[ocr]'\n"
            "  # and ensure tesseract is available: brew install tesseract (macOS)"
        )
    cmd = [
        "ocrmypdf",
        "--skip-text",        # skip pages that already have text
        "-l", language,
        "--output-type", "pdf",
        str(input_path),
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode not in (0, 6):
        # exit 6 = "already has text" which is fine (--skip-text handles it)
        raise RuntimeError(
            f"ocrmypdf failed (exit {result.returncode}): {result.stderr[:500]}"
        )
    return output_path


def ocr_pdf(
    input_path: Path,
    output_dir: Path | None = None,
    language: str = "eng",
) -> Path:
    """Detect + OCR a scanned PDF. Returns the path to the searchable version
    (which may be the sidecar `<name>.ocr.pdf` or the original if not scanned).
    """
    input_path = Path(input_path).expanduser()
    if not is_scanned_pdf(input_path):
        return input_path
    out_dir = output_dir or input_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    ocr_path = out_dir / f"{input_path.stem}.ocr.pdf"
    return run_ocr(input_path, ocr_path, language=language)
