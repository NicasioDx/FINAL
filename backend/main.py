import os
# ✅ บรรทัดที่สำคัญที่สุด: ต้องอยู่ก่อน import torch หรือ ultralytics
os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"] = "0"

import cv2
import base64
import threading
import time
import logging
import torch
import functools
import asyncio
from contextlib import asynccontextmanager

torch.load = functools.partial(torch.load, weights_only=False)
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
from ultralytics import YOLO 
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer

# นำเข้าฟังก์ชันจาก database.py
from database import (
    init_db, add_camera_to_db, get_all_cameras, create_user, authenticate_user,
    get_connection, release_connection, get_camera_credentials,
    add_parking_history, get_parking_history, get_user_role
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("parking_backend")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # โหลดโมเดล YOLOv8n
    global model
    import torch
    global device
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = YOLO('yolov8n.pt')
    print(f"✅ YOLO model loaded on {device}")
    
    # รอฐานข้อมูลพร้อมก่อน init
    max_retries = 30  # รอ 30 ครั้ง (30 วินาที)
    for i in range(max_retries):
        try:
            conn = get_connection()
            if conn:
                release_connection(conn)
                print("✅ Database connected successfully")
                break
        except Exception as e:
            print(f"⏳ Waiting for database... ({i+1}/{max_retries}) - {e}")
            time.sleep(1)
    else:
        print("❌ Could not connect to database after retries")
        return

    # Init database tables
    init_db()
    print("✅ Database initialized")
    yield

app = FastAPI(lifespan=lifespan)

# ปลดล็อก CORS - ยอมรับทุก origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ยอมรับทุก domain/origin
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Models ---
class CameraRegister(BaseModel):
    camera_name: str
    ip: str
    username: str
    password: str
    zone_name: str = "ทั่วไป"

class CameraRequest(BaseModel):
    ip: str
    username: str
    password: str


class CameraByIdRequest(BaseModel):
    camera_id: int

class WebRTCOffer(BaseModel):
    sdp: str
    type: str
    camera: CameraRequest

class UserRegister(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class ParkingHistoryLog(BaseModel):
    username: str
    camera_id: int
    event_type: str = "parking_success"

# --- User Management ---

@app.post("/register")
async def register(data: UserRegister):
    result = create_user(data.username, data.password)

    if result["status"] == "created":
        logger.info("REGISTER_SUCCESS username=%s", data.username)
        return {"status": "success", "message": result["message"]}

    if result["status"] == "duplicate":
        logger.warning("REGISTER_DUPLICATE username=%s", data.username)
        raise HTTPException(status_code=409, detail=result["message"])

    if result["status"] == "db_unavailable":
        logger.error("REGISTER_DB_UNAVAILABLE username=%s", data.username)
        raise HTTPException(status_code=503, detail=result["message"])

    logger.error("REGISTER_DB_ERROR username=%s", data.username)
    raise HTTPException(status_code=500, detail=result["message"])


@app.post("/register/admin")
async def register_admin(data: UserRegister):
    result = create_user(data.username, data.password, role="admin")

    if result["status"] == "created":
        logger.info("REGISTER_ADMIN_SUCCESS username=%s", data.username)
        return {"status": "success", "message": "Admin registered"}

    if result["status"] == "duplicate":
        logger.warning("REGISTER_ADMIN_DUPLICATE username=%s", data.username)
        raise HTTPException(status_code=409, detail=result["message"])

    if result["status"] == "db_unavailable":
        logger.error("REGISTER_ADMIN_DB_UNAVAILABLE username=%s", data.username)
        raise HTTPException(status_code=503, detail=result["message"])

    logger.error("REGISTER_ADMIN_DB_ERROR username=%s", data.username)
    raise HTTPException(status_code=500, detail=result["message"])


@app.post("/login")
async def login(data: UserLogin):
    result = authenticate_user(data.username, data.password)

    if result["status"] == "authenticated":
        logger.info("LOGIN_SUCCESS username=%s", data.username)
        role = get_user_role(data.username)
        return {
            "status": "success",
            "message": result["message"],
            "username": data.username,
            "role": role
        }

    if result["status"] == "invalid_credentials":
        logger.warning("LOGIN_INVALID_CREDENTIALS username=%s", data.username)
        raise HTTPException(status_code=401, detail=result["message"])

    if result["status"] == "db_unavailable":
        logger.error("LOGIN_DB_UNAVAILABLE username=%s", data.username)
        raise HTTPException(status_code=503, detail=result["message"])

    logger.error("LOGIN_DB_ERROR username=%s", data.username)
    raise HTTPException(status_code=500, detail=result["message"])


# --- Parking History Management ---

@app.post("/parking_history/log")
async def log_parking_history(data: ParkingHistoryLog):
    """บันทึกประวัติการเข้าจอด"""
    success = add_parking_history(data.username, data.camera_id, data.event_type)
    
    if success:
        logger.info("PARKING_LOG_SUCCESS username=%s camera_id=%s", data.username, data.camera_id)
        return {"status": "success", "message": "Parking history logged"}
    
    logger.error("PARKING_LOG_ERROR username=%s camera_id=%s", data.username, data.camera_id)
    raise HTTPException(status_code=500, detail="Failed to log parking history")


@app.get("/parking_history")
async def get_user_parking_history(username: str, limit: int = 100):
    """ดึงประวัติการเข้าจอดของผู้ใช้"""
    try:
        history = get_parking_history(username=username, limit=limit)
        return {"status": "success", "data": history}
    except Exception as e:
        logger.error("GET_PARKING_HISTORY_ERROR username=%s error=%s", username, str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch parking history")


@app.get("/parking_history/admin")
async def get_admin_parking_history(zone_name: str = None, limit: int = 100):
    """ดึงประวัติการเข้าจอด (Admin only - แยกตามโซน)"""
    try:
        history = get_parking_history(zone_name=zone_name, limit=limit)
        return {"status": "success", "data": history}
    except Exception as e:
        logger.error("GET_ADMIN_PARKING_HISTORY_ERROR zone=%s error=%s", zone_name, str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch parking history")


# WebRTC connections
pcs = set()

@app.post("/offer")
async def webrtc_offer(data: WebRTCOffer):
    # สร้าง RTSP URL
    url = f"rtsp://{data.camera.username}:{data.camera.password}@{data.camera.ip}:554/stream2"
    
    # สร้าง MediaPlayer สำหรับ RTSP
    player = MediaPlayer(url, format="rtsp", options={
        "rtsp_transport": "tcp",
        "stimeout": "5000000"
    })
    
    # สร้าง PeerConnection
    pc = RTCPeerConnection()
    pcs.add(pc)
    
    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        print(f"ICE connection state: {pc.iceConnectionState}")
        if pc.iceConnectionState == "failed":
            await pc.close()
            pcs.discard(pc)
    
    # เพิ่ม video track
    if player.video:
        pc.addTrack(player.video)
    
    # ตั้ง remote description จาก offer
    offer = RTCSessionDescription(sdp=data.sdp, type=data.type)
    await pc.setRemoteDescription(offer)
    
    # สร้าง answer
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    
    return {
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type
    }


@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    await websocket.accept()
    print("🔗 WebSocket connected for live stream")

    def _is_disconnect_exception(exc: Exception) -> bool:
        name = type(exc).__name__
        return name in {"WebSocketDisconnect", "ClientDisconnected"}
    
    # รับ camera data จาก client
    try:
        data = await websocket.receive_json()
        camera_id = int(data['camera_id'])
        cam = get_camera_credentials(camera_id)
        if not cam:
            await websocket.send_text('error: camera not found')
            await websocket.close()
            return

        ip = cam['ip_address']
        username = cam['username']
        password = cam['password']
        print(f"📡 Received camera request: camera_id={camera_id}, IP={ip}")
    except Exception as e:
        print(f"❌ Failed to receive camera data: {e}")
        await websocket.close()
        return
    
    # สร้าง RTSP URL
    url = f"rtsp://{username}:{password}@{ip}:554/stream2"
    print(f"🎥 Starting live stream for camera_id={camera_id}, ip={ip}")
    
    # เปิด camera
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 0)
    cap.set(cv2.CAP_PROP_FPS, 60)

    # เช็คว่าเปิด RTSP ได้สำเร็จก่อน (ป้องกันเชื่อมไม่ได้แต่เข้าสูตร loop)
    if not cap.isOpened():
        print("❌ Cannot open camera stream")
        await websocket.send_text('error: cannot open camera stream')
        await websocket.close()
        return

    print("✅ Camera stream opened successfully")
    frame_count = 0

    frame_queue = asyncio.Queue(maxsize=3)
    stop_event = asyncio.Event()

    # worker 1: capture camera frames into queue (drop oldest if backlog)
    async def capture_worker():
        while not stop_event.is_set():
            success, frame = await asyncio.get_running_loop().run_in_executor(None, cap.read)
            if not success or frame is None:
                print("⚠️ Failed to read frame from camera")
                await asyncio.sleep(0.05)
                continue

            if frame_queue.full():
                try:
                    _ = frame_queue.get_nowait()  # drop oldest
                except asyncio.QueueEmpty:
                    pass

            await frame_queue.put(frame)
            await asyncio.sleep(0)  # yield event loop

    # worker 2: inference+encode+send
    async def processing_worker():
        nonlocal frame_count
        avg_proc = 0.08
        alpha = 0.1

        while not stop_event.is_set():
            try:
                frame = await asyncio.wait_for(frame_queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue

            t0 = time.time()
            resized_frame = cv2.resize(frame, (640, 360))
            half_precision = device == 'cuda'
            results = model(resized_frame, verbose=False, conf=0.4, device=device, half=half_precision)
            annotated_frame = results[0].plot()
            success, buffer = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 50])

            if not success:
                print("⚠️ JPEG encoding failed")
                continue

            try:
                await websocket.send_bytes(buffer.tobytes())
            except WebSocketDisconnect:
                stop_event.set()
                return
            except RuntimeError as e:
                # Raised when client disconnects and websocket is already closed.
                print(f"ℹ️ WebSocket send stopped: {e}")
                stop_event.set()
                return
            except Exception as e:
                if _is_disconnect_exception(e):
                    stop_event.set()
                    return
                raise

            frame_count += 1

            proc_time = time.time() - t0
            avg_proc = (1 - alpha) * avg_proc + alpha * proc_time
            target_fps = min(30, max(8, int(1.0 / max(avg_proc, 0.001))))
            sleep_time = max(0.0, 1.0 / target_fps - proc_time)

            if frame_count % 50 == 0:
                print(f"📊 Sent {frame_count} frames, avg_proc={avg_proc:.3f}s, target_fps={target_fps}, queue_size={frame_queue.qsize()}")

            await asyncio.sleep(sleep_time)

    capture_task = asyncio.create_task(capture_worker())
    process_task = asyncio.create_task(processing_worker())

    try:
        done, pending = await asyncio.wait({capture_task, process_task}, return_when=asyncio.FIRST_EXCEPTION)

        for t in pending:
            t.cancel()

        for t in done:
            if t.cancelled():
                continue
            exc = t.exception()
            if exc is None:
                continue
            if _is_disconnect_exception(exc):
                print("ℹ️ WebSocket client disconnected")
                continue
            print(f"❌ Error in streaming pipeline: {type(exc).__name__}: {exc}")
    except WebSocketDisconnect:
        print("ℹ️ WebSocket client disconnected")
    except Exception as e:
        print(f"❌ Error in streaming pipeline: {type(e).__name__}: {e}")
    finally:
        stop_event.set()
        try:
            await asyncio.wait_for(
                asyncio.gather(capture_task, process_task, return_exceptions=True),
                timeout=1.5,
            )
        except asyncio.TimeoutError:
            capture_task.cancel()
            process_task.cancel()
        cap.release()
        print("🔚 Camera released, WebSocket closing")
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/ws/preview_camera")
async def websocket_preview_camera(websocket: WebSocket):
    """Low-latency preview stream for add-camera page (no AI inference)."""
    await websocket.accept()
    cap = None

    try:
        data = await websocket.receive_json()
        ip = data['ip']
        username = data['username']
        password = data['password']

        url = f"rtsp://{username}:{password}@{ip}:554/stream2"
        print(f"🔎 Preview stream open for ip={ip}")

        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FPS, 60)

        if not cap.isOpened():
            await websocket.send_text("error: cannot open camera stream")
            return

        while True:
            success, frame = await asyncio.get_running_loop().run_in_executor(None, cap.read)
            if not success or frame is None:
                await asyncio.sleep(0.01)
                continue

            preview = cv2.resize(frame, (640, 360))
            ok, buffer = cv2.imencode('.jpg', preview, [cv2.IMWRITE_JPEG_QUALITY, 55])
            if not ok:
                continue

            await websocket.send_bytes(buffer.tobytes())
            await asyncio.sleep(0)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"❌ Preview WebSocket error: {e}")
    finally:
        if cap:
            cap.release()
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/health")
async def health():
    conn = get_connection()
    if conn is None:
        raise HTTPException(status_code=503, detail="Cannot connect to database")
    cur = None
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database health check failed: {e}")
    finally:
        if cur:
            cur.close()
        release_connection(conn)


