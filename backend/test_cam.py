import cv2
import os

# 1. ตั้งค่า Environment บังคับใช้ TCP และล้างค่าความหน่วง
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

# 2. ใส่ User/Pass ตรงๆ (เช็กให้ชัวร์ว่าพิมพ์ถูก 100% ตามในแอป)
user = "B0BSize"
pw = "12345678"
ip = "192.168.1.46"

# ทดลอง URL 2 รูปแบบ (ถ้าแบบแรกไม่ได้ ให้ลองสลับคอมเมนต์ไปแบบที่สอง)
url = f"rtsp://{user}:{pw}@{ip}:554/stream2"
# url = f"rtsp://{user}:{pw}@{ip}/stream2" # แบบไม่ใส่ Port

print(f"กำลังพยายามเชื่อมต่อที่: {url}")

# 3. ลองเปิดด้วย API Preference CAP_FFMPEG
cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)

# รอให้กล้อง Handshake 2 วินาที
if not cap.isOpened():
    print("ยังเข้าไม่ได้... กำลังลองวิธีสำรอง")
    # วิธีสำรอง: ใส่ชื่อโปรโตคอลนำหน้า
    cap = cv2.VideoCapture(url)

ret, frame = cap.read()

if ret:
    print("--- สำเร็จ! ภาพมาแล้ว ---")
    cv2.imshow("Tapo Camera Test", frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
else:
    print("--- ล้มเหลว: ยังติด 401 Unauthorized ---")
    print("คำแนะนำ: ลองปิดกล้อง (ถอดปลั๊ก) แล้วเสียบใหม่เพื่อให้กล้องล้าง Session เก่า")

cap.release()