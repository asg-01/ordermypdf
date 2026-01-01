"""
Command Intelligence - Parse user commands with confidence scoring and ambiguity detection.

This module implements:
- Confidence scoring for parsed intents (0.0 to 1.0)
- Ambiguity level detection (low, medium, high)
- 3-stage resolution pipeline (direct parse → LLM rephrase → ask user)
- Command validation against 10K+ patterns
"""

from typing import Optional, Tuple, List, Dict, Any
from enum import Enum
from dataclasses import dataclass
import re
import logging


logger = logging.getLogger(__name__)


class ConfidenceLevel(str, Enum):
    """Confidence levels for parsed intents"""
    VERY_LOW = "very_low"  # < 0.5
    LOW = "low"  # 0.5-0.65
    MEDIUM = "medium"  # 0.65-0.8
    HIGH = "high"  # 0.8-0.95
    VERY_HIGH = "very_high"  # >= 0.95


class AmbiguityLevel(str, Enum):
    """Ambiguity levels for user input"""
    LOW = "low"  # Clear intent
    MEDIUM = "medium"  # Some ambiguity, can infer
    HIGH = "high"  # Significant ambiguity, need clarification


@dataclass
class CommandParsing:
    """Result of command parsing"""
    intent: str  # e.g., 'merge', 'split', 'compress'
    parameters: Dict[str, Any]  # operation parameters
    confidence: float  # 0.0 to 1.0
    confidence_level: ConfidenceLevel
    ambiguity: AmbiguityLevel
    
    # Context for 3-stage resolution
    parsed_from_stage: str  # "direct", "rephrased", "clarified"
    issues: List[str] = None  # Issues found during parsing
    
    def __post_init__(self):
        if self.issues is None:
            self.issues = []


class CommandPatterns:
    """Pre-compiled regex patterns for command parsing"""
    
    # Operation detection patterns
    MERGE_PATTERNS = [
        r"merge",
        r"combine",
        r"join",
        r"concatenate",
        r"put together",
        r"combine.*pdfs?",
    ]
    
    SPLIT_PATTERNS = [
        r"split",
        r"extract.*pages?",
        r"keep.*pages?",
        r"take.*pages?",
        r"get.*pages?",
        r"pages?\s+(?:1|first)",
    ]
    
    DELETE_PATTERNS = [
        r"delete",
        r"remove",
        r"drop",
        r"discard",
        r"erase",
        r"pages?\s+(?:delete|remove)",
    ]
    
    COMPRESS_PATTERNS = [
        r"compress",
        r"reduce.*size",
        r"make.*small",
        r"shrink",
        r"zip",
        r"optimize",
        r"email.*ready",
        r"whatsapp",
    ]
    
    OCR_PATTERNS = [
        r"ocr",
        r"make.*searchable",
        r"extract.*text",
        r"recognize",
        r"scan",
    ]
    
    CONVERT_PATTERNS = [
        r"convert",
        r"export",
        r"save as",
        r"to\s+(?:pdf|docx|jpg|png|word|image)",
        r"as\s+(?:pdf|docx|jpg|png|word|image)",
    ]
    
    ROTATE_PATTERNS = [
        r"rotate",
        r"turn",
        r"orientation",
        r"landscape",
        r"portrait",
    ]
    
    CLEAN_PATTERNS = [
        r"clean",
        r"remove.*blank",
        r"remove.*empty",
        r"remove.*duplicate",
        r"deduplicate",
    ]
    
    # Compile patterns
    COMPILED_PATTERNS: Dict[str, List[re.Pattern]] = {
        "merge": [re.compile(p, re.IGNORECASE) for p in MERGE_PATTERNS],
        "split": [re.compile(p, re.IGNORECASE) for p in SPLIT_PATTERNS],
        "delete": [re.compile(p, re.IGNORECASE) for p in DELETE_PATTERNS],
        "compress": [re.compile(p, re.IGNORECASE) for p in COMPRESS_PATTERNS],
        "ocr": [re.compile(p, re.IGNORECASE) for p in OCR_PATTERNS],
        "convert": [re.compile(p, re.IGNORECASE) for p in CONVERT_PATTERNS],
        "rotate": [re.compile(p, re.IGNORECASE) for p in ROTATE_PATTERNS],
        "clean": [re.compile(p, re.IGNORECASE) for p in CLEAN_PATTERNS],
    }


