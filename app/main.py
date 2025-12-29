"""
FastAPI Main Application - Orchestrates AI parsing and PDF processing.

This is where the magic happens:
1. User sends prompt + files
2. AI parses intent → JSON
3. Backend validates and executes
4. Returns processed PDF
"""

import os
import shutil
import time
from typing import List
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.models import ProcessResponse, ParsedIntent
import re
from app.clarification_layer import clarify_intent
from app.pdf_operations import (
    merge_pdfs,
    split_pdf,
    delete_pages,
    compress_pdf,
    pdf_to_docx,
    compress_pdf_to_target,
    ensure_temp_dirs,
    get_upload_path,
    get_output_path
)


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


# ============================================
# STARTUP / SHUTDOWN
# ============================================

# ============================================
# STARTUP / SHUTDOWN
# ============================================

def cleanup_old_files():
    """Delete output files older than 30 minutes"""
    output_dir = "outputs"
    if not os.path.exists(output_dir):
        return
    
    current_time = time.time()
    for filename in os.listdir(output_dir):
        file_path = os.path.join(output_dir, filename)
        if os.path.isfile(file_path):
            file_age_seconds = current_time - os.path.getmtime(file_path)
            if file_age_seconds > 30 * 60:  # 30 minutes in seconds
                try:
                    os.remove(file_path)
                    print(f"🗑️  Deleted old file: {filename}")
                except Exception as e:
                    print(f"Warning: Failed to delete {filename}: {e}")

@app.on_event("startup")
async def startup_event():
    """Initialize directories on startup and schedule cleanup task"""
    ensure_temp_dirs()
    print("✓ OrderMyPDF started successfully")
    print(f"✓ Using LLM model: {settings.llm_model}")
    
    # Start background scheduler for cleanup
    scheduler = BackgroundScheduler()
    scheduler.add_job(cleanup_old_files, 'interval', minutes=5)  # Run cleanup every 5 minutes
    scheduler.start()
    print("✓ Auto-cleanup scheduler started (files deleted after 30 minutes)")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    print("✓ OrderMyPDF shutting down")


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
    
    for file in files:
        # Validate file type
        if not file.filename.endswith('.pdf'):
            raise HTTPException(status_code=400, detail=f"Invalid file type: {file.filename}. Only PDF files allowed.")
        
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
        
        # Save file
        file_path = get_upload_path(file.filename)
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
    
    if intent.operation_type == "merge":
        output_file = merge_pdfs(operation.files)
        message = f"Successfully merged {len(operation.files)} PDFs"
        return output_file, message
    
    elif intent.operation_type == "split":
        output_file = split_pdf(operation.file, operation.pages)
        message = f"Successfully extracted {len(operation.pages)} pages from {operation.file}"
        return output_file, message
    
    elif intent.operation_type == "delete":
        output_file = delete_pages(operation.file, operation.pages_to_delete)
        message = f"Successfully deleted {len(operation.pages_to_delete)} pages from {operation.file}"
        return output_file, message
    
    elif intent.operation_type == "compress":
        output_file = compress_pdf(operation.file)
        message = f"Successfully compressed {operation.file}"
        return output_file, message
    
    elif intent.operation_type == "pdf_to_docx":
        output_file = pdf_to_docx(operation.file)
        message = f"Successfully converted {operation.file} to DOCX"
        return output_file, message
    elif intent.operation_type == "compress_to_target":
        output_file = compress_pdf_to_target(operation.file, operation.target_mb)
        message = f"Compressed {operation.file} to under {operation.target_mb} MB"
        return output_file, message
    else:
        raise ValueError(f"Unknown operation type: {intent.operation_type}")


# ============================================
# API ENDPOINTS
# ============================================

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "OrderMyPDF",
        "status": "running",
        "version": "0.1.0",
        "model": settings.llm_model
    }


@app.post("/process", response_model=ProcessResponse)
async def process_pdfs(
    files: List[UploadFile] = File(..., description="PDF files to process"),
    prompt: str = Form(..., description="Natural language instruction")
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
    try:
        # Validate file count
        if len(files) > settings.max_files_per_request:
            raise HTTPException(
                status_code=400,
                detail=f"Too many files. Maximum {settings.max_files_per_request} files allowed."
            )
        
        # Save uploaded files
        file_names = await save_uploaded_files(files)
        
        # Detect 'compress by X%' BEFORE calling AI parser
        print(f"📝 Prompt: {prompt}")
        print(f"📎 Files: {file_names}")
        percent_match = re.search(r"compress( this)?( pdf)? by (\d{1,3})%", prompt, re.IGNORECASE)
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
                print(f"🤖 Auto-generated compress_to_target intent for {percent}%: {target_mb} MB")
            else:
                return ProcessResponse(
                    status="error",
                    message=f"File not found for compression: {file_name}"
                )
        else:
            clarification_result = clarify_intent(prompt, file_names)
            if clarification_result.intent:
                intent = clarification_result.intent
                print(f"🤖 Parsed intent: {intent.operation_type}")
            else:
                print(f"❓ Clarification needed: {clarification_result.clarification}")
                return ProcessResponse(
                    status="error",
                    message=clarification_result.clarification
                )
        
        # Execute the operation
        try:
            output_file, message = execute_operation(intent)
            print(f"✓ {message}")
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Operation failed: {str(e)}")
        
        # Delete only the uploaded files (keep output file for download)
        try:
            for file_name in file_names:
                upload_path = get_upload_path(file_name)
                if os.path.exists(upload_path):
                    os.remove(upload_path)
            # Note: Output file is kept available for download
            # Users can download it via /download/{filename} endpoint
        except Exception as cleanup_err:
            print(f"Warning: Failed to cleanup uploaded files: {cleanup_err}")

        return ProcessResponse(
            status="success",
            operation=intent.operation_type,
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


@app.get("/download/{filename}")
async def download_file(filename: str):
    """
    Download a processed PDF file.
    
    Note: In production, use signed URLs or tokens for security.
    """
    file_path = get_output_path(filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        file_path,
        media_type="application/pdf",
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

# Mount pre-built frontend dist folder if it exists
frontend_dist_path = "frontend/dist"
if os.path.exists(frontend_dist_path):
    app.mount("/", StaticFiles(directory=frontend_dist_path, html=True), name="static")


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
