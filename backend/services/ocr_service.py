"""
services/ocr_service.py
------------------------
Responsible for ONE thing only: extract raw text from an uploaded file.

Supported formats:
  - Images (JPEG, PNG, WEBP, BMP, TIFF) -> Tesseract OCR via pytesseract
  - PDF                                  -> PyMuPDF (fitz) renders each page
                                            to an image, then Tesseract reads
                                            each page; all page texts are joined.

The raw text returned here is messy (OCR is never perfect). That is fine -
the next step in the pipeline is groq_service.structure_ocr_text(), which
sends this raw text to the AI to pull out clean subject/grade/GPA rows.

Design decision: this service never interprets the text. It just extracts
and returns it. That separation means we can test OCR quality independently
of AI structuring quality.
"""

import os
import io
import pytesseract
from PIL import Image

# If TESSERACT_CMD is set in .env (required on Windows), point pytesseract
# at the correct executable. On Linux/Mac with tesseract on PATH, this is
# a no-op because the env var will be empty.
_tesseract_cmd = os.getenv("TESSERACT_CMD", "").strip()
if _tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd


def extract_text_from_file(file_bytes, filename):
    """
    Extract raw text from an uploaded academic results document.

    Args:
        file_bytes: bytes, the raw file contents (from request.files read)
        filename:   str, original filename - used to detect PDF vs image

    Returns:
        str: the raw OCR text (may be noisy / imperfectly formatted)

    Raises:
        ValueError: if the file type is not supported
        RuntimeError: if OCR or PDF rendering fails
    """
    name_lower = filename.lower()

    if name_lower.endswith(".pdf"):
        return _extract_from_pdf(file_bytes)
    elif any(name_lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif")):
        return _extract_from_image(file_bytes)
    else:
        raise ValueError(
            f"Unsupported file type: '{filename}'. "
            "Please upload a PDF or image (JPG, PNG, WEBP, BMP, TIFF)."
        )


def _extract_from_image(file_bytes):
    """
    Run Tesseract OCR on a single image.

    Args:
        file_bytes: raw bytes of the image file

    Returns:
        str: extracted text
    """
    try:
        image = Image.open(io.BytesIO(file_bytes))

        # Convert to RGB to ensure Tesseract handles all colour modes
        # (e.g. RGBA PNGs with transparency would otherwise cause issues).
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")

        # lang="eng" keeps things fast and predictable for academic docs.
        # config "--psm 6" tells Tesseract to treat the image as a single
        # uniform block of text, which works well for report cards/tables.
        text = pytesseract.image_to_string(image, lang="eng", config="--psm 6")
        return text.strip()

    except Exception as e:
        raise RuntimeError(f"Image OCR failed: {e}")


def _extract_from_pdf(file_bytes):
    """
    Render each page of a PDF to an image, then OCR each page.

    PyMuPDF (fitz) is used for rendering because it's reliable, pure
    Python, and handles multi-page docs gracefully without needing an
    external PDF utility.

    Args:
        file_bytes: raw bytes of the PDF file

    Returns:
        str: concatenated OCR text from all pages, separated by newlines
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise RuntimeError(
            "PyMuPDF is not installed. Run: pip install PyMuPDF"
        )

    try:
        pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
        all_text = []

        for page_number in range(len(pdf_document)):
            page = pdf_document[page_number]

            # Render at 2x zoom (matrix scale=2) for better OCR accuracy.
            # Higher zoom = sharper image = fewer OCR errors, at the cost
            # of a bit more memory. 2x is a good balance for most docs.
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)

            # Convert PyMuPDF pixmap bytes to a PIL Image for pytesseract
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            page_text = pytesseract.image_to_string(img, lang="eng", config="--psm 6")
            all_text.append(page_text.strip())

        pdf_document.close()

        # Join pages with a clear separator so the AI can see page
        # boundaries in the raw text if it needs to.
        return "\n\n--- page break ---\n\n".join(all_text).strip()

    except Exception as e:
        raise RuntimeError(f"PDF OCR failed: {e}")