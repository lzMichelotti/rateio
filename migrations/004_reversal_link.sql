-- 004_reversal_link: every reversal points at the entry it reverses, and only
-- reversals point at an entry.
--
-- No BEGIN/COMMIT here: the migration runner wraps each file in its own transaction.
--
-- A row-local CHECK: cheap, and it catches a store bug that writes a reversal
-- without its link (or an expense with one). Rules that need another row, such
-- as "never reverse a reversal", stay in the domain.

ALTER TABLE journal_entry ADD CONSTRAINT journal_entry_reversal_link_check
    CHECK ((kind = 'reversal') = (reverses_entry_id IS NOT NULL));
