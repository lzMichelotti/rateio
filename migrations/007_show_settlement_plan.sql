-- 007_show_settlement_plan: !fechar becomes !acerto, a read-only command.
--
-- No BEGIN/COMMIT here: the migration runner wraps each file in its own transaction.
--
-- close_book promised to close something; the command only shows positions and
-- the settlement plan. 002 is applied and immutable, and PostgreSQL cannot alter a
-- CHECK expression in place, so the constraint is dropped and re-added, as 003
-- did for posting.role.

ALTER TABLE command DROP CONSTRAINT command_kind_check;

-- Rows recorded under the old name are translated before the new CHECK is added:
-- ADD CONSTRAINT scans the table and would refuse them. Between the DROP and the
-- ADD, because the old CHECK refuses the new name. command is the translation
-- layer, not the ledger.
UPDATE command SET kind = 'show_settlement_plan' WHERE kind = 'close_book';

ALTER TABLE command ADD CONSTRAINT command_kind_check
    CHECK (kind IN ('record_expense', 'declare_settlement', 'confirm', 'reject',
                    'reverse', 'show_position', 'show_statement',
                    'show_settlement_plan', 'help'));
