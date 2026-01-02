

import re
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from enum import Enum

logger = logging.getLogger(__name__)





class SupportedOp(str, Enum):
    MERGE = "merge"
    SPLIT = "split"
    COMPRESS = "compress"
    CONVERT = "convert"
    OCR = "ocr"
    CLEAN = "clean"
    ENHANCE = "enhance"
    ROTATE = "rotate"
    REORDER = "reorder"
    FLATTEN = "flatten"
    WATERMARK = "watermark"
    PAGE_NUMBERS = "page-numbers"



class FileType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    IMG = "img"
    JPG = "jpg"
    PNG = "png"
    JPEG = "jpeg"




 
PREFIX_PATTERNS = [
    r"^and\s+",
    r"^pls\s+",
    r"^plz\s+",
    r"^please\s+",
    r"^do\s+it\s+",
    r"^make\s+small\s+",
    r"^fix\s+this\s+",
    r"^to\s+doc\s+",
    r"^to\s+img\s+",
    r"^\d+\s+to\s+\d+\s+",  # "1 to 2"
    r"^then\s+",
    r"^now\s+",
    r"^just\s+",
    r"^can\s+you\s+",
    r"^i\s+want\s+to\s+",
    r"^i\s+need\s+to\s+",
]


TARGET_FORMAT_PATTERNS = {
    r"\bto\s+pdf\b": FileType.PDF,
    r"\bto\s+docx?\b": FileType.DOCX,
    r"\bto\s+img\b": FileType.IMG,
    r"\bto\s+png\b": FileType.PNG,
    r"\bto\s+jpe?g\b": FileType.JPG,
    r"\bas\s+pdf\b": FileType.PDF,
    r"\bas\s+docx?\b": FileType.DOCX,
}


TARGET_SIZE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(kb|mb|gb)",
    re.IGNORECASE
)


PURPOSE_PATTERNS = {
    r"\bemail\b": "email",
    r"\bwhatsapp\b": "whatsapp",
    r"\bprint\b": "print",
    r"\bweb\b": "web",
    r"\bshare\b": "share",
}


OPERATION_PATTERNS = {
    SupportedOp.MERGE: re.compile(r"\b(merge|combine|join)\b", re.IGNORECASE),
    SupportedOp.SPLIT: re.compile(r"\b(split|separate|divide)\b", re.IGNORECASE),
    SupportedOp.COMPRESS: re.compile(r"\b(compress|reduce|shrink|smaller|make\s+small)\b", re.IGNORECASE),
    SupportedOp.CONVERT: re.compile(r"\b(convert|change\s+to|transform)\b", re.IGNORECASE),
    SupportedOp.OCR: re.compile(r"\bocr\b", re.IGNORECASE),
    SupportedOp.CLEAN: re.compile(r"\b(clean|remove\s+blank|remove\s+duplicate)\b", re.IGNORECASE),
    SupportedOp.ENHANCE: re.compile(r"\b(enhance|improve|better)\b", re.IGNORECASE),
    SupportedOp.ROTATE: re.compile(r"\b(rotate|turn)\b", re.IGNORECASE),
    SupportedOp.REORDER: re.compile(r"\b(reorder|rearrange|reorganize)\b", re.IGNORECASE),
    SupportedOp.FLATTEN: re.compile(r"\b(flatten)\b", re.IGNORECASE),
    SupportedOp.WATERMARK: re.compile(r"\b(watermark)\b", re.IGNORECASE),
    SupportedOp.PAGE_NUMBERS: re.compile(r"\b(page[-\s]?numbers?|add\s+numbers?)\b", re.IGNORECASE),
}


PIPELINE_ARROW = re.compile(r"\s*(?:→|➔|->|>)+\s*")




@dataclass
class ParsedCommand:

    original_input: str
    normalized_input: str
    operations: List[SupportedOp] = field(default_factory=list)
    target_format: Optional[FileType] = None
    target_size_mb: Optional[float] = None
    purpose: Optional[str] = None
    confidence: float = 0.0
    needs_clarification: bool = False
    clarification_options: List[str] = field(default_factory=list)


