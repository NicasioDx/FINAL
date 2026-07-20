import os
# ต้องตั้งค่านี้ก่อน import torch/ultralytics เพื่อหลีกเลี่ยงข้อจำกัดการโหลดน้ำหนักโมเดล
os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"] = "0"
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
import cv2
import base64
import json
import numpy as np
import threading
import time
import logging
import torch
import functools
import asyncio
from contextlib import asynccontextmanager
from typing import Optional, Tuple, Union

torch.load = functools.partial(torch.load, weights_only=False)
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
import uvicorn
from ultralytics import YOLO 
AIORTC_AVAILABLE = True
AIORTC_IMPORT_ERROR = ""
try:
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.contrib.media import MediaPlayer
except Exception as exc:
    # บางเครื่อง Windows อาจบล็อก DLL ของ aiortc/av ด้วยนโยบาย App Control
    AIORTC_AVAILABLE = False
    AIORTC_IMPORT_ERROR = str(exc)
    RTCPeerConnection = None
    RTCSessionDescription = None
    MediaPlayer = None

# ฟังก์ชันช่วยเข้าถึงฐานข้อมูลที่ใช้ใน API และงานประมวลผลสตรีม
from database import (
    init_db, add_camera_to_db, get_all_cameras, create_user, authenticate_user,
    get_connection, release_connection, get_camera_credentials,
    add_parking_history, get_parking_history, get_user_role,
    get_camera_rois, save_camera_rois, delete_camera_from_db,
    promote_latest_anonymous_auto_history
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("parking_backend")
if not AIORTC_AVAILABLE:
    logger.warning("WEBRTC_DISABLED reason=%s", AIORTC_IMPORT_ERROR)

# --- โหมดวิดีโอตัวอย่าง ------------------------------------------------------
# ตั้ง USE_DEMO_VIDEO=true เพื่ออ่านเฟรมจากไฟล์แทนกล้อง RTSP จริง
TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def env_value(name: str, default: str) -> str:
    return os.getenv(name) or os.getenv(f"\ufeff{name}") or default


USE_DEMO_VIDEO = env_value("USE_DEMO_VIDEO", "false").strip().lower() in TRUE_VALUES
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AI_DEVICE = env_value("AI_DEVICE", "auto").strip().lower()
DEMO_VIDEO_PATH = env_value("DEMO_VIDEO_PATH", "videos/demo_parking.mp4")
USE_AUTO_SLOT = env_value("USE_AUTO_SLOT", "true").strip().lower() in TRUE_VALUES
USE_MANUAL_ROI_FALLBACK = env_value("USE_MANUAL_ROI_FALLBACK", "true").strip().lower() in TRUE_VALUES
SLOT_MODEL_PATH = env_value("SLOT_MODEL_PATH", "best.pt")
VEHICLE_MODEL_PATH = env_value("VEHICLE_MODEL_PATH", "yolov8s.pt")
MANUAL_ROI_PATH = env_value("MANUAL_ROI_PATH", "manual_rois.json")
SLOT_CONF = float(env_value("SLOT_CONF", "0.25"))
SLOT_IOU = float(env_value("SLOT_IOU", "0.30"))
SLOT_IMGSZ = int(env_value("SLOT_IMGSZ", "640"))
SLOT_MAX_COUNT = int(env_value("SLOT_MAX_COUNT", "0"))
VEHICLE_CONF = float(env_value("VEHICLE_CONF", "0.25"))
DRAW_VEHICLE_BOXES = env_value("DRAW_VEHICLE_BOXES", "false").strip().lower() in TRUE_VALUES
OCCUPIED_THRESHOLD = float(env_value("OCCUPIED_THRESHOLD", "0.70"))
OCCUPIED_SLOT_THRESHOLD = float(env_value("OCCUPIED_SLOT_THRESHOLD", "0.70"))
CENTER_EDGE_TOLERANCE_PX = float(env_value("CENTER_EDGE_TOLERANCE_PX", "26"))
EDGE_MIN_SLOT_OVERLAP = float(env_value("EDGE_MIN_SLOT_OVERLAP", "0.10"))
VEHICLE_FOOTPRINT_RATIO = float(env_value("VEHICLE_FOOTPRINT_RATIO", "0.38"))
FOOTPRINT_MIN_SLOT_OVERLAP = float(env_value("FOOTPRINT_MIN_SLOT_OVERLAP", "0.14"))
FOOTPRINT_MIN_VEHICLE_OVERLAP = float(env_value("FOOTPRINT_MIN_VEHICLE_OVERLAP", "0.24"))
VEHICLE_BASE_BAND_RATIO = float(env_value("VEHICLE_BASE_BAND_RATIO", "0.18"))
BASE_BAND_MIN_SLOT_OVERLAP = float(env_value("BASE_BAND_MIN_SLOT_OVERLAP", "0.05"))
BASE_BAND_MIN_VEHICLE_OVERLAP = float(env_value("BASE_BAND_MIN_VEHICLE_OVERLAP", "0.14"))
FAR_ZONE_Y_RATIO = float(env_value("FAR_ZONE_Y_RATIO", "0.46"))
FAR_THRESHOLD_SCALE = float(env_value("FAR_THRESHOLD_SCALE", "0.72"))
PARKING_AUTO_LOG_SECONDS = float(env_value("PARKING_AUTO_LOG_SECONDS", "10"))
SLOTS_REFRESH_INTERVAL = int(env_value("SLOTS_REFRESH_INTERVAL", "60"))
STREAM_WIDTH = int(env_value("STREAM_WIDTH", "960"))
STREAM_HEIGHT = int(env_value("STREAM_HEIGHT", "540"))
STREAM_JPEG_QUALITY = int(env_value("STREAM_JPEG_QUALITY", "75"))
PREVIEW_WIDTH = int(env_value("PREVIEW_WIDTH", "960"))
PREVIEW_HEIGHT = int(env_value("PREVIEW_HEIGHT", "540"))
PREVIEW_JPEG_QUALITY = int(env_value("PREVIEW_JPEG_QUALITY", "78"))

STREAM_WIDTH = max(320, STREAM_WIDTH)
STREAM_HEIGHT = max(180, STREAM_HEIGHT)
PREVIEW_WIDTH = max(320, PREVIEW_WIDTH)
PREVIEW_HEIGHT = max(180, PREVIEW_HEIGHT)
STREAM_JPEG_QUALITY = max(40, min(95, STREAM_JPEG_QUALITY))
PREVIEW_JPEG_QUALITY = max(40, min(95, PREVIEW_JPEG_QUALITY))
VEHICLE_FOOTPRINT_RATIO = max(0.20, min(0.70, VEHICLE_FOOTPRINT_RATIO))
FOOTPRINT_MIN_SLOT_OVERLAP = max(0.02, min(0.60, FOOTPRINT_MIN_SLOT_OVERLAP))
FOOTPRINT_MIN_VEHICLE_OVERLAP = max(0.05, min(0.80, FOOTPRINT_MIN_VEHICLE_OVERLAP))
VEHICLE_BASE_BAND_RATIO = max(0.10, min(0.35, VEHICLE_BASE_BAND_RATIO))
BASE_BAND_MIN_SLOT_OVERLAP = max(0.01, min(0.50, BASE_BAND_MIN_SLOT_OVERLAP))
BASE_BAND_MIN_VEHICLE_OVERLAP = max(0.05, min(0.60, BASE_BAND_MIN_VEHICLE_OVERLAP))
FAR_ZONE_Y_RATIO = max(0.10, min(0.90, FAR_ZONE_Y_RATIO))
FAR_THRESHOLD_SCALE = max(0.45, min(1.00, FAR_THRESHOLD_SCALE))
STREAM_SIZE = (STREAM_WIDTH, STREAM_HEIGHT)
PREVIEW_SIZE = (PREVIEW_WIDTH, PREVIEW_HEIGHT)
VEHICLE_CLASS_NAMES = {"car", "bus", "truck"}
Slot = Union[Tuple[int, int, int, int], dict[str, object]]

slot_model = None
vehicle_model = None
model = None
device = "cpu"
parking_state_lock = threading.Lock()
parking_state: dict[int, dict[int, dict[str, object]]] = {}


def resolve_backend_path(path: str, fallbacks: Optional[list[str]] = None) -> str:
    """ค้นหาไฟล์ประกอบให้เจอไม่ว่าจะรัน uvicorn จากโฟลเดอร์ backend/ หรือโฟลเดอร์หลัก"""
    candidates = [path]
    if not os.path.isabs(path):
        candidates.append(os.path.join(BASE_DIR, path))
    for fallback in fallbacks or []:
        candidates.append(fallback)
        if not os.path.isabs(fallback):
            candidates.append(os.path.join(BASE_DIR, fallback))

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    return candidates[1] if len(candidates) > 1 else path


def writable_backend_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)


