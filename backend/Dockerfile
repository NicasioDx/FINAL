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

# ติดตั้ง PyTorch แบบ CPU ก่อน เพื่อลดขนาดและหลีกเลี่ยงการดึงชุด CUDA ที่ใหญ่เกินจำเป็น
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.2.2 torchvision==0.17.2

# จากนั้นติดตั้งแพ็กเกจที่เหลือของโปรเจกต์
RUN pip install --no-cache-dir -r requirements.txt

# Copy โค้ดทั้งหมด
COPY . .

# ดาวน์โหลดโมเดล YOLOv8 ล่วงหน้าเพื่อลดเวลาตอนเริ่มระบบ
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" 2>/dev/null || echo "Model will be downloaded at runtime"

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "main.py"]