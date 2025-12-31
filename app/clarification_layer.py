"""
AI Clarification Layer - Handles ambiguous or incomplete user prompts by interacting with the user for clarification.
"""

from app.ai_parser import ai_parser
from typing import Union
from app.utils import (
    normalize_whitespace,
    fuzzy_match_keyword,
    ALL_NORMALIZE_KEYWORDS,
    RE_EXPLICIT_ORDER,
    RE_AND_THEN,
    RE_BEFORE,
    RE_AFTER,
    RE_MERGE_OPS,
    RE_SPLIT_OPS,
    RE_DELETE_OPS,
    RE_COMPRESS_OPS,
    RE_CONVERT_OPS,
    RE_ROTATE_OPS,
    RE_REORDER_OPS,
    RE_WATERMARK_OPS,
    RE_PAGE_NUMBERS_OPS,
    RE_OCR_OPS,
    RE_IMAGES_OPS,
    RE_PAGE_WITH_DIGIT,
    RE_DIGIT_RANGE,
    RE_DIGIT_COMMA,
)

class ClarificationResult:
    def __init__(self, intent: Union['ParsedIntent', list['ParsedIntent'], None] = None, clarification: str = None, options: list[str] = None):
        self.intent = intent
        self.clarification = clarification
        self.options = options


import re
import os
import json
from app.models import (
    ParsedIntent,
)
from app.pdf_operations import get_upload_path


UNSUPPORTED_REPLY = "Not supported yet or sooner"


def _is_short_followup(prompt: str) -> bool:
    """Check if this is a short follow-up command (≤5 tokens, likely depends on context)."""
    tokens = prompt.strip().split()
    return len(tokens) <= 5


def _rephrase_with_context(user_prompt: str, last_intent: Union['ParsedIntent', list['ParsedIntent'], None], file_names: list[str]) -> str | None:
    """
    LLM-based rephrasing: use prior session context to expand short/ambiguous follow-ups.
    
    Returns a rephrased prompt if successful, or None if rephrasing is not needed/failed.
    Only used for short follow-ups to avoid unnecessary LLM calls.
    """
    if not _is_short_followup(user_prompt):
        return None
    
    if last_intent is None:
        return None
    
    # Infer what the last operation was
    last_op = None
    if isinstance(last_intent, list) and last_intent:
        last_op = getattr(last_intent[-1], 'operation_type', None)
    elif isinstance(last_intent, ParsedIntent):
        last_op = getattr(last_intent, 'operation_type', None)
    
    if not last_op:
        return None
    
    # Map operation to human-readable description
    op_descriptions = {
        'compress': 'compressed the PDF',
        'compress_to_target': 'compressed the PDF to a target size',
        'merge': 'merged the PDFs',
        'split': 'split the PDF',
        'rotate': 'rotated the PDF',
        'delete_pages': 'deleted pages from the PDF',
        'keep_pages': 'extracted specific pages',
        'extract_pages': 'extracted pages from the PDF',
        'ocr': 'ran OCR on the document',
        'pdf_to_docx': 'converted the PDF to DOCX',
        'docx_to_pdf': 'converted the DOCX to PDF',
        'pdf_to_images': 'converted the PDF to images',
    }
    
    last_action = op_descriptions.get(last_op, f"performed '{last_op}' on the file")
    
    # Common short follow-ups and their likely intentions
    prompt_lower = user_prompt.lower().strip()
    
    # "to docx" → "convert to docx" or "convert [result] to docx"
    if prompt_lower in ('to docx', 'as docx', 'to word', 'as word', 'docx', 'word'):
        return f"convert the result to docx"
    
    # "to pdf" → "convert to pdf"
    if prompt_lower in ('to pdf', 'as pdf', 'pdf'):
        return f"convert the result to pdf"
    
    # "to png/jpg/img" → "convert to images"
    if prompt_lower in ('to png', 'as png', 'png', 'to jpg', 'to jpeg', 'as jpg', 'jpg', 'jpeg', 'img', 'to img', 'to image', 'to images'):
        fmt = 'jpg' if 'jpg' in prompt_lower or 'jpeg' in prompt_lower else 'png'
        return f"convert the result to {fmt} images"
    
    # "compress" / "smaller" / "make smaller" after prior operation
    if re.search(r'\b(compress|smaller|reduce|shrink)\b', prompt_lower):
        if last_op not in ('compress', 'compress_to_target'):
            return f"compress the result"
    
    # "merge" / "combine" intent
    if re.search(r'\b(merge|combine|together)\b', prompt_lower) and last_op not in ('merge',):
        return f"merge all the files together"
    
    # Generic fallback: if we can't infer, don't rephrase
    return None


def _is_explicitly_unsupported_request(prompt: str) -> bool:
    """Return True if the user is clearly requesting a currently unsupported feature.

    Corpus rule: if unsupported, reply exactly with UNSUPPORTED_REPLY.
    Keep this conservative to avoid false positives.
    """
    p = (prompt or "").lower()
    if not p:
        return False

    wants_convert = bool(re.search(r"\b(convert|change|export)\b", p))

    # Unsupported conversions / formats.
    if wants_convert and re.search(r"\b(pptx?|powerpoint)\b", p):
        return True
    if wants_convert and re.search(r"\b(xlsx?|xls|excel|csv)\b", p):
        return True
    if wants_convert and re.search(r"\bhtml?\b", p):
        return True

    # Unsupported security / signing workflows.
    if re.search(r"\b(password|encrypt|decrypt|unlock|protect)\b", p):
        return True
    if re.search(r"\b(sign|signature|e-?sign)\b", p):
        return True

    # Unsupported edits that imply authoring/annotation.
    if re.search(r"\b(edit|annotate|highlight)\b", p) and "pdf" in p:
        return True

    return False


def _is_likely_unsupported_validation_error(error_msg: str) -> bool:
    """Heuristic: identify Pydantic/validation failures that indicate an unsupported operation."""
    e = (error_msg or "").lower()
    if not e:
        return False

    # Most common: invalid literal for operation_type.
    if "operation_type" in e and (
        "input should be" in e
        or "literal" in e
        or "unexpected value" in e
        or "validation error" in e
    ):
        return True

    return False


