# 📘 PDF to Image Converter (PoC)

This project provides a **proof-of-concept (PoC)** system that converts PDF files into PNG images using Python, [`pdf2image`](https://pypi.org/project/pdf2image/), and Poppler.
It supports **parallel processing**, runs in **Docker**, and includes **unit & integration tests**.

---

## 📂 Project Structure

```text
.
├── app/
│   ├── converter.py        # Core conversion logic
│   ├── logger.py           # Logging setup
│   ├── main.py             # Entrypoint script
│   └── config.yaml         # Config (source/output dirs, dpi, workers)
├── data/
│   ├── source_pdfs/        # Place your input PDFs here
│   └── output_images/      # Converted images appear here
├── tests/
│   └── test_converter.py   # Unit & integration tests
├── Dockerfile
├── docker-compose.yml
├── docker-compose.test.yml
├── Makefile
└── README.md
```

---

## 🚀 Running the Converter

### Linux / Mac / CI (Makefile)

```bash
make build   # Build Docker images
make run     # Run converter on PDFs
```

### Windows (PowerShell)

```powershell
docker compose build --no-cache
docker compose up
```

Converted images will be saved in:

```text
data/output_images/
```

---

## 🧪 Running Tests

We use **pytest** inside Docker for clean, reproducible test runs.

### Linux / Mac / CI (Makefile)

```bash
make test
```

### Windows (PowerShell)

```powershell
docker compose -f docker-compose.test.yml run --rm tests
```

### ✅ Example Output

```text
tests/test_converter.py::test_dynamic_worker_count PASSED
tests/test_converter.py::test_manual_worker_override PASSED
tests/test_converter.py::test_convert_single_creates_images PASSED
tests/test_converter.py::test_convert_all_cleans_output PASSED
tests/test_converter.py::test_integration_real_pdf PASSED
tests/test_converter.py::test_large_pdf_worker_distribution PASSED
```

---

## ⚡ Makefile Commands (Linux/Mac/CI only)

| Command      | Description                              |
| ------------ | ---------------------------------------- |
| `make build` | Build Docker images (fresh dependencies) |
| `make run`   | Run the converter on PDFs                |
| `make test`  | Run unit & integration tests             |
| `make clean` | Remove containers, volumes & prune cache |

⚠️ On **Windows**, use the equivalent `docker compose ...` commands shown above.

---

## 🛠 Requirements

* [Docker](https://www.docker.com/get-started)
* [Docker Compose](https://docs.docker.com/compose/)

👉 **No local Python setup is required.** Everything runs inside Docker.

---

## 📌 Features

* **Parallel Processing** → Uses multiple workers (`2 × CPU cores` by default).
* **Configurable** → `config.yaml` allows DPI, workers, and folder paths to be customized.
* **Thread Fallback for Tests** → Avoids multiprocessing pickle issues.
* **Error Handling** → Logs conversion failures without halting the job.
* **Skip Processed PDFs** → Avoids reprocessing if images already exist.
* **Client Demo Ready** → Simple, reproducible with Docker + Makefile or raw `docker compose` commands.