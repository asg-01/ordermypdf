"""
Integration Guide - How all new error handling, file-type guards, pipelines, and command intelligence fit together.

This document shows the flow of how user input goes through the new systems and how errors are handled.
"""

# ============================================

# USER REQUEST FLOW

# ============================================

"""

1. USER SENDS REQUEST
   └─ POST /process
   ├─ prompt: "compress to 1mb then convert to docx"
   ├─ files: ["document.pdf"]
   └─ last_operation: (optional, for context inheritance)

2. ENTRY POINT: app/main.py @ process_pdf_request()
   └─ Call clarify_intent(prompt, file_names, last_operation)

3. CLARIFICATION LAYER: app/clarification_layer.py @ clarify_intent()

   Stage A: CONTEXT INHERITANCE (file_type_guards.py)
   ├─ Check: should_inherit_context(prompt)
   ├─ If short command & last_file exists:
   │ └─ Apply context: apply_context_inheritance(prompt, last_file, ...)
   └─ Result: expanded_prompt with full context

   Stage B: ERROR CORRECTION (error_handler.py)
   ├─ Classify typos: ErrorClassifier.classify_typo(expanded_prompt)
   │ └─ "compres" → "compress"
   ├─ Classify shorthand: ErrorClassifier.classify_shorthand(expanded_prompt)
   │ └─ "to doc" → "convert to docx"
   └─ Result: corrected_prompt

   Stage C: COMMAND INTELLIGENCE 3-STAGE RESOLUTION (command_intelligence.py)
   ├─ Stage 1: Direct Parse
   │ ├─ Call: CommandIntelligence.parse_command(corrected_prompt)
   │ ├─ Detect intent: "compress", "convert"
   │ ├─ Extract parameters: {target_mb: 1, target_format: "docx"}
   │ ├─ Calculate confidence: ~0.85
   │ ├─ If confidence >= 0.7: PROCEED TO STAGE D
   │ └─ Else: Go to Stage 2
   │
   ├─ Stage 2: LLM Rephrase (if Stage 1 fails)
   │ ├─ Call LLM to rephrase with context
   │ └─ Re-parse and check confidence
   │ └─ If confidence >= 0.7: PROCEED TO STAGE D
   │ └─ Else: Go to Stage 3
   │
   └─ Stage 3: Ask Clarification (last resort)
   └─ Return: clarification_question + options

4. PIPELINE RESOLUTION: app/pipeline_definitions.py (if Stage C succeeds)
   ├─ Get operations: ["compress", "convert"]
   ├─ Find matching pipeline: get_pipeline_for_operations(["compress", "convert_to_docx"])
   ├─ If pipeline found:
   │ └─ Optimized execution order: ["compress", "convert_to_docx"]
   └─ Else:
   └─ Use heuristic ordering

5. STAGE D: FILE-TYPE VALIDATION (file_type_guards.py)
   ├─ Get file type: get_file_type("document.pdf") → FileType.PDF
   ├─ For each operation:
   │ ├─ Check redundancy: UniversalRedundancyGuards.run_all_redundancy_guards()
   │ │ └─ Is "convert_to_pdf" on a PDF? → SKIP
   │ │ └─ Is "split" on 1-page PDF? → SKIP
   │ ├─ Check compatibility: OperationFileTypeCompatibility.check_compatibility()
   │ │ └─ Is "ocr" on DOCX? → BLOCK with message
   │ │ └─ Is "compress" on PDF? → OK
   │ └─ If guard triggered:
   │ └─ Return GuardResult with action (skip/block/auto_fix)
   └─ Result: validated_operations

6. INTENT PARSING: app/ai_parser.py
   ├─ Use validated operations
   ├─ Generate ParsedIntent objects
   └─ Each intent includes all parameters

7. STAGE E: EXECUTION (app/multi_operation_executor.py)
   ├─ For each intent in chain:
   │ ├─ Try execution: execute_operation(intent)
   │ ├─ If error occurs: Catch and classify
   │ │ └─ Call ErrorClassifier.classify_execution_error()
   │ │ └─ Determine recovery action
   │ │ └─ Attempt recovery or report user-friendly error
   │ └─ Use output as input to next operation
   └─ Return final_output_file

8. RESPONSE: app/main.py
   ├─ Success case:
   │ └─ Return ProcessResponse(status="success", output_file="...")
   └─ Error case:
   ├─ Catch error and classify: ErrorClassifier methods
   └─ Return ErrorResponse with user-friendly message

# ============================================

# ERROR HANDLING FLOW

# ============================================

ERROR DETECTION LAYERS (in execution order):

1. INPUT VALIDATION LAYER
   ├─ Typo detection & correction
   ├─ Shorthand expansion
   └─ Intent normalization
   └─ ErrorType: TYPO, SHORTHAND, VAGUE_INTENT

2. PIPELINE VALIDATION LAYER
   ├─ Conflicting operations detection
   ├─ Missing parameters
   ├─ Invalid operation order
   └─ ErrorType: CONFLICTING_OPS, MISSING_PARAMETER, INVALID_OPERATION_ORDER

3. FILE-TYPE VALIDATION LAYER
   ├─ Redundancy checks (image→image, pdf→pdf)
   ├─ Operation-type compatibility matrix
   └─ ErrorType: TYPE_INCOMPATIBLE, OPERATION_NOT_SUPPORTED_FOR_TYPE

4. FILE CONTENT VALIDATION LAYER
   ├─ XML/Unicode errors
   ├─ Fake text layers
   ├─ Broken fonts
   └─ ErrorType: XML_UNICODE_ERROR, FAKE_TEXT_LAYER, BROKEN_FONTS

5. EXECUTION LAYER
   ├─ PDF parsing failures
   ├─ OCR engine failures
   ├─ Conversion crashes
   └─ ErrorType: PDF_PARSING_FAILURE, OCR_ENGINE_FAILURE, CONVERSION_CRASH

6. RESOURCE LAYER
   ├─ Out of memory
   ├─ Timeout
   └─ ErrorType: OUT_OF_MEMORY, TIMEOUT

7. OUTPUT INTEGRITY LAYER
   ├─ Empty output
   ├─ Corrupt file
   └─ ErrorType: EMPTY_OUTPUT, CORRUPT_FILE

8. FEATURE LAYER
   ├─ Unsupported conversions (PDF→Excel)
   ├─ Unsupported features (digital signatures)
   └─ ErrorType: UNSUPPORTED_FEATURE

RECOVERY ACTIONS:

- skip: Operation already done or meaningless, proceed without it
- auto_fix: Automatically fix and retry
- retry: Retry with same or different parameters
- ask_user: Ask user for clarification
- block: Cannot proceed, return error to user

# ============================================

# MODULE INTERACTIONS

# ============================================

error_handler.py
├─ Used by: clarification_layer.py, main.py, multi_operation_executor.py
├─ Provides: ErrorClassifier, error classification methods
├─ Returns: ErrorClassification objects with recovery actions

file_type_guards.py
├─ Used by: clarification_layer.py, pdf_operations.py
├─ Provides: UniversalRedundancyGuards, OperationFileTypeCompatibility
├─ Returns: GuardResult objects with actions (skip/block/auto_fix)

pipeline_definitions.py
├─ Used by: clarification_layer.py, multi_operation_executor.py
├─ Provides: 120+ Pipeline definitions, execution ordering
├─ Returns: Pipeline objects, optimized operation order

command_intelligence.py
├─ Used by: clarification_layer.py
├─ Provides: 3-stage resolution, confidence scoring, ambiguity detection
├─ Returns: CommandParsing objects, clarification questions

models.py
├─ Used by: all modules
├─ Provides: Pydantic models for all data structures
├─ Includes: ErrorResponse, ErrorTypeEnum, ErrorSeverityEnum

# ============================================

# CONFIGURATION & CONSTANTS

# ============================================

error_handler.py:

- MAX_RETRIES = 1 (never infinite loops)
- OPERATION_FILE_TYPE_MATRIX (8 operations × 6 file types)
- TYPO_CORRECTIONS (20+ common typos)
- SHORTHAND_EXPANSIONS (20+ common shorthand)
- UNSUPPORTED_FEATURES (10+ unsupported operations)

file_type_guards.py:

- FileType enum (PDF, DOCX, JPG, PNG, JPEG, ZIP, TXT)
- GuardAction enum (SKIP, AUTO_FIX, BLOCK, CONVERT, ASK)
- Redundancy guard checks
- Compatibility matrix

command_intelligence.py:

- ConfidenceLevel: VERY_LOW, LOW, MEDIUM, HIGH, VERY_HIGH
- AmbiguityLevel: LOW, MEDIUM, HIGH
- STAGE1_CONFIDENCE_THRESHOLD = 0.7
- 40+ regex patterns for operation detection

pipeline_definitions.py:

- 120+ pipelines across 5 categories:
  - 25+ PDF multi-operation pipelines
  - 30+ natural language shortcuts
  - 10+ image pipelines
  - 10+ DOCX pipelines
- Execution priority system

# ============================================

# EXAMPLE WORKFLOWS

# ============================================

WORKFLOW 1: Simple Compress
User: "compress"
Files: document.pdf

Flow:

1. Inherit context? No (is full command)
2. Correct typos? No typos
3. Stage 1 parse: Intent=compress, Confidence=0.9, Ambiguity=LOW
4. Pipeline: compress
5. File type check: PDF → compress = OK
6. Execute: compress_pdf("document.pdf")
7. Response: success + output_file

WORKFLOW 2: Multi-Step with Context Inheritance
User (1st): "split pages 1-5"
Files: document.pdf
Response: output.pdf (pages 1-5)

User (2nd): "convert to docx"
Files: (implicit: output.pdf from previous)

Flow:

1. Inherit context? Yes (short follow-up ≤5 tokens)
2. Expand: "convert the extracted pages from document.pdf to DOCX"
3. Correct typos? No
4. Stage 1 parse: Intent=convert, Parameters={target_format: docx}, Confidence=0.85, Ambiguity=MEDIUM
5. Pipeline: convert_to_docx
6. File type check: PDF → convert_to_docx = OK
7. Execute: pdf_to_docx("output.pdf")
8. Response: success + output_file

WORKFLOW 3: Conflicting Operations (auto-fix)
User: "split pages 1-5 then merge"
Files: document.pdf

Flow:

1. No context inheritance
2. No typos
3. Stage 1 parse: Operations=[split, merge], Confidence=0.6, Ambiguity=HIGH
4. Conflict detection: split + merge = reorder execution
5. Optimized order: [merge, split] (merge first doesn't make sense for single file)
6. Ask clarification or skip merge

WORKFLOW 4: File Type Incompatibility (block)
User: "ocr this docx"
Files: document.docx

Flow:

1. No context inheritance
2. No typos
3. Stage 1 parse: Intent=ocr, Confidence=0.8, Ambiguity=MEDIUM
4. File type check: DOCX → ocr = BLOCK
5. Response: error "OCR supports scanned PDFs or images only"

WORKFLOW 5: Typo Correction (auto-fix)
User: "compres this pdf"
Files: document.pdf

Flow:

1. No context inheritance
2. Correct typos: "compres" → "compress"
3. Corrected prompt: "compress this pdf"
4. Stage 1 parse: Intent=compress, Confidence=0.95, Ambiguity=LOW
5. Execute: compress_pdf()
6. Response: success

"""

# Summary: All these systems work together to:

# 1. Normalize user input (typos, shorthand, context)

# 2. Understand intent with confidence and ambiguity scores

# 3. Validate against file types and operation compatibility

# 4. Organize operations into optimized pipelines

# 5. Execute with error handling and recovery

# 6. Never show raw errors to users
