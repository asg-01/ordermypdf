# OrderMyPDF

Professional document processing platform powered by AI. Merge, split, compress, OCR, convert, and perform advanced operations on PDFs, images, and Word documents with natural language commands.

## 🚀 Features

- **Natural Language Interface** - Describe what you need in plain English
- **Multi-Format Support** - PDF, PNG, JPG, DOCX with seamless conversion
- **Batch Processing** - Handle multiple files efficiently
- **Advanced Operations**
  - Merge & split PDFs
  - Image compression with quality control
  - OCR text recognition
  - Format conversion (PDF ↔ DOCX/JPG/PNG)
  - Remove blank/duplicate pages
  - Page reordering
  - Watermarking & metadata editing
  - Flatten & optimize
- **Real-time Processing** - Live status updates and progress tracking
- **Secure & Private** - Files processed locally, never stored permanently
- **Mobile Responsive** - Works perfectly on all devices

## 🛠️ Tech Stack

**Backend:**
- Python 3.10+
- FastAPI - Modern async web framework
- Groq API - LLM integration (llama-3.3-70b-versatile)
- PyPDF2 - PDF manipulation
- Pillow - Image processing
- python-docx - Word document handling
- pytesseract - OCR capabilities
- Redis - Job queue management

**Frontend:**
- React 18 - UI library
- Vite - Build tool
- Tailwind CSS - Styling
- Professional glassmorphism design system

## 📋 Prerequisites

- Python 3.10 or higher
- Node.js 16+ and npm
- Groq API key (free at groq.com)
- Tesseract OCR (optional, for OCR features)

## 🔧 Installation

### Clone Repository
```bash
git clone https://github.com/asg-01/ordermypdf.git
cd ordermypdf
```

### Backend Setup
```bash
pip install -r requirements.txt
cp .env.example .env
# Add your Groq API key to .env
python -m uvicorn app.main:app --reload
```

Backend runs on `http://localhost:8000`

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:5173`

## 📖 Usage

1. **Upload Files** - Click "Choose files" and select PDFs, images, or DOCX
2. **Describe Task** - Type what you want to do
3. **Run Agent** - Click "Run" to process with AI guidance
4. **Download Result** - Get your processed file when ready

### Example Commands
- "merge these three PDFs into one"
- "convert this PDF to high-quality images"
- "compress this file to 2MB without losing quality"
- "extract text from these images"
- "split this PDF on page 5"
- "remove all duplicate pages"

## 📁 Project Structure

```
ordermypdf/
├── app/
│   ├── main.py
│   ├── models.py
│   ├── llm.py
│   ├── processors/
│   │   ├── pdf.py
│   │   ├── image.py
│   │   └── docx.py
│   ├── queue/
│   │   └── job_queue.py
│   └── utils/
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── index.css
│   │   └── main.jsx
│   └── package.json
├── uploads/
├── outputs/
└── requirements.txt
```

## 🔐 Environment Variables

Create `.env` file:

```env
GROQ_API_KEY=your_groq_api_key_here
LLM_MODEL=llama-3.3-70b-versatile
PORT=8000
HOST=0.0.0.0
MAX_FILE_SIZE_MB=100
UPLOAD_FOLDER=./uploads
OUTPUT_FOLDER=./outputs
FRONTEND_URL=http://localhost:5173
```

## 🚀 Deployment

### Docker
```bash
docker build -t ordermypdf .
docker run -p 8000:8000 -e GROQ_API_KEY=your_key ordermypdf
```

## 🧪 Testing

```bash
pytest tests/ -v
cd frontend && npm test
```

## 📊 API Endpoints

- `POST /process` - Submit processing request
- `GET /status/{job_id}` - Get job status
- `GET /download/{filename}` - Download processed file
- `GET /health` - Server health check

## 🎨 Design Features

- **Glassmorphism** - Modern frosted glass effect UI
- **Dark Mode** - Professional dark theme
- **Responsive Design** - Perfect on all devices
- **Accessibility** - WCAG 2.1 AA compliant

## 🛡️ Security

- File validation on upload
- Size limits enforcement
- Automatic cleanup of old files
- CORS protection
- No permanent file storage

## 🐛 Troubleshooting

### Port Already in Use
```bash
# Find and kill process
lsof -ti:5173 | xargs kill -9
lsof -ti:8000 | xargs kill -9
```

## 📝 License

This software is proprietary and confidential. All rights reserved. 

**This is NOT open-source software.** Unauthorized copying, modification, distribution, or use is strictly prohibited.

See the [LICENSE](LICENSE) file for the complete proprietary license agreement and terms.

For commercial licensing inquiries, contact the copyright holder.

## 🙏 Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- UI powered by [React](https://react.dev/)
- Styling with [Tailwind CSS](https://tailwindcss.com/)
- LLM via [Groq](https://groq.com/)

---

**© 2025 Amritansh Singh. All rights reserved.**
