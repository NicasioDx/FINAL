FROM python:3.9-slim-bullseye

WORKDIR /app

# ติดตั้ง system dependencies สำหรับ OpenCV และ FFmpeg
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements และติดตั้ง Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy โค้ดทั้งหมด
COPY . .

# Download YOLOv8 model (ถ้ายังไม่มี)
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" 2>/dev/null || echo "Model will be downloaded at runtime"

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "main.py"]