def is_file_source(source: str) -> bool:
    """คืนค่า True เมื่อ source เป็นไฟล์ในเครื่อง ไม่ใช่ RTSP/HTTP"""
    lower = str(source).lower()
    return not (lower.startswith("rtsp://") or lower.startswith("http://") or lower.startswith("https://"))


def build_rtsp_url(username: str, password: str, ip: str) -> str:
    return f"rtsp://{username}:{password}@{ip}:554/stream2"


def _resolve_demo_video_source(ip: str = "") -> str:
    """ค้นหา path วิดีโอตัวอย่างจากค่ากล้องหรือค่า default ของระบบ

    รองรับรูปแบบ ip ในแถวกล้องดังนี้:
    - video:videos/file.mp4
    - file:videos/file.mp4
    - path ปกติแบบ relative/absolute ที่ลงท้ายด้วยนามสกุลวิดีโอ
    """
    value = (ip or "").strip()
    if value:
        lowered = value.lower()
        prefixes = ("video:", "file:")
        if lowered.startswith(prefixes):
            raw_path = value.split(":", 1)[1].strip()
            if raw_path:
                return resolve_backend_path(raw_path)

        if lowered.endswith((".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v")):
            return resolve_backend_path(value)

    return resolve_backend_path(DEMO_VIDEO_PATH)


def get_stream_source(ip: str = "", username: str = "", password: str = "") -> str:
    """คืนค่า URL หรือ path ของแหล่งภาพที่จะให้ OpenCV/MediaPlayer เปิดใช้งาน"""
    value = (ip or "").strip().lower()
    if value.startswith(("video:", "file:")) or value.endswith((".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v")):
        return _resolve_demo_video_source(ip=ip)

    if USE_DEMO_VIDEO:
        return _resolve_demo_video_source(ip=ip)
    return build_rtsp_url(username=username, password=password, ip=ip)


def open_video_capture(source: str) -> cv2.VideoCapture:
    """เปิดตัวรับภาพและตั้งค่าพิเศษของ FFMPEG เมื่อเป็น RTSP"""
    if is_file_source(source):
        cap = cv2.VideoCapture(source)
    else:
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 0)
        cap.set(cv2.CAP_PROP_FPS, 60)
    return cap


def rewind_if_demo_video(cap: cv2.VideoCapture, source: str) -> bool:
    """หากเป็นไฟล์วิดีโอและอ่านจนจบ ให้ย้อนกลับไปเฟรมแรกเพื่อวนลูป"""
    if USE_DEMO_VIDEO or is_file_source(source):
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        return True
    return False


def clamp_box(box: tuple[float, float, float, float], width: int, height: int) -> Optional[tuple[int, int, int, int]]:
    x1, y1, x2, y2 = box
    x1 = max(0, min(width - 1, int(round(x1))))
    y1 = max(0, min(height - 1, int(round(y1))))
    x2 = max(0, min(width - 1, int(round(x2))))
    y2 = max(0, min(height - 1, int(round(y2))))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def maybe_scale_box(box: tuple[float, float, float, float], width: int, height: int) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = box
    if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.5:
        return x1 * width, y1 * height, x2 * width, y2 * height
    return box


# ตัวช่วยแปลง ROI จากหลายรูปแบบให้เป็นกรอบ/พิกัดช่องจอดมาตรฐานภายในระบบ
def roi_to_box(roi, width: int, height: int, source_size: Optional[tuple[int, int]] = None) -> Optional[tuple[int, int, int, int]]:
    points = None
    box = None

    if isinstance(roi, dict):
        if "bbox" in roi:
            raw = roi["bbox"]
            if len(raw) >= 4:
                if roi.get("format") == "xywh":
                    box = (raw[0], raw[1], raw[0] + raw[2], raw[1] + raw[3])
                else:
                    box = tuple(raw[:4])
        elif all(key in roi for key in ("x1", "y1", "x2", "y2")):
            box = (roi["x1"], roi["y1"], roi["x2"], roi["y2"])
        elif all(key in roi for key in ("x", "y", "w", "h")):
            box = (roi["x"], roi["y"], roi["x"] + roi["w"], roi["y"] + roi["h"])
        else:
            points = roi.get("points") or roi.get("polygon") or roi.get("roi")
    elif isinstance(roi, (list, tuple)):
        if len(roi) >= 4 and all(isinstance(v, (int, float)) for v in roi[:4]):
            box = tuple(roi[:4])
        else:
            points = roi

    if points:
        try:
            xs = [float(p[0]) for p in points]
            ys = [float(p[1]) for p in points]
            box = (min(xs), min(ys), max(xs), max(ys))
        except (TypeError, ValueError, IndexError):
            return None

    if not box:
        return None

    box = maybe_scale_box(tuple(float(v) for v in box), width, height)

    if source_size:
        src_w, src_h = source_size
        if src_w and src_h and (src_w != width or src_h != height):
            sx = width / src_w
            sy = height / src_h
            box = (box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy)

    return clamp_box(box, width, height)


def scale_roi_point(point, width: int, height: int, source_size: Optional[tuple[int, int]] = None) -> Optional[tuple[int, int]]:
    try:
        x = float(point[0])
        y = float(point[1])
    except (TypeError, ValueError, IndexError):
        return None

    if max(abs(x), abs(y)) <= 1.5:
        x *= width
        y *= height
    elif source_size:
        src_w, src_h = source_size
        if src_w and src_h and (src_w != width or src_h != height):
            x *= width / src_w
            y *= height / src_h

    x = max(0, min(width - 1, int(round(x))))
    y = max(0, min(height - 1, int(round(y))))
    return x, y


