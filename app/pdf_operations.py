"""
PDF Operations - Core file processing functions.

These functions execute the operations parsed by the AI.
They handle actual file manipulation safely.
"""

import os
import shutil
from pathlib import Path
from typing import List, Optional
import io
import zipfile

from pypdf import PdfReader, PdfWriter
from pdf2docx import Converter
import subprocess
import math
import fitz  # PyMuPDF


# ============================================
# HELPER FUNCTIONS
# ============================================

def ensure_temp_dirs():
    """Create temporary directories if they don't exist"""
    Path("uploads").mkdir(exist_ok=True)
    Path("outputs").mkdir(exist_ok=True)


def get_upload_path(filename: str) -> str:
    """Get full path for an input file.

    Primary source is `uploads/`. For multi-step pipelines, intermediate files live in
    `outputs/` and may be used as inputs for subsequent steps.
    """
    uploads_path = os.path.join("uploads", filename)
    if os.path.exists(uploads_path):
        return uploads_path
    outputs_path = os.path.join("outputs", filename)
    return outputs_path


def get_output_path(filename: str) -> str:
    """Get full path for output file"""
    return os.path.join("outputs", filename)


def _resolve_ghostscript_executable(*, raise_if_missing: bool) -> Optional[str]:
    """Return a Ghostscript executable path if available."""
    # Prefer PATH lookup first.
    if os.name == "nt":
        for name in ("gswin64c.exe", "gswin32c.exe"):
            found = shutil.which(name)
            if found:
                return found

        # Common install locations (best-effort)
        possible_paths = [
            r"C:\Program Files\gs\gs10.06.0\bin\gswin64c.exe",
            r"C:\Program Files (x86)\gs\gs10.06.0\bin\gswin64c.exe",
            r"C:\Program Files\gs\gs10.05.0\bin\gswin64c.exe",
            r"C:\Program Files\gs\gs9.56.1\bin\gswin64c.exe",
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path

        if raise_if_missing:
            raise Exception(
                "Ghostscript not found. Please install Ghostscript from https://ghostscript.com/download/gsdnld.html"
            )
        return None

    # Linux/Mac
    found = shutil.which("gs")
    if found:
        return found
    if raise_if_missing:
        raise Exception("Ghostscript not found. Please install Ghostscript (gs) on the server.")
    return None


# ============================================
# PDF OPERATIONS
# ============================================

def merge_pdfs(file_names: List[str], output_name: str = "merged_output.pdf") -> str:
    """
    Merge multiple PDFs into a single file.
    
    Args:
        file_names: List of PDF file names to merge (in order)
        output_name: Name for the output file
    
    Returns:
        str: Output file name
    
    Raises:
        FileNotFoundError: If any input file doesn't exist
        Exception: If merge fails
    """
    ensure_temp_dirs()
    
    pdf_writer = PdfWriter()
    
    # Add all pages from all PDFs
    for file_name in file_names:
        input_path = get_upload_path(file_name)
        
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"File not found: {file_name}")
        
        pdf_reader = PdfReader(input_path)
        for page in pdf_reader.pages:
            pdf_writer.add_page(page)
    
    # Write merged PDF
    output_path = get_output_path(output_name)
    with open(output_path, "wb") as output_file:
        pdf_writer.write(output_file)
    
    return output_name


def split_pdf(file_name: str, pages_to_keep: List[int], output_name: str = "split_output.pdf") -> str:
    """
    Extract specific pages from a PDF.
    
    Args:
        file_name: Source PDF file name
        pages_to_keep: List of page numbers to keep (1-indexed)
        output_name: Name for the output file
    
    Returns:
        str: Output file name
    
    Raises:
        FileNotFoundError: If input file doesn't exist
        ValueError: If page numbers are invalid
        Exception: If split fails
    """
    ensure_temp_dirs()
    
    input_path = get_upload_path(file_name)
    
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {file_name}")
    
    pdf_reader = PdfReader(input_path)
    total_pages = len(pdf_reader.pages)
    
    # Validate page numbers
    for page_num in pages_to_keep:
        if page_num < 1 or page_num > total_pages:
            raise ValueError(f"Invalid page number: {page_num}. PDF has {total_pages} pages.")
    
    pdf_writer = PdfWriter()
    
    # Add requested pages (convert 1-indexed to 0-indexed)
    for page_num in pages_to_keep:
        pdf_writer.add_page(pdf_reader.pages[page_num - 1])
    
    # Write output PDF
    output_path = get_output_path(output_name)
    with open(output_path, "wb") as output_file:
        pdf_writer.write(output_file)
    
    return output_name


