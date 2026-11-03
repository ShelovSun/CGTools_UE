-- Run once per configured project. Keep model work separate from UE publishing.
-- Take a snapshot of public.scene before applying. Run inside a transaction.
ALTER TABLE public.scene
    ADD COLUMN IF NOT EXISTS "scene.ue_status" text DEFAULT '未开始',
    ADD COLUMN IF NOT EXISTS "scene.ue_artist" text DEFAULT '';

-- The old publisher stored the UE publisher in scene.artist and 'UE' in status.
-- Preserve existing independent UE fields if this migration is run again.
UPDATE public.scene
SET "scene.ue_status" = CASE
        WHEN COALESCE("scene.ue_status", '') IN ('', '未开始') THEN '已完成'
        ELSE "scene.ue_status" END,
    "scene.ue_artist" = CASE
        WHEN COALESCE("scene.ue_artist", '') = '' THEN COALESCE("scene.artist", '')
        ELSE "scene.ue_artist" END,
    "scene.status" = '已完成'
WHERE "scene.status" = 'UE';
