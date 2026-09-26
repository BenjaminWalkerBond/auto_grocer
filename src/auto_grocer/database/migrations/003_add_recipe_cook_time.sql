-- Migration 003: add cook_time column to recipes
-- Stores the recipe cook time in minutes (nullable; existing rows stay NULL
-- until populated by the scraper/seeder).
-- Run this against an existing database created by 001_create_tables.sql.
-- (Base.metadata.create_all in init_db.py will NOT alter an existing table,
--  so this migration must be applied manually on pre-existing databases.)

ALTER TABLE recipes ADD COLUMN IF NOT EXISTS cook_time INTEGER;
