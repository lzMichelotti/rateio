-- 008_channel_and_membership: who belongs to a book, and how a channel names them.
--
-- No BEGIN/COMMIT here: the migration runner wraps each file in its own transaction.
--
-- A person is not a member of a book. Until now every expense was split among
-- whatever list the caller passed; from here on it is split among the book's
-- members, which is what lets one database hold more than one group.
-- participant.joined_on and left_on describe a membership, not a person; they
-- stay unused rather than being dropped for no gain.

CREATE TABLE book_member (
    book_id        uuid        NOT NULL REFERENCES book (id),
    participant_id text        NOT NULL REFERENCES participant (id),
    joined_at      timestamptz NOT NULL DEFAULT now(),
    -- The composite key is the rule: a person joins a book at most once.
    PRIMARY KEY (book_id, participant_id)
);

-- Maps a channel's own identifier (a JID, a CLI handle) to a person. Adding a
-- channel later means replacing this CHECK, as 007 did for command.kind.
CREATE TABLE channel_identity (
    channel        text NOT NULL CHECK (channel IN ('cli', 'whatsapp_unofficial')),
    external_id    text NOT NULL,
    participant_id text NOT NULL REFERENCES participant (id),
    PRIMARY KEY (channel, external_id)
);

-- A chat. The ledger belongs to the book, never to the conversation.
CREATE TABLE conversation (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    channel     text NOT NULL CHECK (channel IN ('cli', 'whatsapp_unofficial')),
    external_id text NOT NULL,
    kind        text NOT NULL CHECK (kind IN ('group', 'direct')),
    book_id     uuid NOT NULL REFERENCES book (id),
    UNIQUE (channel, external_id)
);
