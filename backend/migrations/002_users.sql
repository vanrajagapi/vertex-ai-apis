-- Migration: 002_users.sql
-- Description: Create users table for authentication and authorization

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE,
    full_name VARCHAR(100),
    hashed_password VARCHAR(255) NOT NULL,
    role VARCHAR(20) DEFAULT 'reviewer', -- 'admin' or 'reviewer'
    disabled BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create a default admin user
-- The password is 'admin123', hashed using bcrypt
INSERT INTO users (username, email, full_name, hashed_password, role, disabled)
VALUES (
    'admin',
    'admin@pmjay.gov.in',
    'System Administrator',
    '$2b$12$NqLqX/a36JXYA8cO8oH5eebl0t3r1T3F1d7n/0B9H9rF7v0m8Bv9y', -- hashed 'admin123'
    'admin',
    FALSE
) ON CONFLICT (username) DO NOTHING;
