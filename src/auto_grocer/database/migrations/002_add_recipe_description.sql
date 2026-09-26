-- Migration 002: add description column to recipes
-- Adds a free-text description used for natural-language recipe matching.
-- Run this against an existing database created by 001_create_tables.sql.
-- (Base.metadata.create_all in init_db.py will NOT alter an existing table,
--  so this migration must be applied manually on pre-existing databases.)

ALTER TABLE recipes ADD COLUMN IF NOT EXISTS description TEXT;
