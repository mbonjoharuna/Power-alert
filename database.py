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
                    phone VARCHAR(20) NOT NULL UNIQUE,
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

            # Migration: ensure latitude and longitude columns exist in outages table
            cur.execute("""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'outages' AND COLUMN_NAME IN ('latitude', 'longitude')
            """, (os.getenv("DB_NAME", "douala_power_alert"),))
            existing_cols = [r["COLUMN_NAME"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]

            if "latitude" not in existing_cols:
                cur.execute("ALTER TABLE outages ADD COLUMN latitude DECIMAL(10, 7) NULL;")
            if "longitude" not in existing_cols:
                cur.execute("ALTER TABLE outages ADD COLUMN longitude DECIMAL(10, 7) NULL;")
        ensure_admin()
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
