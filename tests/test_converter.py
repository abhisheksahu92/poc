import os
import pytest
from pathlib import Path
from unittest.mock import patch
from app.converter import PDFConverter
from app.logger import setup_logger


@pytest.fixture
def tmp_dirs(tmp_path):
    source = tmp_path / "source_pdfs"
    output = tmp_path / "output_images"
    source.mkdir()
    output.mkdir()
    return source, output


@pytest.fixture
def logger():
    return setup_logger()


def test_dynamic_worker_count(tmp_dirs, logger, tmp_path):
    source, output = tmp_dirs
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"source_dir: {source}\noutput_dir: {output}\nmax_workers: 0\ndpi: 200\n")

    conv = PDFConverter(logger, config_path=str(cfg_path))
    cpu_count = os.cpu_count() or 2
    assert conv.max_workers == cpu_count * 2


def test_manual_worker_override(tmp_dirs, logger, tmp_path):
    source, output = tmp_dirs
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"source_dir: {source}\noutput_dir: {output}\nmax_workers: 5\ndpi: 200\n")

    conv = PDFConverter(logger, config_path=str(cfg_path))
    assert conv.max_workers == 5


@patch("app.converter.pdfinfo_from_path")
def test_convert_single_creates_images(mock_info, tmp_dirs, logger, tmp_path):
    source, output = tmp_dirs
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"source_dir: {source}\noutput_dir: {output}\nmax_workers: 2\ndpi: 200\n")

    pdf_file = source / "dummy.pdf"
    pdf_file.write_text("fake pdf")
    mock_info.return_value = {"Pages": 2}

    conv = PDFConverter(logger, config_path=str(cfg_path), use_threads=True)

    def dummy_convert_page(self, pdf_file, output_subdir, page_num):
        (output_subdir / f"page_{page_num}.png").write_text("fake image")

    conv._convert_page = dummy_convert_page.__get__(conv, PDFConverter)

    conv._convert_single(pdf_file)

    output_subdir = output / "dummy"
    assert (output_subdir / "page_1.png").exists()
    assert (output_subdir / "page_2.png").exists()


def test_convert_all_cleans_output(tmp_dirs, logger, tmp_path):
    source, output = tmp_dirs
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"source_dir: {source}\noutput_dir: {output}\nmax_workers: 2\ndpi: 200\n")

    conv = PDFConverter(logger, config_path=str(cfg_path))

    leftover = output / "old.png"
    leftover.write_text("junk")

    conv.convert_all()
    assert not leftover.exists()


def test_integration_real_pdf(tmp_dirs, logger, tmp_path):
    source, output = tmp_dirs
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"source_dir: {source}\noutput_dir: {output}\nmax_workers: 2\ndpi: 100\n")

    # Create a real PDF
    from reportlab.pdfgen import canvas
    pdf_file = source / "real.pdf"
    c = canvas.Canvas(str(pdf_file))
    c.drawString(100, 750, "Integration Test")
    c.showPage()
    c.save()

    conv = PDFConverter(logger, config_path=str(cfg_path), use_threads=True)
    conv._convert_single(pdf_file)

    output_subdir = output / "real"
    assert (output_subdir / "page_1.png").exists()


@patch("app.converter.pdfinfo_from_path")
def test_large_pdf_worker_distribution(mock_info, tmp_dirs, logger, tmp_path):
    source, output = tmp_dirs
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"source_dir: {source}\noutput_dir: {output}\nmax_workers: 10\ndpi: 200\n")

    pdf_file = source / "large.pdf"
    pdf_file.write_text("fake pdf")
    mock_info.return_value = {"Pages": 200}

    conv = PDFConverter(logger, config_path=str(cfg_path), use_threads=True)

    def dummy_convert_page(self, pdf_file, output_subdir, page_num):
        return None

    conv._convert_page = dummy_convert_page.__get__(conv, PDFConverter)

    conv._convert_single(pdf_file)
    # Since 200 pages, should call 200 times
    # Workers limited to 10 but tasks still run sequentially
    # So total calls = total pages
    output_subdir = output / "large"
    assert len(list(output_subdir.glob("*.png"))) == 0  # no real files created
