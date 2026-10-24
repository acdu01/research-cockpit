"""M13: OCR module - detection heuristic, missing-binary message."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from research_cockpit.ocr import (
    OCRUnavailableError,
    is_scanned_pdf,
    ocr_available,
    run_ocr,
)


def _make_text_pdf(tmp_path: Path) -> Path:
    """Create a text-rich PDF (detected as not scanned)."""
    import fitz

    path = tmp_path / "text.pdf"
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page()
        page.insert_text((72, 90), "A " * 100)  # 200 chars
    doc.save(path)
    return path


def _make_image_pdf(tmp_path: Path) -> Path:
    """Create an image-only PDF (detected as scanned)."""
    import fitz

    path = tmp_path / "scanned.pdf"
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page()
        # insert a rect - no text at all
        page.draw_rect(fitz.Rect(50, 50, 200, 200))
    doc.save(path)
    return path


def test_text_pdf_not_detected_as_scanned(tmp_path):
    pdf = _make_text_pdf(tmp_path)
    assert not is_scanned_pdf(pdf)


def test_image_pdf_detected_as_scanned(tmp_path):
    pdf = _make_image_pdf(tmp_path)
    assert is_scanned_pdf(pdf)


def test_ocr_unavailable_raises_clear_message(tmp_path):
    pdf = _make_image_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    with mock.patch("shutil.which", return_value=None):
        assert not ocr_available()
        with pytest.raises(OCRUnavailableError, match="ocrmypdf is not installed"):
            run_ocr(pdf, out)


def test_run_ocr_calls_subprocess(tmp_path):
    """When ocrmypdf is 'available', the correct command is assembled."""
    pdf = _make_image_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    with mock.patch("shutil.which", return_value="/usr/local/bin/ocrmypdf"), \
         mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0, stderr="")
        result = run_ocr(pdf, out, language="deu")
        assert result == out
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ocrmypdf"
        assert "-l" in cmd and "deu" in cmd
        assert str(pdf) in cmd and str(out) in cmd
