-- Migration 019: Add conversation_key, receiver_number, intent_detected, extracted_text
-- to fazle_whatsapp_messages for full central message store compliance.
-- Applied: 2026-06-14

ALTER TABLE fazle_whatsapp_messages
  ADD COLUMN IF NOT EXISTS conversation_key TEXT,
  ADD COLUMN IF NOT EXISTS receiver_number  TEXT,
  ADD COLUMN IF NOT EXISTS intent_detected  TEXT,
  ADD COLUMN IF NOT EXISTS extracted_text   TEXT;

CREATE INDEX IF NOT EXISTS idx_fazle_msg_conv_key
  ON fazle_whatsapp_messages (conversation_key, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_fazle_msg_intent
  ON fazle_whatsapp_messages (intent_detected)
  WHERE intent_detected IS NOT NULL;

-- Backfill receiver_number from platform
UPDATE fazle_whatsapp_messages SET receiver_number = '8801958122300' WHERE platform = 'bridge1' AND receiver_number IS NULL;
UPDATE fazle_whatsapp_messages SET receiver_number = '8801880446111' WHERE platform = 'bridge2' AND receiver_number IS NULL;
UPDATE fazle_whatsapp_messages SET receiver_number = '8801958122322' WHERE platform IN ('meta','whatsapp') AND receiver_number IS NULL;

-- Backfill conversation_key = sender_number:platform
UPDATE fazle_whatsapp_messages
  SET conversation_key = sender_number || ':' || platform
  WHERE conversation_key IS NULL AND sender_number IS NOT NULL AND platform IS NOT NULL;
