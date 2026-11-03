-- Run once in each project's PostgreSQL database. Existing values are retained.
ALTER TABLE public.asset
    ADD COLUMN IF NOT EXISTS "asset.ue_status" text DEFAULT '未开始',
    ADD COLUMN IF NOT EXISTS "asset.ue_artist" text DEFAULT '';
