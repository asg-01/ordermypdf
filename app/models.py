"""
Pydantic models for request/response validation and AI intent parsing.
"""

from typing import List, Literal, Optional, Union
from pydantic import BaseModel, Field
from enum import Enum


# ============================================
# ERROR CLASSIFICATION MODELS
# ============================================

class ErrorTypeEnum(str, Enum):
    """Error types for taxonomy"""
    TYPO = "typo"
    SHORTHAND = "shorthand"
    VAGUE_INTENT = "vague_intent"
    CONFLICTING_OPS = "conflicting_ops"
    MISSING_PARAMETER = "missing_parameter"
    INVALID_OPERATION_ORDER = "invalid_operation_order"
    XML_UNICODE_ERROR = "xml_unicode_error"
    FAKE_TEXT_LAYER = "fake_text_layer"
    BROKEN_FONTS = "broken_fonts"
    TYPE_INCOMPATIBLE = "type_incompatible"
    OPERATION_NOT_SUPPORTED_FOR_TYPE = "operation_not_supported_for_type"
    PDF_PARSING_FAILURE = "pdf_parsing_failure"
    OCR_ENGINE_FAILURE = "ocr_engine_failure"
    CONVERSION_CRASH = "conversion_crash"
    OUT_OF_MEMORY = "out_of_memory"
    TIMEOUT = "timeout"
    EMPTY_OUTPUT = "empty_output"
    CORRUPT_FILE = "corrupt_file"
    UNSUPPORTED_FEATURE = "unsupported_feature"