@dataclass
class GuardResult:

    should_skip: bool = False
    should_retry: bool = False
    retry_action: Optional[str] = None
    user_message: Optional[str] = None


@dataclass
class ResolutionResult:

    success: bool
    pipeline: List[str] = field(default_factory=list)
    source_type: Optional[FileType] = None
    target_format: Optional[FileType] = None
    target_size_mb: Optional[float] = None
    guard_result: Optional[GuardResult] = None
    needs_user_choice: bool = False
    options: List[str] = field(default_factory=list)
    error_message: Optional[str] = None




class LocalNormalizer:
    
    @staticmethod
    def normalize(text: str) -> str:
        if not text:
            return text
        
        result = text.lower().strip()
        
        # Strip common prefixes
        for pattern in PREFIX_PATTERNS:
            result = re.sub(pattern, "", result, flags=re.IGNORECASE).strip()
        
        # Fix common typos
        typo_fixes = {
            r"\bcompres\b": "compress",
            r"\bcomprs\b": "compress",
            r"\bmrge\b": "merge",
            r"\bmerg\b": "merge",
            r"\bsplt\b": "split",
            r"\bspill\b": "split",
            r"\bspilt\b": "split",
            r"\bconvrt\b": "convert",
            r"\brotate\b": "rotate",
            r"\brotat\b": "rotate",
            r"\brotae\b": "rotate",
            r"\bwatermark\b": "watermark",
            r"\benhance\b": "enhance",
            r"\breorder\b": "reorder",
            r"\bflatten\b": "flatten",
            r"\bclean\b": "clean",
            r"\badn\b": "and",
            r"\bthn\b": "then",
            r"\bthne\b": "then",
            r"\bdog\b": "docx",
            r"\bdox\b": "docx",
            r"\bpfd\b": "pdf",
            r"\bimag\b": "image",
        }
        
        for typo, fix in typo_fixes.items():
            result = re.sub(typo, fix, result, flags=re.IGNORECASE)
        
        # Normalize arrows
        result = PIPELINE_ARROW.sub(" → ", result)
        
        return result.strip()
    
    @staticmethod
    def extract_operations(text: str) -> List[SupportedOp]:
        """Extract operations from text"""
        operations = []
        
        # Check for pipeline arrow notation
        if "→" in text:
            parts = text.split("→")
            for part in parts:
                part = part.strip()
                for op, pattern in OPERATION_PATTERNS.items():
                    if pattern.search(part):
                        operations.append(op)
                        break
        else:
            # Check each operation pattern
            for op, pattern in OPERATION_PATTERNS.items():
                if pattern.search(text):
                    operations.append(op)
        
        return operations
    
    @staticmethod
    def extract_target_format(text: str) -> Optional[FileType]:
        """Extract target format from text"""
        for pattern, file_type in TARGET_FORMAT_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                return file_type
        return None
    
    @staticmethod
    def extract_target_size(text: str) -> Optional[float]:
        """Extract target size in MB from text"""
        match = TARGET_SIZE_PATTERN.search(text)
        if match:
            value = float(match.group(1))
            unit = match.group(2).lower()
            
            if unit == "kb":
                return value / 1024
            elif unit == "mb":
                return value
            elif unit == "gb":
                return value * 1024
        
        return None
    
    @staticmethod
    def extract_purpose(text: str) -> Optional[str]:
        """Extract purpose from text"""
        for pattern, purpose in PURPOSE_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                return purpose
        return None




