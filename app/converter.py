from pathlib import Path
from pdf2image import convert_from_path
from pdf2image.pdf2image import pdfinfo_from_path
import yaml
import os
import shutil
import concurrent.futures
from tqdm import tqdm


class PDFConverter:
    def __init__(self, logger, config_path: str = "app/config.yaml", use_threads=False):
        self.logger = logger
        # Auto thread fallback in pytest/test mode
        self.use_threads = use_threads or "PYTEST_CURRENT_TEST" in os.environ

        # Load config
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        self.source_dir = Path(config.get("source_dir", "/data/source_pdfs"))
        self.output_dir = Path(config.get("output_dir", "/data/output_images"))
        self.dpi = config.get("dpi", 200)

        self.host_source = Path(os.getenv("HOST_SOURCE_DIR", str(self.source_dir))).resolve()
        self.host_output = Path(os.getenv("HOST_OUTPUT_DIR", str(self.output_dir))).resolve()

        # ⚡ Dynamic worker calculation
        self.cpu_count = os.cpu_count() or 2
        cfg_workers = config.get("max_workers", 0)

        if cfg_workers == 0:  # auto = 2 × CPU cores
            self.max_workers = self.cpu_count * 2
        else:
            self.max_workers = cfg_workers

        self.logger.info(f"Using up to {self.max_workers} workers (detected {self.cpu_count} CPUs)")

    def convert_all(self):
        # Ensure source dir exists
        if not self.source_dir.exists():
            self.logger.warning(f"Source dir does not exist: {self.source_dir.resolve()}")
            return

        # Clean old output contents
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
        try:
            info = pdfinfo_from_path(str(pdf_file))
            total_pages = int(info["Pages"])
        except Exception as e:
            self.logger.error(f"❌ Failed to read PDF info for {pdf_file.name}: {e}")
            return

        output_subdir = self.output_dir / pdf_file.stem

        # Skip if already processed
        if output_subdir.exists() and any(output_subdir.glob("*.png")):
            self.logger.info(f"⏩ Skipping {pdf_file.name}, already processed.")
            return

        output_subdir.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Processing {pdf_file.name} with {total_pages} pages...")

        # ✅ Dynamically choose workers per PDF
        workers = min(total_pages, self.max_workers)
        self.logger.info(f"Using {workers} parallel workers for {pdf_file.name}")

        Executor = concurrent.futures.ThreadPoolExecutor if self.use_threads else concurrent.futures.ProcessPoolExecutor
        with Executor(max_workers=workers) as executor:
            futures = {
                executor.submit(self._convert_page, pdf_file, output_subdir, page_num): page_num
                for page_num in range(1, total_pages + 1)
            }
            for f in tqdm(concurrent.futures.as_completed(futures), total=total_pages, desc=pdf_file.name):
                try:
                    f.result()
                except Exception as e:
                    self.logger.error(f"❌ Error in worker for {pdf_file.name}, page {futures[f]}: {e}")

        self.logger.info(f"✅ Finished {pdf_file.name}, saved {total_pages} pages")

    def _convert_page(self, pdf_file: Path, output_subdir: Path, page_num: int):
        try:
            images = convert_from_path(
                str(pdf_file),
                dpi=self.dpi,
                first_page=page_num,
                last_page=page_num
            )
            out_file = output_subdir / f"page_{page_num}.png"
            images[0].save(out_file, "PNG")
            return out_file
        except Exception as e:
            self.logger.error(f"❌ Failed converting {pdf_file.name} page {page_num}: {e}")
            return None
