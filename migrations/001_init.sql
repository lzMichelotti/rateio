-- 001_init: the participant table.
--
-- No BEGIN/COMMIT here: the migration runner wraps each file in its own transaction.
-- No rows here either: migrations hold structure only. Example participants for
-- development and tests are seeded separately; real ones never enter the repository.
--
-- participant.id is human-readable and stable on purpose: ordering by id is what
-- the rounding remainder rotation relies on.
-- participant holds no phone number and no JID. Channel identity is a separate
-- table (channel_identity), introduced together with the bridge.

CREATE TABLE participant (
    id           text        PRIMARY KEY,
    display_name text        NOT NULL,
    joined_on    date,
    left_on      date,
    created_at   timestamptz NOT NULL DEFAULT now()
);
