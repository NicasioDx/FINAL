import hashlib
import base64
import bcrypt
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import os
from typing import TypedDict, Literal
from urllib.parse import urlparse
from cryptography.fernet import Fernet, InvalidToken

# 1. ตั้งค่าการเชื่อมต่อ
DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    # Parse DATABASE_URL สำหรับ Docker/Production
    parsed = urlparse(DATABASE_URL)
    DB_CONFIG = {
        "host": parsed.hostname,
        "database": parsed.path.lstrip('/'),
        "user": parsed.username,
        "password": parsed.password,
        "port": parsed.port or 5432
    }
else:
    # Local development config
    DB_CONFIG = {
        "host": "localhost",
        "database": "parking_db",
        "user": "postgres",
        "password": "1234",
        "port": 5432
    }

DB_POOL = None
_CAMERA_CIPHER = None


class UserActionResult(TypedDict):
    status: Literal["created", "duplicate", "authenticated", "invalid_credentials", "db_unavailable", "db_error"]
    message: str


def _get_camera_cipher() -> Fernet:
    global _CAMERA_CIPHER
    if _CAMERA_CIPHER is None:
        key_from_env = os.getenv("CAMERA_CREDENTIAL_KEY")
        if key_from_env:
            key = key_from_env.encode("utf-8")
        else:
            # Deterministic local fallback key for development when env var is absent.
            raw = hashlib.sha256((DATABASE_URL or "local-camera-key").encode("utf-8")).digest()
            key = base64.urlsafe_b64encode(raw)
        _CAMERA_CIPHER = Fernet(key)
    return _CAMERA_CIPHER


def encrypt_camera_password(password: str) -> str:
    return _get_camera_cipher().encrypt(password.encode("utf-8")).decode("utf-8")


def decrypt_camera_password(token: str) -> str:
    try:
        return _get_camera_cipher().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # Backward compatibility for existing plaintext rows.
        return token

def init_db_pool():
    global DB_POOL
    if DB_POOL is None:
        try:
            DB_POOL = pool.SimpleConnectionPool(
                1,
                10,
                connect_timeout=5,
                **DB_CONFIG,
            )
            print("✅ Database pool initialized")
        except Exception as e:
            print(f"❌ Error creating connection pool: {e}")
            DB_POOL = None
    return DB_POOL


def get_connection():
    """ดึง connection จาก pool"""
    db_pool = init_db_pool()
    if not db_pool:
        return None
    try:
        conn = db_pool.getconn()
        return conn
    except Exception as e:
        print(f"❌ Error getting connection from pool: {e}")
        return None


def release_connection(conn):
    if conn and DB_POOL:
        try:
            DB_POOL.putconn(conn)
        except Exception as e:
            print(f"❌ Error releasing connection to pool: {e}")


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    return hashed.decode('utf-8')


def _is_bcrypt_hash(stored_hash: str) -> bool:
    return stored_hash.startswith("$2a$") or stored_hash.startswith("$2b$") or stored_hash.startswith("$2y$")


def verify_password(password: str, stored_hash: str) -> tuple[bool, bool]:
    """Return (is_valid, needs_upgrade)."""
    if _is_bcrypt_hash(stored_hash):
        try:
            is_valid = bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
            return is_valid, False
        except ValueError:
            return False, False

    # Legacy SHA-256 fallback for existing users before bcrypt migration.
    legacy_valid = hashlib.sha256(password.encode('utf-8')).hexdigest() == stored_hash
    return legacy_valid, legacy_valid


def init_db():
    """สร้างตารางเริ่มต้น (รันแค่ครั้งเดียวหรือรันตอนเริ่มระบบ)"""
    camera_query = """
    CREATE TABLE IF NOT EXISTS cameras (
        id SERIAL PRIMARY KEY,
        camera_name VARCHAR(100) NOT NULL,
        ip_address VARCHAR(50) NOT NULL,
        username VARCHAR(100) NOT NULL,
        password VARCHAR(100) NOT NULL,
        zone_name VARCHAR(100) NOT NULL DEFAULT 'ทั่วไป',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    user_query = """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        password_hash VARCHAR(256) NOT NULL,
        role VARCHAR(20) NOT NULL DEFAULT 'customer',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    parking_history_query = """
    CREATE TABLE IF NOT EXISTS parking_history (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) NOT NULL,
        camera_id INTEGER NOT NULL,
        zone_name VARCHAR(100) NOT NULL DEFAULT 'ทั่วไป',
        event_type VARCHAR(50) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_parking_history_username ON parking_history(username);
    CREATE INDEX IF NOT EXISTS idx_parking_history_zone ON parking_history(zone_name);
    CREATE INDEX IF NOT EXISTS idx_parking_history_created ON parking_history(created_at DESC);
    """

    conn = get_connection()
    if conn:
        cur = None
        try:
            cur = conn.cursor()
            cur.execute(camera_query)
            cur.execute(user_query)
            cur.execute(parking_history_query)
            # Ensure encrypted camera password tokens can be stored.
            cur.execute("ALTER TABLE cameras ALTER COLUMN password TYPE TEXT")
            # Add columns if they don't exist (for existing tables)
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'customer'")
            cur.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS zone_name VARCHAR(100) NOT NULL DEFAULT 'ทั่วไป'")
            conn.commit()
            print("✅ Database initialized successfully")
        finally:
            if cur:
                cur.close()
            release_connection(conn)


