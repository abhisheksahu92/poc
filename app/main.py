from converter import PDFConverter
from logger import setup_logger

if __name__ == "__main__":
    logger = setup_logger()
    converter = PDFConverter(logger)
    converter.convert_all()
