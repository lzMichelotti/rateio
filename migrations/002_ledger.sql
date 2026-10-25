-- 002_ledger: the book, the edge tables that feed it, and the ledger itself.
--
-- No BEGIN/COMMIT here: the migration runner wraps each file in its own transaction.
--
-- Deliberate additions to the architecture's column tables:
--   - every uuid primary key defaults to gen_random_uuid();
--   - every enumerated text column has both a CHECK and NOT NULL
--     (a CHECK alone lets NULL through).
-- journal_entry.confirmation_id has no foreign key yet: the confirmation table
-- arrives with settlement, and its migration adds the constraint.

CREATE TABLE book (
    id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    name       text        NOT NULL,
    starts_on  date        NOT NULL,
    ends_on    date        NOT NULL,
    currency   char(3)     NOT NULL DEFAULT 'BRL',
    status     text        NOT NULL DEFAULT 'open'
                           CHECK (status IN ('open', 'closed')),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Edge: raw messages addressed to the bot. Disposable; never the source of truth.
CREATE TABLE inbound_message (
    id                       uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    channel                  text        NOT NULL,
    conversation_external_id text        NOT NULL,
    sender_external_id       text        NOT NULL,
    channel_message_id       text,
    dedupe_key               text        NOT NULL UNIQUE,
    raw_payload              jsonb       NOT NULL,
    received_at              timestamptz NOT NULL DEFAULT now(),
    processed_at             timestamptz
);

-- Translation: the canonical structured command. The core accepts nothing else.
CREATE TABLE command (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    inbound_message_id uuid        NOT NULL UNIQUE REFERENCES inbound_message (id),
    book_id            uuid        NOT NULL REFERENCES book (id),
    participant_id     text        NOT NULL REFERENCES participant (id),
    kind               text        NOT NULL
                                   CHECK (kind IN ('record_expense', 'declare_settlement',
                                                   'confirm', 'reject', 'reverse',
                                                   'show_position', 'show_statement',
                                                   'close_book', 'help')),
    payload            jsonb,
    source             text        NOT NULL CHECK (source IN ('syntax', 'llm')),
    llm_confidence     numeric,
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- Financial fact: immutable. Never UPDATE, never DELETE.
CREATE TABLE journal_entry (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id           uuid        NOT NULL REFERENCES book (id),
    seq               bigint      NOT NULL,
    kind              text        NOT NULL CHECK (kind IN ('expense', 'settlement', 'reversal')),
    occurred_on       date        NOT NULL,
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    author_id         text        NOT NULL REFERENCES participant (id),
    -- One command can never produce two entries.
    command_id        uuid        NOT NULL UNIQUE REFERENCES command (id),
    confirmation_id   uuid,
    reverses_entry_id uuid        REFERENCES journal_entry (id),
    payload           jsonb,
    -- Backstop for the single-writer assumption: a violated assumption becomes an
    -- error instead of two entries sharing a sequence number.
    UNIQUE (book_id, seq)
);

-- The legs. One account per participant, signed amounts, summing to zero per entry.
CREATE TABLE posting (
    id             bigserial PRIMARY KEY,
    entry_id       uuid      NOT NULL REFERENCES journal_entry (id),
    participant_id text      NOT NULL REFERENCES participant (id),
    amount_cents   bigint    NOT NULL CHECK (amount_cents <> 0),
    role           text      NOT NULL
                             CHECK (role IN ('outlay', 'share', 'settlement_paid',
                                             'settlement_received', 'reversal'))
);