class CommandIntelligence:
    """Command intelligence system with confidence scoring"""
    
    @staticmethod
    def detect_intent(prompt: str) -> Optional[str]:
        """
        Detect primary intent from prompt.
        
        Returns operation name if detected, None otherwise.
        """
        for intent, patterns in CommandPatterns.COMPILED_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(prompt):
                    logger.debug(f"[INTENT DETECTED] {intent}")
                    return intent
        
        return None
    
    @staticmethod
    def calculate_confidence(
        prompt: str,
        intent: str,
        parameters: Dict[str, Any],
    ) -> float:
        """
        Calculate confidence score (0.0 to 1.0) for parsed intent.
        
        Factors:
        - Clear intent keywords (+0.3)
        - Complete parameters (+0.4)
        - Low ambiguity (+0.3)
        """
        confidence = 0.0
        
        # Factor 1: Intent clarity (0.0-0.3)
        if CommandIntelligence.detect_intent(prompt):
            confidence += 0.3
        
        # Factor 2: Parameter completeness (0.0-0.4)
        required_params = {
            "merge": ["files"],
            "split": ["pages"],
            "delete": ["pages"],
            "compress": [],  # Optional parameters
            "ocr": [],
            "convert": ["target_format"],
            "rotate": ["degrees"],
            "clean": [],
        }
        
        if intent in required_params:
            required = required_params[intent]
            provided = len([p for p in required if p in parameters and parameters[p]])
            if required:
                confidence += 0.4 * (provided / len(required))
            else:
                confidence += 0.4  # No required params
        
        # Factor 3: Low ambiguity (0.0-0.3)
        ambiguity = CommandIntelligence.detect_ambiguity(prompt, intent)
        if ambiguity == AmbiguityLevel.LOW:
            confidence += 0.3
        elif ambiguity == AmbiguityLevel.MEDIUM:
            confidence += 0.15
        
        return min(confidence, 1.0)
    
    @staticmethod
    def get_confidence_level(confidence: float) -> ConfidenceLevel:
        """Convert confidence score to level"""
        if confidence < 0.5:
            return ConfidenceLevel.VERY_LOW
        elif confidence < 0.65:
            return ConfidenceLevel.LOW
        elif confidence < 0.8:
            return ConfidenceLevel.MEDIUM
        elif confidence < 0.95:
            return ConfidenceLevel.HIGH
        else:
            return ConfidenceLevel.VERY_HIGH
    
    @staticmethod
    def detect_ambiguity(prompt: str, intent: str) -> AmbiguityLevel:
        """
        Detect ambiguity level in prompt.
        
        Returns:
        - LOW: Clear parameters, explicit mention of what to do
        - MEDIUM: Missing some parameters but can infer
        - HIGH: Vague, multiple interpretations possible
        """
        prompt_lower = prompt.lower()
        
        # Count clarity indicators
        clarity_score = 0
        
        # Page numbers mentioned
        if re.search(r"pages?\s+\d", prompt_lower):
            clarity_score += 2
        
        # Target format mentioned
        if re.search(r"to\s+(pdf|docx|jpg|png)", prompt_lower):
            clarity_score += 2
        
        # Compression level mentioned
        if re.search(r"(small|tiny|reduce|half|email|whatsapp)", prompt_lower):
            clarity_score += 1
        
        # Multiple operations mentioned
        if len(CommandIntelligence.find_all_intents(prompt)) > 1:
            clarity_score -= 1
        
        # Vague keywords
        if re.search(r"(fix|optimize|make nice|whatever|something)", prompt_lower):
            clarity_score -= 2
        
        if clarity_score >= 2:
            return AmbiguityLevel.LOW
        elif clarity_score >= 0:
            return AmbiguityLevel.MEDIUM
        else:
            return AmbiguityLevel.HIGH
    
    @staticmethod
    def find_all_intents(prompt: str) -> List[str]:
        """Find all potential intents in prompt"""
        intents = []
        
        for intent, patterns in CommandPatterns.COMPILED_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(prompt):
                    intents.append(intent)
                    break
        
        return intents
    
    @staticmethod
    def extract_parameters(prompt: str, intent: str) -> Dict[str, Any]:
        """
        Extract parameters for the given intent.
        
        Returns dictionary of parameter name → value.
        """
        parameters = {}
        prompt_lower = prompt.lower()
        
        if intent == "split":
            # Extract page numbers: "pages 1-5", "pages 1, 3, 5"
            match = re.search(r"pages?\s+(?:(\d+)\s*-\s*(\d+)|(\d+(?:\s*,\s*\d+)*))", prompt_lower)
            if match:
                if match.group(1) and match.group(2):  # Range
                    parameters["pages"] = list(range(int(match.group(1)), int(match.group(2)) + 1))
                elif match.group(3):  # Comma-separated
                    parameters["pages"] = [int(n.strip()) for n in match.group(3).split(",")]
        
        elif intent == "delete":
            # Similar to split
            match = re.search(r"pages?\s+(?:(\d+)\s*-\s*(\d+)|(\d+(?:\s*,\s*\d+)*))", prompt_lower)
            if match:
                if match.group(1) and match.group(2):
                    parameters["pages"] = list(range(int(match.group(1)), int(match.group(2)) + 1))
                elif match.group(3):
                    parameters["pages"] = [int(n.strip()) for n in match.group(3).split(",")]
        
        elif intent == "compress":
            # Extract target size: "to 1mb", "to 2mb"
            match = re.search(r"to\s+(\d+)\s*mb", prompt_lower)
            if match:
                parameters["target_mb"] = int(match.group(1))
            
            # Or compression level
            if "screen" in prompt_lower or "email" in prompt_lower:
                parameters["preset"] = "screen"
            elif "ebook" in prompt_lower:
                parameters["preset"] = "ebook"
            elif "printer" in prompt_lower:
                parameters["preset"] = "printer"
        
        elif intent == "convert":
            # Extract target format
            formats = ["pdf", "docx", "jpg", "png", "word", "image"]
            for fmt in formats:
                if fmt in prompt_lower:
                    parameters["target_format"] = fmt
                    break
        
        elif intent == "rotate":
            # Extract rotation degrees
            if "90" in prompt_lower:
                parameters["degrees"] = 90
            elif "180" in prompt_lower:
                parameters["degrees"] = 180
            elif "270" in prompt_lower:
                parameters["degrees"] = 270
            elif "landscape" in prompt_lower:
                parameters["degrees"] = 90
            elif "portrait" in prompt_lower:
                parameters["degrees"] = 270
        
        return parameters
    
    @staticmethod
    def parse_command(prompt: str) -> Optional[CommandParsing]:
        """
        Parse user command with confidence scoring.
        
        Stage 1: Direct parse attempt (returns if confidence >= 0.7)
        If confidence < 0.7: returns result for Stage 2 (LLM rephrasing)
        
        Returns:
            CommandParsing with confidence and ambiguity, or None if parsing fails
        """
        # Detect intent
        intent = CommandIntelligence.detect_intent(prompt)
        if not intent:
            return None
        
        # Extract parameters
        parameters = CommandIntelligence.extract_parameters(prompt, intent)
        
        # Calculate confidence
        confidence = CommandIntelligence.calculate_confidence(prompt, intent, parameters)
        confidence_level = CommandIntelligence.get_confidence_level(confidence)
        
        # Detect ambiguity
        ambiguity = CommandIntelligence.detect_ambiguity(prompt, intent)
        
        # Identify issues
        issues = []
        if ambiguity == AmbiguityLevel.HIGH:
            issues.append("Vague intent - unclear what to do")
        if confidence_level in [ConfidenceLevel.VERY_LOW, ConfidenceLevel.LOW]:
            issues.append("Missing critical parameters")
        
        return CommandParsing(
            intent=intent,
            parameters=parameters,
            confidence=confidence,
            confidence_level=confidence_level,
            ambiguity=ambiguity,
            parsed_from_stage="direct",
            issues=issues,
        )


