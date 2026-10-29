-- 009_outbound_message: the outbox. Every reply the bot sends is a row here first.
--
-- No BEGIN/COMMIT here: the migration runner wraps each file in its own transaction.
--
-- Written in the same transaction as the command and its ledger effects, so a
-- reply exists exactly when what it reports happened. The channel's sender (the
-- CLI now, the bridge in 05b) polls pending rows and marks them sent. A cache,
-- not truth: dropping it loses no money.

CREATE TABLE outbound_message (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id    uuid        NOT NULL REFERENCES conversation (id),
    body               text        NOT NULL,
    -- reply:<inbound_message_id>, dunning:<settlement_id>:<occurred_on>,
    -- close:<book_id>:<occurred_on>:<attempt>. One row per key, ever.
    dedupe_key         text        NOT NULL UNIQUE,
    status             text        NOT NULL DEFAULT 'pending'
                                   CHECK (status IN ('pending', 'sent', 'failed')),
    attempts           int         NOT NULL DEFAULT 0,
    created_at         timestamptz NOT NULL DEFAULT now(),
    sent_at            timestamptz,
    channel_message_id text
);

-- The sender's poll: pending rows, oldest first. Partial, so sent rows (nearly
-- all of them, over time) are not in the index at all.
CREATE INDEX outbound_message_pending
    ON outbound_message (created_at)
    WHERE status = 'pending';
