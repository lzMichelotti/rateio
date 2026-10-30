-- 010_conversation_created_at: when a conversation was registered.
--
-- No BEGIN/COMMIT here: the migration runner wraps each file in its own transaction.
--
-- The WhatsApp bridge ignores messages older than the conversation's
-- registration, so a history sync or a reconnection can never replay commands
-- typed before the bot was set up. Existing rows take the migration's time,
-- which is when, as far as this rule is concerned, they were registered.

ALTER TABLE conversation
    ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
