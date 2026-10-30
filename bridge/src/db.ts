// The bridge's only SQL: which WhatsApp chats are registered, and landing a
// message in inbound_message. Gate 1 of the idempotency chain lives here: the
// same message delivered twice inserts once (ON CONFLICT on dedupe_key).

import { Pool } from "pg";

import { CHANNEL, type InboundRow } from "./inbound.ts";

export class Db {
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

  async close(): Promise<void> {
    await this.pool.end();
  }
}