def _parse_page_ranges(text: str) -> list[int]:
    """Parse '2,4-6' style page ranges into a sorted unique list of ints."""
    if not text:
        return []
    s = text.replace("pages", "").replace("page", "")
    s = re.sub(r"[^0-9,\-\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return []
    pages: set[int] = set()
    for part in [p.strip() for p in s.split(",") if p.strip()]:
        if "-" in part:
            a, b = [x.strip() for x in part.split("-", 1)]
            if a.isdigit() and b.isdigit():
                start = int(a)
                end = int(b)
                if start > 0 and end > 0:
                    lo, hi = (start, end) if start <= end else (end, start)
                    for i in range(lo, hi + 1):
                        pages.add(i)
        else:
            if part.isdigit():
                n = int(part)
                if n > 0:
                    pages.add(n)
    return sorted(pages)


def _normalize_prompt_for_heuristics(user_prompt: str) -> str:
    """Normalize common operation keywords for typo tolerance.

    This is only used for regex shortcuts and heuristics. The original prompt is still
    sent to the LLM to preserve full meaning.
    """
    # Use cached keyword list and optimized fuzzy matching
    return re.sub(r"[A-Za-z]{2,}", lambda m: fuzzy_match_keyword(m.group(0), ALL_NORMALIZE_KEYWORDS), user_prompt)


def _looks_like_multi_operation_prompt(user_prompt: str) -> bool:
    """Heuristic: if prompt appears to request 2+ ops (or uses explicit sequencing), don't short-circuit to a single-op regex."""
    prompt = _normalize_prompt_for_heuristics(user_prompt).lower()

    # Explicit sequencing words are a strong indicator (use precompiled regex)
    if RE_EXPLICIT_ORDER.search(prompt):
        return True

    # Count how many distinct operation families are mentioned (use precompiled patterns)
    op_hits = 0
    if RE_MERGE_OPS.search(prompt):
        op_hits += 1
    if RE_SPLIT_OPS.search(prompt):
        op_hits += 1
    if RE_DELETE_OPS.search(prompt):
        op_hits += 1
    if RE_COMPRESS_OPS.search(prompt):
        op_hits += 1
    if RE_CONVERT_OPS.search(prompt):
        op_hits += 1
    if RE_ROTATE_OPS.search(prompt) or RE_REORDER_OPS.search(prompt) or RE_WATERMARK_OPS.search(prompt) or RE_PAGE_NUMBERS_OPS.search(prompt) or RE_OCR_OPS.search(prompt) or RE_IMAGES_OPS.search(prompt):
        op_hits += 1

    return op_hits >= 2


def _options_for_pages_question(prefix: str) -> list[str]:
    # Keep it short and runnable.
    return [
        f"{prefix} pages 1",
        f"{prefix} pages 1-2",
        f"{prefix} pages 1-3",
        "all pages",
    ]


def _extract_page_range_tokens(prompt: str) -> bool:
    p = (prompt or "").lower()
    # Simple signal: any digit plus 'page'/'pages' or a raw range like 2-5 (use precompiled patterns)
    return bool(RE_PAGE_WITH_DIGIT.search(p) or RE_DIGIT_RANGE.search(p) or RE_DIGIT_COMMA.search(p))


def _split_two_step_explicit_order(user_prompt: str) -> tuple[str, str] | None:
    """Split a 2-step instruction into (first, second) for explicit order words.

    Supports: "A and then B", "A then B", "A before B", "A after B".
    """
    s = _fix_common_connector_typos(user_prompt)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None

    # Use precompiled patterns for better performance
    m = RE_AND_THEN.search(s)
    if m:
        parts = RE_AND_THEN.split(s, maxsplit=1)
        if len(parts) >= 3:
            a = parts[0].strip(" ,.;")
            b = parts[2].strip(" ,.;")
            if a and b:
                return a, b

    # "A before B" means A first.
    m = RE_BEFORE.search(s)
    if m:
        parts = RE_BEFORE.split(s, maxsplit=1)
        if len(parts) == 2:
            a = parts[0].strip(" ,.;")
            b = parts[1].strip(" ,.;")
            if a and b:
                return a, b

    # "A after B" means B first.
    m = RE_AFTER.search(s)
    if m:
        parts = RE_AFTER.split(s, maxsplit=1)
        if len(parts) == 2:
            a = parts[0].strip(" ,.;")
            b = parts[1].strip(" ,.;")
            if a and b:
                return b, a

    return None


def _fallback_parse_two_step_pipeline(user_prompt: str, file_names: list[str]) -> list[ParsedIntent] | None:
    """Best-effort non-LLM fallback for common 2-step prompts.

    Uses existing single-op heuristics by calling clarify_intent on each clause.
    Returns None if it cannot confidently produce two concrete intents.
    """
    split = _split_two_step_explicit_order(user_prompt)
    if not split:
        return None
    a, b = split

    ra = clarify_intent(a, file_names, last_question="", allow_multi=False)
    if not ra.intent or isinstance(ra.intent, list):
        return None
    rb = clarify_intent(b, file_names, last_question="", allow_multi=False)
    if not rb.intent or isinstance(rb.intent, list):
        return None

    return [ra.intent, rb.intent]


def _fallback_parse_multi_step_pipeline(user_prompt: str, file_names: list[str]) -> list[ParsedIntent] | None:
    """Deterministic fallback for multi-step prompts.

    Splits on explicit sequencing (and then / then / before / after) and parses each
    clause using single-op heuristics (allow_multi=False).
    """
    s = _fix_common_connector_typos(user_prompt)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None

    # Prefer splitting into ALL steps when 'then' is present (use precompiled pattern)
    if RE_AND_THEN.search(s):
        parts = RE_AND_THEN.split(s)
        steps = [p.strip(" ,.;") for p in parts if p.strip(" ,.;")]
    else:
        # Handle before/after (2-step) when no 'then' is present.
        two = _split_two_step_explicit_order(s)
        if not two:
            return None
        a, b = two
        steps = [a, b]

    if len(steps) < 2:
        return None
    if len(steps) > 6:
        steps = steps[:6]

    intents: list[ParsedIntent] = []
    for step in steps:
        r = clarify_intent(step, file_names, last_question="", allow_multi=False)
        if r.intent and not isinstance(r.intent, list):
            intents.append(r.intent)
            continue
        return None

    return intents


def _infer_compress_preset(user_prompt: str) -> str:
    """Infer a Ghostscript-like preset from qualitative wording."""
    prompt = _normalize_prompt_for_heuristics(user_prompt).lower()

    # Strongest compression / smallest output
    if re.search(r"\b(very\s*tiny|tiny|as\s*small\s*as\s*possible|smallest|max(?:imum)?|strong(?:ly)?|a\s*lot)\b", prompt):
        return "screen"

    # Light / minimal compression
    if re.search(r"\b(a\s*little|little\s*bit|a\s*bit|slight(?:ly)?|light(?:ly)?|minor)\b", prompt):
        return "printer"

    # Prefer quality
    if re.search(r"\b(best\s*quality|highest\s*quality|minimal\s*compression|don\s*'?t\s*lose\s*quality)\b", prompt):
        return "prepress"

    # Default
    return "ebook"


def _fix_common_connector_typos(text: str) -> str:
    if not text:
        return text
    s = text
    s = re.sub(r"\badn\b", "and", s, flags=re.IGNORECASE)
    s = re.sub(r"\bn\b", "and", s, flags=re.IGNORECASE)
    s = re.sub(r"\bthne\b", "then", s, flags=re.IGNORECASE)
    s = re.sub(r"\bthn\b", "then", s, flags=re.IGNORECASE)

    # Common action typos seen in the training corpus.
    # Keep this conservative: only fix full-word matches.
    s = re.sub(r"\bcompres\b", "compress", s, flags=re.IGNORECASE)
    s = re.sub(r"\bcomprss\b", "compress", s, flags=re.IGNORECASE)
    s = re.sub(r"\bsplt\b", "split", s, flags=re.IGNORECASE)
    s = re.sub(r"\bspllit\b", "split", s, flags=re.IGNORECASE)
    s = re.sub(r"\bmerg\b", "merge", s, flags=re.IGNORECASE)
    s = re.sub(r"\bconver\b", "convert", s, flags=re.IGNORECASE)
    s = re.sub(r"\bcnvert\b", "convert", s, flags=re.IGNORECASE)
    s = re.sub(r"\bcnvrt\b", "convert", s, flags=re.IGNORECASE)
    s = re.sub(r"\bconvrt\b", "convert", s, flags=re.IGNORECASE)
    return s


def _has_explicit_order_words(text: str) -> bool:
    return bool(re.search(r"\b(and then|then|after|before|first|second|finally)\b", text or "", re.IGNORECASE))


def _insert_missing_and_between_ops(text: str) -> str:
    """Turn shorthand like 'compress rotate 90' into 'compress and rotate 90'."""
    if not text:
        return text
    ops = r"(compress|merge|combine|join|split|extract|keep|delete|remove|convert|rotate|reorder|watermark|ocr|images?|docx|word|txt)"
    return re.sub(rf"\b{ops}\b\s+\b{ops}\b", r"\1 and \2", text, flags=re.IGNORECASE)


def _canonicalize_clause(clause: str) -> str:
    s = (clause or "").strip()
    if not s:
        return s
    lower = s.lower().strip()

    # Avoid nonsense like "compress 90 degrees" (degrees belong to rotate, not compress).
    if "compress" in lower and re.search(r"\b\d+\s*degrees?\b", lower):
        s = re.sub(r"\b\d+\s*degrees?\b", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s+", " ", s).strip(" ,.;")
        lower = s.lower().strip()
    if lower in {"png", "jpg", "jpeg"}:
        return f"export pages as {lower} images"
    if lower in {"docx", "word"}:
        return "convert to docx"
    if lower == "txt":
        return "extract text"
    if lower == "ocr":
        return "ocr this"

    # Rotate without explicit degrees: default to 90 (per spec)
    if re.search(r"\b(rotate|turn|straight|flip)\b", lower) and not re.search(r"-?\d+", lower):
        if re.search(r"\bflip\b", lower):
            return "rotate 180 degrees"
        return "rotate 90 degrees"
    return s


def _detect_op_families(text: str) -> set[str]:
    s = (text or "").lower()
    ops: set[str] = set()
    if re.search(r"\b(merge|combine|join)\b", s):
        ops.add("merge")
    if re.search(r"\b(split|extract|keep)\b", s):
        ops.add("split")
    if re.search(r"\b(delete|remove)\b", s):
        ops.add("delete")
    if re.search(r"\bcompress\b|\bsmaller\b|\bsize\b", s):
        ops.add("compress")
    if re.search(r"\breorder\b|\border\b|\bswap\b|\breverse\b", s):
        ops.add("reorder")
    if re.search(r"\bwatermark\b", s):
        ops.add("watermark")
    if re.search(r"\bpage\s*numbers\b|\bpage\s*number\b", s):
        ops.add("page_numbers")
    if re.search(r"\bocr\b|\bscanned\b|\bselectable\b|\beditable\b|\breadable\b", s):
        ops.add("ocr")
    if re.search(r"\brotate\b|\bturn\b|\bstraight\b|\bflip\b", s):
        ops.add("rotate")
    if re.search(r"\b(docx|word|convert)\b", s):
        ops.add("convert")
    if re.search(r"\b(png|jpg|jpeg|images?)\b", s):
        ops.add("images")
    if re.search(r"\bsplit\s*to\s*files\b|\beach\s*page\s*(as|into)\s*(a\s*)?pdf\b|\bseparate\s+pdfs\b", s):
        ops.add("split_to_files")
    if re.search(r"\bextract\s+text\b|\btext\s+only\b", s):
        ops.add("extract_text")
    return ops


def _split_clauses_no_order(user_prompt: str) -> list[str]:
    """Split a no-explicit-order prompt into rough operation clauses.

    Intended for prompts like "rotate 90 and watermark CONFIDENTIAL and compress".
    Keeps it conservative: split on ' and ' / commas.
    """
    s = _fix_common_connector_typos(user_prompt)
    s = _insert_missing_and_between_ops(s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return []
    # If explicit order words exist, don't split here.
    if _has_explicit_order_words(s):
        return []

    parts: list[str] = []
    # First split by comma, then by ' and '.
    for chunk in [c.strip() for c in s.split(",") if c.strip()]:
        sub = re.split(r"\band\b", chunk, flags=re.IGNORECASE)
        for p in sub:
            p = p.strip(" ,.;")
            if p:
                parts.append(p)

    # Cap to prevent crazy splits.
    return parts[:6]


def _clause_priority(clause: str, file_names: list[str]) -> int:
    """Lower runs earlier."""
    c = (clause or "").lower()
    # Hard-first
    if re.search(r"\bimages?_to_pdf\b|\b(images?)\s*(to|into)\s*pdf\b", c):
        return 0
    if re.search(r"\b(merge|combine|join)\b", c) and len(file_names) >= 2:
        return 1
    if re.search(r"\bocr\b", c):
        return 2

    # Structural edits
    if re.search(r"\b(delete|remove)\b", c):
        return 10
    if re.search(r"\b(split|extract|keep)\b", c):
        return 11
    if re.search(r"\breorder\b|\bswap\b", c):
        return 12
    if re.search(r"\brotate\b|\bturn\b|\bstraight\b|\bflip\b", c):
        return 13

    # Decorations
    if re.search(r"\bwatermark\b", c):
        return 20
    if re.search(r"\bpage\s*numbers?\b", c):
        return 21

    # Compression generally last among PDF-preserving ops
    if re.search(r"\bcompress\b", c):
        return 30

    # Terminal outputs (must be last)
    if re.search(r"\b(convert|docx|word)\b", c):
        return 90
    if re.search(r"\b(png|jpg|jpeg|images?)\b", c):
        return 91
    if re.search(r"\bextract\s+text\b|\btxt\b", c):
        return 92
    if re.search(r"\bsplit\s*to\s*files\b|\bseparate\s+pdfs\b", c):
        return 93

    return 50


def _terminal_type(clause: str) -> str | None:
    c = (clause or "").lower()
    if re.search(r"\b(convert|docx|word)\b", c):
        return "docx"
    if re.search(r"\b(png|jpg|jpeg|images?)\b", c):
        return "images"
    if re.search(r"\bextract\s+text\b|\btxt\b", c):
        return "text"
    if re.search(r"\bsplit\s*to\s*files\b|\bseparate\s+pdfs\b", c):
        return "zip"
    return None


def _auto_order_multi_op_no_order(user_prompt: str, file_names: list[str]) -> str | None:
    """Return a runnable ordered prompt for multi-op requests with no explicit order."""
    clauses = _split_clauses_no_order(user_prompt)
    if len(clauses) < 2:
        return None

    normalized = [_canonicalize_clause(c) for c in clauses]

    # If request implies multiple final outputs, we must ask which one.
    terminals = {}
    for c in normalized:
        t = _terminal_type(c)
        if t:
            terminals[t] = c
    if len(terminals) >= 2:
        # Provide runnable options by picking one terminal and dropping the others.
        options: list[str] = []
        for t, clause in terminals.items():
            others = [x for x in normalized if _terminal_type(x) is None]
            ordered = " and then ".join(sorted(others + [clause], key=lambda x: _clause_priority(x, file_names)))
            options.append(ordered)
        raise ValueError(
            "CLARIFICATION_NEEDED: Your request asks for multiple different final outputs. "
            "Pick one (click an option below)."
            + " | OPTIONS: "
            + json.dumps(options)
        )

    ordered_clauses = sorted(normalized, key=lambda x: _clause_priority(x, file_names))
    return " and then ".join(ordered_clauses)


def _is_order_clarification(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    return (
        ("which" in q and "first" in q and "operation" in q)
        or ("which" in q and "happen first" in q)
        or ("happen first" in q and "or" in q)
    )


def _extract_two_clauses_from_prompt(user_prompt: str) -> tuple[str, str] | None:
    s = _normalize_prompt_for_heuristics(_fix_common_connector_typos(user_prompt))
    s = _insert_missing_and_between_ops(s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None

    # If user already provided ordering words, we shouldn't be here.
    if re.search(r"\b(and then|then|after|before|first|second|finally)\b", s, re.IGNORECASE):
        return None

    # Common pattern: "A and B"
    parts = re.split(r"\band\b", s, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        a = parts[0].strip(" ,.;")
        b = parts[1].strip(" ,.;")
        if a and b:
            return a, b

    # Fallback: comma-separated
    parts = s.split(",", 1)
    if len(parts) == 2:
        a = parts[0].strip(" ,.;")
        b = parts[1].strip(" ,.;")
        if a and b:
            return a, b

    return None


def _maybe_order_ambiguity_options(user_prompt: str, file_names: list[str]) -> ClarificationResult | None:
    """If prompt contains 2+ operations with no explicit order, either infer order or ask once with clickable options."""
    fixed = _fix_common_connector_typos(user_prompt)
    probe = _insert_missing_and_between_ops(fixed)
    norm = _normalize_prompt_for_heuristics(probe)
    ops = _detect_op_families(norm)

    if len(ops) < 2:
        return None
    if _has_explicit_order_words(norm):
        return None

    # If a required slot is missing (pages), ask that FIRST.
    # This prevents repetitive "which first" loops when we still can't execute.
    if "split" in ops and not _extract_page_range_tokens(probe):
        return ClarificationResult(
            clarification="Which pages should I split/keep? (example: 1-3)",
            options=_options_for_pages_question("keep"),
        )
    if "delete" in ops and not _extract_page_range_tokens(probe):
        return ClarificationResult(
            clarification="Which pages should I delete? (example: 2,4-6)",
            options=_options_for_pages_question("delete"),
        )

    clauses = _extract_two_clauses_from_prompt(probe)

    # If user mixes rotate + compress with no explicit order, don't ask.
    # Decide: rotate first, compress last.
    if "rotate" in ops and "compress" in ops and len(ops) == 2 and file_names:
        rotate_clause = "rotate 90 degrees"
        compress_clause = "compress"
        if clauses:
            a, b = clauses
            a = _canonicalize_clause(a)
            b = _canonicalize_clause(b)
            if re.search(r"\b(rotate|turn|straight|flip)\b", a, re.IGNORECASE):
                rotate_clause, compress_clause = a, b
            elif re.search(r"\b(rotate|turn|straight|flip)\b", b, re.IGNORECASE):
                rotate_clause, compress_clause = b, a
            else:
                rotate_clause, compress_clause = "rotate 90 degrees", a

        r1 = clarify_intent(rotate_clause, file_names, last_question="", allow_multi=False)
        r2 = clarify_intent(compress_clause, file_names, last_question="", allow_multi=False)
        if r1.intent and r2.intent and not isinstance(r1.intent, list) and not isinstance(r2.intent, list):
            return ClarificationResult(intent=[r1.intent, r2.intent])

    # Strong defaults / forced ordering for compatibility
    # - Merge must be first when multiple PDFs are present.
    if "merge" in ops and len(file_names) >= 2:
        if clauses:
            a, b = clauses
            a = _canonicalize_clause(a)
            b = _canonicalize_clause(b)
            if re.search(r"\b(merge|combine|join)\b", a, re.IGNORECASE):
                ordered = f"{a} and then {b}"
            elif re.search(r"\b(merge|combine|join)\b", b, re.IGNORECASE):
                ordered = f"{b} and then {a}"
            else:
                ordered = f"merge and then {a}"
            try:
                intent = ai_parser.parse_intent(ordered, file_names)
                return ClarificationResult(intent=intent)
            except Exception:
                pass

    # - OCR should happen first if requested implicitly/explicitly.
    if "ocr" in ops and clauses:
        a, b = clauses
        a = _canonicalize_clause(a)
        b = _canonicalize_clause(b)
        if "ocr" in a.lower():
            ordered = f"{a} and then {b}"
        elif "ocr" in b.lower():
            ordered = f"{b} and then {a}"
        else:
            ordered = f"ocr this and then {a}"
        try:
            intent = ai_parser.parse_intent(ordered, file_names)
            return ClarificationResult(intent=intent)
        except Exception:
            pass

    # - If convert/images/extract is combined with compress, compress must be before convert/images.
    if "compress" in ops and ("convert" in ops or "images" in ops):
        if clauses:
            a, b = clauses
            a = _canonicalize_clause(a)
            b = _canonicalize_clause(b)
            a_low = a.lower()
            b_low = b.lower()
            a_is_compress = "compress" in a_low
            b_is_compress = "compress" in b_low
            if a_is_compress and not b_is_compress:
                ordered = f"{a} and then {b}"
            elif b_is_compress and not a_is_compress:
                ordered = f"{b} and then {a}"
            else:
                ordered = f"compress and then {a}"
            try:
                intent = ai_parser.parse_intent(ordered, file_names)
                return ClarificationResult(intent=intent)
            except Exception:
                pass

    # Default: when compress is combined with other operations and order is not explicit,
    # run the other operation(s) first and compress LAST.
    # This matches user expectation ("compress the final result") and avoids asking.
    if "compress" in ops and clauses:
        a, b = clauses
        a = _canonicalize_clause(a)
        b = _canonicalize_clause(b)
        a_low = a.lower()
        b_low = b.lower()
        a_is_compress = "compress" in a_low
        b_is_compress = "compress" in b_low
        if a_is_compress ^ b_is_compress:
            compress_clause = a if a_is_compress else b
            other_clause = b if a_is_compress else a
            ordered = f"{other_clause} and then {compress_clause}"
            # Prefer deterministic parsing to avoid LLM rate limits.
            fallback = _fallback_parse_two_step_pipeline(ordered, file_names)
            if fallback:
                return ClarificationResult(intent=fallback)
            try:
                intent = ai_parser.parse_intent(ordered, file_names)
                return ClarificationResult(intent=intent)
            except Exception:
                pass

    # Otherwise: ask ONCE with clickable options (only for 2-clause prompts).
    if clauses:
        a, b = clauses
        a = _canonicalize_clause(a)
        b = _canonicalize_clause(b)
        options = [f"{a} and then {b}", f"{b} and then {a}"]
        return ClarificationResult(
            clarification=(
                "Which should happen first? (click an option below)"
            ),
            options=options,
        )

    # If we can't split into two clauses but we see multiple ops, let the LLM handle it.
    return None


def _order_options_from_context(user_prompt: str, question: str) -> list[str] | None:
    # Prefer the actual prompt text because it contains parameters (e.g. rotate 90 degrees).
    clauses = _extract_two_clauses_from_prompt(user_prompt)
    if clauses:
        a, b = clauses
        return [f"{a} and then {b}", f"{b} and then {a}"]

    # Try to extract from the question itself.
    q = (question or "").strip()
    m = re.search(r"first[^\n]*?['\"]([^'\"]+)['\"][^\n]*?\bor\b\s*([^?\n]+)\??", q, re.IGNORECASE)
    if m:
        a = m.group(1).strip(" ,.;")
        b = m.group(2).strip(" ,.;")
        if a and b:
            # If the extracted bits are too short, don't emit.
            return [f"{a} and then {b}", f"{b} and then {a}"]

    return None


def _options_for_common_questions(question: str, user_prompt: str) -> list[str] | None:
    q = (question or "").lower()
    if not q:
        return None

    if _is_order_clarification(question):
        return _order_options_from_context(user_prompt, question)

    # Rotate degrees
    if "rotate" in q and "degree" in q:
        return ["rotate 90 degrees", "rotate 180 degrees", "rotate 270 degrees"]

    # Compress size
    if "compress" in q and ("mb" in q or "size" in q or "target" in q):
        return ["compress to 1mb", "compress to 2mb", "compress to 10mb"]

    # Split / pages
    if ("split" in q or "pages" in q or "page" in q) and ("which" in q or "what" in q):
        return ["keep pages 1", "keep pages 1-3", "keep pages 1-5"]

    return None

def clarify_intent(user_prompt: str, file_names: list[str], last_question: str = "", allow_multi: bool = True) -> ClarificationResult:
    """
    Try to parse the user's intent. Handle common patterns like 'compress to X MB', 'split 1st page', etc.
    If still ambiguous after pattern detection, provide helpful clarification.
    """
    
    # Optional context from the UI: helps interpret very short replies.
    # Also normalizes a few common corpus typos (e.g., compres/splt).
    user_prompt = _fix_common_connector_typos(user_prompt)
    prompt_for_match = _normalize_prompt_for_heuristics(user_prompt)
    prompt_compact = prompt_for_match.strip().lower()

    # Corpus-required strict behavior: if the user clearly requests an unsupported feature,
    # reply exactly with UNSUPPORTED_REPLY.
    if _is_explicitly_unsupported_request(prompt_for_match):
        return ClarificationResult(clarification=UNSUPPORTED_REPLY)

    # ============================================
    # HARDCODED REDUNDANCY & COMPATIBILITY GUARDS
    # Per spec: Never throw generic errors. Skip, auto-fix, or block with clear message.
    # Smart behavior: Convert valid cross-type operations automatically.
    # ============================================
    if file_names:
        primary = file_names[0]
        primary_lower = (primary or "").lower()
        is_image_file = primary_lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp'))
        is_pdf_file = primary_lower.endswith('.pdf')
        is_docx_file = primary_lower.endswith('.docx')
        all_images = all(f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp')) for f in file_names)
        all_pdfs = all(f.lower().endswith('.pdf') for f in file_names)
        num_files = len(file_names)
        
        # Detect user intent from prompt
        wants_to_image = bool(re.search(r"\b(to\s*img|to\s*image|to\s*images|to\s*png|to\s*jpe?g|as\s*png|as\s*jpe?g|export\s*(as\s*)?(png|jpe?g|images?))\b", prompt_compact))
        wants_to_pdf = bool(re.search(r"\b(to\s*pdf|as\s*pdf|convert\s*(to\s*)?pdf)\b", prompt_compact))
        wants_to_docx = bool(re.search(r"\b(to\s*docx|to\s*word|as\s*docx|as\s*word|convert\s*(to\s*)?(docx|word))\b", prompt_compact))
        wants_split = bool(re.search(r"\b(split|extract\s*page|keep\s*page)\b", prompt_compact))
        wants_delete_pages = bool(re.search(r"\b(delete\s*page|remove\s*page)\b", prompt_compact))
        wants_merge = bool(re.search(r"\b(merge|combine|join)\b", prompt_compact))
        wants_ocr = bool(re.search(r"\bocr\b", prompt_compact))
        wants_reorder = bool(re.search(r"\b(reorder|reverse|swap)\b", prompt_compact))
        wants_clean = bool(re.search(r"\b(clean|remove\s*(blank|duplicate)|blank\s*page|duplicate\s*page)\b", prompt_compact))
        wants_compress = bool(re.search(r"\b(compress|smaller|shrink|reduce\s*size|make\s*small|tiny)\b", prompt_compact))
        wants_rotate = bool(re.search(r"\b(rotate|turn|flip|straighten)\b", prompt_compact))
        wants_watermark = bool(re.search(r"\bwatermark\b", prompt_compact))
        wants_page_numbers = bool(re.search(r"\b(page\s*numbers?|number\s*pages?|add\s*numbers?)\b", prompt_compact))
        wants_enhance = bool(re.search(r"\b(enhance|improve|clarify|sharpen|clean\s*up|fix\s*scan)\b", prompt_compact))
        wants_flatten = bool(re.search(r"\b(flatten|sanitize|optimize)\b", prompt_compact))
        wants_extract_text = bool(re.search(r"\b(extract\s*text|to\s*txt|as\s*txt|text\s*only|get\s*text)\b", prompt_compact))
        
        # ========== MULTI-OPERATION COMBO DETECTION ==========
        # Detect when user wants multiple operations at once
        num_operations = sum([
            wants_merge, wants_split, wants_delete_pages, wants_compress, wants_rotate,
            wants_watermark, wants_page_numbers, wants_ocr, wants_enhance, wants_flatten,
            wants_clean, wants_reorder, wants_to_image, wants_to_docx, wants_extract_text
        ])
        
        # ========== PDF MULTI-OP PIPELINES ==========
        if is_pdf_file or all_pdfs:
            
            # PDF + merge + compress → Merge all → Compress
            if wants_merge and wants_compress and all_pdfs and num_files >= 2:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="merge",
                            merge={"operation": "merge", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + merge + watermark → Merge → Watermark
            if wants_merge and wants_watermark and all_pdfs and num_files >= 2:
                m = re.search(r"\bwatermark\b(?:\s+(?:with|text|as))?\s+(\S+)", user_prompt, re.IGNORECASE)
                text = (m.group(1).strip() if m else "").strip("\"'")
                if text:
                    return ClarificationResult(
                        intent=[
                            ParsedIntent(
                                operation_type="merge",
                                merge={"operation": "merge", "files": file_names},
                            ),
                            ParsedIntent(
                                operation_type="watermark",
                                watermark={"operation": "watermark", "file": primary, "text": text},
                            ),
                        ]
                    )
            
            # PDF + OCR + compress → OCR → Compress
            if wants_ocr and wants_compress and is_pdf_file:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + enhance + OCR → Enhance → OCR
            if wants_enhance and wants_ocr and is_pdf_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                    ]
                )
            
            # PDF + enhance + compress → Enhance → Compress
            if wants_enhance and wants_compress and is_pdf_file:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + rotate + compress → Rotate → Compress
            if wants_rotate and wants_compress and is_pdf_file:
                degrees = 90
                if re.search(r"\b(left|counter|anti)\b", prompt_compact):
                    degrees = 270
                elif re.search(r"\b180\b", prompt_compact):
                    degrees = 180
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="rotate",
                            rotate={"operation": "rotate", "file": primary, "degrees": degrees, "pages": None},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + flatten + compress → Flatten → Compress
            if wants_flatten and wants_compress and is_pdf_file:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + clean + compress → Clean → Compress
            if wants_clean and wants_compress and is_pdf_file:
                is_duplicate = bool(re.search(r"\bduplicate\b", prompt_compact))
                op_type = "remove_duplicate_pages" if is_duplicate else "remove_blank_pages"
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type=op_type,
                            **{op_type: {"operation": op_type, "file": primary}},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + watermark + compress → Watermark → Compress
            if wants_watermark and wants_compress and is_pdf_file:
                m = re.search(r"\bwatermark\b(?:\s+(?:with|text|as))?\s+(\S+)", user_prompt, re.IGNORECASE)
                text = (m.group(1).strip() if m else "").strip("\"'")
                if text:
                    preset = _infer_compress_preset(user_prompt)
                    return ClarificationResult(
                        intent=[
                            ParsedIntent(
                                operation_type="watermark",
                                watermark={"operation": "watermark", "file": primary, "text": text},
                            ),
                            ParsedIntent(
                                operation_type="compress",
                                compress={"operation": "compress", "file": primary, "preset": preset},
                            ),
                        ]
                    )
            
            # PDF + page numbers + compress → Page numbers → Compress
            if wants_page_numbers and wants_compress and is_pdf_file:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="page_numbers",
                            page_numbers={"operation": "page_numbers", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + split + compress → Split → Compress
            if wants_split and wants_compress and is_pdf_file:
                pages = _parse_page_ranges(user_prompt)
                if pages:
                    preset = _infer_compress_preset(user_prompt)
                    return ClarificationResult(
                        intent=[
                            ParsedIntent(
                                operation_type="split",
                                split={"operation": "split", "file": primary, "pages": pages},
                            ),
                            ParsedIntent(
                                operation_type="compress",
                                compress={"operation": "compress", "file": primary, "preset": preset},
                            ),
                        ]
                    )
            
            # PDF + watermark + page numbers → Watermark → Page numbers
            if wants_watermark and wants_page_numbers and is_pdf_file:
                m = re.search(r"\bwatermark\b(?:\s+(?:with|text|as))?\s+(\S+)", user_prompt, re.IGNORECASE)
                text = (m.group(1).strip() if m else "").strip("\"'")
                if text:
                    return ClarificationResult(
                        intent=[
                            ParsedIntent(
                                operation_type="watermark",
                                watermark={"operation": "watermark", "file": primary, "text": text},
                            ),
                            ParsedIntent(
                                operation_type="page_numbers",
                                page_numbers={"operation": "page_numbers", "file": primary},
                            ),
                        ]
                    )
            
            # PDF + rotate + split → Rotate → Split
            if wants_rotate and wants_split and is_pdf_file:
                pages = _parse_page_ranges(user_prompt)
                degrees = 90
                if re.search(r"\b(left|counter|anti)\b", prompt_compact):
                    degrees = 270
                elif re.search(r"\b180\b", prompt_compact):
                    degrees = 180
                if pages:
                    return ClarificationResult(
                        intent=[
                            ParsedIntent(
                                operation_type="rotate",
                                rotate={"operation": "rotate", "file": primary, "degrees": degrees, "pages": None},
                            ),
                            ParsedIntent(
                                operation_type="split",
                                split={"operation": "split", "file": primary, "pages": pages},
                            ),
                        ]
                    )
            
            # PDF + merge + OCR → Merge → OCR
            if wants_merge and wants_ocr and all_pdfs and num_files >= 2:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="merge",
                            merge={"operation": "merge", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                    ]
                )
            
            # PDF + merge + enhance → Merge → Enhance
            if wants_merge and wants_enhance and all_pdfs and num_files >= 2:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="merge",
                            merge={"operation": "merge", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                    ]
                )
            
            # PDF + merge + flatten → Merge → Flatten
            if wants_merge and wants_flatten and all_pdfs and num_files >= 2:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="merge",
                            merge={"operation": "merge", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                    ]
                )
            
            # PDF + merge + page numbers → Merge → Page Numbers
            if wants_merge and wants_page_numbers and all_pdfs and num_files >= 2:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="merge",
                            merge={"operation": "merge", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="page_numbers",
                            page_numbers={"operation": "page_numbers", "file": primary},
                        ),
                    ]
                )
            
            # PDF + merge + rotate → Merge → Rotate
            if wants_merge and wants_rotate and all_pdfs and num_files >= 2:
                degrees = 90
                if re.search(r"\b(left|counter|anti)\b", prompt_compact):
                    degrees = 270
                elif re.search(r"\b180\b", prompt_compact):
                    degrees = 180
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="merge",
                            merge={"operation": "merge", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="rotate",
                            rotate={"operation": "rotate", "file": primary, "degrees": degrees, "pages": None},
                        ),
                    ]
                )
            
            # PDF + merge + clean → Merge → Clean
            if wants_merge and wants_clean and all_pdfs and num_files >= 2:
                is_duplicate = bool(re.search(r"\bduplicate\b", prompt_compact))
                op_type = "remove_duplicate_pages" if is_duplicate else "remove_blank_pages"
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="merge",
                            merge={"operation": "merge", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type=op_type,
                            **{op_type: {"operation": op_type, "file": primary}},
                        ),
                    ]
                )
            
            # PDF + OCR + flatten → OCR → Flatten
            if wants_ocr and wants_flatten and is_pdf_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                    ]
                )
            
            # PDF + OCR + page numbers → OCR → Page Numbers
            if wants_ocr and wants_page_numbers and is_pdf_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="page_numbers",
                            page_numbers={"operation": "page_numbers", "file": primary},
                        ),
                    ]
                )
            
            # PDF + OCR + clean → OCR → Clean
            if wants_ocr and wants_clean and is_pdf_file:
                is_duplicate = bool(re.search(r"\bduplicate\b", prompt_compact))
                op_type = "remove_duplicate_pages" if is_duplicate else "remove_blank_pages"
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type=op_type,
                            **{op_type: {"operation": op_type, "file": primary}},
                        ),
                    ]
                )
            
            # PDF + OCR + rotate → OCR → Rotate
            if wants_ocr and wants_rotate and is_pdf_file:
                degrees = 90
                if re.search(r"\b(left|counter|anti)\b", prompt_compact):
                    degrees = 270
                elif re.search(r"\b180\b", prompt_compact):
                    degrees = 180
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="rotate",
                            rotate={"operation": "rotate", "file": primary, "degrees": degrees, "pages": None},
                        ),
                    ]
                )
            
            # PDF + clean + reorder → Clean → Reorder
            if wants_clean and wants_reorder and is_pdf_file:
                is_duplicate = bool(re.search(r"\bduplicate\b", prompt_compact))
                op_type = "remove_duplicate_pages" if is_duplicate else "remove_blank_pages"
                is_reverse = bool(re.search(r"\breverse\b", prompt_compact))
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type=op_type,
                            **{op_type: {"operation": op_type, "file": primary}},
                        ),
                        ParsedIntent(
                            operation_type="reorder",
                            reorder={"operation": "reorder", "file": primary, "new_order": "reverse" if is_reverse else None},
                        ),
                    ]
                )
            
            # PDF + clean + flatten → Clean → Flatten
            if wants_clean and wants_flatten and is_pdf_file:
                is_duplicate = bool(re.search(r"\bduplicate\b", prompt_compact))
                op_type = "remove_duplicate_pages" if is_duplicate else "remove_blank_pages"
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type=op_type,
                            **{op_type: {"operation": op_type, "file": primary}},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                    ]
                )
            
            # PDF + page numbers + flatten → Page Numbers → Flatten
            if wants_page_numbers and wants_flatten and is_pdf_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="page_numbers",
                            page_numbers={"operation": "page_numbers", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                    ]
                )
            
            # PDF + watermark + flatten → Watermark → Flatten
            if wants_watermark and wants_flatten and is_pdf_file:
                m = re.search(r"\bwatermark\b(?:\s+(?:with|text|as))?\s+(\S+)", user_prompt, re.IGNORECASE)
                text = (m.group(1).strip() if m else "").strip("\"'")
                if text:
                    return ClarificationResult(
                        intent=[
                            ParsedIntent(
                                operation_type="watermark",
                                watermark={"operation": "watermark", "file": primary, "text": text},
                            ),
                            ParsedIntent(
                                operation_type="flatten_pdf",
                                flatten_pdf={"operation": "flatten_pdf", "file": primary},
                            ),
                        ]
                    )
            
            # PDF + rotate + reorder → Rotate → Reorder
            if wants_rotate and wants_reorder and is_pdf_file:
                degrees = 90
                if re.search(r"\b(left|counter|anti)\b", prompt_compact):
                    degrees = 270
                elif re.search(r"\b180\b", prompt_compact):
                    degrees = 180
                is_reverse = bool(re.search(r"\breverse\b", prompt_compact))
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="rotate",
                            rotate={"operation": "rotate", "file": primary, "degrees": degrees, "pages": None},
                        ),
                        ParsedIntent(
                            operation_type="reorder",
                            reorder={"operation": "reorder", "file": primary, "new_order": "reverse" if is_reverse else None},
                        ),
                    ]
                )
            
            # ========== 3-STEP PDF PIPELINES ==========
            
            # PDF + enhance + OCR + compress → Enhance → OCR → Compress
            if wants_enhance and wants_ocr and wants_compress and is_pdf_file:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + clean + OCR + compress → Clean → OCR → Compress
            if wants_clean and wants_ocr and wants_compress and is_pdf_file:
                is_duplicate = bool(re.search(r"\bduplicate\b", prompt_compact))
                op_type = "remove_duplicate_pages" if is_duplicate else "remove_blank_pages"
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type=op_type,
                            **{op_type: {"operation": op_type, "file": primary}},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + merge + clean + compress → Merge → Clean → Compress
            if wants_merge and wants_clean and wants_compress and all_pdfs and num_files >= 2:
                is_duplicate = bool(re.search(r"\bduplicate\b", prompt_compact))
                op_type = "remove_duplicate_pages" if is_duplicate else "remove_blank_pages"
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="merge",
                            merge={"operation": "merge", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type=op_type,
                            **{op_type: {"operation": op_type, "file": primary}},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + merge + rotate + compress → Merge → Rotate → Compress
            if wants_merge and wants_rotate and wants_compress and all_pdfs and num_files >= 2:
                degrees = 90
                if re.search(r"\b(left|counter|anti)\b", prompt_compact):
                    degrees = 270
                elif re.search(r"\b180\b", prompt_compact):
                    degrees = 180
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="merge",
                            merge={"operation": "merge", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="rotate",
                            rotate={"operation": "rotate", "file": primary, "degrees": degrees, "pages": None},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + merge + OCR + compress → Merge → OCR → Compress
            if wants_merge and wants_ocr and wants_compress and all_pdfs and num_files >= 2:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="merge",
                            merge={"operation": "merge", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + OCR + page numbers + compress → OCR → Page Numbers → Compress
            if wants_ocr and wants_page_numbers and wants_compress and is_pdf_file:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="page_numbers",
                            page_numbers={"operation": "page_numbers", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + rotate + page numbers + compress → Rotate → Page Numbers → Compress
            if wants_rotate and wants_page_numbers and wants_compress and is_pdf_file:
                degrees = 90
                if re.search(r"\b(left|counter|anti)\b", prompt_compact):
                    degrees = 270
                elif re.search(r"\b180\b", prompt_compact):
                    degrees = 180
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="rotate",
                            rotate={"operation": "rotate", "file": primary, "degrees": degrees, "pages": None},
                        ),
                        ParsedIntent(
                            operation_type="page_numbers",
                            page_numbers={"operation": "page_numbers", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + merge + watermark + compress → Merge → Watermark → Compress
            if wants_merge and wants_watermark and wants_compress and all_pdfs and num_files >= 2:
                m = re.search(r"\bwatermark\b(?:\s+(?:with|text|as))?\s+(\S+)", user_prompt, re.IGNORECASE)
                text = (m.group(1).strip() if m else "").strip("\"'")
                if text:
                    preset = _infer_compress_preset(user_prompt)
                    return ClarificationResult(
                        intent=[
                            ParsedIntent(
                                operation_type="merge",
                                merge={"operation": "merge", "files": file_names},
                            ),
                            ParsedIntent(
                                operation_type="watermark",
                                watermark={"operation": "watermark", "file": primary, "text": text},
                            ),
                            ParsedIntent(
                                operation_type="compress",
                                compress={"operation": "compress", "file": primary, "preset": preset},
                            ),
                        ]
                    )
            
            # PDF + enhance + flatten + compress → Enhance → Flatten → Compress
            if wants_enhance and wants_flatten and wants_compress and is_pdf_file:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # PDF + clean + flatten + compress → Clean → Flatten → Compress (final pdf)
            if wants_clean and wants_flatten and wants_compress and is_pdf_file:
                is_duplicate = bool(re.search(r"\bduplicate\b", prompt_compact))
                op_type = "remove_duplicate_pages" if is_duplicate else "remove_blank_pages"
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type=op_type,
                            **{op_type: {"operation": op_type, "file": primary}},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
        
        # ========== IMAGE MULTI-OP PIPELINES ==========
        if is_image_file or all_images:
            
            # Images + merge/combine + compress → Images to PDF → Compress
            if (wants_merge or wants_to_pdf) and wants_compress and all_images:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # Images + combine + watermark → Images to PDF → Watermark
            if (wants_merge or wants_to_pdf) and wants_watermark and all_images:
                m = re.search(r"\bwatermark\b(?:\s+(?:with|text|as))?\s+(\S+)", user_prompt, re.IGNORECASE)
                text = (m.group(1).strip() if m else "").strip("\"'")
                if text:
                    return ClarificationResult(
                        intent=[
                            ParsedIntent(
                                operation_type="images_to_pdf",
                                images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                            ),
                            ParsedIntent(
                                operation_type="watermark",
                                watermark={"operation": "watermark", "file": primary, "text": text},
                            ),
                        ]
                    )
            
            # Images + combine + page numbers → Images to PDF → Page numbers
            if (wants_merge or wants_to_pdf) and wants_page_numbers and all_images:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="page_numbers",
                            page_numbers={"operation": "page_numbers", "file": primary},
                        ),
                    ]
                )
            
            # Image + enhance + OCR → Enhance → OCR
            if wants_enhance and wants_ocr and is_image_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                    ]
                )
            
            # Image + enhance + to PDF → Enhance → Images to PDF
            if wants_enhance and wants_to_pdf and is_image_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                    ]
                )
            
            # Image + enhance + compress → Enhance → to PDF → Compress
            if wants_enhance and wants_compress and is_image_file:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # Multiple images + combine + rotate → Images to PDF → Rotate
            if (wants_merge or wants_to_pdf) and wants_rotate and all_images:
                degrees = 90
                if re.search(r"\b(left|counter|anti)\b", prompt_compact):
                    degrees = 270
                elif re.search(r"\b180\b", prompt_compact):
                    degrees = 180
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="rotate",
                            rotate={"operation": "rotate", "file": primary, "degrees": degrees, "pages": None},
                        ),
                    ]
                )
            
            # Images + combine + OCR → Images to PDF → OCR
            if (wants_merge or wants_to_pdf) and wants_ocr and all_images:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                    ]
                )
            
            # Images + combine + flatten → Images to PDF → Flatten
            if (wants_merge or wants_to_pdf) and wants_flatten and all_images:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                    ]
                )
            
            # Image + OCR + compress → OCR → Compress
            if wants_ocr and wants_compress and is_image_file:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # Image + OCR + page numbers → OCR → Page Numbers
            if wants_ocr and wants_page_numbers and is_image_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="page_numbers",
                            page_numbers={"operation": "page_numbers", "file": primary},
                        ),
                    ]
                )
            
            # Image + OCR + flatten → OCR → Flatten
            if wants_ocr and wants_flatten and is_image_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                    ]
                )
            
            # Image + enhance + rotate → Enhance → Rotate
            if wants_enhance and wants_rotate and is_image_file:
                degrees = 90
                if re.search(r"\b(left|counter|anti)\b", prompt_compact):
                    degrees = 270
                elif re.search(r"\b180\b", prompt_compact):
                    degrees = 180
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="rotate",
                            rotate={"operation": "rotate", "file": primary, "degrees": degrees, "pages": None},
                        ),
                    ]
                )
            
            # ========== 3-STEP IMAGE PIPELINES ==========
            
            # Image + enhance + OCR + compress → Enhance → OCR → Compress
            if wants_enhance and wants_ocr and wants_compress and is_image_file:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # Images + combine + OCR + compress → Images to PDF → OCR → Compress
            if (wants_merge or wants_to_pdf) and wants_ocr and wants_compress and all_images:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # Images + combine + rotate + compress → Images to PDF → Rotate → Compress
            if (wants_merge or wants_to_pdf) and wants_rotate and wants_compress and all_images:
                degrees = 90
                if re.search(r"\b(left|counter|anti)\b", prompt_compact):
                    degrees = 270
                elif re.search(r"\b180\b", prompt_compact):
                    degrees = 180
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="rotate",
                            rotate={"operation": "rotate", "file": primary, "degrees": degrees, "pages": None},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # Image + enhance + OCR + page numbers → Enhance → OCR → Page Numbers
            if wants_enhance and wants_ocr and wants_page_numbers and is_image_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="page_numbers",
                            page_numbers={"operation": "page_numbers", "file": primary},
                        ),
                    ]
                )
            
            # Images + combine + watermark + compress → Images to PDF → Watermark → Compress
            if (wants_merge or wants_to_pdf) and wants_watermark and wants_compress and all_images:
                m = re.search(r"\bwatermark\b(?:\s+(?:with|text|as))?\s+(\S+)", user_prompt, re.IGNORECASE)
                text = (m.group(1).strip() if m else "").strip("\"'")
                if text:
                    preset = _infer_compress_preset(user_prompt)
                    return ClarificationResult(
                        intent=[
                            ParsedIntent(
                                operation_type="images_to_pdf",
                                images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                            ),
                            ParsedIntent(
                                operation_type="watermark",
                                watermark={"operation": "watermark", "file": primary, "text": text},
                            ),
                            ParsedIntent(
                                operation_type="compress",
                                compress={"operation": "compress", "file": primary, "preset": preset},
                            ),
                        ]
                    )
            
            # Image + OCR + rotate + compress → OCR → Rotate → Compress
            if wants_ocr and wants_rotate and wants_compress and is_image_file:
                degrees = 90
                if re.search(r"\b(left|counter|anti)\b", prompt_compact):
                    degrees = 270
                elif re.search(r"\b180\b", prompt_compact):
                    degrees = 180
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="rotate",
                            rotate={"operation": "rotate", "file": primary, "degrees": degrees, "pages": None},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
        
        # ========== DOCX MULTI-OP PIPELINES ==========
        if is_docx_file:
            
            # DOCX + to PDF + compress → DOCX to PDF → Compress
            if wants_to_pdf and wants_compress:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # DOCX + to PDF + watermark → DOCX to PDF → Watermark
            if wants_to_pdf and wants_watermark:
                m = re.search(r"\bwatermark\b(?:\s+(?:with|text|as))?\s+(\S+)", user_prompt, re.IGNORECASE)
                text = (m.group(1).strip() if m else "").strip("\"'")
                if text:
                    return ClarificationResult(
                        intent=[
                            ParsedIntent(
                                operation_type="docx_to_pdf",
                                docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                            ),
                            ParsedIntent(
                                operation_type="watermark",
                                watermark={"operation": "watermark", "file": primary, "text": text},
                            ),
                        ]
                    )
            
            # DOCX + to PDF + page numbers → DOCX to PDF → Page numbers
            if wants_to_pdf and wants_page_numbers:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="page_numbers",
                            page_numbers={"operation": "page_numbers", "file": primary},
                        ),
                    ]
                )
            
            # DOCX + to images + compress (3-step) → DOCX→PDF→Images (can't compress images in zip)
            # Just do the conversion
            if wants_to_image and wants_compress:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="pdf_to_images",
                            pdf_to_images={"operation": "pdf_to_images", "file": primary, "format": "jpg", "dpi": 100},
                        ),
                    ]
                )
            
            # DOCX + delete pages → DOCX to PDF → Delete
            if wants_delete_pages:
                pages = _parse_page_ranges(user_prompt)
                if pages:
                    return ClarificationResult(
                        intent=[
                            ParsedIntent(
                                operation_type="docx_to_pdf",
                                docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                            ),
                            ParsedIntent(
                                operation_type="delete",
                                delete={"operation": "delete", "file": primary, "pages_to_delete": pages},
                            ),
                        ]
                    )
                else:
                    return ClarificationResult(
                        clarification="Which pages do you want to delete? (Will convert to PDF first)",
                        options=["delete page 1", "delete pages 2-3", "delete last page"]
                    )
            
            # DOCX + to PDF + flatten → DOCX to PDF → Flatten
            if wants_to_pdf and wants_flatten:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                    ]
                )
            
            # DOCX + clean + compress → DOCX to PDF → Clean → Compress
            if wants_clean and wants_compress:
                is_duplicate = bool(re.search(r"\bduplicate\b", prompt_compact))
                op_type = "remove_duplicate_pages" if is_duplicate else "remove_blank_pages"
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type=op_type,
                            **{op_type: {"operation": op_type, "file": primary}},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # DOCX + enhance + compress → DOCX to PDF → Enhance → Compress
            if wants_enhance and wants_compress:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # ========== 3-STEP DOCX PIPELINES ==========
            
            # DOCX + to PDF + OCR + compress → DOCX to PDF → OCR → Compress
            if wants_to_pdf and wants_ocr and wants_compress:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # DOCX + to PDF + watermark + compress → DOCX to PDF → Watermark → Compress
            if wants_to_pdf and wants_watermark and wants_compress:
                m = re.search(r"\bwatermark\b(?:\s+(?:with|text|as))?\s+(\S+)", user_prompt, re.IGNORECASE)
                text = (m.group(1).strip() if m else "").strip("\"'")
                if text:
                    preset = _infer_compress_preset(user_prompt)
                    return ClarificationResult(
                        intent=[
                            ParsedIntent(
                                operation_type="docx_to_pdf",
                                docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                            ),
                            ParsedIntent(
                                operation_type="watermark",
                                watermark={"operation": "watermark", "file": primary, "text": text},
                            ),
                            ParsedIntent(
                                operation_type="compress",
                                compress={"operation": "compress", "file": primary, "preset": preset},
                            ),
                        ]
                    )
            
            # DOCX + to PDF + page numbers + compress → DOCX to PDF → Page Numbers → Compress
            if wants_to_pdf and wants_page_numbers and wants_compress:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="page_numbers",
                            page_numbers={"operation": "page_numbers", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            
            # DOCX + to PDF + flatten + compress → DOCX to PDF → Flatten → Compress
            if wants_to_pdf and wants_flatten and wants_compress:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
        
        # ========== REDUNDANCY GUARDS (skip if already that format) ==========
        
        # Image → to image (same format): Already an image
        if is_image_file and wants_to_image and not wants_to_pdf and not wants_compress:
            return ClarificationResult(clarification="Already an image")
        
        # PDF → to pdf (without any other operation): Already a PDF
        if is_pdf_file and wants_to_pdf and num_operations <= 1:
            return ClarificationResult(clarification="Already a PDF")
        
        # DOCX → to docx: Already a Word document
        if is_docx_file and wants_to_docx:
            return ClarificationResult(clarification="Already a Word document")
        
        # ========== AUTO-FIX: Smart cross-type conversions ==========
        
        # Images + merge → auto-convert to images_to_pdf (combine images into PDF)
        if wants_merge and all_images and num_files >= 1:
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="images_to_pdf",
                    images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                )
            )
        
        # Single/multiple images + "to pdf" → images_to_pdf
        if wants_to_pdf and all_images:
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="images_to_pdf",
                    images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                )
            )
        
        # DOCX + "to pdf" → docx_to_pdf
        if wants_to_pdf and is_docx_file:
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="docx_to_pdf",
                    docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                )
            )
        
        # Image + OCR → valid! OCR works on images (extract text from image)
        if wants_ocr and is_image_file:
            # Convert image to PDF first, then OCR - or just process directly
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="ocr",
                    ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                )
            )
        
        # Image + extract text → use OCR
        if wants_extract_text and is_image_file:
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="ocr",
                    ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                )
            )
        
        # Image + enhance → valid! Enhance scanned image
        if wants_enhance and is_image_file:
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="enhance_scan",
                    enhance_scan={"operation": "enhance_scan", "file": primary},
                )
            )
        
        # ========== AUTO MULTI-STEP OPERATIONS ==========
        # Instead of telling user "convert first, then...", just DO IT!
        
        # DOCX + to image → DOCX→PDF→Images (2 steps, auto)
        if wants_to_image and is_docx_file:
            return ClarificationResult(
                intent=[
                    ParsedIntent(
                        operation_type="docx_to_pdf",
                        docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                    ),
                    ParsedIntent(
                        operation_type="pdf_to_images",
                        pdf_to_images={"operation": "pdf_to_images", "file": primary, "format": "png", "dpi": 150},
                    ),
                ]
            )
        
        # DOCX + split → DOCX→PDF→Split (need pages)
        if wants_split and is_docx_file:
            pages = _parse_page_ranges(user_prompt)
            if pages:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="split",
                            split={"operation": "split", "file": primary, "pages": pages},
                        ),
                    ]
                )
            else:
                return ClarificationResult(
                    clarification="Which pages do you want after converting to PDF?",
                    options=["pages 1", "pages 1-3", "all pages as separate PDFs"]
                )
        
        # DOCX + compress → DOCX→PDF→Compress (auto)
        if wants_compress and is_docx_file:
            preset = _infer_compress_preset(user_prompt)
            return ClarificationResult(
                intent=[
                    ParsedIntent(
                        operation_type="docx_to_pdf",
                        docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                    ),
                    ParsedIntent(
                        operation_type="compress",
                        compress={"operation": "compress", "file": primary, "preset": preset},
                    ),
                ]
            )
        
        # DOCX + watermark → DOCX→PDF→Watermark (need text)
        if wants_watermark and is_docx_file:
            m = re.search(r"\bwatermark\b(?:\s+(?:with|text|as))?\s+(.+)$", user_prompt, re.IGNORECASE)
            text = (m.group(1).strip() if m else "").strip("\"'")
            if text:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="watermark",
                            watermark={"operation": "watermark", "file": primary, "text": text},
                        ),
                    ]
                )
            else:
                return ClarificationResult(
                    clarification="What watermark text? (Will convert DOCX to PDF first)",
                    options=["watermark CONFIDENTIAL", "watermark DRAFT"]
                )
        
        # DOCX + page numbers → DOCX→PDF→Page numbers (auto)
        if wants_page_numbers and is_docx_file:
            return ClarificationResult(
                intent=[
                    ParsedIntent(
                        operation_type="docx_to_pdf",
                        docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                    ),
                    ParsedIntent(
                        operation_type="page_numbers",
                        page_numbers={"operation": "page_numbers", "file": primary},
                    ),
                ]
            )
        
        # DOCX + reorder → DOCX→PDF→Reorder (need order)
        if wants_reorder and is_docx_file:
            m = re.search(r"\b(?:to|as)\b\s*([0-9,\s]+)", user_prompt, re.IGNORECASE)
            is_reverse = bool(re.search(r"\breverse\b", prompt_compact))
            if is_reverse:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="reorder",
                            reorder={"operation": "reorder", "file": primary, "new_order": "reverse"},
                        ),
                    ]
                )
            elif m:
                order = [int(x) for x in re.findall(r"\d+", m.group(1))]
                if order:
                    return ClarificationResult(
                        intent=[
                            ParsedIntent(
                                operation_type="docx_to_pdf",
                                docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                            ),
                            ParsedIntent(
                                operation_type="reorder",
                                reorder={"operation": "reorder", "file": primary, "new_order": order},
                            ),
                        ]
                    )
            return ClarificationResult(
                clarification="What page order after converting to PDF? (example: 2,1,3)",
                options=["reverse all pages", "reorder to 2,1,3"]
            )
        
        # DOCX + flatten → DOCX→PDF→Flatten (auto)
        if wants_flatten and is_docx_file:
            return ClarificationResult(
                intent=[
                    ParsedIntent(
                        operation_type="docx_to_pdf",
                        docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                    ),
                    ParsedIntent(
                        operation_type="flatten_pdf",
                        flatten_pdf={"operation": "flatten_pdf", "file": primary},
                    ),
                ]
            )
        
        # DOCX + clean → DOCX→PDF→Clean (auto)
        if wants_clean and is_docx_file:
            is_duplicate = bool(re.search(r"\bduplicate\b", prompt_compact))
            op_type = "remove_duplicate_pages" if is_duplicate else "remove_blank_pages"
            return ClarificationResult(
                intent=[
                    ParsedIntent(
                        operation_type="docx_to_pdf",
                        docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                    ),
                    ParsedIntent(
                        operation_type=op_type,
                        **{op_type: {"operation": op_type, "file": primary}},
                    ),
                ]
            )
        
        # Image + watermark → Image→PDF→Watermark
        if wants_watermark and is_image_file:
            m = re.search(r"\bwatermark\b(?:\s+(?:with|text|as))?\s+(.+)$", user_prompt, re.IGNORECASE)
            text = (m.group(1).strip() if m else "").strip("\"'")
            if text:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="watermark",
                            watermark={"operation": "watermark", "file": primary, "text": text},
                        ),
                    ]
                )
            else:
                return ClarificationResult(
                    clarification="What watermark text? (Will convert image to PDF first)",
                    options=["watermark CONFIDENTIAL", "watermark DRAFT"]
                )
        
        # Image + page numbers → Image→PDF→Page numbers
        if wants_page_numbers and is_image_file:
            return ClarificationResult(
                intent=[
                    ParsedIntent(
                        operation_type="images_to_pdf",
                        images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                    ),
                    ParsedIntent(
                        operation_type="page_numbers",
                        page_numbers={"operation": "page_numbers", "file": primary},
                    ),
                ]
            )
        
        # Image + compress → Image→PDF→Compress
        if wants_compress and is_image_file:
            preset = _infer_compress_preset(user_prompt)
            return ClarificationResult(
                intent=[
                    ParsedIntent(
                        operation_type="images_to_pdf",
                        images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                    ),
                    ParsedIntent(
                        operation_type="compress",
                        compress={"operation": "compress", "file": primary, "preset": preset},
                    ),
                ]
            )
        
        # Image + rotate → Image→PDF→Rotate
        if wants_rotate and is_image_file:
            degrees = 90  # default
            if re.search(r"\b(left|counter|anti)\b", prompt_compact):
                degrees = 270
            elif re.search(r"\b180\b", prompt_compact):
                degrees = 180
            elif re.search(r"\b270\b", prompt_compact):
                degrees = 270
            return ClarificationResult(
                intent=[
                    ParsedIntent(
                        operation_type="images_to_pdf",
                        images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                    ),
                    ParsedIntent(
                        operation_type="rotate",
                        rotate={"operation": "rotate", "file": primary, "degrees": degrees, "pages": None},
                    ),
                ]
            )
        
        # Image + flatten → Image→PDF→Flatten
        if wants_flatten and is_image_file:
            return ClarificationResult(
                intent=[
                    ParsedIntent(
                        operation_type="images_to_pdf",
                        images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                    ),
                    ParsedIntent(
                        operation_type="flatten_pdf",
                        flatten_pdf={"operation": "flatten_pdf", "file": primary},
                    ),
                ]
            )
        
        # Multiple images + reorder → combine into PDF with specific order
        if wants_reorder and all_images and num_files > 1:
            is_reverse = bool(re.search(r"\breverse\b", prompt_compact))
            if is_reverse:
                # Reverse the file order and combine
                reversed_files = list(reversed(file_names))
                return ClarificationResult(
                    intent=ParsedIntent(
                        operation_type="images_to_pdf",
                        images_to_pdf={"operation": "images_to_pdf", "files": reversed_files},
                    )
                )
            return ClarificationResult(
                clarification="What order should the images be combined into PDF? (example: 2,1,3)",
                options=["combine as uploaded order", "reverse order"]
            )
        
        # ========== NATURAL LANGUAGE SHORTCUTS ==========
        # Handle common phrases users say without being explicit
        
        # "email ready" / "send by email" → compress for email
        wants_email_ready = bool(re.search(r"\b(email\s*ready|for\s*email|send\s*(by\s*)?email|email\s*size)\b", prompt_compact))
        if wants_email_ready:
            if is_pdf_file:
                return ClarificationResult(
                    intent=ParsedIntent(
                        operation_type="compress",
                        compress={"operation": "compress", "file": primary, "preset": "strong"},
                    )
                )
            elif is_docx_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "strong"},
                        ),
                    ]
                )
            elif is_image_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "strong"},
                        ),
                    ]
                )
        
        # "fix this scan" / "fix scanned" → enhance + OCR
        wants_fix_scan = bool(re.search(r"\b(fix\s*(this\s*)?scan|fix\s*scanned|clean\s*scan)\b", prompt_compact))
        if wants_fix_scan:
            if is_pdf_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                    ]
                )
            elif is_image_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                    ]
                )
        
        # "print ready" / "for printing" → flatten (remove fillable elements)
        wants_print_ready = bool(re.search(r"\b(print\s*ready|for\s*print|printing)\b", prompt_compact))
        if wants_print_ready:
            if is_pdf_file:
                return ClarificationResult(
                    intent=ParsedIntent(
                        operation_type="flatten_pdf",
                        flatten_pdf={"operation": "flatten_pdf", "file": primary},
                    )
                )
            elif is_docx_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                    ]
                )
            elif is_image_file:
                return ClarificationResult(
                    intent=ParsedIntent(
                        operation_type="images_to_pdf",
                        images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                    )
                )
        
        # "make searchable" → OCR
        wants_searchable = bool(re.search(r"\b(make\s*searchable|searchable\s*pdf|text\s*searchable)\b", prompt_compact))
        if wants_searchable:
            if is_pdf_file or is_image_file:
                return ClarificationResult(
                    intent=ParsedIntent(
                        operation_type="ocr",
                        ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                    )
                )
        
        # "secure pdf" / "protect pdf" → flatten (removes editable content)
        wants_secure = bool(re.search(r"\b(secure|protect|sanitize)\s*pdf\b", prompt_compact))
        if wants_secure and is_pdf_file:
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="flatten_pdf",
                    flatten_pdf={"operation": "flatten_pdf", "file": primary},
                )
            )
        
        # "optimize file" / "optimize pdf" → Clean → Compress
        wants_optimize = bool(re.search(r"\b(optimize\s*(file|pdf)?|optimise)\b", prompt_compact))
        if wants_optimize:
            if is_pdf_file:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="remove_blank_pages",
                            remove_blank_pages={"operation": "remove_blank_pages", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            elif is_docx_file:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
        
        # "final version" / "final pdf" → Clean → Flatten → Compress
        wants_final = bool(re.search(r"\b(final\s*(version|pdf|copy)?|finalize)\b", prompt_compact))
        if wants_final:
            if is_pdf_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="remove_blank_pages",
                            remove_blank_pages={"operation": "remove_blank_pages", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "balanced"},
                        ),
                    ]
                )
            elif is_docx_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "balanced"},
                        ),
                    ]
                )
        
        # "submission ready" / "college submission" → OCR → Compress
        wants_submission = bool(re.search(r"\b(submission\s*ready|college\s*submission|submit|assignment)\b", prompt_compact))
        if wants_submission:
            if is_pdf_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "balanced"},
                        ),
                    ]
                )
            elif is_image_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "balanced"},
                        ),
                    ]
                )
            elif is_docx_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "balanced"},
                        ),
                    ]
                )
        
        # "archive ready" / "for archive" → Flatten → Compress
        wants_archive = bool(re.search(r"\b(archive\s*ready|for\s*archive|archiving)\b", prompt_compact))
        if wants_archive:
            if is_pdf_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "balanced"},
                        ),
                    ]
                )
            elif is_docx_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "balanced"},
                        ),
                    ]
                )
        
        # "whatsapp size" / "whatsapp ready" → Compress (very strong)
        wants_whatsapp = bool(re.search(r"\b(whatsapp|wa)\s*(size|ready)?\b", prompt_compact))
        if wants_whatsapp:
            if is_pdf_file:
                return ClarificationResult(
                    intent=ParsedIntent(
                        operation_type="compress",
                        compress={"operation": "compress", "file": primary, "preset": "strong"},
                    )
                )
            elif is_docx_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "strong"},
                        ),
                    ]
                )
            elif is_image_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "strong"},
                        ),
                    ]
                )
        
        # "govt submission" / "government" → OCR → Flatten
        wants_govt = bool(re.search(r"\b(govt|government)\s*(submission)?\b", prompt_compact))
        if wants_govt:
            if is_pdf_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                    ]
                )
            elif is_image_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                    ]
                )
        
        # "scan quality fix" / "improve scan quality" → Enhance → OCR
        wants_scan_quality = bool(re.search(r"\b(scan\s*quality|quality\s*fix|improve\s*scan)\b", prompt_compact))
        if wants_scan_quality:
            if is_pdf_file or is_image_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="ocr",
                            ocr={"operation": "ocr", "file": primary, "language": "eng", "deskew": True},
                        ),
                    ]
                )
        
        # "make it neat" / "clean up" → Clean → Enhance
        wants_neat = bool(re.search(r"\b(make\s*it\s*neat|neat\s*up|tidy)\b", prompt_compact))
        if wants_neat:
            if is_pdf_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="remove_blank_pages",
                            remove_blank_pages={"operation": "remove_blank_pages", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="enhance_scan",
                            enhance_scan={"operation": "enhance_scan", "file": primary},
                        ),
                    ]
                )
        
        # "make professional" → Clean → Flatten → Compress
        wants_professional = bool(re.search(r"\b(make\s*professional|professional\s*(copy|version)?|look\s*professional)\b", prompt_compact))
        if wants_professional:
            if is_pdf_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="remove_blank_pages",
                            remove_blank_pages={"operation": "remove_blank_pages", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "balanced"},
                        ),
                    ]
                )
            elif is_docx_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="flatten_pdf",
                            flatten_pdf={"operation": "flatten_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "balanced"},
                        ),
                    ]
                )
        
        # "sendable file" / "shareable" → Compress
        wants_sendable = bool(re.search(r"\b(sendable|shareable|share\s*ready)\b", prompt_compact))
        if wants_sendable:
            if is_pdf_file:
                return ClarificationResult(
                    intent=ParsedIntent(
                        operation_type="compress",
                        compress={"operation": "compress", "file": primary, "preset": "balanced"},
                    )
                )
            elif is_docx_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "balanced"},
                        ),
                    ]
                )
            elif is_image_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "balanced"},
                        ),
                    ]
                )
        
        # "convert and shrink" / "convert & compress" → Convert → Compress
        wants_convert_shrink = bool(re.search(r"\b(convert\s*(and|&)\s*(shrink|compress|smaller))\b", prompt_compact))
        if wants_convert_shrink:
            if is_docx_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "balanced"},
                        ),
                    ]
                )
            elif is_image_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "balanced"},
                        ),
                    ]
                )
        
        # "scan to pdf" → Images to PDF (if images) or just pass through
        wants_scan_to_pdf = bool(re.search(r"\bscan\s*to\s*pdf\b", prompt_compact))
        if wants_scan_to_pdf:
            if is_image_file or all_images:
                return ClarificationResult(
                    intent=ParsedIntent(
                        operation_type="images_to_pdf",
                        images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                    )
                )
        
        # "combine and fix" / "merge and clean" → Merge → Clean
        wants_combine_fix = bool(re.search(r"\b(combine\s*(and|&)\s*fix|merge\s*(and|&)\s*clean)\b", prompt_compact))
        if wants_combine_fix and all_pdfs and num_files >= 2:
            return ClarificationResult(
                intent=[
                    ParsedIntent(
                        operation_type="merge",
                        merge={"operation": "merge", "files": file_names},
                    ),
                    ParsedIntent(
                        operation_type="remove_blank_pages",
                        remove_blank_pages={"operation": "remove_blank_pages", "file": primary},
                    ),
                ]
            )
        
        # "combine and shrink" / "merge and compress" → Merge → Compress
        wants_combine_shrink = bool(re.search(r"\b(combine\s*(and|&)\s*(shrink|compress)|merge\s*(and|&)\s*(shrink|compress))\b", prompt_compact))
        if wants_combine_shrink:
            if all_pdfs and num_files >= 2:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="merge",
                            merge={"operation": "merge", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
            elif all_images:
                preset = _infer_compress_preset(user_prompt)
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": preset},
                        ),
                    ]
                )
        
        # "fix orientation" / "fix rotation" → Rotate
        wants_fix_orientation = bool(re.search(r"\b(fix\s*(orientation|rotation)|orientation\s*fix)\b", prompt_compact))
        if wants_fix_orientation:
            if is_pdf_file:
                return ClarificationResult(
                    intent=ParsedIntent(
                        operation_type="rotate",
                        rotate={"operation": "rotate", "file": primary, "degrees": 90, "pages": None},
                    )
                )
            elif is_image_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="images_to_pdf",
                            images_to_pdf={"operation": "images_to_pdf", "files": file_names},
                        ),
                        ParsedIntent(
                            operation_type="rotate",
                            rotate={"operation": "rotate", "file": primary, "degrees": 90, "pages": None},
                        ),
                    ]
                )
        
        # "remove extra pages" / "extra pages" → Clean (remove blank)
        wants_remove_extra = bool(re.search(r"\b(remove\s*extra|extra\s*pages?|unwanted\s*pages?)\b", prompt_compact))
        if wants_remove_extra:
            if is_pdf_file:
                return ClarificationResult(
                    intent=ParsedIntent(
                        operation_type="remove_blank_pages",
                        remove_blank_pages={"operation": "remove_blank_pages", "file": primary},
                    )
                )
        
        # "mobile optimized" / "for mobile" → Compress (strong)
        wants_mobile = bool(re.search(r"\b(mobile\s*(optimized?|ready)?|for\s*mobile|phone\s*size)\b", prompt_compact))
        if wants_mobile:
            if is_pdf_file:
                return ClarificationResult(
                    intent=ParsedIntent(
                        operation_type="compress",
                        compress={"operation": "compress", "file": primary, "preset": "strong"},
                    )
                )
            elif is_docx_file:
                return ClarificationResult(
                    intent=[
                        ParsedIntent(
                            operation_type="docx_to_pdf",
                            docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                        ),
                        ParsedIntent(
                            operation_type="compress",
                            compress={"operation": "compress", "file": primary, "preset": "strong"},
                        ),
                    ]
                )
        
        # ========== TRULY INCOMPATIBLE (no workaround) ==========
        
        # Split single image: Images don't have pages
        if wants_split and is_image_file:
            return ClarificationResult(clarification="Images don't have pages to split. Upload a multi-page PDF instead.")
        
        # OCR: DOCX is already text-based
        if wants_ocr and is_docx_file:
            return ClarificationResult(clarification="DOCX is already text-based — no OCR needed!")
        
        # Reorder single image: Need multiple files or multi-page PDF
        if wants_reorder and is_image_file and num_files == 1:
            return ClarificationResult(clarification="Upload multiple images to reorder and combine into PDF")
        
        # Clean single image: Need multi-page document
        if wants_clean and is_image_file:
            return ClarificationResult(clarification="Upload a multi-page PDF to remove blank/duplicate pages")
        
        # Mixed file types in merge
        if wants_merge and not all_pdfs and not all_images and num_files > 1:
            return ClarificationResult(clarification="Upload either all PDFs or all images to merge")
        
        # Extract text from DOCX: Already text
        if wants_extract_text and is_docx_file:
            return ClarificationResult(clarification="DOCX is already a text document — just open it!")
        
        # Enhance DOCX: Not applicable
        if wants_enhance and is_docx_file:
            return ClarificationResult(clarification="Enhance is for scanned documents. DOCX is already clear text.")
        
        # Single file + merge: Need at least 2 files
        if wants_merge and num_files == 1:
            if is_pdf_file:
                return ClarificationResult(clarification="Upload at least 2 PDFs to merge")
            if is_image_file:
                return ClarificationResult(clarification="Upload more images to combine, or just say 'to pdf'")
            if is_docx_file:
                return ClarificationResult(clarification="Upload multiple files to merge")
        
        # Image to DOCX → suggest OCR
        if wants_to_docx and is_image_file:
            return ClarificationResult(
                clarification="To extract text from image, try 'OCR' which creates a searchable PDF with embedded text",
                options=["OCR this image"]
            )

    # ============================================
    # END HARDCODED GUARDS
    # ============================================

    # Deterministic convert shortcuts for common ambiguous phrasing.
    # These improve reliability (and reduce LLM calls) for corpus-style commands.
    if file_names:
        primary = file_names[0]
        primary_lower = (primary or "").lower()
        wants_convert = bool(re.search(r"\b(convert|change)\b", prompt_for_match, re.IGNORECASE))
        wants_word = bool(re.search(r"\b(word|docx|doc)\b", prompt_for_match, re.IGNORECASE))
        wants_pdf = bool(re.search(r"\bpdf\b", prompt_for_match, re.IGNORECASE))
        wants_images = bool(re.search(r"\b(images?|img|png|jpe?g)\b", prompt_for_match, re.IGNORECASE))

        # DOCX → PDF
        if wants_convert and wants_pdf and primary_lower.endswith(".docx"):
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="docx_to_pdf",
                    docx_to_pdf={"operation": "docx_to_pdf", "file": primary},
                )
            )

        # PDF → DOCX
        if wants_convert and wants_word and primary_lower.endswith(".pdf"):
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="pdf_to_docx",
                    pdf_to_docx={"operation": "pdf_to_docx", "file": primary},
                )
            )

        # PDF → Images
        if wants_convert and wants_images and primary_lower.endswith(".pdf"):
            fmt = "png"
            if re.search(r"\bjpe?g\b|\bjpg\b", prompt_for_match, re.IGNORECASE):
                fmt = "jpg"
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="pdf_to_images",
                    pdf_to_images={
                        "operation": "pdf_to_images",
                        "file": primary,
                        "format": fmt,
                        "dpi": 150,
                    },
                )
            )

    # If user answered with only a number and the last question was about degrees, treat as rotation.
    if (
        file_names
        and re.fullmatch(r"-?\d+", prompt_compact)
        and "degree" in (last_question or "").lower()
        and "rotate" in (last_question or "").lower()
    ):
        prompt_for_match = f"rotate {prompt_compact} degrees"
        prompt_compact = prompt_for_match

    # One-shot multi-op ambiguity handling (order): infer whenever possible.
    if allow_multi:
        # First: generic auto-ordering for no-explicit-order multi-op prompts.
        try:
            auto_ordered = _auto_order_multi_op_no_order(user_prompt, file_names)
            if auto_ordered:
                user_prompt = auto_ordered
                prompt_for_match = _normalize_prompt_for_heuristics(user_prompt)
                prompt_compact = prompt_for_match.strip().lower()
        except ValueError as e:
            msg = str(e)
            if "CLARIFICATION_NEEDED:" in msg:
                parts = msg.split(" | OPTIONS: ")
                clarification = parts[0].replace("CLARIFICATION_NEEDED: ", "")
                options = None
                if len(parts) > 1:
                    try:
                        options = json.loads(parts[1])
                    except:
                        options = None
                return ClarificationResult(clarification=clarification, options=options)
            # otherwise ignore and continue

        # Only ask order if auto-ordering didn't already resolve it.
        if not _has_explicit_order_words(user_prompt):
            order_result = _maybe_order_ambiguity_options(user_prompt, file_names)
            if order_result is not None:
                return order_result

    # Format-only prompts (very common): "png", "jpg", "docx", "txt", "ocr", "img"
    # Prefer executing rather than asking "convert to what?".
    # Note: "to img" with image files is caught by redundancy guards above ("Already an image")
    if file_names and prompt_compact in {"png", "jpg", "jpeg", "img", "to img", "to image", "to images"}:
        file_name = file_names[0]
        file_lower = file_name.lower()
        
        # If the file is already an image, the redundancy guard above catches "to img" cases.
        # For bare "png"/"jpg"/"img" with image files, also return "Already an image"
        if file_lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp')):
            return ClarificationResult(clarification="Already an image")
        
        # Determine output format - default to png for "img"/"to img" etc
        output_format = "png"
        if prompt_compact in {"jpg", "jpeg"}:
            output_format = "jpg"
        elif prompt_compact == "png":
            output_format = "png"
        
        return ClarificationResult(
            intent=ParsedIntent(
                operation_type="pdf_to_images",
                pdf_to_images={
                    "operation": "pdf_to_images",
                    "file": file_name,
                    "format": output_format,
                    "dpi": 150,
                },
            )
        )

    if file_names and prompt_compact in {"docx", "word"}:
        file_name = file_names[0]
        return ClarificationResult(
            intent=ParsedIntent(
                operation_type="pdf_to_docx",
                pdf_to_docx={"operation": "pdf_to_docx", "file": file_name},
            )
        )

    if file_names and prompt_compact == "txt":
        file_name = file_names[0]
        return ClarificationResult(
            intent=ParsedIntent(
                operation_type="extract_text",
                extract_text={"operation": "extract_text", "file": file_name, "pages": None},
            )
        )

    if file_names and prompt_compact == "ocr":
        file_name = file_names[0]
        return ClarificationResult(
            intent=ParsedIntent(
                operation_type="ocr",
                ocr={"operation": "ocr", "file": file_name, "language": "eng", "deskew": True},
            )
        )

    # Single-op heuristics that should NOT hijack multi-op prompts.
    # These are also used by deterministic clause parsing (allow_multi=False).
    if (not allow_multi) or (not _looks_like_multi_operation_prompt(user_prompt)):
        # Pattern: merge/combine/join
        if len(file_names) >= 2 and re.search(r"\b(merge|combine|join)\b", prompt_for_match, re.IGNORECASE):
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="merge",
                    merge={"operation": "merge", "files": file_names},
                )
            )

        # Pattern: delete/remove pages
        if file_names and re.search(r"\b(delete|remove)\b", prompt_for_match, re.IGNORECASE):
            pages = _parse_page_ranges(user_prompt)
            if not pages:
                return ClarificationResult(
                    clarification="Which pages should I delete? (example: 2,4-6)",
                    options=_options_for_pages_question("delete"),
                )
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="delete",
                    delete={"operation": "delete", "file": file_names[0], "pages_to_delete": pages},
                )
            )

        # Pattern: reorder/reverse pages to ...
        if file_names and re.search(r"\breorder\b|\bswap\b|\breverse\b", prompt_for_match, re.IGNORECASE):
            is_reverse = bool(re.search(r"\breverse\b", prompt_for_match, re.IGNORECASE))
            m = re.search(r"\b(?:to|as)\b\s*([0-9,\s]+)", user_prompt, re.IGNORECASE)
            
            # If user said "reverse" without specific order, return intent with special marker
            if is_reverse and not m:
                return ClarificationResult(
                    intent=ParsedIntent(
                        operation_type="reorder",
                        reorder={"operation": "reorder", "file": file_names[0], "new_order": "reverse"},
                    )
                )
            
            if not m:
                return ClarificationResult(
                    clarification="What is the new page order? (example: 2,1,3)",
                    options=["reorder pages to 2,1,3", "reverse all pages"],
                )
            order = [int(x) for x in re.findall(r"\d+", m.group(1))]
            if not order:
                return ClarificationResult(
                    clarification="What is the new page order? (example: 2,1,3)",
                    options=["reorder pages to 2,1,3", "reverse all pages"],
                )
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="reorder",
                    reorder={"operation": "reorder", "file": file_names[0], "new_order": order},
                )
            )

        # Pattern: watermark ...
        if file_names and re.search(r"\bwatermark\b", prompt_for_match, re.IGNORECASE):
            m = re.search(r"\bwatermark\b(?:\s+(?:with|text|as))?\s+(.+)$", user_prompt, re.IGNORECASE)
            text = (m.group(1).strip() if m else "").strip("\"'")
            if not text:
                return ClarificationResult(
                    clarification="What watermark text should I add?",
                    options=["watermark CONFIDENTIAL", "watermark DRAFT"],
                )
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="watermark",
                    watermark={"operation": "watermark", "file": file_names[0], "text": text},
                )
            )

        # Pattern: add page numbers
        if file_names and re.search(r"\bpage\s*numbers?\b|\bnumber\s*pages\b", prompt_for_match, re.IGNORECASE):
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="page_numbers",
                    page_numbers={"operation": "page_numbers", "file": file_names[0]},
                )
            )

        # Pattern: split to files / separate PDFs (zipped)
        if file_names and re.search(r"\bsplit\s*to\s*files\b|\bseparate\s+pdfs\b|\beach\s+page\b", prompt_for_match, re.IGNORECASE):
            pages = _parse_page_ranges(user_prompt)
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="split_to_files",
                    split_to_files={"operation": "split_to_files", "file": file_names[0], "pages": (pages or None)},
                )
            )

    # If this looks like a multi-step request, let the LLM produce a pipeline plan.
    # This avoids regex shortcuts accidentally collapsing multi-op prompts into a single op.
    if allow_multi and _looks_like_multi_operation_prompt(user_prompt):
        try:
            intent = ai_parser.parse_intent(user_prompt, file_names)
            return ClarificationResult(intent=intent)
        except ValueError as e:
            error_msg = str(e)
            if "CLARIFICATION_NEEDED:" in error_msg:
                parts = error_msg.split(" | OPTIONS: ")
                clarification = parts[0].replace("CLARIFICATION_NEEDED: ", "")
                options = None
                if len(parts) > 1:
                    try:
                        options = json.loads(parts[1])
                    except:
                        pass

                # Ensure order questions always provide full, runnable options.
                if _is_order_clarification(clarification):
                    fallback = _order_options_from_context(user_prompt, clarification)
                    if fallback:
                        options = fallback

                # Add options for common slot questions (degrees/pages/size)
                if not options:
                    options = _options_for_common_questions(clarification, user_prompt)
                print(f"[AI] Requesting clarification: {clarification}")
                return ClarificationResult(clarification=clarification, options=options)

            # If LLM returned an unsupported op schema, enforce corpus reply.
            if _is_likely_unsupported_validation_error(error_msg) or _is_explicitly_unsupported_request(prompt_for_match):
                return ClarificationResult(clarification=UNSUPPORTED_REPLY)

            # Non-clarification failure: fall back to deterministic 2-step parsing
            # so common clickable options like "rotate 90 degrees and then compress" still work.
            # Broader deterministic fallback for 2+ steps.
            fallback_multi = _fallback_parse_multi_step_pipeline(user_prompt, file_names)
            if fallback_multi:
                return ClarificationResult(intent=fallback_multi)

            fallback_pipeline = _fallback_parse_two_step_pipeline(user_prompt, file_names)
            if fallback_pipeline:
                return ClarificationResult(intent=fallback_pipeline)

            return ClarificationResult(
                clarification=(
                    "Sorry, I couldn't fully understand the multi-step request. "
                    "Try adding an explicit order like: 'split pages 1-2 and then compress to 2MB'."
                )
            )

    # Pattern 1: "compress to X MB" or "compress to XMB"
    mb_match = re.search(r"compress( this| pdf)?( to| under)?\s*(\d+)\s*mb", prompt_for_match, re.IGNORECASE)
    if mb_match and file_names:
        target_mb = int(mb_match.group(3))
        file_name = file_names[0]
        compress_intent = ParsedIntent(
            operation_type="compress_to_target",
            compress_to_target={"operation": "compress_to_target", "file": file_name, "target_mb": target_mb},
        )
        return ClarificationResult(intent=compress_intent)
    
    # Pattern 2: "compress by X%" (calculate target size based on percentage)
    percent_match = re.search(r"compress( this)?( pdf)? by (\d{1,3})%", prompt_for_match, re.IGNORECASE)
    if percent_match and file_names:
        percent = int(percent_match.group(3))
        file_name = file_names[0]
        file_path = get_upload_path(file_name)
        if os.path.exists(file_path):
            size_bytes = os.path.getsize(file_path)
            size_mb = size_bytes / (1024 * 1024)
            target_mb = max(1, int(size_mb * (percent / 100)))
            compress_intent = ParsedIntent(
                operation_type="compress_to_target",
                compress_to_target={"operation": "compress_to_target", "file": file_name, "target_mb": target_mb},
            )
            return ClarificationResult(intent=compress_intent)
    
    # Pattern 2.5: "split all pages" (without page range) → treat as split_to_files
    if file_names and re.search(r"\bsplit\s+(all\s+)?pages?\b", prompt_for_match, re.IGNORECASE):
        # If no specific page range mentioned, assume split_to_files.
        if not re.search(r"\b(pages?\s+)?\d+(-\d+)?(\s*,\s*\d+(-\d+)?)*\b", prompt_for_match):
            return ClarificationResult(
                intent=ParsedIntent(
                    operation_type="split_to_files",
                    split_to_files={"operation": "split_to_files", "file": file_names[0], "pages": None},
                )
            )

    # Pattern 3: "split 1st page", "extract first page", "keep page 1"
    first_page_match = re.search(r"(split|extract|keep)\s*(1st|first|page 1)\s*page", prompt_for_match, re.IGNORECASE)
    if first_page_match and file_names:
        file_name = file_names[0]
        split_intent = ParsedIntent(
            operation_type="split",
            split={"operation": "split", "file": file_name, "pages": [1]},
        )
        return ClarificationResult(intent=split_intent)
    
    # Pattern 4: "split first N pages" or "extract first N pages"
    first_n_match = re.search(r"(split|extract|keep)\s*first\s*(\d+)\s*pages?", prompt_for_match, re.IGNORECASE)
    if first_n_match and file_names:
        n = int(first_n_match.group(2))
        file_name = file_names[0]
        split_intent = ParsedIntent(
            operation_type="split",
            split={"operation": "split", "file": file_name, "pages": list(range(1, n + 1))},
        )
        return ClarificationResult(intent=split_intent)

    # Pattern 4.5: rotate (default to 90 degrees when missing)
    # Human inputs: "rotate", "rotate it", "turn it", "flip", "rotate left/right", "90"
    rotate_word = re.search(r"\b(rotate|rotat|turn|flip|straight)\b", prompt_for_match, re.IGNORECASE)
    rotate_number = re.search(r"(-?\d+)\s*(deg|degree|degrees)?\b", prompt_for_match, re.IGNORECASE)
    rotate_dir_left = re.search(r"\b(left|anti|anticlock|counter)\b", prompt_for_match, re.IGNORECASE)
    rotate_dir_right = re.search(r"\b(right|clockwise)\b", prompt_for_match, re.IGNORECASE)

    if file_names and (rotate_word or re.fullmatch(r"-?\d+", prompt_compact)):
        file_name = file_names[0]
        degrees: int

        if rotate_dir_left:
            degrees = 270
        elif rotate_dir_right:
            degrees = 90
        elif re.search(r"\bflip\b", prompt_for_match, re.IGNORECASE):
            degrees = 180
        elif rotate_number:
            raw = int(rotate_number.group(1))
            # Normalize -90 -> 270, 0/360 -> 0 (but our model only supports 90/180/270).
            normalized = raw % 360
            if normalized == 0:
                degrees = 90
            elif normalized == 90:
                degrees = 90
            elif normalized == 180:
                degrees = 180
            elif normalized == 270:
                degrees = 270
            else:
                # For non-right-angle inputs, pick the nearest right angle.
                candidates = [90, 180, 270]
                degrees = min(candidates, key=lambda d: min((normalized - d) % 360, (d - normalized) % 360))
        else:
            # Missing degrees: default per spec.
            degrees = 90

        rotate_intent = ParsedIntent(
            operation_type="rotate",
            rotate={"operation": "rotate", "file": file_name, "degrees": degrees, "pages": None},
        )
        return ClarificationResult(intent=rotate_intent)

    # Pattern 5: qualitative "compress" (no target given)
    if re.search(r"\bcompress\b", prompt_for_match, re.IGNORECASE) and file_names:
        # Spec: if no target is given, use a safe default preset instead of asking.
        preset = _infer_compress_preset(user_prompt)
        file_name = file_names[0]
        compress_intent = ParsedIntent(
            operation_type="compress",
            compress={"operation": "compress", "file": file_name, "preset": preset},
        )
        return ClarificationResult(intent=compress_intent)
    
    # If no patterns matched, try AI parser
    try:
        intent = ai_parser.parse_intent(user_prompt, file_names)
        return ClarificationResult(intent=intent)
    except ValueError as e:
        error_msg = str(e)
        
        # Check if this is a clarification request from AI
        if "CLARIFICATION_NEEDED:" in error_msg:
            parts = error_msg.split(" | OPTIONS: ")
            clarification = parts[0].replace("CLARIFICATION_NEEDED: ", "")
            options = None
            if len(parts) > 1:
                try:
                    options = json.loads(parts[1])
                except:
                    pass

            # Ensure order questions always provide full, runnable options.
            if _is_order_clarification(clarification):
                fallback = _order_options_from_context(user_prompt, clarification)
                if fallback:
                    options = fallback

            # Add options for common slot questions (degrees/pages/size)
            if not options:
                options = _options_for_common_questions(clarification, user_prompt)
            print(f"[AI] Requesting clarification: {clarification}")
            return ClarificationResult(clarification=clarification, options=options)

        # If the request is for an unsupported feature (or the LLM produced an unsupported op),
        # enforce the corpus rule.
        if _is_likely_unsupported_validation_error(error_msg) or _is_explicitly_unsupported_request(prompt_for_match):
            return ClarificationResult(clarification=UNSUPPORTED_REPLY)
        
        # If AI parser fails for other reasons, show helpful examples
        clarification = (
            "Sorry, I couldn't understand your request. Here are some examples:\n\n"
            "📄 Merge: 'merge these files', 'combine all PDFs'\n"
            "✂️ Split: 'split 1st page', 'extract first 3 pages', 'keep pages 1-5'\n"
            "🗑️ Delete: 'delete page 2', 'remove pages 3, 4, 5'\n"
            "🗜️ Compress: 'compress to 1mb', 'compress to 5MB', 'compress by 50%'\n"
            "📝 Convert: 'convert to docx', 'pdf to word'\n"
            "🔄 Rotate: 'rotate page 1 by 90 degrees'\n"
            "🔀 Reorder: 'reorder pages to 2,1,3'\n"
            "🏷️ Watermark: 'watermark with CONFIDENTIAL'\n"
            "#️⃣ Page numbers: 'add page numbers'\n"
            "📄 Text: 'extract text'\n"
            "🖼️ Images: 'export pages as png'\n"
            "🔎 OCR: 'ocr this scan'\n\n"
            "Please try again with a clearer instruction!"
        )
        return ClarificationResult(clarification=clarification)
