#!/usr/bin/env python3
"""
ไฟล์ทดสอบ API แยก (Isolated Test)
รันแล้วดู output ว่า endpoint ตอบยังไง
"""

import requests
import json
import time
from typing import Dict, Any

# ========== ตั้งค่า ==========
BACKEND_LOCAL = "http://127.0.0.1:8000"  # local
BACKEND_NGROK = "https://terraqueous-plantar-phebe.ngrok-free.dev"  # ngrok
FRONTEND_ORIGIN = "https://revocable-ventrally-sergio.ngrok-free.dev"

# เลือกทดสอบแบบไหน
USE_NGROK = True
BASE_URL = BACKEND_NGROK if USE_NGROK else BACKEND_LOCAL

print(f"🧪 Testing API at: {BASE_URL}")
print(f"📍 Frontend Origin: {FRONTEND_ORIGIN}\n")


def test_endpoint(method: str, path: str, name: str, headers: Dict = None) -> Any:
    """ทดสอบ endpoint เดี่ยว"""
    url = f"{BASE_URL}{path}"
    print(f"{'='*60}")
    print(f"📌 Test: {name}")
    print(f"   Method: {method}")
    print(f"   URL: {url}")
    
    if headers is None:
        headers = {}
    
    # เพิ่ม Origin header ทั้งหมด
    headers["Origin"] = FRONTEND_ORIGIN
    
    print(f"   Headers: {json.dumps(headers, indent=6)}\n")
    
    try:
        start = time.time()
        
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=10)
        elif method == "OPTIONS":
            resp = requests.options(url, headers=headers, timeout=10)
        else:
            return {"error": f"Unknown method {method}"}
        
        elapsed = time.time() - start
        
        # ✅ Response Status
        print(f"✅ Status: {resp.status_code}")
        print(f"⏱  Time: {elapsed:.3f}s\n")
        
        # 📋 Response Headers (CORS)
        print("📋 Response Headers (CORS):")
        cors_headers = [
            "access-control-allow-origin",
            "access-control-allow-methods",
            "access-control-allow-headers",
            "access-control-allow-credentials",
            "access-control-max-age",
        ]
        for h in cors_headers:
            val = resp.headers.get(h, resp.headers.get(h.title(), "❌ Not present"))
            print(f"   {h}: {val}")
        
        # 📄 Response Body (first 500 chars)
        print("\n📄 Response Body:")
        try:
            body = resp.json()
            body_str = json.dumps(body, indent=2, ensure_ascii=False)[:500]
            print(f"   {body_str}...")
        except:
            body_str = resp.text[:500]
            print(f"   {body_str}...")
        
        print()
        return resp
        
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Connection Error: {e}\n")
        return None
    except requests.exceptions.Timeout as e:
        print(f"❌ Timeout: {e}\n")
        return None
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}\n")
        return None


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 Starting API Test Suite")
    print("="*60 + "\n")
    
    # Test 1: PING (ง่ายสุด)
    test_endpoint("GET", "/ping", "PING endpoint (ทดสอบ backend ตอบได้)")
    
    # Test 2: OPTIONS (CORS preflight)
    test_endpoint("OPTIONS", "/get_cameras", "CORS Preflight", {
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "Content-Type",
    })
    
    # Test 3: GET /get_cameras
    test_endpoint("GET", "/get_cameras", "GET /get_cameras (ดึงรายการกล้อง)")
    
    print("\n" + "="*60)
    print("✅ Test Complete")
    print("="*60)
    print("\n📌 Note:")
    print("   - ถ้า /ping 200 = backend/ngrok พร้อม")
    print("   - ถ้า OPTIONS 200 + access-control header = CORS ตั้งถูก")
    print("   - ถ้า GET /get_cameras 200 = สำเร็จ!")
    print("   - ถ้า 502/Connection Error = frontend machine ยังไม่เชื่อม ngrok")
