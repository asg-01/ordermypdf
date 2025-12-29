FROM python:3.11-slim

# Install system dependencies (including Ghostscript for PDF compression)
RUN apt-get update && apt-get install -y \
    ghostscript \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy frontend files and build
COPY frontend ./frontend
WORKDIR /app/frontend
RUN npm install && chmod +x node_modules/.bin/* && npm run build

# Copy backend files
WORKDIR /app
COPY app ./app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Start the FastAPI server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
