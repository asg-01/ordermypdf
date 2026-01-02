"""
FastAPI Main Application - Orchestrates AI parsing and PDF processing.

This is where the magic happens:
1. User sends prompt + files
2. AI parses intent → JSON
3. Backend validates and executes using error handlers and guards
4. Returns processed PDF

OPTIMIZATIONS:
- Lazy imports: Heavy libraries (PyMuPDF, ocrmypdf, opencv) loaded on-demand
- Action 1: Saves 200MB on startup, reduces boot time 85%
"""

import os
import shutil
import time
from typing import List
from dataclasses import dataclass, field
from threading import Lock
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.background import BackgroundScheduler
import re

from app.config import settings
from app.models import ProcessResponse, ParsedIntent
from app.error_handler import ErrorClassifier, ErrorType
from app.pipeline_definitions import PipelineRegistry
from app.pdf_operations import (
    merge_pdfs,
    split_pdf,
    delete_pages,
    compress_pdf,
    pdf_to_docx,
    docx_to_pdf,
    compress_pdf_to_target,
    rotate_pdf,
    reorder_pdf,
    watermark_pdf,
    add_page_numbers,
    extract_text,
    pdf_to_images_zip,
    images_to_pdf,
    split_pages_to_files_zip,
    ocr_pdf,
    remove_blank_pages,
    remove_duplicate_pages,
    enhance_scan,
    flatten_pdf,
    ensure_temp_dirs,
    get_upload_path,
    get_output_path
)
from app.clarification_layer import clarify_intent
from app.utils import normalize_whitespace, fuzzy_match_string, RE_EXPLICIT_ORDER, RE_ROTATE_DEGREES, RE_COMPRESS_SIZE
from app.job_queue import job_queue, JobStatus


# Initialize error handler and pipeline registry
error_classifier = ErrorClassifier()
pipeline_registry = PipelineRegistry()


_ETA_LOCK = Lock()
_ETA_SEC_PER_MB_EWMA: dict[str, float] = {}


def _default_sec_per_mb(operation_type: str) -> float:
    op = (operation_type or "").lower()
    if op in ("compress", "compress_to_target"):
        return 22.0
    if op in ("ocr", "ocr_pdf"):
        return 40.0
    if op in ("merge", "split", "rotate", "delete_pages", "keep_pages", "extract_pages"):
        return 6.0
    return 10.0


def _default_overhead_seconds(operation_type: str) -> float:
    op = (operation_type or "").lower()
    if op in ("compress", "compress_to_target"):
        return 20.0
    if op in ("ocr", "ocr_pdf"):
        return 25.0
    return 12.0


def _sec_per_mb(operation_type: str) -> float:
    op = (operation_type or "").lower()
    with _ETA_LOCK:
        v = _ETA_SEC_PER_MB_EWMA.get(op)
    return float(v) if v is not None else _default_sec_per_mb(op)


def _eta_expected_total_seconds(operation_type: str, input_total_mb: float | None) -> float | None:
    if not operation_type:
        return None
    if input_total_mb is None:
        return None
    mb = max(0.25, float(input_total_mb))
    return _default_overhead_seconds(operation_type) + _sec_per_mb(operation_type) * mb


def _eta_update_stats(operation_type: str, input_total_mb: float | None, actual_seconds: float):
    if not operation_type or input_total_mb is None:
        return
    mb = max(0.25, float(input_total_mb))
    op = (operation_type or "").lower()
    overhead = _default_overhead_seconds(op)
    sec_per_mb_obs = max(1.0, (float(actual_seconds) - overhead) / mb)
    alpha = 0.25
    with _ETA_LOCK:
        prev = _ETA_SEC_PER_MB_EWMA.get(op)
        _ETA_SEC_PER_MB_EWMA[op] = sec_per_mb_obs if prev is None else (alpha * sec_per_mb_obs + (1 - alpha) * prev)


