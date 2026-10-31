"""
Database management and Connection Pooling for Douala Power Alert.
Uses mysql.connector.pooling to ensure thread-safe connection reuse,
automatic reconnection, and clean lifecycle management.
"""

import os
from contextlib import contextmanager
from dotenv import load_dotenv
import mysql.connector
from mysql.connector import pooling, Error
from werkzeug.security import generate_password_hash

load_dotenv()

_pool = None


def get_pool():
    """Retrieve or initialize the thread-safe MySQL connection pool."""
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="douala_power_pool",
            pool_size=10,
            pool_reset_session=True,
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "douala_power_alert"),
            charset="utf8mb4",
            collation="utf8mb4_unicode_ci",
        )
    return _pool


def get_db():
    """
    Get a single connection from the pool.
    Calling conn.close() will return the connection back to the pool.
    """
    try:
        return get_pool().get_connection()
    except Exception as e:
        # Fallback to direct connection if pool exhausted or initialization issue
        return mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "douala_power_alert"),
            charset="utf8mb4",
            collation="utf8mb4_unicode_ci",
        )


def get_cursor(conn, dictionary=True):
    """Helper to obtain a dictionary cursor from a connection."""
    return conn.cursor(dictionary=dictionary)


@contextmanager
def get_db_cursor(dictionary=True, commit=False):
    """
    Safe context manager for database queries.
    Automatically handles connection checkout, cursor creation,
    commit on success (if commit=True), rollback on exception,
    and guaranteed release of connection back to the pool.

    Usage:
        with get_db_cursor(commit=True) as cur:
            cur.execute("INSERT INTO users ...", (...,))
    """
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=dictionary)
        yield cur
        if commit:
            conn.commit()
    except Exception:
        if conn and conn.is_connected():
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def init_db():
    """Ensure database schema and required tables exist on startup."""
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    full_name VARCHAR(150) NOT NULL,
                    email VARCHAR(150) NOT NULL UNIQUE,
                    phone VARCHAR(50) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    neighborhood VARCHAR(100) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(100) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS outages (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    neighborhood VARCHAR(100) NOT NULL,
                    location VARCHAR(200) NOT NULL,
                    description TEXT,
                    start_time DATETIME NOT NULL,
                    estimated_restore DATETIME NULL,
                    status ENUM('PENDING', 'VERIFIED', 'RESTORED', 'REJECTED') DEFAULT 'PENDING',
                    latitude DECIMAL(10, 7) NULL,
                    longitude DECIMAL(10, 7) NULL,
                    outage_type ENUM('UNPLANNED', 'SCHEDULED') DEFAULT 'UNPLANNED',
                    schedule_id INT NULL,
                    affects_critical BOOLEAN DEFAULT FALSE,
                    reported_via ENUM('WEB', 'SMS', 'WHATSAPP') DEFAULT 'WEB',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                ) ENGINE=InnoDB;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS confirmations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    outage_id INT NOT NULL,
                    user_id INT NOT NULL,
                    confirmation ENUM('STILL_OFF', 'RESTORED') NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (outage_id) REFERENCES outages(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE KEY unique_user_outage (outage_id, user_id)
                ) ENGINE=InnoDB;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    outage_id INT NULL,
                    title VARCHAR(255) NOT NULL,
                    message TEXT NOT NULL,
                    type VARCHAR(50) DEFAULT 'INFO',
                    is_read BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (outage_id) REFERENCES outages(id) ON DELETE SET NULL,
                    INDEX idx_user_notif (user_id, is_read, created_at)
                ) ENGINE=InnoDB;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_outages (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    neighborhood VARCHAR(100) NOT NULL,
                    title VARCHAR(200) NOT NULL,
                    description TEXT,
                    start_time DATETIME NOT NULL,
                    end_time DATETIME NOT NULL,
                    status ENUM('SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED') DEFAULT 'SCHEDULED',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_sched_zone (neighborhood, start_time, end_time, status)
                ) ENGINE=InnoDB;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS critical_facilities (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    facility_type ENUM('HOSPITAL', 'CLINIC', 'WATER_TREATMENT', 'DIALYSIS', 'BLOOD_BANK', 'OXYGEN_PLANT') NOT NULL,
                    neighborhood VARCHAR(100) NOT NULL,
                    address VARCHAR(255) NULL,
                    latitude DECIMAL(10, 7) NOT NULL,
                    longitude DECIMAL(10, 7) NOT NULL,
                    has_backup_generator BOOLEAN DEFAULT TRUE,
                    generator_capacity_kva INT NULL,
                    fuel_autonomy_hours DECIMAL(5, 2) DEFAULT 12.0,
                    current_power_status ENUM('ON_GRID', 'BACKUP_GENERATOR', 'CRITICAL_BLACKOUT') DEFAULT 'ON_GRID',
                    contact_name VARCHAR(150) NULL,
                    contact_phone VARCHAR(50) NULL,
                    notes TEXT NULL,
                    last_status_change TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_facility_zone (neighborhood, facility_type, current_power_status)
                ) ENGINE=InnoDB;
            """)

            # Option 2: SMS & WhatsApp Gateway Log Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gateway_messages (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    channel ENUM('SMS', 'WHATSAPP') NOT NULL,
                    sender_phone VARCHAR(50) NOT NULL,
                    raw_message TEXT NOT NULL,
                    parsed_command VARCHAR(50) NULL,
                    neighborhood VARCHAR(100) NULL,
                    location VARCHAR(255) NULL,
                    outage_id INT NULL,
                    response_message TEXT NULL,
                    status ENUM('SUCCESS', 'FAILED', 'PENDING') DEFAULT 'SUCCESS',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_gw_phone (sender_phone, channel, created_at),
                    FOREIGN KEY (outage_id) REFERENCES outages(id) ON DELETE SET NULL
                ) ENGINE=InnoDB;
            """)

            # Migration: ensure latitude, longitude, outage_type, schedule_id, affects_critical, and reported_via exist in outages table
            cur.execute("""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'outages' AND COLUMN_NAME IN ('latitude', 'longitude', 'outage_type', 'schedule_id', 'affects_critical', 'reported_via')
            """, (os.getenv("DB_NAME", "douala_power_alert"),))
            existing_cols = [r["COLUMN_NAME"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]

            if "latitude" not in existing_cols:
                cur.execute("ALTER TABLE outages ADD COLUMN latitude DECIMAL(10, 7) NULL;")
            if "longitude" not in existing_cols:
                cur.execute("ALTER TABLE outages ADD COLUMN longitude DECIMAL(10, 7) NULL;")
            if "outage_type" not in existing_cols:
                cur.execute("ALTER TABLE outages ADD COLUMN outage_type ENUM('UNPLANNED', 'SCHEDULED') DEFAULT 'UNPLANNED';")
            if "schedule_id" not in existing_cols:
                cur.execute("ALTER TABLE outages ADD COLUMN schedule_id INT NULL;")
            if "affects_critical" not in existing_cols:
                cur.execute("ALTER TABLE outages ADD COLUMN affects_critical BOOLEAN DEFAULT FALSE;")
            if "reported_via" not in existing_cols:
                cur.execute("ALTER TABLE outages ADD COLUMN reported_via ENUM('WEB', 'SMS', 'WHATSAPP') DEFAULT 'WEB';")
        ensure_admin()
        ensure_default_critical_facilities()
        ensure_default_gateway_user()
    except Exception as e:
        print(f"Database initialization warning: {e}")


def ensure_admin():
    """Ensure default admin account exists."""
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT id FROM admins WHERE username = %s", ("admin",))
            row = cur.fetchone()
            hashed = generate_password_hash("admin123")
            if not row:
                cur.execute(
                    "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
                    ("admin", hashed),
                )
            else:
                cur.execute(
                    "UPDATE admins SET password_hash = %s WHERE username = %s",
                    (hashed, "admin"),
                )
    except Error:
        pass


def ensure_default_critical_facilities():
    """Ensure baseline critical facilities for Douala exist in the database."""
    try:
        from services.facility_service import seed_douala_critical_facilities
        seed_douala_critical_facilities(overwrite=False)
    except Exception:
        pass


def ensure_default_gateway_user():
    """Ensure default system user exists for anonymous or external SMS/WhatsApp reports."""
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT id FROM users WHERE phone = %s", ("+237000000000",))
            row = cur.fetchone()
            if not row:
                cur.execute(
                    """INSERT INTO users (full_name, email, phone, password_hash, neighborhood)
                       VALUES (%s, %s, %s, %s, %s)""",
                    ("Passerelle SMS & WhatsApp", "gateway@power-alert.cm", "+237000000000",
                     generate_password_hash("gatewaysecret123"), "Douala"),
                )
    except Exception:
        pass
