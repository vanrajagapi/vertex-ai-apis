-- ═══════════════════════════════════════════════════════════════
-- PMJAY Claim Pre-Auth System — Database Schema
-- Migration 007 — Simplify text_field_group_mappings Table
-- ═══════════════════════════════════════════════════════════════

-- ───────────────────────────────────────
-- 1. DROP UNNECESSARY COLUMNS
-- ───────────────────────────────────────
ALTER TABLE text_field_group_mappings DROP COLUMN IF EXISTS sort_order;
ALTER TABLE text_field_group_mappings DROP COLUMN IF EXISTS is_mandatory;
