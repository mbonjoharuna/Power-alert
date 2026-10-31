-- ============================================================
-- DOUALA POWER ALERT - Database Schema
-- Run this file in MySQL (phpMyAdmin or mysql CLI)
-- ============================================================

CREATE DATABASE IF NOT EXISTS douala_power_alert
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE douala_power_alert;

-- ----------------------------------------------------------
-- Table: users
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    phone VARCHAR(20) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    neighborhood VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ----------------------------------------------------------
-- Table: admins
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS admins (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ----------------------------------------------------------
-- Table: outages
-- ----------------------------------------------------------
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

-- ----------------------------------------------------------
-- Table: confirmations
-- ----------------------------------------------------------
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

-- ----------------------------------------------------------
-- Table: notifications
-- ----------------------------------------------------------
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

-- ----------------------------------------------------------
-- Default admin is created automatically when you run:
--   python app.py
-- Username: admin
-- Password: admin123
-- (app.py calls ensure_admin() on startup)
-- ----------------------------------------------------------

