// The bridge's only SQL: which WhatsApp chats are registered, and landing a
// message in inbound_message. Gate 1 of the idempotency chain lives here: the
// same message delivered twice inserts once (ON CONFLICT on dedupe_key).

import { Pool } from "pg";

import { CHANNEL, type InboundRow } from "./inbound.ts";
import type { OutboxStore, Pending } from "./outbox.ts";

export class Db implements OutboxStore {
  private readonly pool: Pool;

  constructor(databaseUrl: string) {
    this.pool = new Pool({ connectionString: databaseUrl, max: 2 });
  }

  // Read per batch, not cached at start: a chat registered with make admin
  // counts at once, without restarting the bridge.
  async registeredChats(): Promise<Map<string, Date>> {
    const { rows } = await this.pool.query<{ external_id: string; created_at: Date }>(
      "SELECT external_id, created_at FROM conversation WHERE channel = $1",
      [CHANNEL],
    );
    return new Map(rows.map((r) => [r.external_id, r.created_at]));
  }

  // The new inbound_message id, or undefined if this message was landed before.
  async land(row: InboundRow): Promise<string | undefined> {
    const { rows } = await this.pool.query<{ id: string }>(
      `INSERT INTO inbound_message
           (channel, conversation_external_id, sender_external_id,
            channel_message_id, dedupe_key, raw_payload, received_at)
       VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
       ON CONFLICT (dedupe_key) DO NOTHING
       RETURNING id`,
      [
        row.channel,
        row.conversationExternalId,
        row.senderExternalId,
        row.channelMessageId,
        row.dedupeKey,
        JSON.stringify(row.rawPayload),
        row.receivedAt,
      ],
    );
    return rows[0]?.id;
  }

  // The oldest unsent reply of any WhatsApp chat. Served by the partial index
  // on pending rows; one at a time, so replies leave in the order they were made.
  async nextPending(): Promise<Pending | undefined> {
    const { rows } = await this.pool.query<Pending>(
      `SELECT o.id, c.external_id AS chat, o.body, o.attempts, o.dedupe_key AS "dedupeKey"
       FROM outbound_message o
       JOIN conversation c ON c.id = o.conversation_id
       WHERE o.status = 'pending' AND c.channel = $1
       ORDER BY o.created_at, o.id
       LIMIT 1`,
      [CHANNEL],
    );
    return rows[0];
  }

  async markSent(id: string, channelMessageId: string | undefined): Promise<void> {
    await this.pool.query(
      `UPDATE outbound_message
       SET status = 'sent', sent_at = now(), attempts = attempts + 1,
           channel_message_id = $2
       WHERE id = $1 AND status = 'pending'`,
      [id, channelMessageId ?? null],
    );
  }

  async markAttemptFailed(id: string, failed: boolean): Promise<void> {
    await this.pool.query(
      `UPDATE outbound_message
       SET attempts = attempts + 1,
           status = CASE WHEN $2::boolean THEN 'failed' ELSE status END
       WHERE id = $1 AND status = 'pending'`,
      [id, failed],
    );
  }

  // What the bot said in a message it sent, for a recipient asking for a
  // resend (Baileys' getMessage). The outbox already keeps exactly that.
  async bodyOf(channelMessageId: string): Promise<string | undefined> {
    const { rows } = await this.pool.query<{ body: string }>(
      "SELECT body FROM outbound_message WHERE channel_message_id = $1",
      [channelMessageId],
    );
    return rows[0]?.body;
  }

  async close(): Promise<void> {
    await this.pool.end();
  }
}