# ฟังก์ชันช่วยเหลือสำหรับ API
def add_camera_to_db(name, ip, user, pw, zone_name="ทั่วไป"):
    conn = get_connection()
    if conn:
        cur = None
        try:
            encrypted_pw = encrypt_camera_password(pw)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO cameras (camera_name, ip_address, username, password, zone_name) VALUES (%s, %s, %s, %s, %s)",
                (name, ip, user, encrypted_pw, zone_name)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"Error adding camera: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if cur:
                cur.close()
            release_connection(conn)
    return False


def get_all_cameras():
    conn = get_connection()
    if conn:
        cur = None
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT id, camera_name, ip_address, zone_name, created_at "
                "FROM cameras ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"Error fetching cameras: {e}")
            return []
        finally:
            if cur:
                cur.close()
            release_connection(conn)
    return []


def get_camera_credentials(camera_id: int):
    conn = get_connection()
    if conn:
        cur = None
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT ip_address, username, password FROM cameras WHERE id=%s",
                (camera_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            cam = dict(row)
            cam["password"] = decrypt_camera_password(cam["password"])
            return cam
        except Exception as e:
            print(f"Error fetching camera credentials: {e}")
            return None
        finally:
            if cur:
                cur.close()
            release_connection(conn)
    return None


def create_user(username: str, password: str, role: str = "customer") -> UserActionResult:
    conn = get_connection()
    if not conn:
        return {"status": "db_unavailable", "message": "Database connection is not available"}
    cur = None
    try:
        password_hash = hash_password(password)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
            (username, password_hash, role),
        )
        conn.commit()
        return {"status": "created", "message": "User registered"}
    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()
        return {"status": "duplicate", "message": "Username already exists"}
    except Exception as e:
        print(f"Error creating user: {e}")
        if conn:
            conn.rollback()
        return {"status": "db_error", "message": "Unexpected database error while creating user"}
    finally:
        if cur:
            cur.close()
        release_connection(conn)


def authenticate_user(username: str, password: str) -> UserActionResult:
    conn = get_connection()
    if not conn:
        return {"status": "db_unavailable", "message": "Database connection is not available"}
    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT password_hash FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        if not user:
            return {"status": "invalid_credentials", "message": "Invalid username or password"}

        is_valid, needs_upgrade = verify_password(password, user['password_hash'])
        if is_valid:
            if needs_upgrade:
                upgraded_hash = hash_password(password)
                cur.execute(
                    "UPDATE users SET password_hash=%s WHERE username=%s",
                    (upgraded_hash, username),
                )
                conn.commit()
            return {"status": "authenticated", "message": "Login successful"}

        return {"status": "invalid_credentials", "message": "Invalid username or password"}
    except Exception as e:
        print(f"Error authenticating user: {e}")
        return {"status": "db_error", "message": "Unexpected database error while authenticating user"}
    finally:
        if cur:
            cur.close()
        release_connection(conn)


def add_parking_history(username: str, camera_id: int, event_type: str = "parking_success") -> bool:
    """บันทึกประวัติการเข้าจอด"""
    conn = get_connection()
    if not conn:
        return False
    cur = None
    try:
        cur = conn.cursor()
        # Get zone_name from camera
        cur.execute("SELECT zone_name FROM cameras WHERE id=%s", (camera_id,))
        camera = cur.fetchone()
        zone_name = camera[0] if camera else "ทั่วไป"
        
        # Insert parking history
        cur.execute(
            "INSERT INTO parking_history (username, camera_id, zone_name, event_type) VALUES (%s, %s, %s, %s)",
            (username, camera_id, zone_name, event_type)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Error adding parking history: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if cur:
            cur.close()
        release_connection(conn)


def get_parking_history(username: str = None, zone_name: str = None, limit: int = 100) -> list:
    """ดึงประวัติการเข้าจอด"""
    conn = get_connection()
    if not conn:
        return []
    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = (
            "SELECT ph.username, ph.camera_id, c.camera_name, ph.zone_name, ph.event_type, ph.created_at "
            "FROM parking_history ph "
            "LEFT JOIN cameras c ON c.id = ph.camera_id "
            "WHERE 1=1"
        )
        params = []

        if username:
            query += " AND ph.username=%s"
            params.append(username)

        if zone_name:
            query += " AND ph.zone_name=%s"
            params.append(zone_name)

        query += " ORDER BY ph.created_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, tuple(params))
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"Error fetching parking history: {e}")
        return []
    finally:
        if cur:
            cur.close()
        release_connection(conn)


def get_user_role(username: str) -> str:
    """ดึงบทบาทของผู้ใช้"""
    conn = get_connection()
    if not conn:
        return "customer"
    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT role FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        if user and user.get('role'):
            # Auto-promote admin user
            if username.lower() == 'admin' and user['role'] == 'customer':
                cur.execute("UPDATE users SET role=%s WHERE username=%s", ('admin', username))
                conn.commit()
                return 'admin'
            return user['role']
        return 'customer'
    except Exception as e:
        print(f"Error fetching user role: {e}")
        return 'customer'
    finally:
        if cur:
            cur.close()
        release_connection(conn)

