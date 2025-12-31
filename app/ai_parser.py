"""
AI Intent Parser - Uses LLM to convert natural language to structured JSON.

KEY PRINCIPLE: The AI does NOT access files or execute code.
It ONLY parses user intent and outputs JSON instructions.
"""

import json
from typing import Union
from groq import Groq
from app.config import settings
from app.models import ParsedIntent
import re

# ============================================
# PRECOMPILED PATTERNS FOR PERFORMANCE
# ============================================

RE_NUMERIC_ONLY = re.compile(r'^\d+$')
RE_NUMERIC_WITH_UNIT = re.compile(r'^\d+\s*(mb|kb)?$', re.IGNORECASE)
RE_SHORTHAND_ROT = re.compile(r'\brot\b', re.IGNORECASE)
RE_SHORTHAND_ZIP = re.compile(r'\bzip\b', re.IGNORECASE)
RE_SHORTHAND_TXT = re.compile(r'\btxt\b', re.IGNORECASE)
RE_SHORTHAND_PNG = re.compile(r'\bpng\b', re.IGNORECASE)
RE_SHORTHAND_JPG = re.compile(r'\bjpg\b', re.IGNORECASE)
RE_SHORTHAND_DOCX = re.compile(r'\bdocx?\b', re.IGNORECASE)
RE_SHORTHAND_WORD = re.compile(r'\bword\b', re.IGNORECASE)
RE_SHORTHAND_PPT = re.compile(r'\bppt\b', re.IGNORECASE)
RE_SHORTHAND_XLSX = re.compile(r'\bxlsx?\b', re.IGNORECASE)
RE_SHORTHAND_HTML = re.compile(r'\bhtml\b', re.IGNORECASE)
RE_COMPRESS_EMAIL = re.compile(r'\bemail\b', re.IGNORECASE)
RE_COMPRESS_WHATSAPP = re.compile(r'\bwhatsapp\b', re.IGNORECASE)
RE_COMPRESS_SMALLEST = re.compile(r'\bsmallest\b', re.IGNORECASE)
RE_COMPRESS_TINY = re.compile(r'\btiny\b', re.IGNORECASE)
RE_COMPRESS_HALF = re.compile(r'\bhalf.?size\b', re.IGNORECASE)
RE_COMPRESS_SMALLER = re.compile(r'\bsmaller\b', re.IGNORECASE)
RE_COMPRESS_REDUCED = re.compile(r'\breduced\b', re.IGNORECASE)
import re

# ============================================
# PRECOMPILED PATTERNS FOR PERFORMANCE
# ============================================

RE_NUMERIC_ONLY = re.compile(r'^\d+$')
RE_NUMERIC_WITH_UNIT = re.compile(r'^\d+\s*(mb|kb)?$', re.IGNORECASE)
RE_SHORTHAND_ROT = re.compile(r'\brot\b', re.IGNORECASE)
RE_SHORTHAND_ZIP = re.compile(r'\bzip\b', re.IGNORECASE)
RE_SHORTHAND_TXT = re.compile(r'\btxt\b', re.IGNORECASE)
RE_SHORTHAND_PNG = re.compile(r'\bpng\b', re.IGNORECASE)
RE_SHORTHAND_JPG = re.compile(r'\bjpg\b', re.IGNORECASE)
RE_SHORTHAND_DOCX = re.compile(r'\bdocx?\b', re.IGNORECASE)
RE_SHORTHAND_WORD = re.compile(r'\bword\b', re.IGNORECASE)
RE_SHORTHAND_PPT = re.compile(r'\bppt\b', re.IGNORECASE)
RE_SHORTHAND_XLSX = re.compile(r'\bxlsx?\b', re.IGNORECASE)
RE_SHORTHAND_HTML = re.compile(r'\bhtml\b', re.IGNORECASE)
RE_COMPRESS_EMAIL = re.compile(r'\bemail\b', re.IGNORECASE)
RE_COMPRESS_WHATSAPP = re.compile(r'\bwhatsapp\b', re.IGNORECASE)
RE_COMPRESS_SMALLEST = re.compile(r'\bsmallest\b', re.IGNORECASE)
RE_COMPRESS_TINY = re.compile(r'\btiny\b', re.IGNORECASE)
RE_COMPRESS_HALF = re.compile(r'\bhalf.?size\b', re.IGNORECASE)
RE_COMPRESS_SMALLER = re.compile(r'\bsmaller\b', re.IGNORECASE)
RE_COMPRESS_REDUCED = re.compile(r'\breduced\b', re.IGNORECASE)


