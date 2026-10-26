-- 003_reversal: corrections are reversals, and each entry is reversed at most once.
--
-- No BEGIN/COMMIT here: the migration runner wraps each file in its own transaction.

-- An entry may be reversed at most once. Partial, so rows that reverse nothing
-- (reverses_entry_id IS NULL) are not indexed at all: the rule holds whatever the
-- NULL semantics, and ordinary entries never touch this index.
CREATE UNIQUE INDEX journal_entry_one_reversal
    ON journal_entry (reverses_entry_id)
    WHERE reverses_entry_id IS NOT NULL;

-- A reversal mirrors the original's postings with the same roles, so there is no
-- 'reversal' role. 002 is applied and immutable; the constraint is replaced here.
ALTER TABLE posting DROP CONSTRAINT posting_role_check;
ALTER TABLE posting ADD CONSTRAINT posting_role_check
    CHECK (role IN ('outlay', 'share', 'settlement_paid', 'settlement_received'));
