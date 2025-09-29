import os
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from app.converter import PDFConverter
from app.logger import setup_logger


@pytest.fixture
def tmp_dirs(tmp_path):
    """Create temporary source/output dirs for testing."""
    source = tmp_path / "source_pdfs"
    output = tmp_path / "output_images"
    source.mkdir()
    output.mkdir()
    return source, output


@pytest.fixture
def logger():
    return setup_logger()


def write_dummy_pdf(path: Path):
    """Create a tiny dummy PDF file for testing."""
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path))
    c.drawString(100, 750, "Hello Test")
    c.showPage()
    c.save()


def test_dynamic_worker_count(tmp_dirs, logger, tmp_path):
    source, output = tmp_dirs
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("source_dir: {}\noutput_dir: {}\nmax_workers: 0\ndpi: 200\n".format(source, output))

    conv = PDFConverter(logger, config_path=str(cfg_path))

    cpu_count = os.cpu_count() or 2
    assert conv.max_workers == cpu_count * 2  # auto mode should scale with CPU


def test_manual_worker_override(tmp_dirs, logger, tmp_path):
    source, output = tmp_dirs
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("source_dir: {}\noutput_dir: {}\nmax_workers: 5\ndpi: 200\n".format(source, output))

    conv = PDFConverter(logger, config_path=str(cfg_path))
    assert conv.max_workers == 5

@patch("app.converter.pdfinfo_from_path")
def test_convert_single_creates_images(mock_info, tmp_dirs, logger, tmp_path):
    source, output = tmp_dirs
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        f"source_dir: {source}\noutput_dir: {output}\nmax_workers: 2\ndpi: 200\n"
    )

    pdf_file = source / "dummy.pdf"
    pdf_file.write_text("fake pdf")

    # Pretend 2 pages
    mock_info.return_value = {"Pages": 2}

    # Use threads (safe for mocks)
    conv = PDFConverter(logger, config_path=str(cfg_path), use_threads=True)

    # Patch _convert_page with dummy function
    def dummy_convert_page(self, pdf_file, output_subdir, page_num):
        (output_subdir / f"page_{page_num}.png").write_text("fake image")

    conv._convert_page = dummy_convert_page.__get__(conv, PDFConverter)

    conv._convert_single(pdf_file)

    # Verify dummy outputs created
    output_subdir = output / "dummy"
    assert (output_subdir / "page_1.png").exists()
    assert (output_subdir / "page_2.png").exists()


def test_convert_all_cleans_output(tmp_dirs, logger, tmp_path):
    source, output = tmp_dirs
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("source_dir: {}\noutput_dir: {}\nmax_workers: 2\ndpi: 200\n".format(source, output))

    conv = PDFConverter(logger, config_path=str(cfg_path))

    # Create dummy leftover file in output
    leftover = output / "old.png"
    leftover.write_text("junk")

    conv.convert_all()  # no PDFs, should just cleanup

    assert not leftover.exists()
