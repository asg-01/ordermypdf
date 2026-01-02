# OrderMyPDF - AI-Controlled PDF Processor

A learning-focused MVP that uses natural language prompts to control PDF operations.

## Architecture

```
User Prompt
   ↓
AI Intent Parser (LLM)
   ↓
Structured JSON Plan
   ↓
Backend Executor (Python)
   ↓
Processed PDF Output
```

**Key Principle:** The AI does NOT process files. It only parses intent and outputs instructions.

## Supported Operations

- **Merge** multiple PDFs
- **Split** PDF by page numbers
- **Delete** specific pages from PDF
- **Compress** PDF file size

## Tech Stack

- **Backend:** FastAPI + Python
- **PDF Processing:** PyPDF
- **AI:** Groq (free LLM API)
- **Deployment:** Cloud VM with filesystem access

## Setup

1. Clone the repository
2. Create virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create `.env` file (copy from `.env.example`):
   ```bash
   cp .env.example .env
   ```

5. Get a free Groq API key:
   - Visit https://console.groq.com/
   - Sign up and create an API key
   - Add to `.env` file

6. Run the server:
   ```bash
   uvicorn app.main:app --reload
   ```

## Usage

### API Endpoint

**POST** `/process`

**Request:**
```json
{
  "prompt": "merge file1.pdf and file2.pdf",
  "files": ["file1.pdf", "file2.pdf"]
}
```

**Response:**
```json
{
  "status": "success",
  "operation": "merge",
  "output_file": "merged_output.pdf",
  "message": "Successfully merged 2 PDFs"
}
```

### Example Prompts

- "Merge all these PDFs into one"
- "Split this PDF, keep only pages 1-5"
- "Delete pages 3, 7, and 10 from this document"
- "Compress this PDF to reduce file size"

## Project Goals

This is an **educational project** to learn:
- LLMs as controllers (not magic solvers)
- Prompt-to-action translation
- Safe execution of AI-generated plans
- Backend system design
- File processing pipelines

## Non-Goals

- UI polish
- User authentication
- Payment processing
- Production scalability
- Multi-format support (DOCX, images, etc.)

## License

Educational/Personal Use
