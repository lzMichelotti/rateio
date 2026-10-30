// make bridge: keep the WhatsApp session alive, land the messages addressed to
// the bot in inbound_message, send the outbox while connected.

import path from "node:path";
import { fileURLToPath } from "node:url";

import type { WASocket } from "@whiskeysockets/baileys";

import { loadConfig } from "./config.ts";
import { Db } from "./db.ts";
import { toInbound } from "./inbound.ts";
import { resendLookup, runOutbox } from "./outbox.ts";
import { holdSession, runningPid } from "./pidfile.ts";
import { runSession } from "./session.ts";

const bridgeDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const config = loadConfig(process.env, bridgeDir);
if (runningPid(config.authDir) !== undefined) {
  console.error("another bridge is already running on this session");
  process.exit(1);
}
holdSession(config.authDir);
const db = new Db(config.databaseUrl);

function listen(sock: WASocket): void {
  // Both "notify" and "append" are read: what keeps old commands out is the
  // registration time in toInbound, not the upsert's type.
  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    try {
      const registered = await db.registeredChats();
      const botIds = [sock.user?.id, sock.user?.lid].filter((id): id is string => !!id);
      for (const msg of messages) {
        const result = toInbound(msg, { registered, botIds });
        if ("skip" in result) {
          // Unregistered chats are not even mentioned: nothing of them is kept.
          if (result.skip !== "not_registered") console.log(`skipped (${result.skip}, ${type})`);
          continue;
        }
        const inboundId = await db.land(result);
        console.log(inboundId ? `landed inbound ${inboundId} (${type})` : `duplicate, already landed (${type})`);
      }
    } catch (error) {
      // Postgres down when a message arrives: it is not landed. Logged loudly,
      // without the message's content.
      console.error("could not land a message batch:", (error as Error).message);
    }
  });
}

// One sending loop per open connection; a closed connection stops it, so no
// attempt is burnt while WhatsApp is unreachable.
let sending: AbortController | undefined;

function startSending(sock: WASocket): void {
  sending?.abort();
  sending = new AbortController();
  const send = async (chat: string, body: string) =>
    (await sock.sendMessage(chat, { text: body }))?.key.id ?? undefined;
  void runOutbox(db, send, sending.signal, (line) => console.log(line));
}

await runSession(config, {
  attach: listen,
  onOpen: startSending,
  onClose: () => sending?.abort(),
  getMessage: resendLookup((id) => db.bodyOf(id)),
});
await db.close();