def delete_pages(file_name: str, pages_to_delete: List[int], output_name: str = "deleted_output.pdf") -> str:
    """
    Remove specific pages from a PDF.
    
    Args:
        file_name: Source PDF file name
        pages_to_delete: List of page numbers to delete (1-indexed)
        output_name: Name for the output file
    
    Returns:
        str: Output file name
    
    Raises:
        FileNotFoundError: If input file doesn't exist
        ValueError: If page numbers are invalid
        Exception: If deletion fails
    """
    ensure_temp_dirs()
    
    input_path = get_upload_path(file_name)
    
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {file_name}")
    
    pdf_reader = PdfReader(input_path)
    total_pages = len(pdf_reader.pages)
    
    # Validate page numbers
    for page_num in pages_to_delete:
        if page_num < 1 or page_num > total_pages:
            raise ValueError(f"Invalid page number: {page_num}. PDF has {total_pages} pages.")
    
    pdf_writer = PdfWriter()
    
    # Add all pages EXCEPT the ones to delete
    pages_to_delete_set = set(pages_to_delete)
    for page_num in range(1, total_pages + 1):
        if page_num not in pages_to_delete_set:
            pdf_writer.add_page(pdf_reader.pages[page_num - 1])
    
    # Write output PDF
    output_path = get_output_path(output_name)
    with open(output_path, "wb") as output_file:
        pdf_writer.write(output_file)
    
    return output_name


def compress_pdf(file_name: str, output_name: str = "compressed_output.pdf", preset: str = "ebook") -> str:
    """
    Compress a PDF using a qualitative preset.

    If Ghostscript is available, uses `-dPDFSETTINGS=/<preset>` where preset is one of:
    screen (smallest), ebook (default), printer (light), prepress (highest quality).
    If Ghostscript is not available, falls back to a basic PyPDF stream compression.
    
    Args:
        file_name: Source PDF file name
        output_name: Name for the output file
        preset: Ghostscript PDFSETTINGS preset (screen/ebook/printer/prepress)
    
    Returns:
        str: Output file name
    
    Raises:
        FileNotFoundError: If input file doesn't exist
        Exception: If compression fails
    """
    ensure_temp_dirs()
    
    input_path = get_upload_path(file_name)
    
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {file_name}")
    
    output_path = get_output_path(output_name)

    allowed = {"screen", "ebook", "printer", "prepress"}
    if preset not in allowed:
        preset = "ebook"

    gs_executable = _resolve_ghostscript_executable(raise_if_missing=False)
    if gs_executable:
        subprocess.run(
            [
                gs_executable,
                "-sDEVICE=pdfwrite",
                f"-dPDFSETTINGS=/{preset}",
                "-dNOPAUSE",
                "-dBATCH",
                "-dQUIET",
                f"-sOutputFile={output_path}",
                input_path,
            ],
            check=True,
        )
        return output_name

    # Fallback: PyPDF basic compression
    pdf_reader = PdfReader(input_path)
    pdf_writer = PdfWriter()
    for page in pdf_reader.pages:
        pdf_writer.add_page(page)
    for page in pdf_writer.pages:
        page.compress_content_streams()
    with open(output_path, "wb") as output_file:
        pdf_writer.write(output_file)
    return output_name


# ============================================
# PDF TO DOCX CONVERSION
# ============================================
def pdf_to_docx(file_name: str, output_name: str = "converted_output.docx") -> str:
    """
    Convert a PDF file to DOCX format using pdf2docx.
    """
    ensure_temp_dirs()
    input_path = get_upload_path(file_name)
    output_path = get_output_path(output_name)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {file_name}")
    
    try:
        cv = Converter(input_path)
        cv.convert(output_path, start=0, end=None)
        cv.close()
    except Exception as e:
        raise Exception(f"PDF to DOCX conversion failed: {e}")
    return output_name


