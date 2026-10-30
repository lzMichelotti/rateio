// Which WhatsApp messages become an inbound_message, and as what. Pure: the
// listener only feeds it messages and the registered chats, and writes what it
// returns. The bridge knows nothing about money and does not parse commands:
// it lands the raw message, mentions included, for the Python side to read.

import { areJidsSameUser, BufferJSON, type WAMessage } from "@whiskeysockets/baileys";

export const CHANNEL = "whatsapp_unofficial";

export interface InboundRow {
  channel: typeof CHANNEL;
  conversationExternalId: string; // the group's JID
  senderExternalId: string; // the sender's LID in a group (stage 05b, decision 7)
  channelMessageId: string;
  dedupeKey: string; // wa:<chat>:<message id>
  rawPayload: unknown; // the whole message, as JSON
  receivedAt: Date; // when the person sent it, not when the bridge got it
}

export type SkipReason =
  | "no_id"
  | "not_registered"
  | "from_me"
  | "before_registration"
  | "no_text"
  | "not_addressed";

export interface Context {
  // whatsapp_unofficial conversations: chat JID -> when it was registered
  registered: ReadonlyMap<string, Date>;
  // the bot's own JIDs (LID and phone), possibly with a device suffix
  botIds: readonly string[];
}

export function toInbound(msg: WAMessage, ctx: Context): InboundRow | { skip: SkipReason } {
  const chat = msg.key.remoteJid;
  const id = msg.key.id;
  if (!chat || !id) return { skip: "no_id" };

  // Only chats an operator registered; anything else leaves no row at all.
  const registeredAt = ctx.registered.get(chat);
  if (registeredAt === undefined) return { skip: "not_registered" };

  // The bot's own messages, its replies included: never answer itself.
  if (msg.key.fromMe) return { skip: "from_me" };

  // Older than the chat's registration: a history sync or a late delivery must
  // not replay commands typed before the bot was set up. Filtered by time, not
  // by the upsert's type, so messages sent while the bridge was down still land.
  const sentAt = timestampOf(msg);
  if (sentAt === undefined || sentAt < registeredAt) return { skip: "before_registration" };

  const text = msg.message?.conversation ?? msg.message?.extendedTextMessage?.text;
  if (!text) return { skip: "no_text" };

  // The channel's filter: a command, or a mention of the bot. Everything else
  // the group says is never stored.
  const mentions = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid ?? [];
  const mentionsBot = mentions.some((jid) => ctx.botIds.some((bot) => areJidsSameUser(jid, bot)));
  if (!text.trimStart().startsWith("!") && !mentionsBot) return { skip: "not_addressed" };

  return {
    channel: CHANNEL,
    conversationExternalId: chat,
    // In a group the sender is the participant; in a direct chat, the chat.
    senderExternalId: msg.key.participant ?? chat,
    channelMessageId: id,
    dedupeKey: `wa:${chat}:${id}`,
    // BufferJSON keeps Buffers readable as JSON (and restorable by Baileys).
    rawPayload: JSON.parse(JSON.stringify(msg, BufferJSON.replacer)),
    receivedAt: sentAt,
  };
}

// messageTimestamp is in seconds, as a number or a protobuf Long.
function timestampOf(msg: WAMessage): Date | undefined {
  const ts = msg.messageTimestamp;
  if (ts === null || ts === undefined) return undefined;
  const seconds = typeof ts === "number" ? ts : Number(ts.toString());
  return Number.isFinite(seconds) ? new Date(seconds * 1000) : undefined;
}
