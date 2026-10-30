// What to do when the WhatsApp connection closes. Pure, so it can be tested
// without a phone: the session only carries out what this decides.

import { DisconnectReason } from "@whiskeysockets/baileys";

export type AfterClose =
  | { action: "stop"; reason: "logged_out" | "replaced" | "forbidden" }
  | { action: "reconnect"; delayMs: number };

const MAX_DELAY_MS = 30_000;

// attempt counts the closes since the connection was last open: 0 for the first.
export function afterClose(statusCode: number | undefined, attempt: number): AfterClose {
  switch (statusCode) {
    // The session was ended from the phone: the credentials are dead.
    case DisconnectReason.loggedOut:
      return { action: "stop", reason: "logged_out" };
    // Another bridge took this session over; reconnecting would make the two
    // knock each other off in a loop.
    case DisconnectReason.connectionReplaced:
      return { action: "stop", reason: "replaced" };
    // The account may be blocked; insisting only makes it worse.
    case DisconnectReason.forbidden:
      return { action: "stop", reason: "forbidden" };
    // WhatsApp always drops the connection right after pairing.
    case DisconnectReason.restartRequired:
      return { action: "reconnect", delayMs: 0 };
    default:
      // Doubling waits, capped: a tight reconnect loop while WhatsApp is down
      // is the kind of behaviour that gets an account suspended.
      return { action: "reconnect", delayMs: Math.min(1000 * 2 ** attempt, MAX_DELAY_MS) };
  }
}