# ============================================
# SYSTEM PROMPT FOR THE LLM
# ============================================

SYSTEM_PROMPT = """You are an intelligent intent parser for a PDF processing system. Your job is to analyze user instructions and either:
1. Output structured JSON for clear instructions
2. Request clarification for ambiguous instructions

SUPPORTED OPERATIONS:
1. MERGE: Combine multiple PDFs into one
2. SPLIT: Extract specific pages from a PDF
3. DELETE: Remove specific pages from a PDF
4. COMPRESS: Reduce PDF file size (qualitative presets)
5. PDF_TO_DOCX: Convert a PDF to DOCX format
6. COMPRESS_TO_TARGET: Compress PDF to a target size (in MB)
7. ROTATE: Rotate pages in a PDF
8. REORDER: Reorder pages in a PDF
9. WATERMARK: Add a text watermark
10. PAGE_NUMBERS: Add page numbers
11. EXTRACT_TEXT: Extract text to a .txt file
12. PDF_TO_IMAGES: Export pages to images (returns a .zip)
13. IMAGES_TO_PDF: Combine uploaded images into one PDF
14. SPLIT_TO_FILES: Split pages into separate PDFs (returns a .zip)
15. OCR: Make a searchable PDF (OCR)
16. DOCX_TO_PDF: Convert a DOCX to PDF
17. REMOVE_BLANK_PAGES: Remove blank/empty pages from a PDF
18. REMOVE_DUPLICATE_PAGES: Remove duplicate pages from a PDF
19. ENHANCE_SCAN: Enhance a scanned PDF for readability (image-based)
20. FLATTEN_PDF: Flatten/sanitize a PDF (optimize structure)

CRITICAL RULES:
- You do NOT access files
- You do NOT execute operations
- You ONLY output valid JSON matching the schema
- Whenever you include a file name in JSON, it MUST exactly match one of the provided "Files".
- If the user's text mentions a file name that doesn't exactly match any provided file (typo / mismatch), pick the closest match ONLY if it's obvious; otherwise request clarification.
- Page numbers are 1-indexed (first page = 1, "1st page" = page 1)
- For operations that require PDFs, the "file" must be a PDF from Files.
- For IMAGES_TO_PDF, use "files" with image names from Files (png/jpg/jpeg).
- When user says "compress to XMB" or "compress to X mb", use COMPRESS_TO_TARGET with target_mb = X
- If user says "compress" with qualitative wording, set a COMPRESS preset:
  - "compress very tiny" / "as small as possible" / "maximum compression" => preset = "screen"
  - "compress" (no qualifier) => default to preset = "ebook" (do NOT ask)
  - "compress a little" / "slightly" => preset = "printer"
  - "best quality" / "minimal compression" => preset = "prepress"
  - otherwise default to preset = "ebook" when qualifier implies medium
- When user says "split 1st page" or "extract page 1", use SPLIT with pages = [1]
- When user says "split first N pages", use SPLIT with pages = [1, 2, ..., N]
- Be specific and extract exact numbers from prompts

AMBIGUITY DETECTION:
If the request is AMBIGUOUS or INCOMPLETE, output this format:
{
  "needs_clarification": true,
  "question": "<specific question to ask user>",
  "suggested_format": "<example of how they should respond>",
  "options": ["option 1", "option 2"]
}
(The "options" field is optional but highly recommended for multiple-choice questions like "which should happen first?" or "which pages?". Each option should be a short string that the user can click to reply.)

MULTI-OPERATION (PIPELINE) SUPPORT:
- If the user requests multiple operations in one prompt AND the order is clear (e.g., contains "then", "and then", "after", "before"),
  output a multi-operation plan in this format:
  {
    "is_multi_operation": true,
    "operations": [
      {<single operation JSON>},
      {<single operation JSON>}
    ]
  }
- Each item in "operations" MUST be a valid single-operation object using the exact schemas below.
- Preserve the user-intended order.
- If order is ambiguous (e.g., "split pages 2-3 and compress"), request clarification asking which should happen first.

Examples of AMBIGUOUS requests:
- "split this" (which pages?)
- "compress this" when no target specified (basic compress or target size?)
- "delete some pages" (which pages?)
- "merge" with only 1 file (need at least 2 files)
- "rotate" (missing degrees: default to 90 degrees; do NOT ask)
- "reorder pages" (what order?)
- "watermark" (what text?)
- "export images" (what format/dpi if user cares; otherwise choose defaults)

Examples of CLEAR requests:
- "split 1st page"
- "compress to 2mb"
- "delete page 3"
- "merge all files"

FORMAT-ONLY SHORTCUTS (common user replies):
- If the entire user prompt is one of: png/jpg/jpeg, interpret as PDF_TO_IMAGES with that format.
- If the entire user prompt is docx/word, interpret as PDF_TO_DOCX.
- If the entire user prompt is txt, interpret as EXTRACT_TEXT.
- If the entire user prompt is ocr, interpret as OCR.

OUTPUT FORMAT (choose ONE operation type):

For MERGE:
{
  "operation_type": "merge",
  "merge": {
    "operation": "merge",
    "files": ["file1.pdf", "file2.pdf"]
  }
}

For SPLIT (keep specific pages):
{
  "operation_type": "split",
  "split": {
    "operation": "split",
    "file": "document.pdf",
    "pages": [1, 2, 3, 5]
  }
}

For DELETE (remove specific pages):
{
  "operation_type": "delete",
  "delete": {
    "operation": "delete",
    "file": "document.pdf",
    "pages_to_delete": [3, 7, 10]
  }
}

For COMPRESS:
{
  "operation_type": "compress",
  "compress": {
    "operation": "compress",
    "file": "large_file.pdf",
    "preset": "ebook"
  }
}

For PDF_TO_DOCX:
{
  "operation_type": "pdf_to_docx",
  "pdf_to_docx": {
    "operation": "pdf_to_docx",
    "file": "document.pdf"
  }
}

For COMPRESS_TO_TARGET:
{
  "operation_type": "compress_to_target",
  "compress_to_target": {
    "operation": "compress_to_target",
    "file": "large_file.pdf",
    "target_mb": 14
  }
}

For ROTATE:
{
  "operation_type": "rotate",
  "rotate": {
    "operation": "rotate",
    "file": "document.pdf",
    "degrees": 90,
    "pages": [1, 2]
  }
}

For REORDER:
{
  "operation_type": "reorder",
  "reorder": {
    "operation": "reorder",
    "file": "document.pdf",
    "new_order": [2, 1, 3]
  }
}

For WATERMARK:
{
  "operation_type": "watermark",
  "watermark": {
    "operation": "watermark",
    "file": "document.pdf",
    "text": "CONFIDENTIAL",
    "opacity": 0.12,
    "angle": 0
  }
}

For PAGE_NUMBERS:
{
  "operation_type": "page_numbers",
  "page_numbers": {
    "operation": "page_numbers",
    "file": "document.pdf",
    "position": "bottom_center",
    "start_at": 1
  }
}

For EXTRACT_TEXT:
{
  "operation_type": "extract_text",
  "extract_text": {
    "operation": "extract_text",
    "file": "document.pdf",
    "pages": [1, 2]
  }
}

For PDF_TO_IMAGES:
{
  "operation_type": "pdf_to_images",
  "pdf_to_images": {
    "operation": "pdf_to_images",
    "file": "document.pdf",
    "format": "png",
    "dpi": 150
  }
}

For IMAGES_TO_PDF:
{
  "operation_type": "images_to_pdf",
  "images_to_pdf": {
    "operation": "images_to_pdf",
    "files": ["page1.png", "page2.jpg"]
  }
}

For SPLIT_TO_FILES:
{
  "operation_type": "split_to_files",
  "split_to_files": {
    "operation": "split_to_files",
    "file": "document.pdf",
    "pages": [1, 5, 9]
  }
}

For OCR:
{
  "operation_type": "ocr",
  "ocr": {
    "operation": "ocr",
    "file": "scan.pdf",
    "language": "eng",
    "deskew": true
  }
}

For DOCX_TO_PDF:
{
  "operation_type": "docx_to_pdf",
  "docx_to_pdf": {
    "operation": "docx_to_pdf",
    "file": "document.docx"
  }
}

For REMOVE_BLANK_PAGES:
{
  "operation_type": "remove_blank_pages",
  "remove_blank_pages": {
    "operation": "remove_blank_pages",
    "file": "document.pdf"
  }
}

For REMOVE_DUPLICATE_PAGES:
{
  "operation_type": "remove_duplicate_pages",
  "remove_duplicate_pages": {
    "operation": "remove_duplicate_pages",
    "file": "document.pdf"
  }
}

For ENHANCE_SCAN:
{
  "operation_type": "enhance_scan",
  "enhance_scan": {
    "operation": "enhance_scan",
    "file": "scan.pdf"
  }
}

For FLATTEN_PDF:
{
  "operation_type": "flatten_pdf",
  "flatten_pdf": {
    "operation": "flatten_pdf",
    "file": "document.pdf"
  }
}

EXAMPLES:

Prompt: "merge all these files"
Files: ["report.pdf", "appendix.pdf"]
Output: {"operation_type": "merge", "merge": {"operation": "merge", "files": ["report.pdf", "appendix.pdf"]}}

Prompt: "keep only the first 5 pages"
Files: ["book.pdf"]
Output: {"operation_type": "split", "split": {"operation": "split", "file": "book.pdf", "pages": [1, 2, 3, 4, 5]}}

Prompt: "remove pages 2, 4, and 6"
Files: ["slides.pdf"]
Output: {"operation_type": "delete", "delete": {"operation": "delete", "file": "slides.pdf", "pages_to_delete": [2, 4, 6]}}

Prompt: "make this smaller"
Files: ["huge.pdf"]
Output: {"operation_type": "compress", "compress": {"operation": "compress", "file": "huge.pdf"}}

Prompt: "convert this to docx"
Files: ["sample.pdf"]
Output: {"operation_type": "pdf_to_docx", "pdf_to_docx": {"operation": "pdf_to_docx", "file": "sample.pdf"}}

Prompt: "compress this under 14MB"
Files: ["big.pdf"]
Output: {"operation_type": "compress_to_target", "compress_to_target": {"operation": "compress_to_target", "file": "big.pdf", "target_mb": 14}}

Prompt: "compress to 1mb"
Files: ["report.pdf"]
Output: {"operation_type": "compress_to_target", "compress_to_target": {"operation": "compress_to_target", "file": "report.pdf", "target_mb": 1}}

Prompt: "split 1st page"
Files: ["document.pdf"]
Output: {"operation_type": "split", "split": {"operation": "split", "file": "document.pdf", "pages": [1]}}

Prompt: "extract first 3 pages"
Files: ["book.pdf"]
Output: {"operation_type": "split", "split": {"operation": "split", "file": "book.pdf", "pages": [1, 2, 3]}}

Prompt: "keep page 1 and page 5"
Files: ["slides.pdf"]
Output: {"operation_type": "split", "split": {"operation": "split", "file": "slides.pdf", "pages": [1, 5]}}

AMBIGUOUS EXAMPLES:

Prompt: "split this"
Files: ["document.pdf"]
Output: {"needs_clarification": true, "question": "Which pages would you like to keep?", "suggested_format": "Example: 'keep pages 1-5' or 'extract page 1'"}

Prompt: "compress this pdf"
Files: ["file.pdf"]
Output: {"needs_clarification": true, "question": "Would you like basic compression or compress to a specific size?", "suggested_format": "Example: 'compress to 2MB' or just 'compress' for basic compression"}

Prompt: "delete some pages"
Files: ["doc.pdf"]
Output: {"needs_clarification": true, "question": "Which page numbers would you like to delete?", "suggested_format": "Example: 'delete pages 2, 3, 5'"}

MULTI-OPERATION EXAMPLES:

Prompt: "split pages 2-3 and then compress to 1mb"
Files: ["doc.pdf"]
Output: {
  "is_multi_operation": true,
  "operations": [
    {"operation_type": "split", "split": {"operation": "split", "file": "doc.pdf", "pages": [2, 3]}},
    {"operation_type": "compress_to_target", "compress_to_target": {"operation": "compress_to_target", "file": "doc.pdf", "target_mb": 1}}
  ]
}

Prompt: "compress and then split pages 2-3"
Files: ["doc.pdf"]
Output: {
  "is_multi_operation": true,
  "operations": [
    {"operation_type": "compress", "compress": {"operation": "compress", "file": "doc.pdf"}},
    {"operation_type": "split", "split": {"operation": "split", "file": "doc.pdf", "pages": [2, 3]}}
  ]
}

Prompt: "add watermark confidential and then add page numbers"
Files: ["doc.pdf"]
Output: {
  "is_multi_operation": true,
  "operations": [
    {"operation_type": "watermark", "watermark": {"operation": "watermark", "file": "doc.pdf", "text": "CONFIDENTIAL"}},
    {"operation_type": "page_numbers", "page_numbers": {"operation": "page_numbers", "file": "doc.pdf", "position": "bottom_center", "start_at": 1}}
  ]
}

Now parse the following request and respond with ONLY valid JSON, no explanation:"""


