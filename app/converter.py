from pathlib import Path
from pdf2image import convert_from_path
import yaml
import os
import shutil

class PDFConverter:
    def __init__(self, logger, config_path: str = "app/config.yaml"):
        self.logger = logger

        # Load config
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        self.source_dir = Path(config.get("source_dir", "/data/source_pdfs"))
        self.output_dir = Path(config.get("output_dir", "/data/output_images"))
        self.dpi = config.get("dpi", 200)

        # Host paths for logging clarity
        self.host_source = Path(os.getenv("HOST_SOURCE_DIR", "./data/source_pdfs")).resolve()
        self.host_output = Path(os.getenv("HOST_OUTPUT_DIR", "./data/output_images")).resolve()

        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def convert_all(self):
        # Clean old output
        if self.output_dir.exists():
            for item in self.output_dir.iterdir():
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            self.logger.info(f"Cleared contents of: {self.output_dir.resolve()}")

        pdf_files = list(self.source_dir.glob("*.pdf"))
        if not pdf_files:
            self.logger.warning("No PDF files found.")
            self.logger.info(f"Container path: {self.source_dir.resolve()}")
            self.logger.info(f"Host path:      {self.host_source}")
            return

        for pdf_file in pdf_files:
            self._convert_single(pdf_file)

    def _convert_single(self, pdf_file: Path):
        output_subdir = self.output_dir / pdf_file.stem
        output_subdir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Processing {pdf_file.name}...")
        images = convert_from_path(str(pdf_file), dpi=self.dpi)

        for i, img in enumerate(images, start=1):
            out_file = output_subdir / f"page_{i}.png"
            img.save(out_file, "PNG")

        self.logger.info(f"Saved {len(images)} pages from {pdf_file.name}")
        self.logger.info(f"Container path: {output_subdir.resolve()}")
        self.logger.info(f"Host path:      {self.host_output / pdf_file.stem}")