class DeterministicGuards:
    
    @staticmethod
    def check_redundancy(
        source_type: FileType,
        target_format: Optional[FileType],
        operations: List[SupportedOp]
    ) -> GuardResult:
        
        # Image to image conversion is redundant
        if source_type in (FileType.IMG, FileType.JPG, FileType.PNG, FileType.JPEG):
            if target_format in (FileType.IMG, FileType.JPG, FileType.PNG, FileType.JPEG):
                if source_type == target_format:
                    return GuardResult(
                        should_skip=True,
                        user_message="File is already in the target format"
                    )
        
        # PDF to PDF conversion is redundant
        if source_type == FileType.PDF and target_format == FileType.PDF:
            if SupportedOp.CONVERT in operations and len(operations) == 1:
                return GuardResult(
                    should_skip=True,
                    user_message="File is already in PDF format"
                )
        
        return GuardResult()
    
    @staticmethod
    def check_compatibility(
        source_type: FileType,
        operations: List[SupportedOp]
    ) -> GuardResult:
        
        # OCR only makes sense on PDFs/images
        if SupportedOp.OCR in operations:
            if source_type == FileType.DOCX:
                return GuardResult(
                    should_skip=True,
                    user_message="OCR is not needed for DOCX files - text is already extractable"
                )
        
        # Merge requires multiple files (handled elsewhere)
        
        return GuardResult()
    
    @staticmethod
    def check_size_miss(
        achieved_size_mb: float,
        target_size_mb: float,
        retry_count: int = 0
    ) -> GuardResult:
        
        if achieved_size_mb <= target_size_mb:
            return GuardResult()
        
        if retry_count == 0:
            return GuardResult(
                should_retry=True,
                retry_action="stronger_preset",
                user_message=f"Retrying with stronger compression to reach {target_size_mb}MB"
            )
        else:
            return GuardResult(
                user_message=f"Achieved {achieved_size_mb:.1f}MB - closest possible to target {target_size_mb}MB"
            )
    
    @staticmethod
    def check_xml_unicode_error(error_message: str, retry_count: int = 0) -> GuardResult:
        
        xml_error_patterns = [
            "xml compatible",
            "unicode",
            "encoding",
            "character",
            "null byte",
        ]
        
        is_xml_error = any(p in error_message.lower() for p in xml_error_patterns)
        
        if is_xml_error and retry_count == 0:
            return GuardResult(
                should_retry=True,
                retry_action="ocr_fallback",
                user_message="Processing with OCR fallback"
            )
        
        return GuardResult()




class PipelineMatcher:
    
    @staticmethod
    def match(parsed: ParsedCommand, source_type: FileType) -> ResolutionResult:
        
        operations = parsed.operations
        
        if not operations:
            return ResolutionResult(
                success=False,
                needs_user_choice=True,
                options=["Merge files", "Compress", "Convert to PDF", "OCR (extract text)"],
                error_message="Could not detect operation"
            )
        
        # Apply guards
        guards = DeterministicGuards()
        
        # Check redundancy
        redundancy_result = guards.check_redundancy(
            source_type,
            parsed.target_format,
            operations
        )
        if redundancy_result.should_skip:
            return ResolutionResult(
                success=True,
                pipeline=[],
                guard_result=redundancy_result
            )
        
        # Check compatibility
        compat_result = guards.check_compatibility(source_type, operations)
        if compat_result.should_skip:
            # Remove incompatible operation
            operations = [op for op in operations if op != SupportedOp.OCR]
        
        # Build pipeline string
        pipeline = [op.value for op in operations]
        
        # High confidence if we have operations and they make sense
        confidence = 0.9 if len(operations) >= 1 else 0.5
        
        return ResolutionResult(
            success=True,
            pipeline=pipeline,
            source_type=source_type,
            target_format=parsed.target_format,
            target_size_mb=parsed.target_size_mb,
            guard_result=redundancy_result if redundancy_result.user_message else compat_result
        )