# ============================================
# COMPRESS TO TARGET SIZE (EXPERIMENTAL)
# ============================================
def compress_pdf_to_target(file_name: str, target_mb: int, output_name: str = "compressed_target_output.pdf") -> str:
    """
    Compress a PDF to a target size (in MB) using Ghostscript.
    Args:
        file_name: Source PDF file name
        target_mb: Target size in MB
        output_name: Name for the output file
    Returns:
        str: Output file name
    Raises:
        FileNotFoundError: If input file doesn't exist
        Exception: If compression fails completely
    """
    ensure_temp_dirs()
    input_path = get_upload_path(file_name)
    output_path = get_output_path(output_name)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {file_name}")
    
    gs_executable = _resolve_ghostscript_executable(raise_if_missing=True)
    
    original_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    best_size_mb = original_size_mb
    best_quality = None
    
    # Try different quality settings until under target
    qualities = ["screen", "ebook", "printer", "prepress"]
    for quality in qualities:
        try:
            subprocess.run([
                gs_executable,
                "-sDEVICE=pdfwrite",
                f"-dPDFSETTINGS=/{quality}",
                "-dNOPAUSE",
                "-dBATCH",
                "-dQUIET",
                f"-sOutputFile={output_path}",
                input_path
            ], check=True)
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            if size_mb <= target_mb:
                return output_name
            # Track best compression achieved
            if size_mb < best_size_mb:
                best_size_mb = size_mb
                best_quality = quality
        except Exception as e:
            continue
    
    # If we couldn't reach target but got some compression, return best result with info
    if best_quality:
        # Re-compress with best quality setting
        subprocess.run([
            gs_executable,
            "-sDEVICE=pdfwrite",
            f"-dPDFSETTINGS=/{best_quality}",
            "-dNOPAUSE",
            "-dBATCH",
            "-dQUIET",
            f"-sOutputFile={output_path}",
            input_path
        ], check=True)
        # Return with special marker that will be caught
        raise Exception(f"PARTIAL_SUCCESS:Compressed from {original_size_mb:.1f}MB to {best_size_mb:.1f}MB (target was {target_mb}MB). Maximum compression reached.")
    
    raise Exception(f"Could not compress {file_name}. The PDF may already be optimized.")


# ============================================
# ADDITIONAL PDF OPERATIONS
# ============================================

def rotate_pdf(
    file_name: str,
    degrees: int,
    pages: Optional[List[int]] = None,
    output_name: str = "rotated_output.pdf",
) -> str:
    """Rotate pages in a PDF.

    Args:
        file_name: Source PDF file name
        degrees: 90/180/270 clockwise
        pages: Optional list of 1-indexed pages to rotate. If None, rotate all pages.
        output_name: Output PDF name
    """
    ensure_temp_dirs()

    if degrees not in (90, 180, 270):
        raise ValueError("degrees must be one of 90, 180, 270")

    input_path = get_upload_path(file_name)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {file_name}")

    reader = PdfReader(input_path)
    total_pages = len(reader.pages)

    if pages is None:
        pages_set = set(range(1, total_pages + 1))
    else:
        for p in pages:
            if p < 1 or p > total_pages:
                raise ValueError(f"Invalid page number: {p}. PDF has {total_pages} pages.")
        pages_set = set(pages)

    writer = PdfWriter()
    for idx, page in enumerate(reader.pages, start=1):
        if idx in pages_set:
            # pypdf rotation API differs by version
            if hasattr(page, "rotate_clockwise"):
                page = page.rotate_clockwise(degrees)
            elif hasattr(page, "rotate"):
                page = page.rotate(degrees)
            elif hasattr(page, "rotateClockwise"):
                page.rotateClockwise(degrees)
        writer.add_page(page)

    output_path = get_output_path(output_name)
    with open(output_path, "wb") as f:
        writer.write(f)
    return output_name


