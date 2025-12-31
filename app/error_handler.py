"""
Error Handler - Comprehensive error taxonomy and classification system.

This module implements the 8-layer error classification system to ensure users
NEVER see raw technical errors. Every failure is detected, classified, auto-recovered
if possible, or shown as a simple human-friendly message.

Error Classification Layers:
1. User Input Errors (typos, shorthand, vague intent)
2. Pipeline Planning Errors (conflicting operations)
3. File Content Errors (XML/Unicode issues, fake text layers, broken fonts)
4. File Type Compatibility Errors (operation not supported for file type)
5. Execution/Library Errors (parsing failures, OCR engine failure, conversion crash)
6. Resource/System Errors (OOM, timeout)
7. Output Integrity Errors (empty output, corrupt file)
8. Unsupported Feature Errors (Excel conversion, digital signatures)
"""

from enum import Enum
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
import logging


logger = logging.getLogger(__name__)


class ErrorType(str, Enum):
    """Enumeration of all error types"""
    # Layer 1: User Input Errors
    TYPO = "typo"
    SHORTHAND = "shorthand"
    VAGUE_INTENT = "vague_intent"
    
    # Layer 2: Pipeline Planning Errors
    CONFLICTING_OPS = "conflicting_ops"
    MISSING_PARAMETER = "missing_parameter"
    INVALID_OPERATION_ORDER = "invalid_operation_order"
    
    # Layer 3: File Content Errors
    XML_UNICODE_ERROR = "xml_unicode_error"
    FAKE_TEXT_LAYER = "fake_text_layer"
    BROKEN_FONTS = "broken_fonts"
    
    # Layer 4: File Type Compatibility Errors
    TYPE_INCOMPATIBLE = "type_incompatible"
    OPERATION_NOT_SUPPORTED_FOR_TYPE = "operation_not_supported_for_type"
    
    # Layer 5: Execution Errors
    PDF_PARSING_FAILURE = "pdf_parsing_failure"
    OCR_ENGINE_FAILURE = "ocr_engine_failure"
    CONVERSION_CRASH = "conversion_crash"
    
    # Layer 6: Resource Errors
    OUT_OF_MEMORY = "out_of_memory"
    TIMEOUT = "timeout"
    
    # Layer 7: Output Integrity Errors
    EMPTY_OUTPUT = "empty_output"
    CORRUPT_FILE = "corrupt_file"
    
    # Layer 8: Unsupported Features
    UNSUPPORTED_FEATURE = "unsupported_feature"


class ErrorSeverity(str, Enum):
    """Error severity levels"""
    LOW = "low"  # Can auto-recover or skip
    MEDIUM = "medium"  # Should ask user
    HIGH = "high"  # Cannot continue


@dataclass
class ErrorClassification:
    """Classification result for an error"""
    error_type: ErrorType
    severity: ErrorSeverity
    user_message: str
    system_message: str
    action: str  # 'skip', 'retry', 'auto_fix', 'ask_user', 'block'
    can_recover: bool = False
    recovery_action: Optional[str] = None


