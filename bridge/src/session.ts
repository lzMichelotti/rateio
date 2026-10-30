// The WhatsApp session: connect, pair once, persist credentials, reconnect.
//
// The credentials in authDir are the account's keys: whoever holds those files
// controls the bot's WhatsApp. They are never printed, and the Baileys logger
// stays at "warn", since at "debug" it prints every frame sent and received.
// https://baileys.wiki/concepts/socket-config.md
// https://baileys.wiki/authentication/session-management.md
// https://baileys.wiki/authentication/pairing-code.md

import {
  Browsers,
  makeCacheableSignalKeyStore,
  makeWASocket,
  useMultiFileAuthState,
  type proto,
  type WAMessageKey,
  type WASocket,
} from "@whiskeysockets/baileys";
import pino from "pino";
import qrcode from "qrcode-terminal";

import type { Config } from "./config.ts";
import { log } from "./log.ts";
import { afterClose } from "./reconnect.ts";

const logger = pino({ level: "warn" });

export interface Hooks {
  // Called for every new socket, before it connects: the place to listen to events.
  attach?: (sock: WASocket) => void;
  // Called on every successful (re)connection.
  onOpen?: (sock: WASocket) => void | Promise<void>;
  // Called whenever the connection closes, whatever happens next.
  onClose?: () => void;
  // The content of a message the bot sent, when a recipient asks for a resend.
  getMessage?: (key: WAMessageKey) => Promise<proto.IMessage | undefined>;
}

// Runs until the session is ended from the phone (or taken over, or refused).
export async function runSession(config: Config, hooks: Hooks = {}): Promise<void> {
  // Created if missing; saved on every creds.update, or the next connection
  // fails to decrypt.
  const { state, saveCreds } = await useMultiFileAuthState(config.authDir);
  let attempt = 0;

  return new Promise((resolve) => {
    const start = (): void => {
      const sock = makeWASocket({
        auth: { creds: state.creds, keys: makeCacheableSignalKeyStore(state.keys, logger) },
        logger,
        browser: Browsers.ubuntu("Rateio"),
        // History sync stays on: turning it off entirely keeps Baileys from the
        // initial LID mappings, and it warns of session errors. Old commands are
        // kept out by the receiver instead (only messages newer than the chat's
        // registration, deduplicated). Only the full history is declined.
        syncFullHistory: false,
        // Online all the time would silence the bot phone's own notifications.
        markOnlineOnConnect: false,
        // Without it, retry delivery silently fails when a recipient could not
        // decrypt a message and asks for it again.
        ...(hooks.getMessage ? { getMessage: hooks.getMessage } : {}),
      });
      sock.ev.on("creds.update", saveCreds);
      hooks.attach?.(sock);

      let pairingRequested = false;
      sock.ev.on("connection.update", async ({ connection, lastDisconnect, qr }) => {
        // A qr event means "ready to pair". With a phone number configured the
        // bridge asks for a pairing code once; otherwise it draws each QR it
        // gets (they rotate every few seconds) for the bot's phone to scan.
        if (qr && !sock.authState.creds.registered) {
          if (config.pairingPhone === undefined) {
            qrcode.generate(qr, { small: true });
            console.log(
              "scan with the bot's phone: WhatsApp > Linked devices > Link a device",
            );
          } else if (!pairingRequested) {
            pairingRequested = true;
            const code = await sock.requestPairingCode(config.pairingPhone);
            console.log(
              `pairing code: ${code}\n` +
                "on the bot's phone: WhatsApp > Linked devices > Link a device > " +
                "Link with phone number instead, then type the code",
            );
          }
        }

        if (connection === "open") {
          attempt = 0;
          log("session.connected");
          void hooks.onOpen?.(sock);
        }

        if (connection === "close") {
          hooks.onClose?.();
          const statusCode = (lastDisconnect?.error as { output?: { statusCode?: number } })
            ?.output?.statusCode;
          const next = afterClose(statusCode, attempt);
          if (next.action === "stop") {
            console.error(STOP_MESSAGES[next.reason]);
            process.exitCode = 1;
            resolve();
            return;
          }
          attempt += 1;
          log("session.closed", { code: statusCode, retry_in_ms: next.delayMs });
          setTimeout(start, next.delayMs);
        }
      });
    };
    start();
  });
}

const STOP_MESSAGES = {
  logged_out:
    "session ended from the phone: delete bridge/auth/ and run make bridge to pair again",
  replaced: "another bridge took over this session: stop the other one first",
  forbidden: "WhatsApp refused the connection (the account may be restricted)",
} as const;
