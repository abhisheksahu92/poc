import logging
from pathlib import Path
from datetime import datetime

def setup_logger(name: str = "PDFConverter") -> logging.Logger:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"pdf2img_{today}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(name)