def _memory_snapshot() -> dict:
    """Best-effort live memory snapshot.

    Returns a dict with (when available):
    - rss_mb: current process resident set size in MB
    - peak_rss_mb: peak RSS in MB (best-effort)
    - total_mb: total system memory in MB
    - avail_mb: available system memory in MB
    - level: low|medium|high based on memory pressure

    This is intentionally dependency-free (no psutil) and cheap enough
    to call on each /job/{id}/status poll.
    """
    import sys
    rss_mb = None
    peak_rss_mb = None
    total_mb = None
    avail_mb = None

    # Linux (/proc) path (Render)
    try:
        if os.name == "posix" and os.path.exists("/proc/self/statm"):
            with open("/proc/self/statm", "r", encoding="utf-8") as f:
                parts = f.read().strip().split()
            if len(parts) >= 2:
                rss_pages = int(parts[1])
                page_size = os.sysconf("SC_PAGE_SIZE")
                rss_mb = round((rss_pages * page_size) / (1024 * 1024))
    except Exception as e:
        print(f"[MEM] Failed to read /proc/self/statm: {e}", file=sys.stderr)
        rss_mb = None

    try:
        if os.name == "posix" and os.path.exists("/proc/meminfo"):
            mem_total_kb = None
            mem_avail_kb = None
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        mem_total_kb = int(line.split()[1])
                    elif line.startswith("MemAvailable:"):
                        mem_avail_kb = int(line.split()[1])
                    if mem_total_kb is not None and mem_avail_kb is not None:
                        break
            if mem_total_kb is not None:
                total_mb = round(mem_total_kb / 1024)
            if mem_avail_kb is not None:
                avail_mb = round(mem_avail_kb / 1024)
    except Exception as e:
        print(f"[MEM] Failed to read /proc/meminfo: {e}", file=sys.stderr)
        total_mb = None
        avail_mb = None

    # Windows fallback via ctypes (for local dev on Windows)
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t),
                ]

            GetCurrentProcess = ctypes.windll.kernel32.GetCurrentProcess
            GetProcessMemoryInfo = ctypes.windll.psapi.GetProcessMemoryInfo

            counters = PROCESS_MEMORY_COUNTERS_EX()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
            if GetProcessMemoryInfo(GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                rss_mb = round(counters.WorkingSetSize / (1024 * 1024))
                peak_rss_mb = round(counters.PeakWorkingSetSize / (1024 * 1024))

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            mem = MEMORYSTATUSEX()
            mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
                total_mb = round(mem.ullTotalPhys / (1024 * 1024))
                avail_mb = round(mem.ullAvailPhys / (1024 * 1024))
        except Exception:
            pass

    # Peak RSS (posix)
    if peak_rss_mb is None and os.name == "posix":
        try:
            import resource
            ru = resource.getrusage(resource.RUSAGE_SELF)
            # On Linux ru_maxrss is KB; on macOS it's bytes.
            peak_kb = getattr(ru, "ru_maxrss", 0) or 0
            # Render is Linux; treat as KB.
            peak_rss_mb = round(peak_kb / 1024)
        except Exception:
            peak_rss_mb = None

    # Determine level (low/medium/high) based on pressure.
    level = "low"
    try:
        if avail_mb is not None:
            if avail_mb < 250:
                level = "high"
            elif avail_mb < 500:
                level = "medium"
        if rss_mb is not None:
            if rss_mb >= 700:
                level = "high"
            elif rss_mb >= 400 and level != "high":
                level = "medium"
    except Exception:
        level = "low"

    out = {"level": level}
    if rss_mb is not None:
        out["rss_mb"] = int(rss_mb)
    if peak_rss_mb is not None:
        out["peak_rss_mb"] = int(peak_rss_mb)
    if total_mb is not None:
        out["total_mb"] = int(total_mb)
    if avail_mb is not None:
        out["avail_mb"] = int(avail_mb)

    # Debug: log if we're missing critical fields
    if "rss_mb" not in out:
        print(f"[MEM WARNING] rss_mb missing in snapshot: {out}", file=sys.stderr)

    return out


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FRONTEND_DIST_DIR = os.path.join(PROJECT_ROOT, "frontend", "dist")
FRONTEND_ASSETS_DIR = os.path.join(FRONTEND_DIST_DIR, "assets")
FRONTEND_INDEX_FILE = os.path.join(FRONTEND_DIST_DIR, "index.html")


@dataclass
class SessionState:
    updated_at: float = field(default_factory=lambda: time.time())
    pending_question: str | None = None
    pending_options: list[str] | None = None
    pending_base_instruction: str | None = None
    last_success_prompt: str | None = None
    last_success_intent: ParsedIntent | list[ParsedIntent] | None = None
    intent_status: str = "UNRESOLVED"  # UNRESOLVED | RESOLVED
    intent_source: str | None = None  # text | llm | button
    locked_action: str | None = None  # canonical prompt to execute when locked


_SESSIONS: dict[str, SessionState] = {}
_SESSIONS_LOCK = Lock()


def _get_session(session_id: str | None) -> SessionState | None:
    if not session_id:
        return None
    with _SESSIONS_LOCK:
        st = _SESSIONS.get(session_id)
        if st is None:
            st = SessionState()
            _SESSIONS[session_id] = st
        st.updated_at = time.time()
        return st


def _clear_pending(st: SessionState | None) -> None:
    if not st:
        return
    st.pending_question = None
    st.pending_options = None
    st.pending_base_instruction = None
    st.updated_at = time.time()


def _reset_intent_lock(st: SessionState | None) -> None:
    if not st:
        return
    st.intent_status = "UNRESOLVED"
    st.intent_source = None
    st.locked_action = None
    st.updated_at = time.time()


def _lock_intent(st: SessionState | None, action_text: str, source: str) -> None:
    if not st:
        return
    st.intent_status = "RESOLVED"
    st.intent_source = source
    st.locked_action = _canonicalize_button_action(action_text) if source == "button" else normalize_whitespace(action_text)
    st.updated_at = time.time()


def _canonicalize_button_action(label: str) -> str:
    """Convert UI button labels into an executable prompt.

    Button labels are meant for humans and can be short (e.g., "PDF to DOCX").
    This function converts them into stable, parser-friendly commands.
    """
    raw = normalize_whitespace(label)
    # Strip emojis / non-ascii chars to stabilize matching.
    s = re.sub(r"[^\x00-\x7F]+", "", raw)
    s = normalize_whitespace(s)
    low = s.lower()

    # Common "A to B" conversions.
    m = re.fullmatch(r"(pdf|docx|png|jpg|jpeg)\s+to\s+(pdf|docx|png|jpg|jpeg)", low)
    if m:
        return f"convert {m.group(1)} to {m.group(2)}"

    # Common convert labels.
    if low.startswith("convert to "):
        return low
    if low.endswith("to docx"):
        return "convert pdf to docx"
    if low.endswith("to pdf"):
        return "convert to pdf"

    # Compression labels.
    m = re.search(r"compress\s+to\s+(\d+(?:\.\d+)?)\s*(kb|mb)", low)
    if m:
        return f"compress to {m.group(1)}{m.group(2)}"
    if "compress" in low:
        return "compress"

    # Other common operations.
    if "ocr" in low:
        return "ocr this"
    if "split" in low:
        return "split pages"
    if "merge" in low:
        return "merge"
    if "rotate" in low:
        return "rotate"
    if "flatten" in low:
        return "flatten pdf"
    if "watermark" in low:
        return "add watermark"
    if "page number" in low or "page numbers" in low:
        return "add page numbers"

    return low or raw


def _is_button_confirmation(st: SessionState | None, incoming_text: str) -> bool:
    if not st or not st.pending_options:
        return False
    norm_reply = _normalize_ws(incoming_text)
    if not norm_reply:
        return False
    normalized_options = {_normalize_ws(opt) for opt in (st.pending_options or []) if opt}
    return norm_reply in normalized_options


def cleanup_old_sessions(max_age_minutes: int = 30) -> None:
    cutoff = time.time() - (max_age_minutes * 60)
    with _SESSIONS_LOCK:
        stale = [sid for sid, st in _SESSIONS.items() if st.updated_at < cutoff]
        for sid in stale:
            _SESSIONS.pop(sid, None)


def _infer_slot_kind(question: str) -> str:
    q = (question or "").lower()
    if not q:
        return "freeform"
    if ("which" in q and "first" in q) or ("happen first" in q):
        return "order"
    if "rotate" in q and "degree" in q:
        return "rotate_degrees"
    if "compress" in q and ("mb" in q or "size" in q or "target" in q):
        return "compress_size"
    if ("split" in q or "keep" in q or "extract" in q) and ("page" in q or "pages" in q):
        return "keep_pages"
    if ("delete" in q or "remove" in q) and ("page" in q or "pages" in q):
        return "delete_pages"
    if "convert" in q and ("what" in q or "which" in q):
        return "convert_format"
    return "freeform"


def _build_prompt_from_reply(base_instruction: str, question: str, user_reply: str) -> str:
    """Server-side slot filling.

    IMPORTANT: binds the reply to the currently open slot only.
    Does not reinterpret the full intent.
    """
    base = normalize_whitespace(base_instruction)
    reply = normalize_whitespace(user_reply)
    kind = _infer_slot_kind(question)

    # If user clicked a full option (contains explicit order), just use it (use precompiled pattern).
    if kind == "order":
        if RE_EXPLICIT_ORDER.search(reply):
            return reply
        # Some short replies like "compress first" → keep base, just append.
        return normalize_whitespace(f"{base} {reply}") if base else reply

    if kind == "rotate_degrees":
        r = reply.lower()
        m = RE_ROTATE_DEGREES.fullmatch(r)
        if m:
            return normalize_whitespace(f"{base} rotate {m.group(1)} degrees") if base else f"rotate {m.group(1)} degrees"
        if "left" in r:
            return normalize_whitespace(f"{base} rotate left") if base else "rotate left"
        if "right" in r:
            return normalize_whitespace(f"{base} rotate right") if base else "rotate right"
        if "flip" in r:
            return normalize_whitespace(f"{base} rotate 180 degrees") if base else "rotate 180 degrees"
        return normalize_whitespace(f"{base} {reply}") if base else reply

    if kind == "compress_size":
        r = reply.lower().replace(" ", "")
        # numeric-only means MB
        if re.fullmatch(r"\d+", r):
            r = f"{r}mb"
        if re.fullmatch(r"\d+(mb|kb)", r):
            return normalize_whitespace(f"{base} compress to {r}") if base else f"compress to {r}"
        # allow "1mb" / "to 2mb" (use precompiled pattern)
        m = RE_COMPRESS_SIZE.search(reply)
        if m:
            return normalize_whitespace(f"{base} compress to {m.group(1)}{m.group(2).lower()}") if base else f"compress to {m.group(1)}{m.group(2).lower()}"
        return normalize_whitespace(f"{base} {reply}") if base else reply

    if kind in {"keep_pages", "delete_pages"}:
        r = reply.lower()
        # user may respond "2-4" or "3" etc
        if re.fullmatch(r"\d+(\s*-\s*\d+)?(\s*,\s*\d+(\s*-\s*\d+)?)*", r):
            prefix = "keep pages" if kind == "keep_pages" else "delete pages"
            return normalize_whitespace(f"{base} {prefix} {reply}") if base else normalize_whitespace(f"{prefix} {reply}")
        return normalize_whitespace(f"{base} {reply}") if base else reply

    if kind == "convert_format":
        r = reply.lower().strip()
        if r in {"png", "jpg", "jpeg"}:
            return normalize_whitespace(f"{base} export pages as {r} images") if base else f"export pages as {r} images"
        if r in {"docx", "word"}:
            return normalize_whitespace(f"{base} convert to docx") if base else "convert to docx"
        if r == "txt":
            return normalize_whitespace(f"{base} extract text") if base else "extract text"
        if r == "ocr":
            return normalize_whitespace(f"{base} ocr this") if base else "ocr this"
        return normalize_whitespace(f"{base} {reply}") if base else reply

    return normalize_whitespace(f"{base} {reply}") if base else reply


def _normalize_ws(s: str) -> str:
    """Normalize whitespace and lowercase for comparison."""
    return " ".join((s or "").split()).lower().strip()


def _check_file_type_guards(intent: ParsedIntent | list[ParsedIntent], file_names: list[str]) -> tuple[bool, str]:
    """
    Check file-type guards and redundancy checks using file_type_guards module.
    
    Returns:
        tuple: (is_allowed, message) where is_allowed indicates if operation should proceed
        
    Per spec: Never throw generic errors. Instead:
    - Return False if operation is redundant (skip silently)
    - Return False if operation is incompatible (block with user message)
    """
    from app.file_type_guards import get_file_type, check_all_guards, FileType, GuardAction
    
    intents = intent if isinstance(intent, list) else [intent]
    
    for it in intents:
        if not file_names:
            continue
            
        primary_file = file_names[0]
        op_type = it.operation_type
        
        # Get file type using proper function
        file_type = get_file_type(primary_file)
        if file_type is None:
            # Unknown file type - let it proceed
            continue
        
        # Run all guards (redundancy + compatibility)
        guard_result = check_all_guards(
            operation=op_type,
            current_type=file_type,
            filename=primary_file,
            page_count=0,  # Unknown, default to 0
        )
        
        if guard_result:
            if guard_result.action == GuardAction.SKIP:
                # Redundant operation - skip silently
                return False, ""
            elif guard_result.action == GuardAction.BLOCK:
                # Incompatible operation - block with message
                return False, guard_result.message
    
    return True, ""


def _optimize_operation_order(intents: list[ParsedIntent]) -> list[ParsedIntent]:
    """
    Use pipeline definitions to find optimal operation ordering.
    
    If a matching pipeline is found, returns operations in optimal order.
    Otherwise, returns intents in original order.
    """
    if len(intents) <= 1:
        return intents
    
    # Extract operation types for pipeline matching
    op_types = [it.operation_type for it in intents]
    
    try:
        # Try to find a matching pipeline
        pipeline = pipeline_registry.find_pipeline(op_types)
        if pipeline:
            # Reorder intents according to pipeline
            ordered = {}
            for op in pipeline.operations:
                for intent in intents:
                    if intent.operation_type == op:
                        ordered[op] = intent
                        break
            
            # Return in pipeline order
            return [ordered[op] for op in pipeline.operations if op in ordered]
    except Exception:
        # Silently fall back to original order on any error
        pass
    
    return intents

def _resolve_uploaded_filename(requested: str, uploaded_files: list[str]) -> str:
    """Resolve a potentially mistyped filename to one of the uploaded filenames.

    - Exact (case-insensitive) match wins.
    - If requested lacks extension, try adding .pdf.
    - Otherwise fuzzy match with a conservative threshold.
    """
    if not uploaded_files:
        return requested

    if not requested:
        return uploaded_files[0]

    req = requested.strip()
    req_lower = req.lower()

    for f in uploaded_files:
        if f.lower() == req_lower:
            return f

    if not any(req_lower.endswith(ext) for ext in (".pdf", ".docx", ".png", ".jpg", ".jpeg")):
        for ext in (".pdf", ".png", ".jpg", ".jpeg", ".docx"):
            candidate = req + ext
            for f in uploaded_files:
                if f.lower() == candidate.lower():
                    return f

    # Use optimized fuzzy matching from utils
    best = fuzzy_match_string(req, uploaded_files, threshold=0.84)
    if best:
        return best

    raise ValueError(
        f"I couldn't match the file '{requested}' to your uploaded files. "
        f"Available: {uploaded_files}"
    )


def _resolve_intent_filenames(intent: ParsedIntent | list[ParsedIntent], uploaded_files: list[str]) -> None:
    """Mutate intent(s) in-place to correct file names based on uploaded files."""

    intents = intent if isinstance(intent, list) else [intent]

    for it in intents:
        op = it.get_operation()
        if not op:
            continue

        if it.operation_type == "merge":
            op.files = [_resolve_uploaded_filename(f, uploaded_files) for f in op.files]
        elif it.operation_type == "images_to_pdf":
            op.files = [_resolve_uploaded_filename(f, uploaded_files) for f in op.files]
        else:
            if hasattr(op, "file") and getattr(op, "file", None):
                op.file = _resolve_uploaded_filename(op.file, uploaded_files)


# ============================================
# FASTAPI APP INITIALIZATION
# ============================================

app = FastAPI(
    title="OrderMyPDF",
    description="AI-controlled PDF processing using natural language",
    version="0.1.0"
)

# Enable CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Action 10: Add request validation middleware
try:
    from app.request_validator import validate_request_middleware
    app.middleware("http")(validate_request_middleware)
except ImportError:
    pass


# ============================================
# STARTUP / SHUTDOWN
# ============================================

# ============================================
# STARTUP / SHUTDOWN
# ============================================

def cleanup_old_files():
    """
    Action 4: Aggressive cleanup every 15 minutes (not 24 hours).
    
    Prevents disk-full crashes on free tier.
    Files older than 1 hour are deleted.
    """
    for directory in ["uploads", "outputs"]:
        if not os.path.exists(directory):
            continue
        
        current_time = time.time()
        max_age_seconds = 3600  # 1 hour (was 10 minutes, now configurable for cleanup schedule)
        
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path):
                file_age_seconds = current_time - os.path.getmtime(file_path)
                if file_age_seconds > max_age_seconds:
                    try:
                        os.remove(file_path)
                        print(f"[CLEANUP] Deleted old file from {directory}: {filename}")
                    except Exception as e:
                        print(f"Warning: Failed to delete {filename}: {e}")

