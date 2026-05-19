# OCR Setup

This workspace uses a local Python virtual environment for OCR:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt
```

PaddleOCR models are cached locally under `.paddlex` by setting `PADDLE_PDX_CACHE_HOME` before running OCR:

```powershell
$env:PADDLE_PDX_CACHE_HOME = (Resolve-Path ".").Path + "\.paddlex"
```

The verified primary OCR stack is:

- `paddleocr==3.5.0`
- `paddlepaddle==3.2.2`
- PP-OCRv5 server detection model
- PP-OCRv5 server recognition model

PaddlePaddle `3.3.1` failed on this Windows CPU environment with a oneDNN/PIR runtime error, so the environment is pinned to `3.2.2`.

The Tesseract fallback Python packages are installed, but the native `tesseract` and Ghostscript executables are not currently available on PATH. `ocrmypdf` is installed and importable, but it will need those native executables before the fallback pipeline can run.
