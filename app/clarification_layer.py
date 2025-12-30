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
    s = re.sub(r"\bthne\b", "then", s, flags=re.IGNORECASE)
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
    if re.search(r"\breorder\b|\border\b|\bswap\b", s):
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
    user_prompt = _fix_common_connector_typos(user_prompt)
    prompt_for_match = _normalize_prompt_for_heuristics(user_prompt)
    prompt_compact = prompt_for_match.strip().lower()

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

    # Format-only prompts (very common): "png", "jpg", "docx", "txt", "ocr"
    # Prefer executing rather than asking "convert to what?".
    if file_names and prompt_compact in {"png", "jpg", "jpeg"}:
        file_name = file_names[0]
        return ClarificationResult(
            intent=ParsedIntent(
                operation_type="pdf_to_images",
                pdf_to_images={
                    "operation": "pdf_to_images",
                    "file": file_name,
                    "format": prompt_compact,
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

        # Pattern: reorder pages to ...
        if file_names and re.search(r"\breorder\b|\bswap\b", prompt_for_match, re.IGNORECASE):
            m = re.search(r"\b(?:to|as)\b\s*([0-9,\s]+)", user_prompt, re.IGNORECASE)
            if not m:
                return ClarificationResult(
                    clarification="What is the new page order? (example: 2,1,3)",
                    options=["reorder pages to 2,1,3"],
                )
            order = [int(x) for x in re.findall(r"\d+", m.group(1))]
            if not order:
                return ClarificationResult(
                    clarification="What is the new page order? (example: 2,1,3)",
                    options=["reorder pages to 2,1,3"],
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