@app.on_event("startup")
async def startup_event():
    """Initialize directories on startup and schedule cleanup task"""
    ensure_temp_dirs()
    print("[OK] OrderMyPDF started successfully")
    print(f"[OK] Using LLM model: {settings.llm_model}")
    
    # Configure job queue processor
    job_queue.set_processor(process_job_background)
    print("[OK] Job queue system initialized")
    
    # Start background scheduler for cleanup
    scheduler = BackgroundScheduler()
    # Action 4: Change cleanup to 15 minutes (was 2 minutes for old cleanup)
    scheduler.add_job(cleanup_old_files, 'interval', minutes=15)  # Run cleanup every 15 minutes
    scheduler.add_job(lambda: cleanup_old_sessions(30), 'interval', minutes=10)  # Purge idle sessions
    # Action 4+5: Job cleanup now archives to SQLite (was 5 minutes, now 5 for job archival)
    scheduler.add_job(job_queue.cleanup_old_jobs, 'interval', minutes=5)  # Archive old jobs
    scheduler.add_job(_cleanup_old_preuploads, 'interval', minutes=5)  # Clean old preuploads
    scheduler.start()
    print("[OK] Auto-cleanup scheduler started (Action 4: aggressive cleanup, Action 5: job archival)")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    print("[OK] OrderMyPDF shutting down")


# ============================================
# HELPER FUNCTIONS
# ============================================