# --- Camera Manager ---
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

class CameraStream:
    def __init__(self):
        self.cap = None
        self.frame = None
        self.status = False
        self.current_url = ""
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.update, daemon=True)
        self.thread.start()

    def update(self):
        while True:
            if self.cap and self.cap.isOpened():
                success, frame = self.cap.read()
                if success:
                    with self.lock:
                        self.frame = frame.copy()
                        self.status = True
                else:
                    self.status = False
                    time.sleep(1)
            else:
                time.sleep(0.1)

    def change_camera(self, url):
        if self.current_url != url:
            with self.lock:
                print(f"🔄 Switching camera to: {url}")
                if self.cap:
                    self.cap.release()
                self.current_url = url
                self.cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

cam_manager = CameraStream()

# --- API Endpoints ---

@app.post("/add_camera")
async def add_camera(data: CameraRegister):
    success = add_camera_to_db(data.camera_name, data.ip, data.username, data.password, data.zone_name)
    if success:
        return {"status": "success", "message": "Camera added"}
    raise HTTPException(status_code=500, detail="Failed to add camera")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled server error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )

# --- Health & Debug Routes ---
@app.get("/ping")
async def ping():
    """ทดสอบว่า backend + ngrok ตอบได้ปกติ"""
    return {"status": "ok", "time": time.time()}