def reorder_pdf(file_name: str, new_order: List[int], output_name: str = "reordered_output.pdf") -> str:
    """Reorder pages in a PDF according to new_order (1-indexed)."""
    ensure_temp_dirs()

    input_path = get_upload_path(file_name)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {file_name}")

    reader = PdfReader(input_path)
    total_pages = len(reader.pages)

    if len(new_order) != total_pages:
        raise ValueError(f"new_order must have exactly {total_pages} entries")

    expected = set(range(1, total_pages + 1))
    if set(new_order) != expected:
        raise ValueError("new_order must include each page number exactly once")

    writer = PdfWriter()
    for p in new_order:
        writer.add_page(reader.pages[p - 1])

    output_path = get_output_path(output_name)
    with open(output_path, "wb") as f:
        writer.write(f)
    return output_name


def watermark_pdf(
    file_name: str,
    text: str,
    opacity: float = 0.12,
    angle: int = 30,
    output_name: str = "watermarked_output.pdf",
) -> str:
    """Add a diagonal text watermark to each page."""
    ensure_temp_dirs()

    input_path = get_upload_path(file_name)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {file_name}")

    if opacity < 0 or opacity > 1:
        raise ValueError("opacity must be between 0 and 1")

    # PyMuPDF's rotate parameter for text insertion is limited to multiples of 90.
    # To keep the API flexible (user might ask for 30°), round to nearest 90.
    try:
        angle_int = int(angle)
    except Exception:
        angle_int = 0
    angle_quantized = (int(round(angle_int / 90.0)) * 90) % 360

    doc = fitz.open(input_path)

    for page in doc:
        rect = page.rect
        # Watermark box roughly centered
        box = fitz.Rect(
            rect.width * 0.10,
            rect.height * 0.40,
            rect.width * 0.90,
            rect.height * 0.60,
        )

        shape = page.new_shape()
        shape.insert_textbox(
            box,
            text,
            fontsize=max(18, min(72, int(min(rect.width, rect.height) / 10))),
            fontname="helv",
            rotate=angle_quantized,
            align=1,
        )
        shape.finish(color=(0, 0, 0), fill=None, fill_opacity=opacity, stroke_opacity=opacity)
        shape.commit(overlay=True)

    output_path = get_output_path(output_name)
    doc.save(output_path)
    doc.close()
    return output_name


def add_page_numbers(
    file_name: str,
    position: str = "bottom_center",
    start_at: int = 1,
    output_name: str = "page_numbers_output.pdf",
) -> str:
    """Add page numbers to each page."""
    ensure_temp_dirs()

    input_path = get_upload_path(file_name)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {file_name}")

    doc = fitz.open(input_path)

    def _pos(rect: fitz.Rect) -> fitz.Point:
        margin_x = rect.width * 0.06
        margin_y = rect.height * 0.04
        if position == "bottom_right":
            return fitz.Point(rect.width - margin_x, rect.height - margin_y)
        if position == "bottom_left":
            return fitz.Point(margin_x, rect.height - margin_y)
        if position == "top_right":
            return fitz.Point(rect.width - margin_x, margin_y)
        if position == "top_left":
            return fitz.Point(margin_x, margin_y)
        if position == "top_center":
            return fitz.Point(rect.width / 2, margin_y)
        # bottom_center default
        return fitz.Point(rect.width / 2, rect.height - margin_y)

    for i, page in enumerate(doc, start=0):
        rect = page.rect
        p = _pos(rect)
        number = start_at + i
        # Use textbox so centering works nicely
        w = rect.width * 0.6
        h = 20
        box = fitz.Rect(p.x - w / 2, p.y - h / 2, p.x + w / 2, p.y + h / 2)

        shape = page.new_shape()
        shape.insert_textbox(box, str(number), fontsize=11, fontname="helv", align=1)
        shape.finish(color=(0, 0, 0))
        shape.commit(overlay=True)

    output_path = get_output_path(output_name)
    doc.save(output_path)
    doc.close()
    return output_name


