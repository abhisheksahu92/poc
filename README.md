# PDF → Images Converter (POC)

## What it does
- Reads PDFs from `source_pdfs/`
- Converts each page into `.png`
- Saves images in `output_images/<pdf_name>/`
- Configurable via `config.yaml`

## How to run
1. Clone this repo
2. Put PDFs into `source_pdfs/`
3. Run:

```bash
docker compose up --build
