"""
40K Pattern Matching Engine

This module implements efficient pattern matching for 40,050 CASE patterns.
Instead of hardcoding each case, we use regex groups to match pattern families.

PATTERN STRUCTURE (from spec analysis):
- INPUT: `[prefix] [operations] to [format] [size/purpose]`
- PIPELINE: `[INPUT_TYPE] → [op1] → [op2] → ...`
- GUARDS: redundancy, compatibility, size-miss
- RETRY: once (preset/ocr)

PREFIX GROUPS:
- "and", "pls", "plz", "do it", "make small", "fix this"
- "to doc", "to img", "1 to 2", "then"

OPERATION GROUPS:
- Single: merge, split, compress, convert, ocr, clean, enhance, rotate, reorder, flatten, watermark, page-numbers
- Chained: op1 → op2, op1 → op2 → op3

TARGET GROUPS:
- Formats: to pdf, to docx, to img, to png, to jpg
- Sizes: 500kb, 1mb, 2mb
- Purposes: email, whatsapp, print
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict, Set
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================
# PATTERN FAMILIES
# ============================================

class PatternFamily(str, Enum):
    """High-level pattern family categories"""
    
    # Single operation patterns
    SINGLE_OP = "single_op"
    
    # Two-step pipeline patterns
    TWO_STEP = "two_step"
    
    # Three-step pipeline patterns
    THREE_STEP = "three_step"
    
    # Target-focused patterns (compress to size)
    SIZE_TARGET = "size_target"
    
    # Purpose-focused patterns (optimize for email)
    PURPOSE_TARGET = "purpose_target"
    
    # Format conversion patterns
    FORMAT_CONVERT = "format_convert"


@dataclass
class MatchedPattern:
    """Result of pattern matching"""
    family: PatternFamily
    operations: List[str] = field(default_factory=list)
    target_format: Optional[str] = None
    target_size_mb: Optional[float] = None
    purpose: Optional[str] = None
    confidence: float = 0.0
    matched_text: str = ""
    case_id: Optional[str] = None  # For debugging/tracing


# ============================================
# REGEX PATTERN DEFINITIONS
# ============================================

# Master list of operations
ALL_OPERATIONS = [
    "merge", "split", "compress", "convert", "ocr", "clean",
    "enhance", "rotate", "reorder", "flatten", "watermark", "page-numbers"
]

# Operation aliases
OP_ALIASES = {
    "combine": "merge",
    "join": "merge",
    "separate": "split",
    "divide": "split",
    "reduce": "compress",
    "shrink": "compress",
    "smaller": "compress",
    "make small": "compress",
    "make it small": "compress",
    "make it smaller": "compress",
    "change to": "convert",
    "transform": "convert",
    "extract text": "ocr",
    "text recognition": "ocr",
    "remove blank": "clean",
    "remove duplicate": "clean",
    "improve": "enhance",
    "better": "enhance",
    "turn": "rotate",
    "rearrange": "reorder",
    "reorganize": "reorder",
    "add numbers": "page-numbers",
    "number pages": "page-numbers",
}

# Build operation pattern (matches any operation or alias)
OP_PATTERN_STR = "|".join(
    [re.escape(op) for op in ALL_OPERATIONS] +
    [re.escape(alias) for alias in OP_ALIASES.keys()]
)
OP_PATTERN = re.compile(rf"\b({OP_PATTERN_STR})\b", re.IGNORECASE)

# Target format patterns
FORMAT_PATTERNS = {
    "pdf": re.compile(r"\b(to\s+pdf|as\s+pdf|pdf\s+format|\.pdf)\b", re.IGNORECASE),
    "docx": re.compile(r"\b(to\s+docx?|as\s+docx?|word|\.docx?)\b", re.IGNORECASE),
    "jpg": re.compile(r"\b(to\s+jpe?g|as\s+jpe?g|\.jpe?g)\b", re.IGNORECASE),
    "png": re.compile(r"\b(to\s+png|as\s+png|\.png)\b", re.IGNORECASE),
    "img": re.compile(r"\b(to\s+img|to\s+image|as\s+image)\b", re.IGNORECASE),
}

# Target size patterns (returns MB)
SIZE_PATTERNS = [
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*kb\b", re.IGNORECASE), 0.001),  # KB to MB
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*mb\b", re.IGNORECASE), 1.0),     # MB
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*gb\b", re.IGNORECASE), 1024.0),  # GB to MB
]

# Named size shortcuts
NAMED_SIZES = {
    "500kb": 0.5,
    "1mb": 1.0,
    "2mb": 2.0,
    "5mb": 5.0,
    "10mb": 10.0,
}

# Purpose patterns
PURPOSE_PATTERNS = {
    "email": re.compile(r"\b(email|e-mail|mail|send)\b", re.IGNORECASE),
    "whatsapp": re.compile(r"\b(whatsapp|wa|whats\s*app)\b", re.IGNORECASE),
    "print": re.compile(r"\b(print|printing|printer)\b", re.IGNORECASE),
    "web": re.compile(r"\b(web|website|online)\b", re.IGNORECASE),
    "share": re.compile(r"\b(share|sharing)\b", re.IGNORECASE),
}

# Pipeline arrow pattern
ARROW_PATTERN = re.compile(r"\s*[→➔\->]+\s*")

# Noise prefix pattern (to strip)
NOISE_PATTERN = re.compile(
    r"^(and|pls|plz|please|do\s+it|then|now|just|can\s+you|"
    r"i\s+want\s+to|i\s+need\s+to|help\s+me|could\s+you|would\s+you)\s+",
    re.IGNORECASE
)


# ============================================
# PATTERN MATCHER CLASS
# ============================================

class PatternMatcher:
    """
    Matches user input against 40K+ pattern families.
    Uses regex groups for efficient matching.
    """
    
    def __init__(self):
        self.op_pattern = OP_PATTERN
        self.format_patterns = FORMAT_PATTERNS
        self.size_patterns = SIZE_PATTERNS
        self.purpose_patterns = PURPOSE_PATTERNS
    
    def match(self, text: str) -> Optional[MatchedPattern]:
        """
        Match input text against pattern families.
        
        Args:
            text: User input text
        
        Returns:
            MatchedPattern if matched, None if no match
        """
        
        # Normalize input
        normalized = self._normalize(text)
        
        if not normalized:
            return None
        
        # Extract components
        operations = self._extract_operations(normalized)
        target_format = self._extract_format(normalized)
        target_size = self._extract_size(normalized)
        purpose = self._extract_purpose(normalized)
        
        # Determine pattern family
        family = self._determine_family(operations, target_format, target_size, purpose)
        
        # Calculate confidence
        confidence = self._calculate_confidence(operations, target_format, target_size, purpose)
        
        if not operations and not target_format and not purpose:
            return None
        
        return MatchedPattern(
            family=family,
            operations=operations,
            target_format=target_format,
            target_size_mb=target_size,
            purpose=purpose,
            confidence=confidence,
            matched_text=normalized
        )
    
    def _normalize(self, text: str) -> str:
        """Normalize input text"""
        
        if not text:
            return ""
        
        result = text.lower().strip()
        
        # Strip noise prefixes
        result = NOISE_PATTERN.sub("", result).strip()
        
        # Normalize arrows
        result = ARROW_PATTERN.sub(" → ", result)
        
        return result
    
    def _extract_operations(self, text: str) -> List[str]:
        """Extract operations from text"""
        
        operations = []
        
        # Check for arrow pipeline notation
        if "→" in text:
            parts = text.split("→")
            for part in parts:
                part = part.strip()
                match = self.op_pattern.search(part)
                if match:
                    op = match.group(1).lower()
                    # Resolve aliases
                    op = OP_ALIASES.get(op, op)
                    if op not in operations:
                        operations.append(op)
        else:
            # Find all operations
            for match in self.op_pattern.finditer(text):
                op = match.group(1).lower()
                op = OP_ALIASES.get(op, op)
                if op not in operations:
                    operations.append(op)
        
        return operations
    
    def _extract_format(self, text: str) -> Optional[str]:
        """Extract target format from text"""
        
        for fmt, pattern in self.format_patterns.items():
            if pattern.search(text):
                return fmt
        
        return None
    
    def _extract_size(self, text: str) -> Optional[float]:
        """Extract target size in MB from text"""
        
        # Check named sizes first
        for name, size in NAMED_SIZES.items():
            if name in text.replace(" ", "").lower():
                return size
        
        # Check patterns
        for pattern, multiplier in self.size_patterns:
            match = pattern.search(text)
            if match:
                value = float(match.group(1))
                return value * multiplier
        
        return None
    
    def _extract_purpose(self, text: str) -> Optional[str]:
        """Extract purpose from text"""
        
        for purpose, pattern in self.purpose_patterns.items():
            if pattern.search(text):
                return purpose
        
        return None
    
    def _determine_family(
        self,
        operations: List[str],
        target_format: Optional[str],
        target_size: Optional[float],
        purpose: Optional[str]
    ) -> PatternFamily:
        """Determine which pattern family this matches"""
        
        # Size-targeted operations
        if target_size:
            return PatternFamily.SIZE_TARGET
        
        # Purpose-targeted operations
        if purpose:
            return PatternFamily.PURPOSE_TARGET
        
        # Format conversion
        if target_format and ("convert" in operations or len(operations) == 0):
            return PatternFamily.FORMAT_CONVERT
        
        # Multi-step pipelines
        if len(operations) >= 3:
            return PatternFamily.THREE_STEP
        elif len(operations) == 2:
            return PatternFamily.TWO_STEP
        
        return PatternFamily.SINGLE_OP
    
    def _calculate_confidence(
        self,
        operations: List[str],
        target_format: Optional[str],
        target_size: Optional[float],
        purpose: Optional[str]
    ) -> float:
        """Calculate match confidence score"""
        
        score = 0.0
        
        # Operations detected - higher base score for clear operations
        if operations:
            score += 0.5 + (0.1 * min(len(operations), 3))
        
        # Target format specified
        if target_format:
            score += 0.15
        
        # Target size specified
        if target_size:
            score += 0.15
        
        # Purpose specified
        if purpose:
            score += 0.15
        
        return min(score, 1.0)
    
    def match_to_pipeline(
        self,
        matched: MatchedPattern,
        source_type: str
    ) -> Tuple[List[str], Dict]:
        """
        Convert matched pattern to executable pipeline.
        
        Args:
            matched: MatchedPattern from match()
            source_type: Source file type
        
        Returns:
            (pipeline, options) where pipeline is list of ops and options is config dict
        """
        
        pipeline = matched.operations.copy()
        options = {}
        
        # Add conversion if format specified but not in operations
        if matched.target_format and "convert" not in pipeline:
            if source_type != matched.target_format:
                pipeline.append("convert")
                options["target_format"] = matched.target_format
        
        # Add compression if size target specified
        if matched.target_size_mb:
            if "compress" not in pipeline:
                pipeline.insert(0, "compress")
            options["target_size_mb"] = matched.target_size_mb
        
        # Apply purpose presets
        if matched.purpose:
            presets = PURPOSE_PRESETS.get(matched.purpose, {})
            options.update(presets)
            
            # Ensure compress is in pipeline for purpose targets
            if "compress" not in pipeline and "max_size_mb" in presets:
                pipeline.insert(0, "compress")
        
        return pipeline, options


# Purpose presets
PURPOSE_PRESETS = {
    "email": {
        "max_size_mb": 10.0,
        "quality": "medium",
        "dpi": 150,
    },
    "whatsapp": {
        "max_size_mb": 16.0,
        "quality": "medium",
        "dpi": 150,
    },
    "print": {
        "max_size_mb": 50.0,
        "quality": "high",
        "dpi": 300,
    },
    "web": {
        "max_size_mb": 5.0,
        "quality": "low",
        "dpi": 72,
    },
    "share": {
        "max_size_mb": 25.0,
        "quality": "medium",
        "dpi": 150,
    },
}


# ============================================
# CASE ID GENERATOR (for tracing)
# ============================================

def generate_case_id(matched: MatchedPattern) -> str:
    """
    Generate a CASE-XXXXX ID for debugging/tracing.
    Maps the matched pattern to a case number range.
    """
    
    # Base case ranges by family
    base_ranges = {
        PatternFamily.SINGLE_OP: 0,
        PatternFamily.TWO_STEP: 10000,
        PatternFamily.THREE_STEP: 20000,
        PatternFamily.SIZE_TARGET: 30000,
        PatternFamily.PURPOSE_TARGET: 35000,
        PatternFamily.FORMAT_CONVERT: 38000,
    }
    
    base = base_ranges.get(matched.family, 0)
    
    # Add offset based on first operation
    op_offset = {op: i * 100 for i, op in enumerate(ALL_OPERATIONS)}
    
    offset = 0
    if matched.operations:
        offset = op_offset.get(matched.operations[0], 0)
    
    case_num = base + offset + hash(matched.matched_text) % 100
    
    return f"CASE-{case_num:05d}"


# ============================================
# CONVENIENCE FUNCTIONS
# ============================================

def match_command(text: str) -> Optional[MatchedPattern]:
    """
    Convenience function to match a command.
    
    Args:
        text: User input text
    
    Returns:
        MatchedPattern if matched, None otherwise
    """
    
    matcher = PatternMatcher()
    return matcher.match(text)


def get_pipeline_for_command(
    text: str,
    source_file: str
) -> Tuple[List[str], Dict]:
    """
    Get executable pipeline for a command.
    
    Args:
        text: User input text
        source_file: Source filename
    
    Returns:
        (pipeline, options)
    """
    
    # Get source type from filename
    ext = source_file.rsplit(".", 1)[-1].lower() if "." in source_file else "pdf"
    
    matcher = PatternMatcher()
    matched = matcher.match(text)
    
    if not matched:
        return [], {}
    
    return matcher.match_to_pipeline(matched, ext)


# Global matcher instance
pattern_matcher = PatternMatcher()
