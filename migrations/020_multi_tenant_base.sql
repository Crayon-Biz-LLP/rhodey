-- Migration 020: Multi-Tenant Base
-- Adds user-scoping infrastructure for all tenant tables.
-- Run in Supabase SQL Editor.

-- ============================================
-- PART 1: User Profiles (persona + approval)
-- ============================================
CREATE TABLE IF NOT EXISTS user_profiles (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  owner_name TEXT NOT NULL DEFAULT 'User',
  owner_full_name TEXT,
  company_name TEXT,
  location TEXT DEFAULT 'India',
  domains_config JSONB DEFAULT '[]'::jsonb,
  approval_status TEXT NOT NULL DEFAULT 'pending' CHECK (approval_status IN ('pending', 'approved', 'rejected')),
  approved_by UUID REFERENCES auth.users(id),
  approved_at TIMESTAMPTZ,
  onboarding_completed BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- PART 2: Per-User Google OAuth Tokens
-- ============================================
CREATE TABLE IF NOT EXISTS user_google_tokens (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  access_token TEXT,
  refresh_token TEXT NOT NULL,
  expiry TIMESTAMPTZ,
  scope TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- PART 3: Telegram Chat Linking
-- ============================================
CREATE TABLE IF NOT EXISTS user_telegram_links (
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  chat_id BIGINT NOT NULL,
  verified_at TIMESTAMPTZ,
  PRIMARY KEY (user_id, chat_id)
);

CREATE TABLE IF NOT EXISTS telegram_verification_codes (
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '10 minutes'),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (user_id, code)
);

-- ============================================
-- PART 4: Add user_id to all tenant tables
-- ============================================
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE memories ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE raw_dumps ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE people ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE graph_nodes ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE graph_edges ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE resources ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE emails ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE email_pending_tasks ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE email_drafts ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE agent_queue ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);

-- ============================================
-- PART 5: Rename danny_decision to user_decision
-- ============================================
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'email_pending_tasks' AND column_name = 'danny_decision'
  ) THEN
    ALTER TABLE email_pending_tasks RENAME COLUMN danny_decision TO user_decision;
  END IF;
END $$;

-- ============================================
-- PART 6: Create indexes for user-scoped queries
-- ============================================
CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id);
CREATE INDEX IF NOT EXISTS idx_raw_dumps_user_id ON raw_dumps(user_id);
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_people_user_id ON people(user_id);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_user_id ON graph_nodes(user_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_user_id ON graph_edges(user_id);
CREATE INDEX IF NOT EXISTS idx_resources_user_id ON resources(user_id);
CREATE INDEX IF NOT EXISTS idx_emails_user_id ON emails(user_id);
CREATE INDEX IF NOT EXISTS idx_email_pending_tasks_user_id ON email_pending_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_email_drafts_user_id ON email_drafts(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_queue_user_id ON agent_queue(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);

-- ============================================
-- PART 7: Backfill existing data — set user_id
-- Run AFTER creating the admin user in Supabase Auth UI.
-- Replace 'ADMIN_USER_UUID' with the actual UUID of Danny's auth.users entry.
-- ============================================
-- UPDATE tasks SET user_id = 'ADMIN_USER_UUID' WHERE user_id IS NULL;
-- UPDATE memories SET user_id = 'ADMIN_USER_UUID' WHERE user_id IS NULL;
-- UPDATE raw_dumps SET user_id = 'ADMIN_USER_UUID' WHERE user_id IS NULL;
-- UPDATE projects SET user_id = 'ADMIN_USER_UUID' WHERE user_id IS NULL;
-- UPDATE people SET user_id = 'ADMIN_USER_UUID' WHERE user_id IS NULL;
-- UPDATE graph_nodes SET user_id = 'ADMIN_USER_UUID' WHERE user_id IS NULL;
-- UPDATE graph_edges SET user_id = 'ADMIN_USER_UUID' WHERE user_id IS NULL;
-- UPDATE resources SET user_id = 'ADMIN_USER_UUID' WHERE user_id IS NULL;
-- UPDATE emails SET user_id = 'ADMIN_USER_UUID' WHERE user_id IS NULL;
-- UPDATE email_pending_tasks SET user_id = 'ADMIN_USER_UUID' WHERE user_id IS NULL;
-- UPDATE email_drafts SET user_id = 'ADMIN_USER_UUID' WHERE user_id IS NULL;
-- UPDATE agent_queue SET user_id = 'ADMIN_USER_UUID' WHERE user_id IS NULL;
-- UPDATE conversations SET user_id = 'ADMIN_USER_UUID' WHERE user_id IS NULL;

-- ============================================
-- VERIFICATION
-- ============================================
-- Check all columns exist:
-- SELECT table_name, column_name FROM information_schema.columns
-- WHERE column_name = 'user_id' AND table_schema = 'public'
-- ORDER BY table_name;