# ============================================
# INPUT NORMALIZATION (HUMAN ERROR HANDLING)
# ============================================

def normalize_human_input(user_prompt: str, last_question: str = "") -> str:
    """
    Normalize messy real-world input before sending to LLM.
    
    Handles:
    - Typos (rotet → rotate, teh → the)
    - Single numbers → interpret in context
    - Shorthand (rot, compress, zip, txt)
    - Missing context (infer from last_question)
    
    Args:
        user_prompt: Raw user input
        last_question: Previous clarification question (for context)
    
    Returns:
        Normalized prompt ready for LLM
    """
    import re
    p = user_prompt.strip().lower()
    
    # Handle common typos
    typo_map = {
        'rotet': 'rotate',
        'roate': 'rotate',
        'rotae': 'rotate',
        'rotate teh': 'rotate the',
        'teh ': 'the ',
        'degres': 'degrees',
        'splti': 'split',
        'compres': 'compress',
        'comress': 'compress',
        'mergee': 'merge',
        'wattermark': 'watermark',
        'watermak': 'watermark',
        'orc': 'ocr',
        'exract': 'extract',
        'extrat': 'extract',
    }
    for typo, correct in typo_map.items():
      # Avoid corrupting already-correct words (e.g., "compress" contains "compres").
      # For simple letter-only typos, replace whole words only.
      if typo.isalpha():
        p = re.sub(rf"\b{re.escape(typo)}\b", correct, p)
      else:
        p = p.replace(typo, correct)
    
    # Handle shorthand
    shorthand_map = {
        r'\brot\b': 'rotate',
        r'\bzip\b': 'compress as small as possible',
        r'\btxt\b': 'extract text',
        r'\bpng\b': 'export as png images',
        r'\bjpg\b': 'export as jpg images',
        r'\bdocx?\b': 'convert to docx',
        r'\bword\b': 'convert to word',
        r'\bppt\b': 'convert to ppt',
        r'\bxlsx?\b': 'convert to excel',
        r'\bhtml\b': 'convert to html',
    }
    for pattern, replacement in shorthand_map.items():
      # Avoid duplicating expansions when user already wrote the full phrase.
      if pattern in {r'\bpng\b', r'\bjpg\b'} and ("export" in p or "image" in p or "images" in p):
        continue
      if pattern == r'\btxt\b' and ("extract" in p and "text" in p):
        continue
      p = re.sub(pattern, replacement, p)
    
    # Handle numeric-only responses in context
    # If user just typed a number and last_question asked about degrees → rotate N degrees
    if re.match(r'^\d+$', p) and 'degree' in last_question.lower():
        p = f'rotate {p} degrees'
    
    # If user just typed a number and last_question asked about page → split page N
    elif re.match(r'^\d+$', p) and ('page' in last_question.lower() and 'extract' in last_question.lower()):
        p = f'split page {p}'
    
    # If user just typed a number and last_question asked about target size → compress to N MB
    elif re.match(r'^\d+\s*(mb|kb)?$', p, re.IGNORECASE) and 'size' in last_question.lower():
        p = f'compress to {p}'
    
    # Handle common directional aliases for rotate
    rotate_aliases = {
        'left': 'rotate 270 degrees (counter-clockwise)',
        'right': 'rotate 90 degrees (clockwise)',
        'flip': 'rotate 180 degrees',
        'turn': 'rotate',
        'make straight': 'rotate to correct orientation',
    }
    for alias, expansion in rotate_aliases.items():
        if alias in p:
            p = p.replace(alias, expansion)
    
    # Handle compression shortcuts
    compression_map = {
        r'\bemail\b': 'compress to email-safe size (10MB max)',
        r'\bwhatsapp\b': 'compress very aggressively for whatsapp',
        r'\bsmallest\b': 'compress to smallest possible size',
        r'\btiny\b': 'compress as small as possible',
        r'\bhalf.?size\b': 'compress to half size',
        r'\bsmaller\b': 'make file smaller',
        r'\breduced\b': 'reduce file size',
    }
    for pattern, replacement in compression_map.items():
        p = re.sub(pattern, replacement, p)
    
    return p


