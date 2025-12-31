"""
File Type Guards - Universal redundancy guards and file-type compatibility checks.

This module implements hard-coded rules to handle redundancy, ambiguity, and logic errors
across ALL supported file types and ALL supported functions.

Core Principle: If an operation is redundant, impossible, or meaningless for a file type,
the system must NEVER throw a generic error. It must either SKIP, AUTO-FIX, or BLOCK
with a clear message.
"""

from typing import Optional, Tuple, Dict, List
from enum import Enum
import os
import logging


logger = logging.getLogger(__name__)


class FileType(str, Enum):
    """Supported file types"""
    PDF = "pdf"
    DOCX = "docx"
    JPG = "jpg"
    PNG = "png"
    JPEG = "jpeg"
    ZIP = "zip"
    TXT = "txt"


def get_file_type(filename: str) -> Optional[FileType]:
    """Extract and validate file type from filename."""
    if not filename:
        return None
    
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    
    try:
        return FileType[ext.upper()]
    except KeyError:
        return None


class GuardAction(str, Enum):
    """Action to take when guard is triggered"""
    SKIP = "skip"
    AUTO_FIX = "auto_fix"
    BLOCK = "block"
    CONVERT = "convert"
    ASK = "ask"


class GuardResult:
    """Result of guard evaluation"""
    def __init__(
        self,
        action: GuardAction,
        message: str = "",
        can_proceed: bool = False,
        suggestion: Optional[str] = None,
    ):
        self.action = action
        self.message = message
        self.can_proceed = can_proceed
        self.suggestion = suggestion


class UniversalRedundancyGuards:
    """
    Guards that check for redundant operations across ALL file types.
    
    If an operation is redundant, impossible, or meaningless,
    this returns SKIP or blocks with a clear message.
    """
    
    @staticmethod
    def check_image_to_image(operation: str, current_type: FileType) -> Optional[GuardResult]:
        """
        Detect: image → to_image (redundant)
        Returns GuardResult if redundant, None otherwise.
        """
        image_types = {FileType.JPG, FileType.PNG, FileType.JPEG}
        
        if operation in ["convert_to_image", "to_image"] and current_type in image_types:
            return GuardResult(
                action=GuardAction.SKIP,
                message="Already an image",
                can_proceed=False,
            )
        
        return None
    
    @staticmethod
    def check_pdf_to_pdf(operation: str, current_type: FileType) -> Optional[GuardResult]:
        """
        Detect: pdf → to_pdf (redundant)
        Returns GuardResult if redundant, None otherwise.
        """
        if operation in ["convert_to_pdf", "to_pdf"] and current_type == FileType.PDF:
            return GuardResult(
                action=GuardAction.SKIP,
                message="Already a PDF",
                can_proceed=False,
            )
        
        return None
    
    @staticmethod
    def check_docx_to_docx(operation: str, current_type: FileType) -> Optional[GuardResult]:
        """
        Detect: docx → to_docx (redundant)
        Returns GuardResult if redundant, None otherwise.
        """
        if operation in ["convert_to_docx", "to_docx"] and current_type == FileType.DOCX:
            return GuardResult(
                action=GuardAction.SKIP,
                message="Already a Word document",
                can_proceed=False,
            )
        
        return None
    
    @staticmethod
    def check_already_compressed(operation: str, filename: str) -> Optional[GuardResult]:
        """
        Detect: compressed → compress again (redundant)
        Heuristic: if filename contains '_compressed' or '_shrunk'
        """
        if operation in ["compress", "compress_to_target"]:
            if "_compressed" in filename.lower() or "_shrunk" in filename.lower():
                return GuardResult(
                    action=GuardAction.SKIP,
                    message="Already optimized for size",
                    can_proceed=False,
                )
        
        return None
    
    @staticmethod
    def check_single_page_split(operation: str, page_count: int) -> Optional[GuardResult]:
        """
        Detect: single_page_pdf → split (meaningless)
        """
        if operation == "split" and page_count == 1:
            return GuardResult(
                action=GuardAction.SKIP,
                message="Only one page available",
                can_proceed=False,
            )
        
        return None
    
    @staticmethod
    def run_all_redundancy_guards(
        operation: str,
        current_type: FileType,
        filename: str = "",
        page_count: int = 0,
    ) -> Optional[GuardResult]:
        """
        Run all redundancy guards in sequence.
        Returns first triggered guard result, or None if no redundancy.
        """
        guards = [
            UniversalRedundancyGuards.check_image_to_image(operation, current_type),
            UniversalRedundancyGuards.check_pdf_to_pdf(operation, current_type),
            UniversalRedundancyGuards.check_docx_to_docx(operation, current_type),
            UniversalRedundancyGuards.check_already_compressed(operation, filename),
            UniversalRedundancyGuards.check_single_page_split(operation, page_count),
        ]
        
        # Return first non-None result
        for guard_result in guards:
            if guard_result is not None:
                logger.info(f"[REDUNDANCY GUARD TRIGGERED] {guard_result.message}")
                return guard_result
        
        return None