class ErrorSeverityEnum(str, Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ErrorResponse(BaseModel):
    """Error response sent to user"""
    status: Literal["error"]
    error_type: ErrorTypeEnum
    severity: ErrorSeverityEnum
    user_message: str  # Human-friendly message
    system_message: str  # Technical details for logging
    action: str  # 'skip', 'retry', 'auto_fix', 'ask_user', 'block'
    can_recover: bool = False
    recovery_action: Optional[str] = None


# ============================================
# API REQUEST / RESPONSE MODELS
# ============================================

class ProcessRequest(BaseModel):
    """User's request to process PDFs"""
    prompt: str = Field(..., description="Natural language instruction")
    file_names: List[str] = Field(..., description="List of uploaded PDF file names")


class ProcessResponse(BaseModel):
    """Response after processing PDFs or requesting clarification"""
    status: Literal["success", "error"]
    operation: Optional[str] = None
    output_file: Optional[str] = None
    message: str
    options: Optional[List[str]] = None


# ============================================
# AI INTENT PARSING MODELS
# ============================================

class MergeIntent(BaseModel):
    """Intent to merge multiple PDFs"""
    operation: Literal["merge"] = "merge"
    files: List[str] = Field(..., description="Files to merge in order")


class SplitIntent(BaseModel):
    """Intent to split/extract pages from PDF"""
    operation: Literal["split"] = "split"
    file: str = Field(..., description="Source PDF file")
    pages: List[int] = Field(..., description="Page numbers to keep (1-indexed)")


class DeleteIntent(BaseModel):
    """Intent to delete specific pages from PDF"""
    operation: Literal["delete"] = "delete"
    file: str = Field(..., description="Source PDF file")
    pages_to_delete: List[int] = Field(..., description="Page numbers to delete (1-indexed)")



class CompressIntent(BaseModel):
    """Intent to compress PDF file size"""
    operation: Literal["compress"] = "compress"
    file: str = Field(..., description="PDF file to compress")
    preset: Optional[Literal["screen", "ebook", "printer", "prepress"]] = Field(
        default=None,
        description=(
            "Optional Ghostscript PDFSETTINGS preset for qualitative compression. "
            "screen=smallest/most compression, ebook=default, printer=light, prepress=highest quality."
        ),
    )


class RotateIntent(BaseModel):
    """Intent to rotate PDF pages"""
    operation: Literal["rotate"] = "rotate"
    file: str = Field(..., description="Source PDF file")
    degrees: Literal[90, 180, 270] = Field(..., description="Rotation degrees (clockwise)")
    pages: Optional[List[int]] = Field(
        default=None,
        description="Optional list of pages to rotate (1-indexed). If omitted, rotate all pages.",
    )


class ReorderIntent(BaseModel):
    """Intent to reorder PDF pages"""
    operation: Literal["reorder"] = "reorder"
    file: str = Field(..., description="Source PDF file")
    new_order: Union[List[int], Literal["reverse"]] = Field(
        ..., description="New page order (1-indexed). Must include each page exactly once, or 'reverse' to reverse all pages."
    )


class DocxToPdfIntent(BaseModel):
    """Intent to convert DOCX to PDF"""
    operation: Literal["docx_to_pdf"] = "docx_to_pdf"
    file: str = Field(..., description="DOCX file to convert")


class RemoveBlankPagesIntent(BaseModel):
    """Intent to remove blank/empty pages from a PDF"""
    operation: Literal["remove_blank_pages"] = "remove_blank_pages"
    file: str = Field(..., description="Source PDF file")


class RemoveDuplicatePagesIntent(BaseModel):
    """Intent to remove duplicate pages from a PDF"""
    operation: Literal["remove_duplicate_pages"] = "remove_duplicate_pages"
    file: str = Field(..., description="Source PDF file")


class EnhanceScanIntent(BaseModel):
    """Intent to enhance a scanned PDF for readability (image-based processing)"""
    operation: Literal["enhance_scan"] = "enhance_scan"
    file: str = Field(..., description="Source PDF file")


class FlattenPdfIntent(BaseModel):
    """Intent to flatten/sanitize a PDF (remove incremental/update structure and optimize)"""
    operation: Literal["flatten_pdf"] = "flatten_pdf"
    file: str = Field(..., description="Source PDF file")


class WatermarkIntent(BaseModel):
    """Intent to add a text watermark to a PDF"""
    operation: Literal["watermark"] = "watermark"
    file: str = Field(..., description="Source PDF file")
    text: str = Field(..., description="Watermark text")
    opacity: Optional[float] = Field(
        default=0.12, description="Opacity from 0 to 1 (default 0.12)"
    )
    angle: Optional[int] = Field(
        default=0,
        description=(
            "Rotation in degrees for watermark text. Note: renderer supports 0/90/180/270; "
            "other values will be rounded to the nearest 90. (default 0)"
        ),
    )


class PageNumbersIntent(BaseModel):
    """Intent to add page numbers"""
    operation: Literal["page_numbers"] = "page_numbers"
    file: str = Field(..., description="Source PDF file")
    position: Optional[
        Literal["bottom_center", "bottom_right", "bottom_left", "top_center", "top_right", "top_left"]
    ] = Field(default="bottom_center", description="Position for page numbers")
    start_at: Optional[int] = Field(default=1, description="First page number to render")


class ExtractTextIntent(BaseModel):
    """Intent to extract text from a PDF"""
    operation: Literal["extract_text"] = "extract_text"
    file: str = Field(..., description="Source PDF file")
    pages: Optional[List[int]] = Field(
        default=None,
        description="Optional list of pages to extract (1-indexed). If omitted, extract all pages.",
    )


class PdfToImagesIntent(BaseModel):
    """Intent to export PDF pages to images"""
    operation: Literal["pdf_to_images"] = "pdf_to_images"
    file: str = Field(..., description="Source PDF file")
    format: Optional[Literal["png", "jpg", "jpeg"]] = Field(
        default="png", description="Image output format"
    )
    dpi: Optional[int] = Field(default=150, description="Render DPI (default 150)")


class ImagesToPdfIntent(BaseModel):
    """Intent to convert uploaded images into a single PDF"""
    operation: Literal["images_to_pdf"] = "images_to_pdf"
    files: List[str] = Field(..., description="Image files to combine (in order)")


class SplitToFilesIntent(BaseModel):
    """Intent to split/extract pages as separate PDFs (zipped)"""
    operation: Literal["split_to_files"] = "split_to_files"
    file: str = Field(..., description="Source PDF file")
    pages: Optional[List[int]] = Field(
        default=None,
        description="Optional pages to extract as separate PDFs (1-indexed). If omitted, split all pages.",
    )


class OcrIntent(BaseModel):
    """Intent to run OCR on a PDF and return searchable PDF"""
    operation: Literal["ocr"] = "ocr"
    file: str = Field(..., description="Source PDF file")
    language: Optional[str] = Field(default="eng", description="OCR language (default eng)")
    deskew: Optional[bool] = Field(default=True, description="Deskew during OCR (default true)")

# === New: PDF to DOCX Conversion Intent ===
class DocxConvertIntent(BaseModel):
    """Intent to convert PDF to DOCX"""
    operation: Literal["pdf_to_docx"] = "pdf_to_docx"
    file: str = Field(..., description="PDF file to convert")

# === New: Compress to Target Size Intent ===
class CompressToTargetIntent(BaseModel):
    """Intent to compress PDF to a target size (MB)"""
    operation: Literal["compress_to_target"] = "compress_to_target"
    file: str = Field(..., description="PDF file to compress")
    target_mb: int = Field(..., description="Target size in MB")


class ParsedIntent(BaseModel):
    """
    Structured intent parsed by AI.
    Only one operation type will be populated.
    """
    operation_type: Literal[
        "merge",
        "split",
        "delete",
        "compress",
        "pdf_to_docx",
        "compress_to_target",
        "rotate",
        "reorder",
        "watermark",
        "page_numbers",
        "extract_text",
        "pdf_to_images",
        "images_to_pdf",
        "split_to_files",
        "ocr",
        "docx_to_pdf",
        "remove_blank_pages",
        "remove_duplicate_pages",
        "enhance_scan",
        "flatten_pdf",
    ]
    merge: Optional[MergeIntent] = None
    split: Optional[SplitIntent] = None
    delete: Optional[DeleteIntent] = None
    compress: Optional[CompressIntent] = None
    pdf_to_docx: Optional[DocxConvertIntent] = None
    compress_to_target: Optional[CompressToTargetIntent] = None
    rotate: Optional[RotateIntent] = None
    reorder: Optional[ReorderIntent] = None
    watermark: Optional[WatermarkIntent] = None
    page_numbers: Optional[PageNumbersIntent] = None
    extract_text: Optional[ExtractTextIntent] = None
    pdf_to_images: Optional[PdfToImagesIntent] = None
    images_to_pdf: Optional[ImagesToPdfIntent] = None
    split_to_files: Optional[SplitToFilesIntent] = None
    ocr: Optional[OcrIntent] = None
    docx_to_pdf: Optional[DocxToPdfIntent] = None
    remove_blank_pages: Optional[RemoveBlankPagesIntent] = None
    remove_duplicate_pages: Optional[RemoveDuplicatePagesIntent] = None
    enhance_scan: Optional[EnhanceScanIntent] = None
    flatten_pdf: Optional[FlattenPdfIntent] = None

    def get_operation(self):
        """Get the actual operation intent"""
        if self.operation_type == "merge":
            return self.merge
        elif self.operation_type == "split":
            return self.split
        elif self.operation_type == "delete":
            return self.delete
        elif self.operation_type == "compress":
            return self.compress
        elif self.operation_type == "pdf_to_docx":
            return self.pdf_to_docx
        elif self.operation_type == "compress_to_target":
            return self.compress_to_target
        elif self.operation_type == "rotate":
            return self.rotate
        elif self.operation_type == "reorder":
            return self.reorder
        elif self.operation_type == "watermark":
            return self.watermark
        elif self.operation_type == "page_numbers":
            return self.page_numbers
        elif self.operation_type == "extract_text":
            return self.extract_text
        elif self.operation_type == "pdf_to_images":
            return self.pdf_to_images
        elif self.operation_type == "images_to_pdf":
            return self.images_to_pdf
        elif self.operation_type == "split_to_files":
            return self.split_to_files
        elif self.operation_type == "ocr":
            return self.ocr
        elif self.operation_type == "docx_to_pdf":
            return self.docx_to_pdf
        elif self.operation_type == "remove_blank_pages":
            return self.remove_blank_pages
        elif self.operation_type == "remove_duplicate_pages":
            return self.remove_duplicate_pages
        elif self.operation_type == "enhance_scan":
            return self.enhance_scan
        elif self.operation_type == "flatten_pdf":
            return self.flatten_pdf
        return None
