# OrderMyPDF

OrderMyPDF is an AI-powered PDF and document processor that lets you use natural language to perform advanced PDF operations. It features a FastAPI backend and a modern React frontend, supporting operations like merge, split, compress, convert, OCR, and more.

## Features
- Natural language prompt to control PDF operations
- Supports PDF, DOCX, PNG, JPG/JPEG
- Merge, split, compress, convert, OCR, reorder, watermark, and more
- Multi-file upload with format consistency enforcement
- Button-based disambiguation for unclear commands
- Real-time progress and ETA

## Tech Stack
- **Backend:** Python 3.10+, FastAPI, PyPDF, pydantic, APScheduler
- **Frontend:** React, Vite, Tailwind CSS
- **AI:** Groq LLM API, Baseten (optional), fallback LLMs
- **Deployment:** Docker, Render.com, or any VM

## Getting Started

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/ordermypdf.git
cd ordermypdf
```

### 2. Backend Setup
- Create a Python virtual environment:
  ```bash
  python -m venv venv
  source venv/bin/activate  # On Windows: venv\Scripts\activate
  ```
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```
- Set up environment variables (see `.env.example`).
- Start the FastAPI server:
  ```bash
  uvicorn app.main:app --reload
  ```

### 3. Frontend Setup
- Go to the frontend directory:
  ```bash
  cd frontend
  npm install
  npm run dev
  ```
- Open [http://localhost:5173](http://localhost:5173) in your browser.

### 4. Usage
- Upload your PDF(s) or supported files.
- Enter a prompt (e.g., "merge these", "compress under 10MB", "convert to docx").
- Download the processed result.

## Deployment
- Supports Docker and Render.com (see Dockerfile and render.yaml).
- For Render.com, connect your GitHub repo and set environment variables as needed.

## License
This project is licensed under the MIT License. See the LICENSE file for details.

## Contributing
Pull requests and issues are welcome! Please open an issue for major changes.

## Acknowledgments
- Groq for LLM API
- Baseten for fallback LLM
- PyPDF, FastAPI, React, Tailwind CSS
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