class OperationFileTypeCompatibility:
    """
    File-Type × Function Compatibility Matrix.
    
    Defines which operations are valid for which file types.
    """
    
    # Compatibility matrix: operation → valid file types
    MATRIX: Dict[str, Dict[str, any]] = {
        # PDF-only operations
        "merge": {
            "valid_types": [FileType.PDF],
            "message": "Merge supports PDFs only",
            "block": True,
        },
        "split": {
            "valid_types": [FileType.PDF],
            "message": "Split supports PDFs only",
            "block": True,
        },
        "delete": {
            "valid_types": [FileType.PDF],
            "message": "Delete pages supports PDFs only",
            "block": True,
        },
        "reorder": {
            "valid_types": [FileType.PDF],
            "message": "Reorder works on PDFs only",
            "block": True,
        },
        "clean": {
            "valid_types": [FileType.PDF],
            "message": "Cleaning works on PDFs only",
            "block": True,
        },
        "rotate": {
            "valid_types": [FileType.PDF],
            "message": "Rotate works on PDFs only",
            "block": True,
        },
        "flatten": {
            "valid_types": [FileType.PDF],
            "message": "Flatten works on PDFs only",
            "block": True,
        },
        
        # Image/scanned file operations
        "ocr": {
            "valid_types": [FileType.PDF, FileType.JPG, FileType.PNG, FileType.JPEG],
            "message": "OCR supports scanned PDFs or images only",
            "block": True,
        },
        "enhance_scan": {
            "valid_types": [FileType.PDF, FileType.JPG, FileType.PNG, FileType.JPEG],
            "message": "Enhancing scan",
            "block": False,
        },
        
        # Multi-format operations
        "compress": {
            "valid_types": [FileType.PDF, FileType.JPG, FileType.PNG, FileType.JPEG, FileType.DOCX],
            "message": "Compressing file",
            "block": False,
        },
        "compress_to_target": {
            "valid_types": [FileType.PDF, FileType.JPG, FileType.PNG, FileType.JPEG, FileType.DOCX],
            "message": "Compressing to target size",
            "block": False,
        },
        
        # Conversion operations (specific rules)
        "convert_to_image": {
            "valid_types": [FileType.PDF],
            "message": "PDF to image conversion",
            "block": True,
        },
        "convert_to_pdf": {
            "valid_types": [FileType.DOCX, FileType.JPG, FileType.PNG, FileType.JPEG],
            "message": "Document to PDF conversion",
            "block": True,
        },
        "convert_to_docx": {
            "valid_types": [FileType.PDF],
            "message": "PDF to DOCX conversion",
            "block": True,
        },
    }
    
    @staticmethod
    def check_compatibility(
        operation: str,
        file_type: FileType,
    ) -> Optional[GuardResult]:
        """
        Check if operation is supported for the given file type.
        
        Returns:
            GuardResult if incompatible (action=BLOCK), None if compatible.
        """
        if operation not in OperationFileTypeCompatibility.MATRIX:
            # Unknown operation - don't block, let it proceed
            return None
        
        entry = OperationFileTypeCompatibility.MATRIX[operation]
        valid_types = entry["valid_types"]
        
        if file_type not in valid_types:
            if entry["block"]:
                return GuardResult(
                    action=GuardAction.BLOCK,
                    message=entry["message"],
                    can_proceed=False,
                )
            else:
                # Non-blocking incompatibility, can still proceed
                logger.warning(
                    f"[COMPATIBILITY WARNING] Operation '{operation}' may not work well with {file_type}"
                )
        
        return None


