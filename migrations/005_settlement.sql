-- 005_settlement: confirmations for every financial fact, and two-sided settlement.
--
-- No BEGIN/COMMIT here: the migration runner wraps each file in its own transaction.
--
-- confirmation and settlement are workflow state: their status is updated in
-- place. Only journal_entry and posting are append-only.
--
-- journal_entry.confirmation_id gets its foreign key here but stays nullable;
-- 006 makes it NOT NULL once every write path goes through a confirmation.

CREATE TABLE confirmation (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- One letter and one digit, without the ambiguous I, L, O, 0 and 1: 184 codes.
    code        text        NOT NULL CHECK (code ~ '^[A-HJKMNP-Z][2-9]$'),
    book_id     uuid        NOT NULL REFERENCES book (id),
    -- The proposing command: the same proposal processed twice opens one confirmation.
    command_id  uuid        NOT NULL UNIQUE REFERENCES command (id),
    kind        text        NOT NULL
                            CHECK (kind IN ('expense_proposal', 'settlement_declaration',
                                            'reversal_proposal')),
    payload     jsonb       NOT NULL,
    created_by  text        NOT NULL REFERENCES participant (id),
    confirmer   text        NOT NULL REFERENCES participant (id),
    status      text        NOT NULL DEFAULT 'open'
                            CHECK (status IN ('open', 'confirmed', 'discarded', 'expired')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    entry_id    uuid        REFERENCES journal_entry (id),
    -- Row-local consistency, cheap to enforce here.
    CHECK ((status = 'confirmed') = (entry_id IS NOT NULL)),
    CHECK ((status = 'open') = (resolved_at IS NULL)),
    -- Two-sided reconciliation: only a settlement is confirmed by someone else.
    CHECK ((kind = 'settlement_declaration') = (confirmer <> created_by))
);

-- A code is unique among a book's open confirmations, and recycled once resolved.
CREATE UNIQUE INDEX confirmation_open_code
    ON confirmation (book_id, code)
    WHERE status = 'open';

CREATE TABLE settlement (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id         uuid        NOT NULL REFERENCES book (id),
    payer_id        text        NOT NULL REFERENCES participant (id),
    payee_id        text        NOT NULL REFERENCES participant (id),
    amount_cents    bigint      NOT NULL CHECK (amount_cents > 0),
    status          text        NOT NULL DEFAULT 'declared'
                                CHECK (status IN ('declared', 'confirmed', 'rejected',
                                                  'cancelled')),
    declared_at     timestamptz NOT NULL DEFAULT now(),
    confirmed_at    timestamptz,
    confirmation_id uuid        NOT NULL UNIQUE REFERENCES confirmation (id),
    -- NULL while declared: the ledger cannot know about an unconfirmed payment.
    entry_id        uuid        REFERENCES journal_entry (id),
    CHECK (payer_id <> payee_id),
    CHECK ((status = 'confirmed') = (entry_id IS NOT NULL))
);

ALTER TABLE journal_entry
    ADD CONSTRAINT journal_entry_confirmation_id_fkey
    FOREIGN KEY (confirmation_id) REFERENCES confirmation (id);
