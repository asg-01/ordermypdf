"""Smoke test for Baseten rephraser.

Usage (PowerShell):
  $env:BASETEN_API_KEY="<your key>"
  python scripts/test_baseten_phraser.py

This does NOT stream; it just verifies we get a valid response.
"""

from __future__ import annotations

import os


def main() -> int:
    if not os.getenv("BASETEN_API_KEY"):
        print("Missing BASETEN_API_KEY env var.")
        return 2

    from app.phraser import rephrase_with_fallback

    prompt = "to docx"
    files = ["sample.pdf"]

    out = rephrase_with_fallback(prompt, file_names=files)
    if not out:
        print("No rephrase result (provider not configured or request failed).")
        return 1

    print(f"Provider: {out.provider}")
    print(f"Rephrased: {out.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