class ErrorClassifier:
    """Classifies and handles errors across all layers"""
    
    # Layer 4: File Type Compatibility Matrix
    OPERATION_FILE_TYPE_MATRIX = {
        "merge": {"valid": ["pdf"], "message": "Merge supports PDFs only"},
        "split": {"valid": ["pdf"], "message": "Split supports PDFs only"},
        "delete": {"valid": ["pdf"], "message": "Delete supports PDFs only"},
        "reorder": {"valid": ["pdf"], "message": "Reorder works on PDFs only"},
        "clean": {"valid": ["pdf"], "message": "Cleaning works on PDFs only"},
        "ocr": {"valid": ["pdf", "jpg", "png", "jpeg"], "message": "OCR supports scanned files only"},
        "compress": {"valid": ["pdf", "jpg", "png", "jpeg", "docx"], "message": "Compress"},
        "rotate": {"valid": ["pdf"], "message": "Rotate works on PDFs only"},
        "enhance_scan": {"valid": ["pdf", "jpg", "png", "jpeg"], "message": "Enhancing scan"},
        "convert_to_image": {"valid": ["pdf"], "message": "Already an image"},
        "convert_to_pdf": {"valid": ["docx", "jpg", "png", "jpeg"], "message": "Already a PDF"},
        "convert_to_docx": {"valid": ["pdf"], "message": "Conversion"},
    }
    
    # Layer 1: Common typos and their corrections
    TYPO_CORRECTIONS = {
        "compres": "compress",
        "cnvert": "convert",
        "spllit": "split",
        "to doc": "to docx",
        "to img": "to image",
    }
    
    # Layer 1: Shorthand expansions
    SHORTHAND_EXPANSIONS = {
        "to doc": "convert to docx",
        "to img": "convert to image",
        "to pdf": "convert to pdf",
        "make small": "compress",
        "make smaller": "compress",
        "reduce size": "compress",
        "shrink": "compress",
        "email ready": "compress and optimize for email",
        "for email": "compress for email",
        "whatsapp size": "compress for whatsapp",
        "print ready": "flatten for print",
        "make searchable": "ocr",
        "fix scan": "enhance and ocr",
        "scan quality": "enhance and ocr",
        "govt submission": "ocr and flatten",
        "college submission": "ocr and compress",
    }
    
    # Layer 8: Unsupported features
    UNSUPPORTED_FEATURES = {
        "to excel": "PDF to Excel conversion not supported yet",
        "to xlsx": "PDF to Excel conversion not supported yet",
        "digital signature": "Digital signatures not supported yet",
        "sign pdf": "PDF signing not supported yet",
        "watermark": "Watermarking not fully supported yet",
        "redact": "Redaction not supported yet",
        "extract text": "Text extraction API not exposed yet",
        "extract table": "Table extraction not supported yet",
    }
    
    @staticmethod
    def classify_typo(prompt: str) -> Optional[str]:
        """Detect and correct typos. Returns corrected prompt or None."""
        prompt_lower = prompt.lower()
        for typo, correction in ErrorClassifier.TYPO_CORRECTIONS.items():
            if typo in prompt_lower:
                corrected = prompt_lower.replace(typo, correction)
                logger.info(f"[TYPO CORRECTED] '{typo}' → '{correction}'")
                return corrected
        return None
    
    @staticmethod
    def classify_shorthand(prompt: str) -> Optional[str]:
        """Expand shorthand. Returns expanded prompt or None."""
        prompt_lower = prompt.lower()
        for shorthand, expansion in ErrorClassifier.SHORTHAND_EXPANSIONS.items():
            if shorthand in prompt_lower:
                expanded = prompt_lower.replace(shorthand, expansion)
                logger.info(f"[SHORTHAND EXPANDED] '{shorthand}' → '{expansion}'")
                return expanded
        return None
    
    @staticmethod
    def classify_redundancy(operation: str, file_type: str) -> Optional[ErrorClassification]:
        """
        Check for redundant operations (e.g., image → to_image, pdf → to_pdf)
        Returns ErrorClassification if redundant, None otherwise.
        """
        # Skip operations
        skip_cases = [
            ("convert_to_image", "jpg"),
            ("convert_to_image", "png"),
            ("convert_to_image", "jpeg"),
            ("convert_to_pdf", "pdf"),
            ("convert_to_docx", "docx"),
        ]
        
        for op, ftype in skip_cases:
            if operation == op and file_type.lower() == ftype.lower():
                return ErrorClassification(
                    error_type=ErrorType.TYPE_INCOMPATIBLE,
                    severity=ErrorSeverity.LOW,
                    user_message=f"Already {'an image' if 'image' in op else 'a PDF' if 'pdf' in op else 'a Word document'}",
                    system_message=f"Skipping redundant operation: {operation} on {file_type}",
                    action="skip",
                    can_recover=True,
                    recovery_action="skip"
                )
        
        return None
    
    @staticmethod
    def classify_file_type_incompatibility(
        operation: str, 
        file_type: str
    ) -> Optional[ErrorClassification]:
        """
        Check if operation is supported for the file type.
        Returns ErrorClassification if incompatible, None otherwise.
        """
        if operation not in ErrorClassifier.OPERATION_FILE_TYPE_MATRIX:
            return None
        
        matrix_entry = ErrorClassifier.OPERATION_FILE_TYPE_MATRIX[operation]
        valid_types = [t.lower() for t in matrix_entry["valid"]]
        
        if file_type.lower() not in valid_types:
            return ErrorClassification(
                error_type=ErrorType.OPERATION_NOT_SUPPORTED_FOR_TYPE,
                severity=ErrorSeverity.MEDIUM,
                user_message=matrix_entry["message"],
                system_message=f"Operation '{operation}' not supported for file type '{file_type}'",
                action="block",
                can_recover=False
            )
        
        return None
    
    @staticmethod
    def classify_unsupported_feature(prompt: str) -> Optional[ErrorClassification]:
        """
        Detect requests for unsupported features.
        Returns ErrorClassification if unsupported, None otherwise.
        """
        prompt_lower = prompt.lower()
        
        for feature, message in ErrorClassifier.UNSUPPORTED_FEATURES.items():
            if feature.lower() in prompt_lower:
                return ErrorClassification(
                    error_type=ErrorType.UNSUPPORTED_FEATURE,
                    severity=ErrorSeverity.MEDIUM,
                    user_message="Not supported yet",
                    system_message=message,
                    action="block",
                    can_recover=False
                )
        
        return None
    
    @staticmethod
    def classify_conflicting_operations(operations: list[str]) -> Optional[ErrorClassification]:
        """
        Detect conflicting operation sequences (e.g., merge + split, split + merge).
        Returns ErrorClassification if conflicting, None otherwise.
        """
        conflict_pairs = [
            ("merge", "split"),
            ("split", "merge"),
        ]
        
        ops_lower = [op.lower() for op in operations]
        
        for op1, op2 in conflict_pairs:
            if op1 in ops_lower and op2 in ops_lower:
                op1_idx = ops_lower.index(op1)
                op2_idx = ops_lower.index(op2)
                
                return ErrorClassification(
                    error_type=ErrorType.CONFLICTING_OPS,
                    severity=ErrorSeverity.MEDIUM,
                    user_message="These operations conflict. I'll apply them in logical order.",
                    system_message=f"Conflicting operations: {op1} and {op2}. Reordering.",
                    action="auto_fix",
                    can_recover=True,
                    recovery_action=f"reorder to execute {op1 if op1_idx > op2_idx else op2} first"
                )
        
        return None
    
    @staticmethod
    def classify_execution_error(
        error_type: str, 
        error_message: str
    ) -> ErrorClassification:
        """
        Classify execution errors (parsing failure, OCR failure, conversion crash).
        Determine if error is auto-recoverable.
        """
        # OCR failures can retry with enhanced image
        if "ocr" in error_message.lower() or "tesseract" in error_message.lower():
            return ErrorClassification(
                error_type=ErrorType.OCR_ENGINE_FAILURE,
                severity=ErrorSeverity.MEDIUM,
                user_message="Retrying with image enhancement...",
                system_message=f"OCR failure: {error_message}",
                action="retry",
                can_recover=True,
                recovery_action="enhance_then_retry"
            )
        
        # PDF parsing failures might be fixable with repair
        if "pdf" in error_message.lower() and ("parse" in error_message.lower() or "corrupt" in error_message.lower()):
            return ErrorClassification(
                error_type=ErrorType.PDF_PARSING_FAILURE,
                severity=ErrorSeverity.MEDIUM,
                user_message="Attempting to repair and retry...",
                system_message=f"PDF parsing failure: {error_message}",
                action="retry",
                can_recover=True,
                recovery_action="repair_then_retry"
            )
        
        # Font/XML errors can use OCR fallback
        if "font" in error_message.lower() or "xml" in error_message.lower():
            return ErrorClassification(
                error_type=ErrorType.FILE_CONTENT_ERRORS if "xml" in error_message.lower() else ErrorType.BROKEN_FONTS,
                severity=ErrorSeverity.MEDIUM,
                user_message="Using OCR fallback...",
                system_message=f"Content error: {error_message}. Using OCR.",
                action="retry",
                can_recover=True,
                recovery_action="ocr_fallback"
            )
        
        # Generic conversion crash
        return ErrorClassification(
            error_type=ErrorType.CONVERSION_CRASH,
            severity=ErrorSeverity.HIGH,
            user_message="Conversion failed. Please try again.",
            system_message=f"Conversion crashed: {error_message}",
            action="block",
            can_recover=False
        )
    
    @staticmethod
    def classify_resource_error(error_message: str) -> ErrorClassification:
        """Classify resource-related errors (OOM, timeout)."""
        if "memory" in error_message.lower() or "oom" in error_message.lower():
            return ErrorClassification(
                error_type=ErrorType.OUT_OF_MEMORY,
                severity=ErrorSeverity.HIGH,
                user_message="File too large. Attempting to reduce quality...",
                system_message=f"Out of memory: {error_message}",
                action="retry",
                can_recover=True,
                recovery_action="split_and_retry"
            )
        
        if "timeout" in error_message.lower():
            return ErrorClassification(
                error_type=ErrorType.TIMEOUT,
                severity=ErrorSeverity.MEDIUM,
                user_message="Operation taking too long. Retrying with lower quality...",
                system_message=f"Timeout: {error_message}",
                action="retry",
                can_recover=True,
                recovery_action="reduce_quality"
            )
        
        return ErrorClassification(
            error_type=ErrorType.OUT_OF_MEMORY,
            severity=ErrorSeverity.HIGH,
            user_message="System resource error. Please try a smaller file.",
            system_message=f"Resource error: {error_message}",
            action="block",
            can_recover=False
        )
    
    @staticmethod
    def classify_output_error(error_type: str) -> ErrorClassification:
        """Classify output integrity errors."""
        if error_type == "empty":
            return ErrorClassification(
                error_type=ErrorType.EMPTY_OUTPUT,
                severity=ErrorSeverity.MEDIUM,
                user_message="Output is empty. Regenerating...",
                system_message="Output file is empty",
                action="retry",
                can_recover=True,
                recovery_action="regenerate"
            )
        
        if error_type == "corrupt":
            return ErrorClassification(
                error_type=ErrorType.CORRUPT_FILE,
                severity=ErrorSeverity.HIGH,
                user_message="Output corrupted. Please try again.",
                system_message="Output file is corrupt",
                action="retry",
                can_recover=True,
                recovery_action="regenerate"
            )
        
        return ErrorClassification(
            error_type=ErrorType.CORRUPT_FILE,
            severity=ErrorSeverity.HIGH,
            user_message="Output validation failed.",
            system_message="Output validation failed",
            action="block",
            can_recover=False
        )


# Retry policy constants
MAX_RETRIES = 1  # Never infinite loops
RETRY_ACTIONS = {
    "enhance_then_retry": "Enhance image and retry OCR",
    "repair_then_retry": "Repair PDF structure and retry",
    "ocr_fallback": "Fall back to OCR",
    "split_and_retry": "Split file and process separately",
    "reduce_quality": "Reduce compression quality and retry",
    "regenerate": "Regenerate output",
}