def roi_to_slot(roi, width: int, height: int, source_size: Optional[tuple[int, int]] = None) -> Optional[Slot]:
    raw_points = None
    if isinstance(roi, dict):
        raw_points = roi.get("points") or roi.get("polygon") or roi.get("roi")
    elif isinstance(roi, (list, tuple)) and not (len(roi) >= 4 and all(isinstance(v, (int, float)) for v in roi[:4])):
        raw_points = roi

    if raw_points:
        points = [point for point in (scale_roi_point(p, width, height, source_size) for p in raw_points) if point]
        if len(points) >= 3:
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            box = clamp_box((min(xs), min(ys), max(xs), max(ys)), width, height)
            if box:
                return {"box": box, "points": points}

    box = roi_to_box(roi, width, height, source_size)
    return box


def slot_box(slot: Slot) -> tuple[int, int, int, int]:
    if isinstance(slot, dict):
        return slot["box"]  # type: ignore[return-value]
    return slot


def slot_polygon(slot: Slot) -> list[tuple[int, int]]:
    if isinstance(slot, dict):
        points = slot.get("points")
        if isinstance(points, list) and len(points) >= 3:
            return points  # type: ignore[return-value]
    x1, y1, x2, y2 = slot_box(slot)
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def sort_slots(slots: list[Slot]) -> list[Slot]:
    return sorted(slots, key=lambda slot: (slot_box(slot)[1] // 30, slot_box(slot)[0]))


# การโหลดช่องจอดจะใช้ ROI ของกล้องนั้นก่อน แล้วค่อย fallback ไป ROI กลางถ้าเปิดใช้งาน
def load_manual_slots(width: int, height: int) -> list[Slot]:
    path = resolve_backend_path(MANUAL_ROI_PATH)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("MANUAL_ROI_LOAD_FAILED path=%s error=%s", path, exc)
        return []

    source_size = None
    rois = data
    if isinstance(data, dict):
        raw_size = data.get("image_size") or data.get("size")
        if isinstance(raw_size, dict):
            source_size = (int(raw_size.get("width", 0)), int(raw_size.get("height", 0)))
        elif isinstance(raw_size, (list, tuple)) and len(raw_size) >= 2:
            source_size = (int(raw_size[0]), int(raw_size[1]))
        rois = data.get("rois") or data.get("slots") or data.get("parking_slots") or data.get("manual_rois") or []

    slots = []
    for roi in rois if isinstance(rois, list) else []:
        slot = roi_to_slot(roi, width, height, source_size)
        if slot:
            slots.append(slot)

    return sort_slots(slots)


def load_camera_manual_slots(camera_id: int, width: int, height: int) -> list[Slot]:
    camera_rois = get_camera_rois(camera_id)
    if not camera_rois:
        return []

    source_size = None
    raw_size = camera_rois.get("image_size")
    if isinstance(raw_size, dict):
        source_size = (int(raw_size.get("width", 0)), int(raw_size.get("height", 0)))
    elif isinstance(raw_size, (list, tuple)) and len(raw_size) >= 2:
        source_size = (int(raw_size[0]), int(raw_size[1]))

    slots: list[Slot] = []
    rois = camera_rois.get("rois") or []
    for roi in rois if isinstance(rois, list) else []:
        slot = roi_to_slot(roi, width, height, source_size)
        if slot:
            slots.append(slot)

    return sort_slots(slots)


def boxes_from_yolo(result, width: int, height: int, allowed_names: Optional[set[str]] = None) -> list[tuple[int, int, int, int]]:
    boxes = []
    names = getattr(result, "names", {}) or {}
    for box in getattr(result, "boxes", []):
        cls_id = int(box.cls[0]) if box.cls is not None else -1
        cls_name = str(names.get(cls_id, cls_id)).lower()
        if allowed_names is not None and cls_name not in allowed_names:
            continue
        xyxy = box.xyxy[0].detach().cpu().tolist()
        clamped = clamp_box(tuple(xyxy), width, height)
        if clamped:
            boxes.append(clamped)
    return boxes


def scored_boxes_from_yolo(result, width: int, height: int) -> list[tuple[tuple[int, int, int, int], float]]:
    boxes = []
    for box in getattr(result, "boxes", []):
        xyxy = box.xyxy[0].detach().cpu().tolist()
        clamped = clamp_box(tuple(xyxy), width, height)
        if clamped:
            score = float(box.conf[0]) if box.conf is not None else 0.0
            boxes.append((clamped, score))
    return boxes


def detect_slots(frame, half_precision: bool) -> list[tuple[int, int, int, int]]:
    if not USE_AUTO_SLOT or slot_model is None:
        return []
    result = slot_model(
        frame,
        verbose=False,
        conf=SLOT_CONF,
        iou=SLOT_IOU,
        imgsz=SLOT_IMGSZ,
        device=device,
        half=half_precision,
    )[0]
    height, width = frame.shape[:2]
    scored_slots = scored_boxes_from_yolo(result, width, height)
    if SLOT_MAX_COUNT > 0:
        scored_slots = sorted(scored_slots, key=lambda item: item[1], reverse=True)[:SLOT_MAX_COUNT]
    return sort_slots([box for box, _ in scored_slots])


def detect_vehicles(frame, half_precision: bool) -> list[tuple[int, int, int, int]]:
    if vehicle_model is None:
        return []
    result = vehicle_model(frame, verbose=False, conf=VEHICLE_CONF, device=device, half=half_precision)[0]
    height, width = frame.shape[:2]
    return boxes_from_yolo(result, width, height, VEHICLE_CLASS_NAMES)


# กติกาจับคู่รถกับช่องจะนับว่าจอดก็ต่อเมื่อผ่านเงื่อนไขทับซ้อน/จุดกึ่งกลาง
def intersection_area(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    return max(0, x2 - x1) * max(0, y2 - y1)


def convex_intersection_area(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> float:
    a_poly = np.array(a, dtype=np.float32)
    b_poly = np.array(b, dtype=np.float32)
    area, _ = cv2.intersectConvexConvex(a_poly, b_poly)
    return float(area)


def polygon_area(points: list[tuple[int, int]]) -> float:
    return float(cv2.contourArea(np.array(points, dtype=np.float32)))


def polygon_centroid(points: list[tuple[int, int]]) -> tuple[float, float]:
    contour = np.array(points, dtype=np.float32)
    moments = cv2.moments(contour)
    if moments["m00"]:
        return (moments["m10"] / moments["m00"], moments["m01"] / moments["m00"])
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (float(sum(xs) / max(1, len(xs))), float(sum(ys) / max(1, len(ys))))


def vehicle_center(vehicle: tuple[int, int, int, int]) -> tuple[float, float]:
    return ((vehicle[0] + vehicle[2]) / 2.0, (vehicle[1] + vehicle[3]) / 2.0)


def vehicle_footprint_box(vehicle: tuple[int, int, int, int], ratio: float) -> tuple[int, int, int, int]:
    """คืนกรอบช่วงล่างของรถเพื่อแทนตำแหน่งสัมผัสพื้น (เหมาะกับมุมกล้องเฉียง/รถสูง)"""
    x1, y1, x2, y2 = vehicle
    h = max(1, y2 - y1)
    footprint_h = max(1, int(round(h * ratio)))
    fy1 = max(y1, y2 - footprint_h)
    return (x1, fy1, x2, y2)


def vehicle_base_band_box(vehicle: tuple[int, int, int, int], ratio: float) -> tuple[int, int, int, int]:
    """ช่วงล่างสุดของรถแบบแคบกว่าฟุตปริ้นท์ เหมาะกับมุมกล้องเฉียงและรถสูง"""
    x1, y1, x2, y2 = vehicle
    h = max(1, y2 - y1)
    band_h = max(1, int(round(h * ratio)))
    by1 = max(y1, y2 - band_h)
    return (x1, by1, x2, y2)


def slot_vehicle_match_score(slot: Slot, vehicle: tuple[int, int, int, int]) -> Optional[float]:
    polygon = slot_polygon(slot)
    slot_area = max(1.0, polygon_area(polygon))
    slot_cx, slot_cy = polygon_centroid(polygon)
    slot_center_y = float(np.mean([point[1] for point in polygon]))
    slot_y_ratio = slot_center_y / max(1.0, float(STREAM_HEIGHT))
    is_far_slot = slot_y_ratio <= FAR_ZONE_Y_RATIO
    threshold_scale = FAR_THRESHOLD_SCALE if is_far_slot else 1.0

    occupied_threshold = OCCUPIED_THRESHOLD * threshold_scale
    occupied_slot_threshold = OCCUPIED_SLOT_THRESHOLD * threshold_scale
    edge_min_slot_overlap = EDGE_MIN_SLOT_OVERLAP * threshold_scale
    footprint_min_slot_overlap = FOOTPRINT_MIN_SLOT_OVERLAP * threshold_scale
    footprint_min_vehicle_overlap = FOOTPRINT_MIN_VEHICLE_OVERLAP * threshold_scale
    bottom_center_overlap = 0.10 * threshold_scale

    vehicle_area = max(1, (vehicle[2] - vehicle[0]) * (vehicle[3] - vehicle[1]))
    vehicle_polygon = [(vehicle[0], vehicle[1]), (vehicle[2], vehicle[1]), (vehicle[2], vehicle[3]), (vehicle[0], vehicle[3])]
    overlap_area = convex_intersection_area(polygon, vehicle_polygon)

    footprint = vehicle_footprint_box(vehicle, VEHICLE_FOOTPRINT_RATIO)
    base_band = vehicle_base_band_box(vehicle, VEHICLE_BASE_BAND_RATIO)
    footprint_area = max(1, (footprint[2] - footprint[0]) * (footprint[3] - footprint[1]))
    base_band_area = max(1, (base_band[2] - base_band[0]) * (base_band[3] - base_band[1]))
    footprint_polygon = [
        (footprint[0], footprint[1]),
        (footprint[2], footprint[1]),
        (footprint[2], footprint[3]),
        (footprint[0], footprint[3]),
    ]
    base_band_polygon = [
        (base_band[0], base_band[1]),
        (base_band[2], base_band[1]),
        (base_band[2], base_band[3]),
        (base_band[0], base_band[3]),
    ]
    footprint_overlap_area = convex_intersection_area(polygon, footprint_polygon)
    base_band_overlap_area = convex_intersection_area(polygon, base_band_polygon)

    if overlap_area <= 0 and footprint_overlap_area <= 0 and base_band_overlap_area <= 0:
        return None

    vehicle_overlap_ratio = overlap_area / vehicle_area
    slot_overlap_ratio = overlap_area / slot_area
    footprint_vehicle_overlap_ratio = footprint_overlap_area / footprint_area
    footprint_slot_overlap_ratio = footprint_overlap_area / slot_area
    base_band_vehicle_overlap_ratio = base_band_overlap_area / base_band_area
    base_band_slot_overlap_ratio = base_band_overlap_area / slot_area
    center_x, center_y = vehicle_center(vehicle)
    bottom_center_x = (vehicle[0] + vehicle[2]) / 2.0
    bottom_center_y = float(vehicle[3])
    contour = np.array(polygon, dtype=np.int32)
    center_distance = cv2.pointPolygonTest(contour, (center_x, center_y), True)
    bottom_center_distance = cv2.pointPolygonTest(contour, (bottom_center_x, bottom_center_y), True)
    slot_center_in_vehicle = cv2.pointPolygonTest(
        np.array(vehicle_polygon, dtype=np.int32),
        (slot_cx, slot_cy),
        False,
    ) >= 0
    slot_center_in_footprint = cv2.pointPolygonTest(
        np.array(footprint_polygon, dtype=np.int32),
        (slot_cx, slot_cy),
        False,
    ) >= 0
    slot_center_in_base_band = cv2.pointPolygonTest(
        np.array(base_band_polygon, dtype=np.int32),
        (slot_cx, slot_cy),
        False,
    ) >= 0
    center_in_slot = center_distance >= 0
    center_near_edge = center_distance >= -CENTER_EDGE_TOLERANCE_PX
    bottom_center_in_slot = bottom_center_distance >= 0
    bottom_center_near_edge = bottom_center_distance >= -CENTER_EDGE_TOLERANCE_PX

    is_candidate = (
        vehicle_overlap_ratio >= occupied_threshold
        or slot_overlap_ratio >= occupied_slot_threshold
        or (center_in_slot and slot_overlap_ratio >= 0.05)
        or (center_near_edge and slot_overlap_ratio >= edge_min_slot_overlap)
        or (footprint_slot_overlap_ratio >= footprint_min_slot_overlap)
        or (footprint_vehicle_overlap_ratio >= footprint_min_vehicle_overlap)
        or (base_band_slot_overlap_ratio >= BASE_BAND_MIN_SLOT_OVERLAP)
        or (base_band_vehicle_overlap_ratio >= BASE_BAND_MIN_VEHICLE_OVERLAP)
        or (slot_center_in_vehicle and footprint_slot_overlap_ratio >= 0.05)
        or (slot_center_in_footprint and footprint_slot_overlap_ratio >= 0.03)
        or (slot_center_in_base_band and base_band_slot_overlap_ratio >= 0.02)
        or (bottom_center_in_slot and footprint_slot_overlap_ratio >= 0.06)
        or (bottom_center_near_edge and footprint_slot_overlap_ratio >= bottom_center_overlap)
    )

    if not is_candidate:
        return None

    return (
        (slot_overlap_ratio * 0.35)
        + (vehicle_overlap_ratio * 0.20)
        + (footprint_slot_overlap_ratio * 0.35)
        + (footprint_vehicle_overlap_ratio * 0.10)
        + (base_band_slot_overlap_ratio * 0.25)
        + (base_band_vehicle_overlap_ratio * 0.10)
        + (0.20 if slot_center_in_footprint else 0.0)
        + (0.20 if slot_center_in_base_band else 0.0)
        + (0.12 if slot_center_in_vehicle else 0.0)
        + (0.18 if center_in_slot else 0.0)
        + (0.22 if bottom_center_in_slot else 0.0)
    )


def assign_occupied_slots(slots: list[Slot], vehicles: list[tuple[int, int, int, int]]) -> set[int]:
    """จับคู่รถแต่ละคันได้สูงสุดหนึ่งช่อง เพื่อกันการนับรถคันเดียวซ้ำหลายช่อง"""
    candidates: list[tuple[float, int, int]] = []
    for slot_idx, slot in enumerate(slots):
        for vehicle_idx, vehicle in enumerate(vehicles):
            score = slot_vehicle_match_score(slot, vehicle)
            if score is not None:
                candidates.append((score, slot_idx, vehicle_idx))

    candidates.sort(reverse=True, key=lambda item: item[0])
    used_slots: set[int] = set()
    used_vehicles: set[int] = set()

    for _, slot_idx, vehicle_idx in candidates:
        if slot_idx in used_slots or vehicle_idx in used_vehicles:
            continue
        used_slots.add(slot_idx)
        used_vehicles.add(vehicle_idx)

    return used_slots


def draw_parking_overlay(frame, slots: list[Slot], vehicles: list[tuple[int, int, int, int]]):
    annotated = frame.copy()
    occupied_slot_indexes = assign_occupied_slots(slots, vehicles)
    occupied_slots = sorted(index + 1 for index in occupied_slot_indexes)
    occupied_count = len(occupied_slots)

    if DRAW_VEHICLE_BOXES:
        for vehicle in vehicles:
            cv2.rectangle(annotated, (vehicle[0], vehicle[1]), (vehicle[2], vehicle[3]), (255, 180, 0), 1)

    for index, slot in enumerate(slots, start=1):
        occupied = (index - 1) in occupied_slot_indexes
        color = (0, 0, 255) if occupied else (0, 190, 0)
        box = slot_box(slot)
        points = np.array(slot_polygon(slot), dtype=np.int32)
        cv2.polylines(annotated, [points], True, color, 2)
        label = str(index)
        center_x = int(np.mean(points[:, 0]))
        center_y = int(np.mean(points[:, 1]))
        (text_width, text_height), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.58, 2)
        text_x = center_x - text_width // 2
        text_y = center_y + text_height // 2
        cv2.putText(
            annotated,
            label,
            (text_x, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            color,
            2,
            cv2.LINE_AA,
        )

    empty_count = max(0, len(slots) - occupied_count)
    summary = f"Slots {len(slots)} | Occupied {occupied_count} | Empty {empty_count}"
    cv2.rectangle(annotated, (8, 8), (330, 42), (0, 0, 0), -1)
    cv2.putText(annotated, summary, (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2, cv2.LINE_AA)
    return annotated, {"total": len(slots), "occupied": occupied_count, "empty": empty_count, "occupied_slots": occupied_slots}


def annotate_parking_frame(
    frame,
    cached_slots: Optional[list[Slot]] = None,
    force_slot_refresh: bool = False,
    camera_id: Optional[int] = None,
):
    resized_frame = cv2.resize(frame, STREAM_SIZE)
    half_precision = str(device).startswith("cuda")
    slots = cached_slots or []

    if force_slot_refresh or not slots:
        camera_roi_defined = False
        if camera_id is not None:
            camera_roi_defined = get_camera_rois(camera_id) is not None
            slots = load_camera_manual_slots(camera_id, *STREAM_SIZE)

        if not slots and not camera_roi_defined:
            slots = detect_slots(resized_frame, half_precision)
            if not slots and USE_MANUAL_ROI_FALLBACK:
                slots = load_manual_slots(*STREAM_SIZE)

    vehicles = detect_vehicles(resized_frame, half_precision)
    annotated_frame, stats = draw_parking_overlay(resized_frame, slots, vehicles)
    return annotated_frame, slots, stats


# สถานะช่องจอดแบบเรียลไทม์ใช้ติดตามระยะเวลาครอบครองและสร้างเหตุการณ์เข้า/ออก
def update_parking_state(camera_id: int, occupied_slots: list[int]) -> tuple[list[int], list[dict[str, object]]]:
    now = time.time()
    auto_log_slots: list[int] = []
    exit_events: list[dict[str, object]] = []
    occupied_set = set(int(slot) for slot in occupied_slots)

    with parking_state_lock:
        camera_state = parking_state.setdefault(camera_id, {})

        for slot_number in list(camera_state.keys()):
            if slot_number not in occupied_set:
                slot_state = camera_state[slot_number]
                was_logged = bool(slot_state.get("auto_logged", False)) or bool(slot_state.get("manual_logged", False))
                if was_logged:
                    exit_events.append({
                        "slot_number": slot_number,
                        "username": slot_state.get("username"),
                    })
                del camera_state[slot_number]

        for slot_number in occupied_set:
            slot_state = camera_state.get(slot_number)
            if slot_state is None:
                camera_state[slot_number] = {
                    "occupied_since": now,
                    "last_seen": now,
                    "auto_logged": False,
                    "manual_logged": False,
                    "username": None,
                }
                continue

            slot_state["last_seen"] = now
            occupied_since = float(slot_state.get("occupied_since", now))
            auto_logged = bool(slot_state.get("auto_logged", False))
            if not auto_logged and now - occupied_since >= PARKING_AUTO_LOG_SECONDS:
                slot_state["auto_logged"] = True
                auto_log_slots.append(slot_number)

    return auto_log_slots, exit_events


def get_latest_occupied_slots(camera_id: int) -> list[dict[str, object]]:
    now = time.time()
    with parking_state_lock:
        camera_state = parking_state.get(camera_id, {})
        slots = []
        for slot_number, slot_state in camera_state.items():
            occupied_since = float(slot_state.get("occupied_since", now))
            slots.append({
                "slot_number": slot_number,
                "occupied_seconds": max(0.0, now - occupied_since),
                "manual_logged": bool(slot_state.get("manual_logged", False)),
                "auto_logged": bool(slot_state.get("auto_logged", False)),
            })
    return sorted(slots, key=lambda item: item["occupied_seconds"])


def latest_unlogged_slot_number(camera_id: int) -> Optional[int]:
    with parking_state_lock:
        camera_state = parking_state.get(camera_id, {})
        unlogged_slots = {
            number: state
            for number, state in camera_state.items()
            if not bool(state.get("manual_logged", False))
        }
        if not unlogged_slots:
            return None
        return max(
            unlogged_slots,
            key=lambda number: float(unlogged_slots[number].get("occupied_since", 0)),
        )


def mark_manual_logged(camera_id: int, slot_number: int, username: str) -> bool:
    with parking_state_lock:
        camera_state = parking_state.get(camera_id, {})
        unlogged_slots = {
            number: state
            for number, state in camera_state.items()
            if not bool(state.get("manual_logged", False))
        }
        if not unlogged_slots:
            return False
        latest_slot = max(
            unlogged_slots,
            key=lambda number: float(unlogged_slots[number].get("occupied_since", 0)),
        )
        if slot_number != latest_slot:
            return False

        slot_state = camera_state.get(slot_number)
        if slot_state is None:
            return False
        slot_state["manual_logged"] = True
        slot_state["username"] = username
        return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    # โหลดโมเดล AI ตอนเริ่มระบบ
    global model, slot_model, vehicle_model
    import torch
    global device
    if AI_DEVICE == "auto":
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    elif AI_DEVICE.startswith("cuda") or AI_DEVICE == "0":
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        if device == "cpu":
            logger.warning("AI_DEVICE=%s requested but CUDA is not available; falling back to CPU", AI_DEVICE)
    else:
        device = AI_DEVICE
    slot_path = resolve_backend_path(SLOT_MODEL_PATH, ["best.pt", "yolov8n.pt"])
    vehicle_path = resolve_backend_path(VEHICLE_MODEL_PATH, ["yolov8s.pt", "yolov8n.pt"])

    def _load_model_with_fallback(local_path: str, configured_value: str, model_name: str):
        if os.path.exists(local_path):
            return YOLO(local_path)
        # รองรับชื่อโมเดลสำเร็จรูปของ Ultralytics (เช่น yolov8n.pt) ให้ดาวน์โหลดอัตโนมัติ
        if (
            configured_value
            and os.path.basename(configured_value) == configured_value
            and configured_value.lower().endswith(".pt")
        ):
            logger.warning("%s_LOCAL_FILE_MISSING trying_pretrained=%s", model_name, configured_value)
            return YOLO(configured_value)
        raise FileNotFoundError(f"Model file not found: {local_path}")

    if USE_AUTO_SLOT:
        try:
            slot_model = _load_model_with_fallback(slot_path, SLOT_MODEL_PATH, "AUTO_SLOT")
        except Exception as exc:
            logger.warning("AUTO_SLOT_DISABLED reason=%s path=%s", exc, slot_path)
            slot_model = None
    else:
        slot_model = None

    try:
        vehicle_model = _load_model_with_fallback(vehicle_path, VEHICLE_MODEL_PATH, "VEHICLE_MODEL")
    except Exception as exc:
        logger.warning("VEHICLE_MODEL_DISABLED reason=%s path=%s", exc, vehicle_path)
        vehicle_model = None

    model = vehicle_model
    print(f"âœ… AI components initialized on {device}")
    
    # รอให้ฐานข้อมูลพร้อมก่อนเริ่มต้นระบบ
    max_retries = int(env_value("DB_STARTUP_RETRIES", "1"))
    for i in range(max_retries):
        try:
            conn = get_connection()
            if conn:
                release_connection(conn)
                print("âœ… Database connected successfully")
                break
        except Exception as e:
            print(f"â³ Waiting for database... ({i+1}/{max_retries}) - {e}")
            time.sleep(1)
    else:
        print("Database unavailable after retries; starting API without database")
        yield
        return

    # สร้าง/อัปเดตโครงสร้างตารางที่จำเป็น
    try:
        init_db()
        print("Database initialized")
    except Exception as exc:
        logger.error("Database initialization failed; starting API without database: %s", exc)
    yield

app = FastAPI(lifespan=lifespan)

# เปิด CORS ให้ทุก origin เพื่อรองรับการเรียกจากส่วนหน้า
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # อนุญาตทุก domain/origin
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- โมเดลข้อมูลรับ-ส่งของ API ---
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


class CameraDeleteRequest(BaseModel):
    camera_id: int
    username: str
    password: str

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
    slot_number: Optional[int] = None


class RoiMarkerSave(BaseModel):
    camera_id: Optional[int] = None
    image_size: list[int]
    rois: list[dict]

# --- จัดการผู้ใช้ ---

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


# --- จัดการประวัติการจอด ---

@app.post("/parking_history/log")
async def log_parking_history(data: ParkingHistoryLog):
    """บันทึกประวัติการจอดรถ"""
    slot_number = data.slot_number
    if slot_number is None:
        slot_number = latest_unlogged_slot_number(data.camera_id)
    if slot_number is None:
        raise HTTPException(status_code=409, detail="No latest occupied slot is available")
    if not mark_manual_logged(data.camera_id, slot_number, data.username):
        raise HTTPException(status_code=409, detail="Selected slot is not the latest occupied slot or was already logged")

    success = False
    if data.event_type == "parking_success":
        success = promote_latest_anonymous_auto_history(
            data.username,
            data.camera_id,
            slot_number,
            data.event_type,
        )

    if not success:
        success = add_parking_history(data.username, data.camera_id, data.event_type, slot_number)
    
    if success:
        logger.info("PARKING_LOG_SUCCESS username=%s camera_id=%s", data.username, data.camera_id)
        return {"status": "success", "message": "Parking history logged", "slot_number": slot_number}
    
    logger.error("PARKING_LOG_ERROR username=%s camera_id=%s", data.username, data.camera_id)
    raise HTTPException(status_code=500, detail="Failed to log parking history")


@app.get("/parking_status/latest")
async def latest_parking_status(camera_id: int):
    return {"status": "success", "slots": get_latest_occupied_slots(camera_id)}


@app.get("/parking_history")
async def get_user_parking_history(username: str, limit: int = 100):
    """ดึงประวัติการจอดของผู้ใช้"""
    try:
        history = get_parking_history(username=username, limit=limit)
        return {"status": "success", "data": history}
    except Exception as e:
        logger.error("GET_PARKING_HISTORY_ERROR username=%s error=%s", username, str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch parking history")


@app.get("/parking_history/admin")
async def get_admin_parking_history(zone_name: str = None, limit: int = 100):
    """ดึงประวัติการจอดสำหรับแอดมิน โดยสามารถกรองตามโซน"""
    try:
        history = get_parking_history(
            zone_name=zone_name,
            limit=limit,
            min_anonymous_auto_age_seconds=PARKING_AUTO_LOG_SECONDS,
        )
        return {"status": "success", "data": history}
    except Exception as e:
        logger.error("GET_ADMIN_PARKING_HISTORY_ERROR zone=%s error=%s", zone_name, str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch parking history")


# เก็บรายการการเชื่อมต่อ WebRTC ที่กำลังใช้งาน
pcs = set()

@app.post("/offer")
async def webrtc_offer(data: WebRTCOffer):
    if not AIORTC_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail=(
                "WebRTC is unavailable on this machine because aiortc/av could not be loaded. "
                f"Reason: {AIORTC_IMPORT_ERROR}"
            ),
        )

    # สร้าง source สำหรับ WebRTC: ใช้ไฟล์เมื่อเป็นโหมด demo หรือใช้ RTSP จริง
    url = get_stream_source(data.camera.ip, data.camera.username, data.camera.password)
    print(f"ðŸŽ¥ WebRTC source: {url}")

    if is_file_source(url):
        player = MediaPlayer(url)
    else:
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
    print("ðŸ”— WebSocket connected for live stream")

    def _is_disconnect_exception(exc: Exception) -> bool:
        name = type(exc).__name__
        return name in {"WebSocketDisconnect", "ClientDisconnected"}
    
    # รับข้อมูลกล้องจาก client
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
        print(f"ðŸ“¡ Received camera request: camera_id={camera_id}, IP={ip}")
    except Exception as e:
        print(f"âŒ Failed to receive camera data: {e}")
        await websocket.close()
        return
    
    # สร้างแหล่งภาพ: ถ้าเปิด demo mode จะใช้ไฟล์แทน RTSP
    url = get_stream_source(ip=ip, username=username, password=password)
    if USE_DEMO_VIDEO:
        print(f"ðŸŽ¥ Starting DEMO video for camera_id={camera_id}: {url}")
    else:
        print(f"ðŸŽ¥ Starting live stream for camera_id={camera_id}, ip={ip}")

    # เปิดกล้องหรือไฟล์วิดีโอ
    cap = open_video_capture(url)

    # ตรวจสอบว่าเปิดสตรีมได้ก่อนเข้า loop หลัก
    if not cap.isOpened():
        print(f"âŒ Cannot open video source: {url}")
        await websocket.send_text('error: cannot open video source')
        await websocket.close()
        return

    print("âœ… Video source opened successfully")
    frame_count = 0

    frame_queue = asyncio.Queue(maxsize=3)
    stop_event = asyncio.Event()

    # ตัวทำงานที่ 1: อ่านเฟรมจากกล้องเข้า queue (ถ้าค้างให้ทิ้งเฟรมเก่าสุด)
    async def capture_worker():
        while not stop_event.is_set():
            success, frame = await asyncio.get_running_loop().run_in_executor(None, cap.read)
            if not success or frame is None:
                if rewind_if_demo_video(cap, url):
                    await asyncio.sleep(0.03)
                    continue
                print("âš ï¸ Failed to read frame from camera")
                await asyncio.sleep(0.05)
                continue

            if frame_queue.full():
                try:
                    _ = frame_queue.get_nowait()  # ทิ้งเฟรมเก่าสุด
                except asyncio.QueueEmpty:
                    pass

            await frame_queue.put(frame)
            await asyncio.sleep(0)  # เปิดโอกาสให้ event loop ทำงานอื่น

    # ตัวทำงานที่ 2: ทำอนุมาน + เข้ารหัสภาพ + ส่งกลับไปยัง client
    async def processing_worker():
        nonlocal frame_count
        avg_proc = 0.08
        alpha = 0.1
        cached_slots = []
        last_slot_refresh = 0.0

        while not stop_event.is_set():
            try:
                frame = await asyncio.wait_for(frame_queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue

            t0 = time.time()
            now = time.time()
            force_slot_refresh = not cached_slots or (now - last_slot_refresh) >= SLOTS_REFRESH_INTERVAL
            annotated_frame, cached_slots, stats = annotate_parking_frame(frame, cached_slots, force_slot_refresh, camera_id)
            if force_slot_refresh:
                last_slot_refresh = now
            auto_log_slots, exit_events = update_parking_state(camera_id, stats.get("occupied_slots", []))
            for slot_number in auto_log_slots:
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    add_parking_history,
                    None,
                    camera_id,
                    "parking_auto",
                    slot_number,
                )
            for event in exit_events:
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    add_parking_history,
                    event.get("username"),
                    camera_id,
                    "parking_exit",
                    event["slot_number"],
                )
            success, buffer = cv2.imencode(
                '.jpg',
                annotated_frame,
                [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_QUALITY],
            )

            if not success:
                print("âš ï¸ JPEG encoding failed")
                continue

            try:
                await websocket.send_bytes(buffer.tobytes())
            except WebSocketDisconnect:
                stop_event.set()
                return
            except RuntimeError as e:
                # เกิดเมื่อ client ตัดการเชื่อมต่อและ websocket ถูกปิดไปแล้ว
                print(f"â„¹ï¸ WebSocket send stopped: {e}")
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
                print(f"ðŸ“Š Sent {frame_count} frames, avg_proc={avg_proc:.3f}s, target_fps={target_fps}, queue_size={frame_queue.qsize()}")

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
                print("â„¹ï¸ WebSocket client disconnected")
                continue
            print(f"âŒ Error in streaming pipeline: {type(exc).__name__}: {exc}")
    except WebSocketDisconnect:
        print("â„¹ï¸ WebSocket client disconnected")
    except Exception as e:
        print(f"âŒ Error in streaming pipeline: {type(e).__name__}: {e}")
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
        print("ðŸ”š Camera released, WebSocket closing")
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/ws/preview_camera")
async def websocket_preview_camera(websocket: WebSocket):
    """สตรีมภาพพรีวิวหน่วงต่ำสำหรับหน้าเพิ่มกล้อง (ไม่รัน AI)"""
    await websocket.accept()
    cap = None

    try:
        data = await websocket.receive_json()
        ip = data['ip']
        username = data['username']
        password = data['password']

        url = get_stream_source(ip=ip, username=username, password=password)
        if USE_DEMO_VIDEO:
            print(f"ðŸ”Ž Preview DEMO video open: {url}")
        else:
            print(f"ðŸ”Ž Preview stream open for ip={ip}")

        cap = open_video_capture(url)

        if not cap.isOpened():
            await websocket.send_text("error: cannot open camera stream")
            return

        while True:
            success, frame = await asyncio.get_running_loop().run_in_executor(None, cap.read)
            if not success or frame is None:
                if rewind_if_demo_video(cap, url):
                    await asyncio.sleep(0.03)
                    continue
                await asyncio.sleep(0.01)
                continue

            preview = cv2.resize(frame, PREVIEW_SIZE)
            ok, buffer = cv2.imencode('.jpg', preview, [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_JPEG_QUALITY])
            if not ok:
                continue

            await websocket.send_bytes(buffer.tobytes())
            await asyncio.sleep(0)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"âŒ Preview WebSocket error: {e}")
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


# --- ตัวจัดการกล้องสำหรับจุดเรียกดึงภาพเดี่ยว ---
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
                    # ถ้าเป็นไฟล์วิดีโอและเล่นจบ ให้ย้อนกลับเฟรมแรกเพื่อวนลูป
                    if self.current_url and rewind_if_demo_video(self.cap, self.current_url):
                        self.status = False
                        time.sleep(0.03)
                    else:
                        self.status = False
                        time.sleep(1)
            else:
                time.sleep(0.1)

    def change_camera(self, url):
        if self.current_url != url:
            with self.lock:
                print(f"ðŸ”„ Switching camera to: {url}")
                if self.cap:
                    self.cap.release()
                self.current_url = url
                self.cap = open_video_capture(url)
                if not is_file_source(url):
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

cam_manager = CameraStream()

# --- จุดเรียก API หลัก ---

@app.post("/add_camera")
async def add_camera(data: CameraRegister):
    camera_id = add_camera_to_db(data.camera_name, data.ip, data.username, data.password, data.zone_name)
    if camera_id:
        # กล้องใหม่เริ่มด้วย ROI ว่าง เพื่อไม่ให้สืบทอด ROI กลางเดิม
        save_camera_rois(camera_id, [960, 540], [])
        return {"status": "success", "message": "Camera added", "camera_id": camera_id}
    raise HTTPException(status_code=500, detail="Failed to add camera")


@app.post("/delete_camera")
async def delete_camera(data: CameraDeleteRequest):
    auth = authenticate_user(data.username, data.password)
    if auth["status"] != "authenticated":
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    role = get_user_role(data.username)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can delete camera")

    deleted = delete_camera_from_db(data.camera_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Camera not found or cannot be deleted")

    return {"status": "success", "message": "Camera deleted", "camera_id": data.camera_id}

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

# --- เส้นทางตรวจสอบสถานะและดีบัก ---
@app.get("/ping")
async def ping():
    """ทดสอบว่า backend ตอบสนองได้ตามปกติ"""
    return {"status": "ok", "time": time.time()}


@app.get("/roi_marker", response_class=HTMLResponse)
async def roi_marker_page():
    path = resolve_backend_path("roi_marker.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="ROI marker page not found")
    with open(path, "r", encoding="utf-8") as file:
        return HTMLResponse(file.read())


@app.get("/roi_marker/data")
async def roi_marker_data(camera_id: Optional[int] = None):
    if camera_id is not None:
        data = get_camera_rois(camera_id)
        if data:
            return data
        return {
            "camera_id": camera_id,
            "image_size": [960, 540],
            "rois": [],
            "scope": "camera",
        }

    path = resolve_backend_path(MANUAL_ROI_PATH)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return {"image_size": [960, 540], "rois": []}

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read ROI file: {exc}")

    return data


@app.get("/roi_marker/frame")
async def roi_marker_frame(camera_id: Optional[int] = None, second: float = 50.0):
    if camera_id is not None:
        cam = get_camera_credentials(camera_id)
        if not cam:
            raise HTTPException(status_code=404, detail="Camera not found")
        source = get_stream_source(
            ip=cam["ip_address"],
            username=cam["username"],
            password=cam["password"],
        )
    else:
        source = get_stream_source()

    cap = open_video_capture(source)
    try:
        if not cap.isOpened():
            raise HTTPException(status_code=500, detail="Cannot open video source")
        if is_file_source(source):
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, second) * 1000)
        ok, frame = cap.read()
    finally:
        cap.release()

    if not ok or frame is None:
        raise HTTPException(status_code=500, detail="Cannot read frame")

    frame = cv2.resize(frame, (960, 540))
    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(status_code=500, detail="Cannot encode frame")
    return Response(content=buffer.tobytes(), media_type="image/jpeg")


@app.post("/roi_marker/save")
async def roi_marker_save(data: RoiMarkerSave):
    if len(data.image_size) < 2:
        raise HTTPException(status_code=400, detail="image_size must contain width and height")

    cleaned_rois = []
    for roi in data.rois:
        points = roi.get("points")
        if not isinstance(points, list) or len(points) < 3:
            continue
        cleaned_points = []
        for point in points[:4]:
            if not isinstance(point, list) or len(point) < 2:
                continue
            cleaned_points.append([int(round(float(point[0]))), int(round(float(point[1])))])
        if len(cleaned_points) >= 3:
            cleaned_rois.append({"points": cleaned_points})

    output = {
        "image_size": [int(data.image_size[0]), int(data.image_size[1])],
        "rois": cleaned_rois,
    }

    if data.camera_id is not None:
        if not save_camera_rois(data.camera_id, output["image_size"], output["rois"]):
            raise HTTPException(status_code=500, detail="Failed to save camera-specific ROI")
        return {
            "status": "success",
            "slots": len(cleaned_rois),
            "camera_id": data.camera_id,
            "scope": "camera",
        }

    path = writable_backend_path(MANUAL_ROI_PATH)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temp_path = f"{path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(output, file, indent=2)
            file.write("\n")
        os.replace(temp_path, path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save ROI file: {exc}")

    return {"status": "success", "slots": len(cleaned_rois), "path": path, "scope": "global"}


@app.options("/get_cameras")
async def get_cameras_options():
    """ตอบ CORS preflight สำหรับจุดเรียกรายการกล้อง"""
    print("ðŸ“‹ OPTIONS /get_cameras preflight")
    return {}


@app.get("/get_cameras")
async def get_cameras():
    """ดึงรายการกล้องทั้งหมด"""
    print("âž¡ï¸ /get_cameras called")
    request_time = time.time()
    try:
        cameras = get_all_cameras()
        elapsed = time.time() - request_time
        print(f"âœ… /get_cameras returned {len(cameras)} cameras in {elapsed:.3f}s")
        # ส่งข้อมูลกลับได้ทันที ไม่ต้องใส่ header เพิ่มเอง
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

    target_url = get_stream_source(
        ip=cam['ip_address'],
        username=cam['username'],
        password=cam['password'],
    )
    cam_manager.change_camera(target_url)

    if cam_manager.status and cam_manager.frame is not None:
        with cam_manager.lock:
            input_frame = cam_manager.frame.copy()

        # ประมวลผล AI และวาดผลลงภาพ
        annotated_frame, _, stats = annotate_parking_frame(input_frame, force_slot_refresh=True, camera_id=data.camera_id)

        # เข้ารหัสภาพเป็น JPEG + Base64 สำหรับส่งกลับ
        _, buffer = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')
        
        return {
            "status": "success", 
            "image": jpg_as_text,
            "count": stats["occupied"],
            "slots": stats
        }
    
    return {"status": "error", "message": "Connecting..."}

@app.post("/preview_camera")
async def preview_camera(data: CameraByIdRequest):
    """ดึงภาพพรีวิวจากกล้องตาม camera_id เพื่อทดสอบก่อนบันทึก"""
    cam = get_camera_credentials(data.camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    target_url = get_stream_source(
        ip=cam['ip_address'],
        username=cam['username'],
        password=cam['password'],
    )

    # ทดลองอ่านภาพจากกล้องด้วย OpenCV
    cap = open_video_capture(target_url)
    success, frame = cap.read()
    cap.release() # ปล่อยกล้องทันทีหลังอ่านเฟรม เพื่อไม่ให้ค้างการเชื่อมต่อ

    if success:
        # ย่อภาพและแปลงเป็น Base64 เพื่อส่งกลับให้หน้าเว็บแสดงผล
        resized = cv2.resize(frame, (640, 360))
        _, buffer = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, 80])
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')
        return {"status": "success", "image": jpg_as_text}
    
    return {"status": "error", "message": "à¹„à¸¡à¹ˆà¸ªà¸²à¸¡à¸²à¸£à¸–à¹€à¸Šà¸·à¹ˆà¸­à¸¡à¸•à¹ˆà¸­à¸à¸¥à¹‰à¸­à¸‡à¹„à¸”à¹‰ à¹‚à¸›à¸£à¸”à¹€à¸Šà¹‡à¸„ IP à¸«à¸£à¸·à¸­ User/Pass"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