def extract_text(
    file_name: str,
    pages: Optional[List[int]] = None,
    output_name: str = "extracted_text.txt",
) -> str:
    """Extract text from a PDF into a .txt file."""
    ensure_temp_dirs()

    input_path = get_upload_path(file_name)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {file_name}")

    doc = fitz.open(input_path)
    total_pages = doc.page_count

    if pages is None:
        page_numbers = list(range(1, total_pages + 1))
    else:
        for p in pages:
            if p < 1 or p > total_pages:
                raise ValueError(f"Invalid page number: {p}. PDF has {total_pages} pages.")
        page_numbers = pages

    parts: list[str] = []
    for p in page_numbers:
        page = doc.load_page(p - 1)
        parts.append(f"--- Page {p} ---\n")
        parts.append(page.get_text("text"))
        parts.append("\n")

    doc.close()
    output_path = get_output_path(output_name)
    with open(output_path, "w", encoding="utf-8", errors="replace") as f:
        f.write("".join(parts))
    return output_name


def pdf_to_images_zip(
    file_name: str,
    fmt: str = "png",
    dpi: int = 150,
    output_name: str = "pdf_images.zip",
) -> str:
    """Render PDF pages to images and return a zip file."""
    ensure_temp_dirs()

    input_path = get_upload_path(file_name)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {file_name}")

    fmt_lower = (fmt or "png").lower()
    if fmt_lower == "jpg":
        fmt_lower = "jpeg"
    if fmt_lower not in {"png", "jpeg"}:
        fmt_lower = "png"

    doc = fitz.open(input_path)
    output_path = get_output_path(output_name)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes(fmt_lower)
            zf.writestr(f"page_{i+1:04d}.{ 'jpg' if fmt_lower=='jpeg' else fmt_lower }", img_bytes)
    doc.close()
    return output_name


def images_to_pdf(
    file_names: List[str],
    output_name: str = "images_output.pdf",
) -> str:
    """Combine uploaded images into a single PDF in the given order."""
    ensure_temp_dirs()

    if not file_names:
        raise ValueError("No image files provided")

    doc = fitz.open()

    for name in file_names:
        input_path = get_upload_path(name)
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"File not found: {name}")

        pix = fitz.Pixmap(input_path)
        # Convert CMYK/alpha to RGB when needed
        if pix.n >= 5:
            pix = fitz.Pixmap(fitz.csRGB, pix)

        page = doc.new_page(width=pix.width, height=pix.height)
        page.insert_image(page.rect, pixmap=pix)

    output_path = get_output_path(output_name)
    doc.save(output_path)
    doc.close()
    return output_name


def split_pages_to_files_zip(
    file_name: str,
    pages: Optional[List[int]] = None,
    output_name: str = "split_pages.zip",
) -> str:
    """Extract pages as individual single-page PDFs and return a zip file."""
    ensure_temp_dirs()

    input_path = get_upload_path(file_name)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {file_name}")

    reader = PdfReader(input_path)
    total_pages = len(reader.pages)

    if pages is None:
        pages_list = list(range(1, total_pages + 1))
    else:
        for p in pages:
            if p < 1 or p > total_pages:
                raise ValueError(f"Invalid page number: {p}. PDF has {total_pages} pages.")
        pages_list = pages

    output_path = get_output_path(output_name)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in pages_list:
            writer = PdfWriter()
            writer.add_page(reader.pages[p - 1])
            buf = io.BytesIO()
            writer.write(buf)
            zf.writestr(f"page_{p:04d}.pdf", buf.getvalue())
    return output_name


def ocr_pdf(
    file_name: str,
    language: str = "eng",
    deskew: bool = True,
    output_name: str = "ocr_output.pdf",
) -> str:
    """Run OCR to produce a searchable PDF.

    This uses the optional `ocrmypdf` dependency (and requires Tesseract installed on the machine).
    """
    ensure_temp_dirs()

    input_path = get_upload_path(file_name)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {file_name}")

    try:
        import ocrmypdf  # type: ignore
    except Exception:
        raise Exception(
            "OCR requires the optional dependency 'ocrmypdf' and a Tesseract install. "
            "Install with: pip install ocrmypdf  (and install Tesseract on your system)."
        )

    output_path = get_output_path(output_name)

    # ocrmypdf may raise detailed exceptions; bubble up with context
    try:
        ocrmypdf.ocr(
            input_path,
            output_path,
            language=language or "eng",
            deskew=bool(deskew),
            force_ocr=True,
            skip_text=True,
            output_type="pdf",
            progress_bar=False,
        )
    except Exception as e:
        raise Exception(f"OCR failed: {e}")

    return output_name