def check_all_guards(
    operation: str,
    current_type: FileType,
    filename: str = "",
    page_count: int = 0,
) -> Optional[GuardResult]:
    """
    Run all guards (redundancy + compatibility) in sequence.
    
    Args:
        operation: Operation name (e.g., 'merge', 'split', 'compress')
        current_type: Current file type
        filename: Current filename (for redundancy checks)
        page_count: Page count (for PDF-specific checks)
    
    Returns:
        GuardResult if any guard is triggered, None if all clear.
    """
    # First check redundancy
    redundancy_result = UniversalRedundancyGuards.run_all_redundancy_guards(
        operation, current_type, filename, page_count
    )
    if redundancy_result:
        return redundancy_result
    
    # Then check compatibility
    compatibility_result = OperationFileTypeCompatibility.check_compatibility(
        operation, current_type
    )
    if compatibility_result:
        return compatibility_result
    
    return None


# ============================================
# CONTEXT INHERITANCE RULES
# ============================================

def should_inherit_context(prompt: str) -> bool:
    """
    Determine if a short follow-up command should inherit context from last operation.
    
    Short commands (≤5 tokens) without explicit file references should inherit context.
    Examples:
    - "to docx" → inherit
    - "compress" → inherit
    - "then convert" → inherit
    - "to excel" → inherit (even if unsupported, still inherit to provide context)
    
    Non-inheriting prompts:
    - "merge file1 and file2" → explicit files
    - "split pages 1-5" → explicit operation with parameters
    """
    tokens = prompt.strip().split()
    
    # Rule: ≤5 tokens without explicit file references
    if len(tokens) > 5:
        return False
    
    # Check for explicit file references (e.g., "file1", "file2")
    if any(keyword in prompt.lower() for keyword in ["file1", "file2", "file3", "upload"]):
        return False
    
    return True


def apply_context_inheritance(
    short_prompt: str,
    last_file: str,
    last_operation_type: str,
    last_output_type: FileType,
) -> str:
    """
    Expand a short follow-up command using prior context.
    
    Args:
        short_prompt: Short follow-up command (e.g., "to docx")
        last_file: Last file that was processed
        last_operation_type: Type of last operation (e.g., "compress")
        last_output_type: File type of last output
    
    Returns:
        Expanded prompt with full context
    """
    op_descriptions = {
        "compress": f"the compressed version of {last_file}",
        "merge": f"the merged PDF from {last_file}",
        "split": f"the split pages from {last_file}",
        "rotate": f"the rotated {last_file}",
        "delete": f"the file with pages deleted from {last_file}",
        "ocr": f"the OCR'd version of {last_file}",
        "convert": f"the converted {last_file}",
    }
    
    last_output_desc = op_descriptions.get(
        last_operation_type,
        f"the processed {last_file}",
    )
    
    # Expand common short follow-ups
    expansions = {
        "to docx": f"convert {last_output_desc} to DOCX",
        "to pdf": f"convert {last_output_desc} to PDF",
        "to image": f"convert {last_output_desc} to image",
        "compress": f"compress {last_output_desc}",
        "ocr": f"run OCR on {last_output_desc}",
        "merge": f"would need another file to merge with {last_output_desc}",
        "split": f"split {last_output_desc}",
        "flatten": f"flatten {last_output_desc}",
    }
    
    # Try to match and expand
    prompt_lower = short_prompt.lower().strip()
    for shorthand, expansion in expansions.items():
        if shorthand in prompt_lower:
            expanded = prompt_lower.replace(shorthand, expansion)
            logger.info(f"[CONTEXT INHERITED] '{short_prompt}' → '{expanded}'")
            return expanded
    
    # Default: add file context
    return f"apply '{short_prompt}' to {last_output_desc}"