class OneFlowResolver:
    
    def __init__(self):
        self.normalizer = LocalNormalizer()
        self.matcher = PipelineMatcher()
        self.guards = DeterministicGuards()
    
    def resolve(
        self,
        user_input: str,
        source_type: FileType,
        retry_count: int = 0
    ) -> ResolutionResult:
        
        # Stage 1: Normalize
        normalized = self.normalizer.normalize(user_input)
        
        # Extract components
        operations = self.normalizer.extract_operations(normalized)
        target_format = self.normalizer.extract_target_format(normalized)
        target_size = self.normalizer.extract_target_size(normalized)
        purpose = self.normalizer.extract_purpose(normalized)
        
        parsed = ParsedCommand(
            original_input=user_input,
            normalized_input=normalized,
            operations=operations,
            target_format=target_format,
            target_size_mb=target_size,
            purpose=purpose,
            confidence=0.8 if operations else 0.3
        )
        
        logger.debug(f"[ONE-FLOW] Parsed: {parsed}")
        
        # Stage 2: Deterministic Match
        result = self.matcher.match(parsed, source_type)
        
        if result.success and result.pipeline:
            logger.info(f"[ONE-FLOW] Matched pipeline: {result.pipeline}")
            return result
        
        # Stage 3: If unclear, provide options (LLM rephrase would go here in full impl)
        if not result.success or result.needs_user_choice:
            # Generate contextual options based on file type
            options = self._generate_options(source_type, parsed)
            
            return ResolutionResult(
                success=False,
                needs_user_choice=True,
                options=options,
                error_message="Please select an action"
            )
        
        return result
    
    def _generate_options(
        self,
        source_type: FileType,
        parsed: ParsedCommand
    ) -> List[str]:
        
        # Common options for all file types
        base_options = []
        
        if source_type == FileType.PDF:
            base_options = [
                "Compress PDF",
                "Convert to DOCX",
                "OCR (extract text)",
                "Split pages",
                "Merge with other PDFs",
                "Add watermark",
                "Add page numbers",
            ]
        elif source_type == FileType.DOCX:
            base_options = [
                "Convert to PDF",
                "Compress",
                "Add watermark",
                "Add page numbers",
            ]
        elif source_type in (FileType.IMG, FileType.JPG, FileType.PNG, FileType.JPEG):
            base_options = [
                "Convert to PDF",
                "Compress image",
                "Enhance quality",
                "Merge into PDF",
            ]
        
        # If we detected partial operations, prioritize related options
        if parsed.operations:
            # Move related options to top
            for op in parsed.operations:
                op_name = op.value.title()
                matching = [o for o in base_options if op_name.lower() in o.lower()]
                for m in matching:
                    base_options.remove(m)
                    base_options.insert(0, m)
        
        # Return top 3-5 options
        return base_options[:5]
    
    def handle_retry(
        self,
        original_result: ResolutionResult,
        error_message: str,
        retry_count: int
    ) -> Tuple[bool, Optional[str]]:
        
        # Check for size miss
        if original_result.target_size_mb:
            # This would need actual achieved size - placeholder
            pass
        
        # Check for XML/Unicode error
        xml_result = self.guards.check_xml_unicode_error(error_message, retry_count)
        if xml_result.should_retry:
            return True, xml_result.retry_action
        
        return False, None




def resolve_command(
    user_input: str,
    filename: str
) -> ResolutionResult:
    
    # Detect file type from filename
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    
    type_map = {
        "pdf": FileType.PDF,
        "docx": FileType.DOCX,
        "doc": FileType.DOCX,
        "jpg": FileType.JPG,
        "jpeg": FileType.JPEG,
        "png": FileType.PNG,
    }
    
    source_type = type_map.get(ext, FileType.PDF)
    
    resolver = OneFlowResolver()
    return resolver.resolve(user_input, source_type)


def get_purpose_presets(purpose: str) -> dict:
    
    presets = {
        "email": {
            "max_size_mb": 10,
            "quality": "medium",
            "dpi": 150,
        },
        "whatsapp": {
            "max_size_mb": 16,
            "quality": "medium",
            "dpi": 150,
        },
        "print": {
            "max_size_mb": 50,
            "quality": "high",
            "dpi": 300,
        },
        "web": {
            "max_size_mb": 5,
            "quality": "low",
            "dpi": 72,
        },
        "share": {
            "max_size_mb": 25,
            "quality": "medium",
            "dpi": 150,
        },
    }
    
    return presets.get(purpose, presets["email"])


# Global resolver instance
one_flow_resolver = OneFlowResolver()