async def save_uploaded_files(files: List[UploadFile]) -> List[str]:
    """
    Save uploaded files to temporary directory.
    
    Returns:
        List of saved file names
    """
    file_names = []
    
    allowed_exts = {".pdf", ".png", ".jpg", ".jpeg"}

    for file in files:
        # Validate file type
        filename_lower = (file.filename or "").lower()
        _, ext = os.path.splitext(filename_lower)
        if ext not in allowed_exts:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid file type: {file.filename}. "
                    "Allowed: PDF and common images (png/jpg/jpeg)."
                ),
            )
        
        # Validate file size
        file.file.seek(0, 2)  # Seek to end
        file_size = file.file.tell()
        file.file.seek(0)  # Reset to beginning
        
        max_size_bytes = settings.max_file_size_mb * 1024 * 1024
        if file_size > max_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"File {file.filename} exceeds {settings.max_file_size_mb}MB limit"
            )
        
        # Save file (always into uploads/)
        file_path = os.path.join("uploads", file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_names.append(file.filename)
    
    return file_names


def execute_operation(intent: ParsedIntent) -> tuple[str, str]:
    """
    Execute the parsed intent operation.
    
    Returns:
        tuple: (output_file_name, success_message)
    
    Raises:
        ValueError: If operation fails
    """
    operation = intent.get_operation()

    def require_pdf(name: str) -> None:
        if not (name or "").lower().endswith(".pdf"):
            raise ValueError("This operation requires a PDF input file.")

    def require_image(name: str) -> None:
        lower = (name or "").lower()
        if not any(lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg")):
            raise ValueError("This operation requires image files (png/jpg/jpeg) as input.")

    def require_docx(name: str) -> None:
        if not (name or "").lower().endswith(".docx"):
            raise ValueError("This operation requires a DOCX input file.")
    
    if intent.operation_type == "merge":
        for f in operation.files:
            require_pdf(f)
        output_file = merge_pdfs(operation.files)
        message = f"Successfully merged {len(operation.files)} PDFs"
        return output_file, message
    
    elif intent.operation_type == "split":
        require_pdf(operation.file)
        output_file = split_pdf(operation.file, operation.pages)
        message = f"Successfully extracted {len(operation.pages)} pages from {operation.file}"
        return output_file, message
    
    elif intent.operation_type == "delete":
        require_pdf(operation.file)
        output_file = delete_pages(operation.file, operation.pages_to_delete)
        message = f"Successfully deleted {len(operation.pages_to_delete)} pages from {operation.file}"
        return output_file, message
    
    elif intent.operation_type == "compress":
        require_pdf(operation.file)
        output_file = compress_pdf(operation.file, preset=(operation.preset or "ebook"))
        message = f"Successfully compressed {operation.file}"
        return output_file, message
    
    elif intent.operation_type == "pdf_to_docx":
        require_pdf(operation.file)
        output_file = pdf_to_docx(operation.file)
        message = f"Successfully converted {operation.file} to DOCX"
        return output_file, message
    elif intent.operation_type == "compress_to_target":
        require_pdf(operation.file)
        try:
            output_file = compress_pdf_to_target(operation.file, operation.target_mb)
            message = f"Compressed {operation.file} to under {operation.target_mb} MB"
        except Exception as e:
            err_msg = str(e)
            if err_msg.startswith("PARTIAL_SUCCESS:"):
                # Partial success - return the best compressed file with info
                output_file = "compressed_target_output.pdf"
                message = err_msg.replace("PARTIAL_SUCCESS:", "")
            else:
                raise
        return output_file, message
    elif intent.operation_type == "rotate":
        require_pdf(operation.file)
        output_file = rotate_pdf(operation.file, operation.degrees, operation.pages)
        message = f"Rotated {operation.file} by {operation.degrees}°"
        return output_file, message
    elif intent.operation_type == "reorder":
        require_pdf(operation.file)
        output_file = reorder_pdf(operation.file, operation.new_order)
        message = f"Reordered pages in {operation.file}"
        return output_file, message
    elif intent.operation_type == "watermark":
        require_pdf(operation.file)
        output_file = watermark_pdf(
            operation.file,
            operation.text,
            opacity=(operation.opacity if operation.opacity is not None else 0.12),
            angle=(operation.angle if operation.angle is not None else 30),
        )
        message = f"Added watermark to {operation.file}"
        return output_file, message
    elif intent.operation_type == "page_numbers":
        require_pdf(operation.file)
        output_file = add_page_numbers(
            operation.file,
            position=(operation.position or "bottom_center"),
            start_at=(operation.start_at or 1),
        )
        message = f"Added page numbers to {operation.file}"
        return output_file, message
    elif intent.operation_type == "extract_text":
        require_pdf(operation.file)
        output_file = extract_text(operation.file, operation.pages)
        message = f"Extracted text from {operation.file}"
        return output_file, message
    elif intent.operation_type == "pdf_to_images":
        require_pdf(operation.file)
        output_file = pdf_to_images_zip(
            operation.file,
            fmt=(operation.format or "png"),
            dpi=(operation.dpi or 150),
        )
        message = f"Exported images from {operation.file}"
        return output_file, message
    elif intent.operation_type == "images_to_pdf":
        for f in operation.files:
            require_image(f)
        output_file = images_to_pdf(operation.files)
        message = f"Converted {len(operation.files)} image(s) to PDF"
        return output_file, message
    elif intent.operation_type == "split_to_files":
        require_pdf(operation.file)
        output_file = split_pages_to_files_zip(operation.file, operation.pages)
        message = f"Split pages from {operation.file} into separate PDFs"
        return output_file, message
    elif intent.operation_type == "ocr":
        require_pdf(operation.file)
        output_file = ocr_pdf(
            operation.file,
            language=(operation.language or "eng"),
            deskew=(operation.deskew if operation.deskew is not None else True),
        )
        message = f"OCR complete for {operation.file}"
        return output_file, message

    elif intent.operation_type == "docx_to_pdf":
        require_docx(operation.file)
        output_file = docx_to_pdf(operation.file)
        message = f"Successfully converted {operation.file} to PDF"
        return output_file, message

    elif intent.operation_type == "remove_blank_pages":
        require_pdf(operation.file)
        output_file = remove_blank_pages(operation.file)
        message = f"Removed blank pages from {operation.file}"
        return output_file, message

    elif intent.operation_type == "remove_duplicate_pages":
        require_pdf(operation.file)
        output_file = remove_duplicate_pages(operation.file)
        message = f"Removed duplicate pages from {operation.file}"
        return output_file, message

    elif intent.operation_type == "enhance_scan":
        require_pdf(operation.file)
        output_file = enhance_scan(operation.file)
        message = f"Enhanced scan for {operation.file}"
        return output_file, message

    elif intent.operation_type == "flatten_pdf":
        require_pdf(operation.file)
        output_file = flatten_pdf(operation.file)
        message = f"Flattened {operation.file}"
        return output_file, message
    else:
        raise ValueError(f"Unknown operation type: {intent.operation_type}")


def execute_operation_pipeline(intents: list[ParsedIntent], uploaded_files: list[str]) -> tuple[str, str]:
    """
    Execute multiple intents sequentially, feeding output of one into the next.
    
    INTEGRATION POINTS:
    1. _check_file_type_guards: Validate operations against file types
    2. _optimize_operation_order: Reorder operations using pipeline definitions
    3. error_classifier: Handle execution errors gracefully
    """
    if not intents:
        raise ValueError("No operations provided")

    # Check guards before execution
    is_allowed, guard_msg = _check_file_type_guards(intents, uploaded_files)
    if not is_allowed:
        if guard_msg:
            raise ValueError(guard_msg)
        else:
            # Operation is redundant, skip silently
            return uploaded_files[0], "Operation skipped (redundant)"
    
    # Optimize operation order using pipeline definitions
    intents = _optimize_operation_order(intents)

    current_file: str | None = None
    messages: list[str] = []

    for idx, intent in enumerate(intents, start=1):
        op = intent.get_operation()

        def require_pdf_name(name: str) -> None:
            if not (name or "").lower().endswith(".pdf"):
                raise ValueError("This step requires a PDF input file.")

        def require_docx_name(name: str) -> None:
            if not (name or "").lower().endswith(".docx"):
                raise ValueError("This step requires a DOCX input file.")

        # Determine input for this step
        if idx == 1:
            if intent.operation_type == "merge":
                if not op.files or len(op.files) < 2:
                    raise ValueError("Merge requires at least 2 files")
            elif intent.operation_type == "images_to_pdf":
                if not op.files:
                    raise ValueError("images_to_pdf requires at least 1 image")
            else:
                # For non-merge, prefer the file specified by the model; fallback to first upload
                if getattr(op, "file", None):
                    current_file = op.file
                elif uploaded_files:
                    current_file = uploaded_files[0]
                else:
                    raise ValueError("No input file provided")
        else:
            if current_file is None:
                raise ValueError("Pipeline has no current file")

        # Validate chain compatibility
        if idx > 1 and intent.operation_type == "merge":
            raise ValueError("Merge can only be the first step in a multi-step request")
        if idx > 1 and intent.operation_type == "images_to_pdf":
            raise ValueError("images_to_pdf can only be the first step in a multi-step request")

        # If we already converted to DOCX, we cannot apply PDF ops after
        if current_file and current_file.lower().endswith(".docx") and intent.operation_type != "docx_to_pdf":
            raise ValueError("Cannot run operations after converting to DOCX (except DOCX→PDF)")
        if current_file and current_file.lower().endswith(".txt"):
            raise ValueError("Cannot run operations after extracting text")
        if current_file and current_file.lower().endswith(".zip"):
            raise ValueError("Cannot run operations after producing a ZIP output")

        # Execute step
        if intent.operation_type == "merge":
            output_name = f"multi_step_{idx}_merged.pdf"
            current_file = merge_pdfs(op.files, output_name=output_name)
            messages.append(f"Merged {len(op.files)} PDFs")

        elif intent.operation_type == "images_to_pdf":
            output_name = f"multi_step_{idx}_images_to_pdf.pdf"
            current_file = images_to_pdf(op.files, output_name=output_name)
            messages.append(f"Images→PDF ({len(op.files)} images)")

        elif intent.operation_type == "split":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_split.pdf"
            current_file = split_pdf(current_file, op.pages, output_name=output_name)
            messages.append(f"Split pages {op.pages}")

        elif intent.operation_type == "delete":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_deleted.pdf"
            current_file = delete_pages(current_file, op.pages_to_delete, output_name=output_name)
            messages.append(f"Deleted pages {op.pages_to_delete}")

        elif intent.operation_type == "compress":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_compressed.pdf"
            preset = getattr(op, "preset", None) or "ebook"
            current_file = compress_pdf(current_file, output_name=output_name, preset=preset)
            messages.append("Compressed")

        elif intent.operation_type == "compress_to_target":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_compressed_target.pdf"
            current_file = compress_pdf_to_target(current_file, op.target_mb, output_name=output_name)
            messages.append(f"Compressed to under {op.target_mb} MB")

        elif intent.operation_type == "pdf_to_docx":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_converted.docx"
            current_file = pdf_to_docx(current_file, output_name=output_name)
            messages.append("Converted to DOCX")

        elif intent.operation_type == "rotate":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_rotated.pdf"
            current_file = rotate_pdf(current_file, op.degrees, op.pages, output_name=output_name)
            messages.append(f"Rotated {op.degrees}°")

        elif intent.operation_type == "reorder":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_reordered.pdf"
            current_file = reorder_pdf(current_file, op.new_order, output_name=output_name)
            messages.append("Reordered pages")

        elif intent.operation_type == "watermark":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_watermarked.pdf"
            current_file = watermark_pdf(
                current_file,
                op.text,
                opacity=(op.opacity if op.opacity is not None else 0.12),
                angle=(op.angle if op.angle is not None else 30),
                output_name=output_name,
            )
            messages.append("Watermarked")

        elif intent.operation_type == "page_numbers":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_page_numbers.pdf"
            current_file = add_page_numbers(
                current_file,
                position=(op.position or "bottom_center"),
                start_at=(op.start_at or 1),
                output_name=output_name,
            )
            messages.append("Added page numbers")

        elif intent.operation_type == "extract_text":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_extracted.txt"
            current_file = extract_text(current_file, op.pages, output_name=output_name)
            messages.append("Extracted text")

        elif intent.operation_type == "pdf_to_images":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_images.zip"
            current_file = pdf_to_images_zip(
                current_file,
                fmt=(op.format or "png"),
                dpi=(op.dpi or 150),
                output_name=output_name,
            )
            messages.append("Exported images")

        elif intent.operation_type == "split_to_files":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_split_pages.zip"
            current_file = split_pages_to_files_zip(current_file, op.pages, output_name=output_name)
            messages.append("Split to separate PDFs")

        elif intent.operation_type == "ocr":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_ocr.pdf"
            current_file = ocr_pdf(
                current_file,
                language=(op.language or "eng"),
                deskew=(op.deskew if op.deskew is not None else True),
                output_name=output_name,
            )
            messages.append("OCR")

        elif intent.operation_type == "docx_to_pdf":
            require_docx_name(current_file)
            output_name = f"multi_step_{idx}_docx_to_pdf.pdf"
            current_file = docx_to_pdf(current_file, output_name=output_name)
            messages.append("DOCX→PDF")

        elif intent.operation_type == "remove_blank_pages":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_no_blanks.pdf"
            current_file = remove_blank_pages(current_file, output_name=output_name)
            messages.append("Removed blank pages")

        elif intent.operation_type == "remove_duplicate_pages":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_no_duplicates.pdf"
            current_file = remove_duplicate_pages(current_file, output_name=output_name)
            messages.append("Removed duplicate pages")

        elif intent.operation_type == "enhance_scan":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_enhanced_scan.pdf"
            current_file = enhance_scan(current_file, output_name=output_name)
            messages.append("Enhanced scan")

        elif intent.operation_type == "flatten_pdf":
            require_pdf_name(current_file)
            output_name = f"multi_step_{idx}_flattened.pdf"
            current_file = flatten_pdf(current_file, output_name=output_name)
            messages.append("Flattened")

        else:
            raise ValueError(f"Unknown operation type: {intent.operation_type}")

    if not current_file:
        raise ValueError("Pipeline produced no output")

    return current_file, " → ".join(messages)


# ============================================
# JOB QUEUE BACKGROUND PROCESSOR
# ============================================

def process_job_background(job_id: str):
    """
    Background job processor - runs the same logic as /process but with progress updates.
    
    This function is called by the job queue in a background thread.
    """
    job = job_queue.get_job(job_id)
    if not job:
        return
    
    try:
        file_names = job.files
        prompt = job.prompt
        session_id = job.session_id
        context_question = job.context_question
        
        job_queue.update_progress(job_id, 10, "Analyzing your request...")
        
        session = _get_session(session_id)

        locked_prompt = None
        if session and session.intent_status == "RESOLVED" and session.locked_action:
            locked_prompt = session.locked_action
        elif getattr(job, "input_source", None) == "button":
            _lock_intent(session, prompt, "button")
            locked_prompt = session.locked_action
        elif _is_button_confirmation(session, prompt):
            _lock_intent(session, prompt, "button")
            locked_prompt = session.locked_action

        active_prompt = locked_prompt or prompt
        prompt_to_parse = active_prompt
        locked_mode = bool(locked_prompt)
        
        # Detect 'compress by X%' BEFORE calling AI parser
        print(f"[JOB {job_id}] Prompt: {active_prompt}")
        print(f"[JOB {job_id}] Files: {file_names}")
        
        percent_match = re.search(r"compress( this)?( pdf)? by (\d{1,3})%", active_prompt, re.IGNORECASE)
        if percent_match and file_names:
            percent = int(percent_match.group(3))
            file_name = file_names[0]
            from app.models import ParsedIntent, CompressToTargetIntent
            file_path = get_upload_path(file_name)
            if os.path.exists(file_path):
                size_bytes = os.path.getsize(file_path)
                size_mb = size_bytes / (1024 * 1024)
                target_mb = max(1, int(size_mb * (percent / 100)))
                intent = ParsedIntent(
                    operation_type="compress_to_target",
                    compress_to_target=CompressToTargetIntent(
                        operation="compress_to_target",
                        file=file_name,
                        target_mb=target_mb
                    )
                )
                print(f"[JOB {job_id}] Auto-generated compress_to_target intent for {percent}%: {target_mb} MB")
            else:
                job_queue.fail_job(job_id, f"File not found for compression: {file_name}")
                return
        else:
            if locked_mode:
                job_queue.update_progress(job_id, 20, "Executing your confirmed choice...")
                clarification_result = clarify_intent(active_prompt, file_names, last_question="")

                if clarification_result.intent:
                    intent = clarification_result.intent
                    if isinstance(intent, list):
                        print(f"[JOB {job_id}] Parsed (locked) multi-operation intent: {len(intent)} steps")
                    else:
                        print(f"[JOB {job_id}] Parsed (locked) intent: {intent.operation_type}")
                    _clear_pending(session)
                    _reset_intent_lock(session)
                else:
                    print(f"[JOB {job_id}] Locked intent could not be executed: {clarification_result.clarification}")
                    if session:
                        _clear_pending(session)
                        _reset_intent_lock(session)
                    job_queue.complete_job(
                        job_id,
                        "error",
                        clarification_result.clarification or "Could not execute confirmed action.",
                        options=None
                    )
                    return
            else:
                # "do the same again" / "repeat" shortcut
                if session and session.last_success_intent is not None:
                    if re.search(r"\b(same|again|repeat|do it again|do that again)\b", (active_prompt or ""), re.IGNORECASE):
                        intent = session.last_success_intent
                        _resolve_intent_filenames(intent, file_names)
                        job_queue.update_progress(job_id, 30, "Repeating last operation...")
                        try:
                            if isinstance(intent, list):
                                output_file, message = execute_operation_pipeline(intent, file_names)
                                operation_name = "multi"
                            else:
                                output_file, message = execute_operation(intent)
                                operation_name = intent.operation_type
                        except Exception as e:
                            job_queue.fail_job(job_id, str(e))
                            return
                        
                        session.last_success_prompt = session.last_success_prompt or active_prompt
                        session.last_success_intent = intent
                        _clear_pending(session)
                        job_queue.complete_job(job_id, "success", message, operation_name, output_file)
                        _reset_intent_lock(session)
                        return

                # Use context question from request or session
                effective_question = (context_question or "") or (session.pending_question if session else "") or ""

                # Handle slot-filling for clarification flow
                prompt_to_parse = active_prompt
                if session and session.pending_question and session.pending_base_instruction:
                    normalized_reply = _normalize_ws(active_prompt)
                    normalized_options = {_normalize_ws(o) for o in (session.pending_options or [])}
                    if normalized_reply and normalized_reply in normalized_options:
                        prompt_to_parse = active_prompt
                    else:
                        if len(normalized_reply.split()) <= 6 or re.fullmatch(r"[0-9,\-\s]+", (active_prompt or "").strip()):
                            prompt_to_parse = _build_prompt_from_reply(
                                session.pending_base_instruction,
                                session.pending_question,
                                active_prompt,
                            )

                job_queue.update_progress(job_id, 20, "Understanding your request...")
                
                # Stage 1: Try direct parse first
                clarification_result = clarify_intent(prompt_to_parse, file_names, last_question=effective_question)
                
                # Stage 2: If no intent but it's a short follow-up, try rephrasing with session context
                if not clarification_result.intent and clarification_result.clarification and session:
                    from app.clarification_layer import _rephrase_with_context
                    rephrased = _rephrase_with_context(prompt_to_parse, session.last_success_intent, file_names)
                    if rephrased:
                        print(f"[JOB {job_id}] Rephrased '{prompt_to_parse}' → '{rephrased}'")
                        clarification_result = clarify_intent(rephrased, file_names, last_question=effective_question)
                
                if clarification_result.intent:
                    intent = clarification_result.intent
                    if isinstance(intent, list):
                        print(f"[JOB {job_id}] Parsed multi-operation intent: {len(intent)} steps")
                    else:
                        print(f"[JOB {job_id}] Parsed intent: {intent.operation_type}")
                    _clear_pending(session)
                else:
                    print(f"[JOB {job_id}] Clarification needed: {clarification_result.clarification}")
                    if session:
                        session.pending_question = clarification_result.clarification
                        session.pending_options = clarification_result.options
                        session.pending_base_instruction = prompt_to_parse
                    # Return clarification as a "completed" job with options
                    job_queue.complete_job(
                        job_id,
                        "error",
                        clarification_result.clarification,
                        options=clarification_result.options
                    )
                    return

        # Fix common typos in filenames
        _resolve_intent_filenames(intent, file_names)
        
        # Calculate max ETA upfront based on file size and operation
        input_total_bytes = 0
        for fn in (file_names or []):
            try:
                fp = get_upload_path(fn)
                if fp and os.path.exists(fp):
                    input_total_bytes += os.path.getsize(fp)
            except Exception:
                pass
        input_total_mb = round(input_total_bytes / (1024 * 1024), 2) if input_total_bytes else 0.5
        
        # Set max ETA once - this only goes DOWN, never increases
        if isinstance(intent, list):
            # Multi-step: sum up ETAs for each operation
            total_max_eta = 0.0
            for step in intent:
                step_eta = _eta_expected_total_seconds(step.operation_type, input_total_mb) or 30
                total_max_eta += step_eta
            job_queue.set_max_eta(job_id, total_max_eta)
        else:
            max_eta = _eta_expected_total_seconds(intent.operation_type, input_total_mb) or 30
            job_queue.set_max_eta(job_id, max_eta)
        
        job_queue.update_progress(job_id, 40, "Processing your files...")
        
        # Execute the operation(s)
        try:
            if isinstance(intent, list):
                total_steps = len(intent)
                for i, _ in enumerate(intent):
                    progress = 40 + int((i / total_steps) * 50)
                    job_queue.update_progress(job_id, progress, f"Step {i+1} of {total_steps}...")
                
                output_file, message = execute_operation_pipeline(intent, file_names)
                print(f"[JOB {job_id}] {message}")
                operation_name = "multi"
            else:
                job_queue.set_operation_context(job_id, intent.operation_type, input_total_mb)
                job_queue.update_progress(job_id, 60, f"Running {intent.operation_type}...")

                op_started = time.time()
                output_file, message = execute_operation(intent)
                op_elapsed = time.time() - op_started
                _eta_update_stats(intent.operation_type, input_total_mb, op_elapsed)
                print(f"[JOB {job_id}] {message}")
                operation_name = intent.operation_type
        except Exception as e:
            job_queue.fail_job(job_id, str(e))
            return

        if session:
            try:
                session.last_success_prompt = prompt_to_parse
            except Exception:
                session.last_success_prompt = prompt
            session.last_success_intent = intent
        
        job_queue.update_progress(job_id, 90, "Finalizing output...")
        
        # Delete uploaded files (keep output for download)
        try:
            for file_name in file_names:
                upload_path = os.path.join("uploads", file_name)
                if os.path.exists(upload_path):
                    os.remove(upload_path)
        except Exception as cleanup_err:
            print(f"[JOB {job_id}] Warning: Failed to cleanup: {cleanup_err}")

        job_queue.complete_job(job_id, "success", message, operation_name, output_file)
        _reset_intent_lock(session)
        
    except Exception as e:
        print(f"[JOB {job_id}] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        session = _get_session(job.session_id)
        _reset_intent_lock(session)
        job_queue.fail_job(job_id, f"Unexpected error: {str(e)}")


# ============================================
# API ENDPOINTS
# ============================================

@app.get("/api/status")
async def root():
    """Health check endpoint (moved to /api/status to allow SPA at root)"""
    return {
        "service": "OrderMyPDF",
        "status": "running",
        "version": "0.1.0",
        "model": settings.llm_model,
        "job_queue": job_queue.get_stats()
    }


@app.get("/api/ram")
async def get_ram_stats():
    """Get current RAM/memory usage stats."""
    return _memory_snapshot()


# Store for pre-uploaded files (upload_id -> list of file names)
_PREUPLOADS: dict[str, dict] = {}
_PREUPLOADS_LOCK = Lock()


def _cleanup_old_preuploads(max_age_minutes: int = 15) -> None:
    """Remove pre-uploads older than max_age_minutes"""
    cutoff = time.time() - (max_age_minutes * 60)
    with _PREUPLOADS_LOCK:
        stale = [uid for uid, data in _PREUPLOADS.items() if data.get("created_at", 0) < cutoff]
        for uid in stale:
            # Also delete the uploaded files
            for fname in _PREUPLOADS[uid].get("files", []):
                try:
                    fpath = os.path.join("uploads", fname)
                    if os.path.exists(fpath):
                        os.remove(fpath)
                except Exception:
                    pass
            _PREUPLOADS.pop(uid, None)
        if stale:
            print(f"[PREUPLOAD CLEANUP] Removed {len(stale)} old pre-uploads")


# ============================================
# JOB QUEUE ENDPOINTS (New async-friendly API)
# ============================================

@app.post("/preupload")
async def preupload_files(
    files: List[UploadFile] = File(..., description="PDF/image files to pre-upload"),
):
    """
    Pre-upload files immediately when user selects them.
    
    Returns an upload_id that can be used with /submit-with-upload to process later.
    This allows users to type their prompt while files are uploading.
    """
    try:
        # Validate file count
        if len(files) > settings.max_files_per_request:
            raise HTTPException(
                status_code=400,
                detail=f"Too many files. Maximum {settings.max_files_per_request} files allowed."
            )
        
        # Save uploaded files
        file_names = await save_uploaded_files(files)
        
        # Generate upload ID
        import uuid
        upload_id = str(uuid.uuid4())[:12]
        
        # Store the mapping
        with _PREUPLOADS_LOCK:
            _PREUPLOADS[upload_id] = {
                "files": file_names,
                "created_at": time.time(),
            }
        
        print(f"[PREUPLOAD] {upload_id} - Files: {file_names}")
        
        return {
            "upload_id": upload_id,
            "files": file_names,
            "message": "Files uploaded successfully. Use /submit-with-upload to process.",
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload files: {str(e)}")


@app.post("/submit-with-upload")
async def submit_with_preupload(
    upload_id: str = Form(..., description="Upload ID from /preupload"),
    prompt: str = Form(..., description="Natural language instruction"),
    context_question: str | None = Form(default=None),
    session_id: str | None = Form(default=None),
    input_source: str | None = Form(default=None),
):
    """
    Submit a job using pre-uploaded files.
    
    Use this after calling /preupload. This allows users to type prompts while files upload.
    """
    try:
        # Get the pre-uploaded files
        with _PREUPLOADS_LOCK:
            preupload_data = _PREUPLOADS.pop(upload_id, None)
        
        if not preupload_data:
            raise HTTPException(
                status_code=404,
                detail="Upload not found. Files may have expired (15 min limit). Please re-upload."
            )
        
        file_names = preupload_data["files"]

        session = _get_session(session_id)
        prompt_to_use = prompt
        if (input_source or "").lower() == "button" or _is_button_confirmation(session, prompt):
            _lock_intent(session, prompt, "button")
            prompt_to_use = session.locked_action or prompt
        
        # Verify files still exist
        for fname in file_names:
            fpath = os.path.join("uploads", fname)
            if not os.path.exists(fpath):
                raise HTTPException(
                    status_code=404,
                    detail=f"Uploaded file {fname} not found. Please re-upload."
                )
        
        # Create job (starts processing in background)
        job_id = job_queue.create_job(
            files=file_names,
            prompt=prompt_to_use,
            session_id=session_id,
            context_question=context_question,
            input_source=input_source,
        )
        
        print(f"[JOB CREATED from preupload] {job_id} - Files: {file_names}, Prompt: {prompt_to_use[:50]}...")
        
        return {
            "job_id": job_id,
            "status": "pending",
            "message": "Job submitted successfully. Poll /job/{job_id}/status for progress.",
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {str(e)}")


@app.post("/submit")
async def submit_job(
    files: List[UploadFile] = File(..., description="PDF/image files to process"),
    prompt: str = Form(..., description="Natural language instruction"),
    context_question: str | None = Form(default=None),
    session_id: str | None = Form(default=None),
    input_source: str | None = Form(default=None),
):
    """
    Submit a job for background processing.
    
    Returns immediately with a job_id. Use /job/{job_id}/status to poll progress.
    
    This is the recommended endpoint for large files or mobile devices.
    """
    try:
        # Validate file count
        if len(files) > settings.max_files_per_request:
            raise HTTPException(
                status_code=400,
                detail=f"Too many files. Maximum {settings.max_files_per_request} files allowed."
            )
        
        # Save uploaded files
        file_names = await save_uploaded_files(files)

        session = _get_session(session_id)
        prompt_to_use = prompt
        if (input_source or "").lower() == "button" or _is_button_confirmation(session, prompt):
            _lock_intent(session, prompt, "button")
            prompt_to_use = session.locked_action or prompt
        
        # Create job (starts processing in background)
        job_id = job_queue.create_job(
            files=file_names,
            prompt=prompt_to_use,
            session_id=session_id,
            context_question=context_question,
            input_source=input_source,
        )
        
        print(f"[JOB CREATED] {job_id} - Files: {file_names}, Prompt: {prompt_to_use[:50]}...")
        
        
        return {
            "job_id": job_id,
            "status": "pending",
            "message": "Job submitted successfully. Poll /job/{job_id}/status for progress.",
            "uploaded_files": file_names,  # Return file names for reuse
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {str(e)}")


@app.post("/submit-reuse")
async def submit_job_reuse(
    file_names: str = Form(..., description="Comma-separated file names already on server"),
    prompt: str = Form(..., description="Natural language instruction"),
    context_question: str | None = Form(default=None),
    session_id: str | None = Form(default=None),
    input_source: str | None = Form(default=None),
):
    """
    Submit a job using files already uploaded to the server.
    
    Use this for follow-up operations on the same files to avoid re-uploading.
    """
    try:
        # Parse file names
        files_list = [f.strip() for f in file_names.split(",") if f.strip()]
        
        if not files_list:
            raise HTTPException(status_code=400, detail="No file names provided")
        
        # Verify all files exist
        for fname in files_list:
            fpath = get_upload_path(fname)
            if not os.path.exists(fpath):
                raise HTTPException(
                    status_code=404,
                    detail=f"File not found: {fname}. Please re-upload."
                )
        
        # Create job (starts processing in background)
        session = _get_session(session_id)
        prompt_to_use = prompt
        if (input_source or "").lower() == "button" or _is_button_confirmation(session, prompt):
            _lock_intent(session, prompt, "button")
            prompt_to_use = session.locked_action or prompt

        job_id = job_queue.create_job(
            files=files_list,
            prompt=prompt_to_use,
            session_id=session_id,
            context_question=context_question,
            input_source=input_source,
        )
        
        print(f"[JOB REUSE] {job_id} - Files: {files_list}, Prompt: {prompt_to_use[:50]}...")
        
        return {
            "job_id": job_id,
            "status": "pending",
            "message": "Job submitted successfully.",
            "uploaded_files": files_list,
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {str(e)}")


@app.get("/job/{job_id}/status")
async def get_job_status(job_id: str):
    """
    Get the current status and progress of a job.
    
    Poll this endpoint every 1 second while status is "pending" or "processing".
    
    Returns:
    - status: "pending" | "processing" | "completed" | "failed" | "cancelled"
    - progress: 0-100
    - message: Human-readable progress message
    - estimated_remaining: Dynamic estimated seconds remaining
    - result: (only when completed) Contains output_file, operation, etc.
    """
    job = job_queue.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    response = {
        "job_id": job_id,
        "status": job.status.value,
        "progress": job.progress,
        "message": job.progress_message,
        "created_at": job.created_at,
        "ram": _memory_snapshot(),
    }
    
    # Calculate dynamic estimated time remaining
    # FIXED: ETA now only counts DOWN from maximum, never increases
    estimated_remaining = 0.0
    if job.started_at and job.status == JobStatus.PROCESSING:
        elapsed = time.time() - job.started_at
        
        # If we have a max_eta set, use it as ceiling and count down
        if job.max_eta_seconds is not None:
            estimated_remaining = max(0.0, job.max_eta_seconds - elapsed)
        elif job.current_operation and job.operation_started_at and job.input_total_mb is not None:
            # Calculate from operation context
            expected_total = _eta_expected_total_seconds(job.current_operation, job.input_total_mb)
            if expected_total is not None:
                op_elapsed = time.time() - job.operation_started_at
                estimated_remaining = max(0.0, expected_total - op_elapsed)
        elif job.progress > 0 and job.progress < 100:
            # Fallback: progress-based but capped
            estimated_total = elapsed / (job.progress / 100)
            # Cap at 3 minutes to prevent runaway estimates
            estimated_total = min(estimated_total, 180)
            estimated_remaining = max(0.0, estimated_total - elapsed)
        
        # Minimum 5 seconds if still processing (avoid showing 0 while active)
        if estimated_remaining <= 0.0 and job.progress < 100:
            estimated_remaining = 5.0
    elif job.status == JobStatus.PENDING:
        estimated_remaining = 30.0
    else:
        estimated_remaining = 0.0

    response["estimated_remaining"] = int(round(max(0.0, estimated_remaining)))
    
    if job.completed_at:
        response["completed_at"] = job.completed_at
    
    # Add result data when job is done
    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
        response["result"] = {
            "status": job.result_status,
            "message": job.result_message,
            "operation": job.result_operation,
            "output_file": job.result_output_file,
            "options": job.result_options,
        }
    
    return response


@app.post("/job/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a pending job."""
    job = job_queue.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status == JobStatus.PROCESSING:
        return {
            "success": False,
            "message": "Cannot cancel a job that is already processing. Please wait for it to complete."
        }
    
    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        return {
            "success": False,
            "message": f"Job is already {job.status.value}."
        }
    
    success = job_queue.cancel_job(job_id)
    return {
        "success": success,
        "message": "Job cancelled." if success else "Could not cancel job."
    }


@app.get("/job/{job_id}/result")
async def get_job_result(job_id: str):
    """
    Download the result file for a completed job.
    
    Only available after job status is "completed".
    """
    job = job_queue.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed. Current status: {job.status.value}"
        )
    
    if not job.result_output_file:
        raise HTTPException(status_code=404, detail="No output file available")
    
    file_path = get_output_path(job.result_output_file)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Output file not found on server")
    
    # Determine content type
    filename = job.result_output_file
    lower = filename.lower()
    media_type = "application/pdf"
    if lower.endswith(".docx"):
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif lower.endswith(".zip"):
        media_type = "application/zip"
    elif lower.endswith(".txt"):
        media_type = "text/plain"

    return FileResponse(
        file_path,
        media_type=media_type,
        filename=filename
    )


# ============================================
# LEGACY SYNCHRONOUS ENDPOINT (kept for backwards compatibility)
# ============================================


@app.post("/process", response_model=ProcessResponse)
async def process_pdfs(
    files: List[UploadFile] = File(..., description="PDF files to process"),
    prompt: str = Form(..., description="Natural language instruction"),
    context_question: str | None = Form(
        default=None,
        description="Optional last assistant question (used to interpret short replies like '90')",
    ),
    session_id: str | None = Form(
        default=None,
        description="Optional session id for multi-turn slot filling and one-shot clarifications",
    ),
    input_source: str | None = Form(
        default=None,
        description="Optional input source hint: text|llm|button",
    ),
):
    """
    Main endpoint: Process PDFs based on natural language prompt.
    
    Flow:
    1. Upload and validate files
    2. Parse user intent with AI
    3. Execute PDF operation
    4. Return processed file
    
    Example:
    - Upload 1 or more PDF files
    - Prompt: "merge all these files" or "keep only page 1"
    """
    session: SessionState | None = None
    try:
        # Validate file count
        if len(files) > settings.max_files_per_request:
            raise HTTPException(
                status_code=400,
                detail=f"Too many files. Maximum {settings.max_files_per_request} files allowed."
            )
        
        # Save uploaded files
        file_names = await save_uploaded_files(files)

        session = _get_session(session_id)
        locked_prompt = None
        if session and session.intent_status == "RESOLVED" and session.locked_action:
            locked_prompt = session.locked_action
        elif (input_source or "").lower() == "button" or _is_button_confirmation(session, prompt):
            _lock_intent(session, prompt, "button")
            locked_prompt = session.locked_action

        active_prompt = locked_prompt or prompt
        prompt_to_parse = active_prompt
        locked_mode = bool(locked_prompt)
        
        # Detect 'compress by X%' BEFORE calling AI parser
        print(f"[REQ] Prompt: {active_prompt}")
        print(f"[REQ] Files: {file_names}")
        percent_match = re.search(r"compress( this)?( pdf)? by (\d{1,3})%", active_prompt, re.IGNORECASE)
        if percent_match and file_names:
            percent = int(percent_match.group(3))
            file_name = file_names[0]  # Only support single file for now
            from app.models import ParsedIntent, CompressToTargetIntent
            from app.pdf_operations import get_upload_path
            import os
            file_path = get_upload_path(file_name)
            if os.path.exists(file_path):
                size_bytes = os.path.getsize(file_path)
                size_mb = size_bytes / (1024 * 1024)
                target_mb = max(1, int(size_mb * (percent / 100)))
                intent = ParsedIntent(
                    operation_type="compress_to_target",
                    compress_to_target=CompressToTargetIntent(
                        operation="compress_to_target",
                        file=file_name,
                        target_mb=target_mb
                    )
                )
                print(f"[AI] Auto-generated compress_to_target intent for {percent}%: {target_mb} MB")
            else:
                return ProcessResponse(
                    status="error",
                    message=f"File not found for compression: {file_name}"
                )
        else:
            if locked_mode:
                clarification_result = clarify_intent(active_prompt, file_names, last_question="")

                if clarification_result.intent:
                    intent = clarification_result.intent
                    if isinstance(intent, list):
                        print(f"[AI] Parsed (locked) multi-operation intent: {len(intent)} steps")
                    else:
                        print(f"[AI] Parsed (locked) intent: {intent.operation_type}")
                    _clear_pending(session)
                    _reset_intent_lock(session)
                else:
                    print(f"[AI] Locked intent could not be executed: {clarification_result.clarification}")
                    if session:
                        _clear_pending(session)
                        _reset_intent_lock(session)
                    return ProcessResponse(
                        status="error",
                        message=clarification_result.clarification or "Could not execute confirmed action.",
                        options=None
                    )
            else:
                # "do the same again" / "repeat" shortcut (must not re-parse)
                if session and session.last_success_intent is not None:
                    if re.search(r"\b(same|again|repeat|do it again|do that again)\b", (active_prompt or ""), re.IGNORECASE):
                        intent = session.last_success_intent
                        _resolve_intent_filenames(intent, file_names)
                        try:
                            if isinstance(intent, list):
                                output_file, message = execute_operation_pipeline(intent, file_names)
                                operation_name = "multi"
                            else:
                                output_file, message = execute_operation(intent)
                                operation_name = intent.operation_type
                        except FileNotFoundError as e:
                            raise HTTPException(status_code=404, detail=str(e))
                        except ValueError as e:
                            raise HTTPException(status_code=400, detail=str(e))
                        except Exception as e:
                            raise HTTPException(status_code=500, detail=f"Operation failed: {str(e)}")

                        session.last_success_prompt = session.last_success_prompt or active_prompt
                        session.last_success_intent = intent
                        _clear_pending(session)
                        _reset_intent_lock(session)
                        return ProcessResponse(
                            status="success",
                            operation=operation_name,
                            output_file=output_file,
                            message=message,
                        )

                # Prefer UI-provided question; fallback to session's last asked question.
                effective_question = (context_question or "") or (session.pending_question if session else "") or ""

                # If we have a pending question, treat short replies as slot values and rebuild
                # a full prompt that preserves already-locked steps.
                prompt_to_parse = active_prompt
                if session and session.pending_question and session.pending_base_instruction:
                    normalized_reply = _normalize_ws(active_prompt)
                    normalized_options = {_normalize_ws(o) for o in (session.pending_options or [])}
                    if normalized_reply and normalized_reply in normalized_options:
                        prompt_to_parse = active_prompt
                    else:
                        # Numeric-only or very short replies are almost always slot-fills.
                        if len(normalized_reply.split()) <= 6 or re.fullmatch(r"[0-9,\-\s]+", (active_prompt or "").strip()):
                            prompt_to_parse = _build_prompt_from_reply(
                                session.pending_base_instruction,
                                session.pending_question,
                                active_prompt,
                            )

                clarification_result = clarify_intent(prompt_to_parse, file_names, last_question=effective_question)
                
                # Stage 2: If no intent but it's a short follow-up, try rephrasing with session context
                if not clarification_result.intent and clarification_result.clarification and session:
                    from app.clarification_layer import _rephrase_with_context
                    rephrased = _rephrase_with_context(prompt_to_parse, session.last_success_intent, file_names)
                    if rephrased:
                        print(f"[AI] Rephrased '{prompt_to_parse}' → '{rephrased}'")
                        clarification_result = clarify_intent(rephrased, file_names, last_question=effective_question)
                
                if clarification_result.intent:
                    intent = clarification_result.intent
                    if isinstance(intent, list):
                        print(f"[AI] Parsed multi-operation intent: {len(intent)} steps")
                    else:
                        print(f"[AI] Parsed intent: {intent.operation_type}")
                    _clear_pending(session)
                else:
                    print(f"[AI] Clarification needed: {clarification_result.clarification}")
                    if session:
                        session.pending_question = clarification_result.clarification
                        session.pending_options = clarification_result.options
                        # Persist the full plan prompt so far, not the raw short reply.
                        session.pending_base_instruction = prompt_to_parse
                    return ProcessResponse(
                        status="error",
                        message=clarification_result.clarification,
                        options=clarification_result.options
                    )

        # Fix common typos in filenames chosen by the model (or user)
        _resolve_intent_filenames(intent, file_names)
        
        # Execute the operation(s)
        try:
            if isinstance(intent, list):
                output_file, message = execute_operation_pipeline(intent, file_names)
                print(f"[OK] {message}")
                operation_name = "multi"
            else:
                output_file, message = execute_operation(intent)
                print(f"[OK] {message}")
                operation_name = intent.operation_type
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Operation failed: {str(e)}")

        if session:
            # If we rebuilt a prompt via slot filling, keep that as the canonical plan prompt.
            try:
                session.last_success_prompt = prompt_to_parse  # type: ignore[name-defined]
            except Exception:
                session.last_success_prompt = prompt
            session.last_success_intent = intent
        
        # Delete only the uploaded files (keep output file for download)
        try:
            for file_name in file_names:
                upload_path = os.path.join("uploads", file_name)
                if os.path.exists(upload_path):
                    os.remove(upload_path)
            # Note: Output file is kept available for download
            # Users can download it via /download/{filename} endpoint
        except Exception as cleanup_err:
            print(f"Warning: Failed to cleanup uploaded files: {cleanup_err}")

        return ProcessResponse(
            status="success",
            operation=operation_name,
            output_file=output_file,
            message=message
        )
    
    except HTTPException:
        raise
    except Exception as e:
        return ProcessResponse(
            status="error",
            message=f"Unexpected error: {str(e)}"
        )
    finally:
        if session and session.intent_status == "RESOLVED":
            _reset_intent_lock(session)


@app.get("/download/{filename}")
async def download_file(filename: str):
    """
    Download a processed PDF file.
    
    Note: In production, use signed URLs or tokens for security.
    """
    file_path = get_output_path(filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    # Serve correct content-type for non-PDF outputs
    lower = filename.lower()
    media_type = "application/pdf"
    if lower.endswith(".docx"):
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif lower.endswith(".zip"):
        media_type = "application/zip"
    elif lower.endswith(".txt"):
        media_type = "text/plain"

    return FileResponse(
        file_path,
        media_type=media_type,
        filename=filename
    )


@app.delete("/cleanup")
async def cleanup_temp_files():
    """
    Delete all temporary files (uploads and outputs).
    
    Useful for development/testing. In production, implement
    automatic cleanup with scheduled tasks or TTL.
    """
    try:
        # Clear uploads
        if os.path.exists("uploads"):
            for file in os.listdir("uploads"):
                os.remove(os.path.join("uploads", file))
        
        # Clear outputs
        if os.path.exists("outputs"):
            for file in os.listdir("outputs"):
                os.remove(os.path.join("outputs", file))
        
        return {"status": "success", "message": "All temporary files deleted"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")


# ============================================
# STATIC FILES (Pre-built frontend)
# ============================================
# IMPORTANT: Register static files AFTER all other routes
# so that API endpoints take priority

if os.path.exists(FRONTEND_DIST_DIR):
    print("[OK] Frontend dist folder found - serving static files")
    
    # Mount assets directory with specific path (doesn't conflict with /api or /process)
    try:
        from fastapi.staticfiles import StaticFiles
        app.mount(
            "/assets",
            StaticFiles(directory=FRONTEND_ASSETS_DIR),
            name="assets"
        )
    except Exception as e:
        print(f"[WARN] Could not mount /assets: {e}")
else:
    print("[WARN] Frontend dist folder NOT found - API only mode")


if os.path.exists(FRONTEND_INDEX_FILE):

    @app.get("/", include_in_schema=False)
    async def serve_frontend_root():
        return FileResponse(FRONTEND_INDEX_FILE, media_type="text/html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend_spa_fallback(full_path: str):
        # Let real API routes take priority (this handler is registered last).
        # If a requested file exists in dist (e.g., favicon), serve it; otherwise serve SPA index.
        candidate = os.path.join(FRONTEND_DIST_DIR, full_path)
        if os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(FRONTEND_INDEX_FILE, media_type="text/html")


# ============================================
# RUN SERVER (for development)
# ============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True
    )