# Three-stage resolution pipeline
class ResolutionPipeline:
    """Three-stage command resolution pipeline"""
    
    # Stage 1: Direct parse
    STAGE1_CONFIDENCE_THRESHOLD = 0.7
    
    @staticmethod
    def stage1_direct_parse(prompt: str) -> Optional[CommandParsing]:
        """
        Stage 1: Attempt direct parse.
        
        Returns CommandParsing if confidence >= threshold, None otherwise.
        """
        parsing = CommandIntelligence.parse_command(prompt)
        
        if parsing and parsing.confidence >= ResolutionPipeline.STAGE1_CONFIDENCE_THRESHOLD:
            logger.info(f"[STAGE 1 SUCCESS] Direct parse confidence: {parsing.confidence:.2f}")
            parsing.parsed_from_stage = "direct"
            return parsing
        
        logger.info(f"[STAGE 1 FAILED] Confidence too low: {parsing.confidence:.2f if parsing else 0:.2f}")
        return None
    
    @staticmethod
    def stage2_llm_rephrase(
        prompt: str,
        prior_context: Optional[str] = None,
    ) -> Optional[CommandParsing]:
        """
        Stage 2: LLM-guided rephrasing (NO USER INTERRUPTION).
        
        Uses LLM to:
        - Fix typos
        - Expand shorthand
        - Attach missing context from prior operations
        - Infer chaining intent
        
        Then re-parses with updated prompt.
        """
        try:
            from app.config import settings
            if not getattr(settings, "enable_llm_rephrase", True):
                return None
        except Exception:
            # If config is unavailable, remain non-blocking.
            return None

        try:
            from app.phraser import rephrase_with_fallback

            # If prior_context is provided, include it in the prompt lightly.
            # Keep it minimal to avoid changing semantics.
            prompt_to_rephrase = prompt
            if prior_context:
                prompt_to_rephrase = f"{prompt}\nContext: {prior_context}"

            out = rephrase_with_fallback(prompt_to_rephrase)
            if not out or not out.text:
                return None

            parsing = CommandIntelligence.parse_command(out.text)
            if parsing:
                parsing.parsed_from_stage = "rephrased"
                logger.info(f"[STAGE 2 REPHRASE:{out.provider}] New confidence: {parsing.confidence:.2f}")
                return parsing
            return None
        except Exception:
            return None
    
    @staticmethod
    def stage3_ask_clarification(
        prompt: str,
        parsing: Optional[CommandParsing] = None,
    ) -> Tuple[str, List[str]]:
        """
        Stage 3: Ask user for clarification (LAST RESORT).
        
        Only called if Stages 1 and 2 fail.
        
        Returns:
            (clarification_question, possible_answers)
        """
        if not parsing:
            return (
                "I'm not sure what you'd like to do. Could you clarify?",
                ["compress", "merge", "split", "convert", "OCR", "something else"],
            )
        
        if parsing.intent == "split":
            return (
                "Which pages would you like to keep? (e.g., 1-5, or 1,3,5)",
                ["pages 1-5", "pages 1,3,5", "first 5 pages"],
            )
        
        elif parsing.intent == "convert":
            return (
                "What format would you like to convert to?",
                ["PDF", "DOCX", "JPG", "PNG"],
            )
        
        elif parsing.intent == "compress":
            return (
                "How much compression?",
                ["screen (smallest)", "ebook (default)", "to 1MB", "to 2MB"],
            )
        
        return (
            f"About {parsing.intent} - any additional details?",
            ["yes, here they are", "no, proceed"],
        )
    
    @staticmethod
    def resolve(
        prompt: str,
        prior_context: Optional[str] = None,
    ) -> Tuple[Optional[CommandParsing], Optional[Tuple[str, List[str]]]]:
        """
        Execute the 3-stage resolution pipeline.
        
        Args:
            prompt: User input
            prior_context: Prior operation context (for Stage 2)
        
        Returns:
            (CommandParsing, clarification_tuple) where at most one is not None
            - If CommandParsing is returned: resolved successfully
            - If clarification_tuple is returned: need user input
        """
        # Stage 1: Direct parse
        parsing = ResolutionPipeline.stage1_direct_parse(prompt)
        if parsing:
            return parsing, None
        
        # Stage 2: LLM rephrase
        parsing = ResolutionPipeline.stage2_llm_rephrase(prompt, prior_context)
        if parsing and parsing.confidence >= ResolutionPipeline.STAGE1_CONFIDENCE_THRESHOLD:
            return parsing, None
        
        # Stage 3: Ask clarification
        clarification = ResolutionPipeline.stage3_ask_clarification(prompt, parsing)
        return None, clarification
