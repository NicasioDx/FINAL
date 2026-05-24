# Parking AI System

ระบบจัดการที่จอดรถอัจฉริยะด้วย AI (YOLOv8) สำหรับดูภาพกล้องและวิเคราะห์ภาพแบบเรียลไทม์

## โครงสร้างโปรเจกต์

- backend: FastAPI + PostgreSQL + OpenCV + YOLOv8
- parking_web: Flutter Web
- docker-compose.yml: รันฐานข้อมูลและ backend ด้วย Docker
- setup_new_machine.ps1: สคริปต์เตรียมเครื่องใหม่แบบรันครั้งเดียว

## ฟีเจอร์ปัจจุบัน

- ระบบสมัครสมาชิก/ล็อกอิน
- เก็บรหัสผ่านผู้ใช้แบบ bcrypt
- เก็บรหัสผ่านกล้องแบบเข้ารหัส (encryption at rest)
- รายการกล้องไม่ส่ง credential ออกมาฝั่ง frontend
- ดูภาพสดผ่าน WebSocket
- Preview กล้องผ่าน WebSocket แบบ low latency
- Route guard: หน้าหลักต้องล็อกอินก่อนเข้าถึง
- Dark mode สลับได้และจำค่าไว้
- ปุ่มขยายภาพเต็มหน้าจอในหน้าดูกล้อง

## ความปลอดภัยที่ใช้อยู่

- User password:
  - ใช้ bcrypt
  - รองรับบัญชีเก่าแบบ SHA-256 และจะอัปเกรดเป็น bcrypt อัตโนมัติหลังล็อกอินสำเร็จ
- Camera password:
  - เข้ารหัสก่อนเก็บใน DB
  - backend ถอดรหัสเองตอนต้องเชื่อม RTSP
  - frontend ไม่ได้รับ password จาก API รายการกล้อง
- คีย์เข้ารหัสกล้อง:
  - ใช้ CAMERA_CREDENTIAL_KEY จาก environment

## การติดตั้งแบบเร็ว (แนะนำ)

### Windows (PowerShell)

จากโฟลเดอร์โปรเจกต์:

```powershell
.\setup_new_machine.ps1
```

สคริปต์จะทำให้:

- สร้าง backend venv
- ติดตั้ง Python dependencies
- สร้าง backend/.env (ถ้ายังไม่มี)
- สตาร์ตฐานข้อมูลด้วย Docker (ถ้าไม่ใส่ -SkipDocker)
- flutter pub get

ตัวเลือกเสริม:

```powershell
.\setup_new_machine.ps1 -SkipDocker
.\setup_new_machine.ps1 -StartBackend
.\setup_new_machine.ps1 -StartFrontend
```

## การรันแบบแยกเอง

### 1) Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Backend จะรันที่:

- http://localhost:8000

### 2) Frontend

```powershell
cd parking_web
flutter pub get
flutter run -d chrome
```

## Environment สำคัญ (backend/.env)

ตัวอย่าง:

```env
DATABASE_URL=postgresql://postgres:1234@localhost:5432/parking_db
CAMERA_CREDENTIAL_KEY=<your_fernet_key>
```

หมายเหตุ:

- โปรดตั้ง CAMERA_CREDENTIAL_KEY ให้คงที่ใน production
- ถ้าเปลี่ยนคีย์แล้วข้อมูลกล้องเดิมจะถอดรหัสไม่ได้

## Docker Compose

รันฐานข้อมูลและ backend:

```powershell
docker compose up -d
```

เช็กสถานะ:

```powershell
docker compose ps
docker compose logs -f
```

## API หลัก (ล่าสุด)

### Auth

- POST /register
- POST /login

### Camera

- GET /get_cameras
- POST /add_camera

### Streaming

- WebSocket /ws/live
  - client ส่ง camera_id
  - server ดึง credential จาก DB เอง
- WebSocket /ws/preview_camera
  - ใช้ preview ก่อนบันทึกกล้อง

### System

- GET /health
- GET /ping

## หมายเหตุการพัฒนา

- build web ล่าสุดผ่านแล้ว
- หากแก้ config หรือ dependency ควร restart backend/frontend

## License

MIT