# ============================================
# PARSER IMPLEMENTATION
# ============================================

class AIParser:
    """Parses user intent using Groq LLM"""
    
    def __init__(self):
        self.client = Groq(api_key=settings.groq_api_key)
        self.model = settings.llm_model
    
    def parse_intent(self, user_prompt: str, file_names: list[str], last_question: str = "") -> Union[ParsedIntent, list[ParsedIntent]]:
        """
        Convert natural language prompt + file list into structured intent.
        
        Args:
            user_prompt: User's natural language instruction
            file_names: List of uploaded PDF file names
            last_question: Previous clarification question (for context in ambiguous cases)
        
        Returns:
            ParsedIntent: Structured operation intent
        
        Raises:
            ValueError: If intent cannot be parsed or needs clarification (message contains the question)
        """
        # Normalize messy human input BEFORE sending to LLM
        normalized_prompt = normalize_human_input(user_prompt, last_question)
        print(f"[AI] Normalized input: '{user_prompt}' → '{normalized_prompt}'")
        
        # Build the user message
        user_message = f"""
Prompt: "{normalized_prompt}"
Files: {json.dumps(file_names)}

Parse this into JSON:"""
        
        try:
            # Call Groq API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.1,  # Low temperature for consistent parsing
                max_tokens=500,
                response_format={"type": "json_object"}  # Force JSON output
            )
            
            # Extract JSON response
            raw_json = response.choices[0].message.content
            print(f"[AI] Response: {raw_json}")
            parsed_json = json.loads(raw_json)

            def _sanitize_rotate_pages(obj: dict) -> None:
                """Normalize common LLM outputs for rotate.pages.

                Schema expects pages: Optional[List[int]]. LLM sometimes returns
                strings like "all"/"all pages"; treat those as None (= all pages).
                """
                try:
                    if obj.get("operation_type") != "rotate":
                        return
                    rotate = obj.get("rotate")
                    if not isinstance(rotate, dict):
                        return
                    pages = rotate.get("pages")
                    if isinstance(pages, str):
                        p = pages.strip().lower()
                        if p in {"all", "all pages", "every", "every page", "entire"}:
                            rotate["pages"] = None
                except Exception:
                    return
            
            # Check if AI is requesting clarification
            if parsed_json.get("needs_clarification"):
                question = parsed_json.get("question", "Could you please clarify your request?")
                suggested_format = parsed_json.get("suggested_format", "")
                options = parsed_json.get("options", [])
                
                clarification_msg = f"{question}\n\n{suggested_format}" if suggested_format else question
                
                # Encode options into the error message so clarify_intent can extract them
                if options:
                    options_str = json.dumps(options)
                    raise ValueError(f"CLARIFICATION_NEEDED: {clarification_msg} | OPTIONS: {options_str}")
                
                raise ValueError(f"CLARIFICATION_NEEDED: {clarification_msg}")

            # Multi-operation plan
            if parsed_json.get("is_multi_operation") and isinstance(parsed_json.get("operations"), list):
              intents: list[ParsedIntent] = []
              for op in parsed_json["operations"]:
                if isinstance(op, dict):
                  _sanitize_rotate_pages(op)
                intents.append(ParsedIntent(**op))
              return intents

            if isinstance(parsed_json, dict):
              _sanitize_rotate_pages(parsed_json)
            
            # Validate against Pydantic model
            intent = ParsedIntent(**parsed_json)
            
            return intent
            
        except json.JSONDecodeError as e:
            print(f"[ERR] JSON decode error: {e}")
            raise ValueError(f"LLM returned invalid JSON: {e}")
        except ValueError as e:
            # Re-raise clarification requests as-is
            if "CLARIFICATION_NEEDED" in str(e):
                raise
            print(f"[ERR] Validation error: {e}")
            raise ValueError(f"Failed to validate intent: {e}")
        except Exception as e:
            print(f"[ERR] Parse error: {type(e).__name__}: {e}")
            raise ValueError(f"Failed to parse intent: {e}")


# Global parser instance
ai_parser = AIParser()
