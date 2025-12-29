FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ghostscript \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy pre-built frontend (built locally before deployment)
COPY frontend/dist ./frontend/dist

# Copy backend
COPY app ./app

# Set environment
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE 8000

# Start FastAPI with static file serving
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
