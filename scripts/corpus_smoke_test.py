"""Lightweight smoke checks for corpus-driven behavior.

Goal: enforce the dataset rule:
- If unsupported -> reply exactly: "Not supported yet or sooner"

Also validates key typo normalizations that should work without calling the LLM.

Run:
  python scripts/corpus_smoke_test.py

Exit code is non-zero if any check fails.
"""

from __future__ import annotations

import sys
from pathlib import Path


# Ensure repo root is importable so `import app...` works when running this file directly.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def main() -> int:
    # Import lazily so this script is runnable from repo root.
    from app.clarification_layer import (
        UNSUPPORTED_REPLY,
        clarify_intent,
        _is_likely_unsupported_validation_error,
    )

    checks: list[tuple[str, None]] = []

    # -------------------------
    # Unsupported feature checks
    # -------------------------

    # Conversions/formats we do not support.
    for prompt in [
        "convert pdf to ppt",
        "cnvert this to pptx",
        "export to excel",
        "convert to xlsx",
        "convert to html",
        "convert pdf to csv",
    ]:
        r = clarify_intent(prompt, ["doc.pdf"], allow_multi=False)
        if r.clarification != UNSUPPORTED_REPLY:
            _fail(f"Unsupported prompt did not return exact reply. prompt={prompt!r} got={r.clarification!r}")
        checks.append((prompt, None))

    # Security/signing/authoring workflows (unsupported).
    for prompt in [
        "password protect this pdf",
        "encrypt pdf",
        "decrypt pdf",
        "unlock pdf",
        "sign this pdf",
        "add signature to pdf",
        "annotate pdf",
        "highlight text in pdf",
        "edit pdf",
    ]:
        r = clarify_intent(prompt, ["doc.pdf"], allow_multi=False)
        if r.clarification != UNSUPPORTED_REPLY:
            _fail(f"Unsupported prompt did not return exact reply. prompt={prompt!r} got={r.clarification!r}")
        checks.append((prompt, None))

    # Validation-error heuristic sanity.
    if not _is_likely_unsupported_validation_error(
        "Failed to validate intent: 1 validation error for ParsedIntent\noperation_type\n  Input should be 'merge' or 'split'"
    ):
        _fail("Expected validation-error heuristic to return True")

    # -------------------------
    # Typo normalization checks
    # -------------------------

    # cnvert -> convert (PDF->DOCX deterministic shortcut)
    r = clarify_intent("cnvert to docx", ["a.pdf"], allow_multi=False)
    if not r.intent:
        _fail("Expected intent for 'cnvert to docx'")
    if getattr(r.intent, "operation_type", None) != "pdf_to_docx":
        _fail(f"Expected pdf_to_docx for 'cnvert to docx', got {getattr(r.intent, 'operation_type', None)!r}")

    # spllit -> split (split first N pages pattern)
    r = clarify_intent("spllit first 2 pages", ["a.pdf"], allow_multi=False)
    if not r.intent:
        _fail("Expected intent for 'spllit first 2 pages'")
    if getattr(r.intent, "operation_type", None) != "split":
        _fail(f"Expected split for 'spllit first 2 pages', got {getattr(r.intent, 'operation_type', None)!r}")

    # merge n compress: make sure it doesn't crash and normalizes 'n' -> 'and'
    # We avoid multi-step behavior here (LLM) by setting allow_multi=False. This should at least parse merge.
    r = clarify_intent("merge n compress", ["a.pdf", "b.pdf"], allow_multi=False)
    if not r.intent:
        _fail("Expected intent for 'merge n compress' with two PDFs")
    if getattr(r.intent, "operation_type", None) != "merge":
        _fail(f"Expected merge (single-step heuristic) for 'merge n compress' allow_multi=False, got {getattr(r.intent, 'operation_type', None)!r}")

    print(f"OK: {len(checks) + 4} checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"FAIL: {e}")
        raise SystemExit(1)
