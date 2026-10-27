-- 006_confirmation_required: no entry exists without a human having confirmed it.
--
-- No BEGIN/COMMIT here: the migration runner wraps each file in its own transaction.
--
-- Nullable until now only because the confirmation table did not exist. Every
-- write path goes through store.confirmations.resolve from here on.
--
-- On a large production table this would be split: add
-- CHECK (confirmation_id IS NOT NULL) NOT VALID, VALIDATE CONSTRAINT under a light
-- lock, then SET NOT NULL (which skips the scan given a valid CHECK), then drop
-- the CHECK. This book is small enough for the direct form.

ALTER TABLE journal_entry ALTER COLUMN confirmation_id SET NOT NULL;