@app.options("/get_cameras")
async def get_cameras_options():
    """CORS preflight - ให้ CORSMiddleware จัดการ"""
    print("📋 OPTIONS /get_cameras preflight")
    return {}


@app.get("/get_cameras")
async def get_cameras():
    """ดึงรายการกล้องทั้งหมด - ให้ CORSMiddleware จัดการ header"""
    print("➡️ /get_cameras called")
    request_time = time.time()
    try:
        cameras = get_all_cameras()
        elapsed = time.time() - request_time
        print(f"✅ /get_cameras returned {len(cameras)} cameras in {elapsed:.3f}s")
        # ส่ง data กลับอย่างเรียบร้อย ไม่ต้อง custom headers
        return cameras
    except Exception as e:
        elapsed = time.time() - request_time
        logger.exception("/get_cameras failed after %.3fs", elapsed)
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.post("/get_frame")
async def get_frame(data: CameraByIdRequest):
    cam = get_camera_credentials(data.camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    target_url = f"rtsp://{cam['username']}:{cam['password']}@{cam['ip_address']}:554/stream2"
    cam_manager.change_camera(target_url)

    if cam_manager.status and cam_manager.frame is not None:
        with cam_manager.lock:
            input_frame = cam_manager.frame.copy()

        # ประมวลผล AI
        results = model(input_frame, verbose=False, conf=0.4)
        annotated_frame = results[0].plot()

        # ย่อขนาดและเข้ารหัส
        resized_frame = cv2.resize(annotated_frame, (640, 360))
        _, buffer = cv2.imencode('.jpg', resized_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')
        
        return {
            "status": "success", 
            "image": jpg_as_text,
            "count": len(results[0].boxes)
        }
    
    return {"status": "error", "message": "Connecting..."}

@app.post("/preview_camera")
async def preview_camera(data: CameraByIdRequest):
    """ฟังก์ชันสำหรับกด Preview ดูภาพก่อนบันทึก"""
    cam = get_camera_credentials(data.camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    target_url = f"rtsp://{cam['username']}:{cam['password']}@{cam['ip_address']}:554/stream2"
    
    # ทดสอบดึงภาพด้วย OpenCV
    cap = cv2.VideoCapture(target_url)
    success, frame = cap.read()
    cap.release() # เปิดแล้วรีบปิดทันทีเพื่อไม่ให้ค้าง

    if success:
        # ย่อขนาดและแปลงเป็น Base64 ส่งกลับไปให้ดู
        resized = cv2.resize(frame, (640, 360))
        _, buffer = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, 80])
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')
        return {"status": "success", "image": jpg_as_text}
    
    return {"status": "error", "message": "ไม่สามารถเชื่อมต่อกล้องได้ โปรดเช็ค IP หรือ User/Pass"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)