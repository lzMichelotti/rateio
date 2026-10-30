// Sending the outbox to WhatsApp: at least once, in order.
//
// Send first, mark sent after. If the bridge dies in between, the message is
// sent again when it comes back: a repeated message in the group is acceptable,
// a lost reply is not. Exactly-once is out of reach: sendMessage takes no
// idempotency key, so WhatsApp cannot tell a second call is the same message.
//
// A failing message holds the line until it is given up on, so replies never
// overtake each other: an !ok's answer must not arrive before the proposal's.

import { setTimeout as sleep } from "node:timers/promises";

export const MAX_ATTEMPTS = 5;
// Not from any documentation (Baileys states no rate limit): a precaution
// against looking like a bot flooding the network, which is what gets
// unofficial clients banned. Imperceptible for a group of five.
export const PAUSE_MS = 1000;
export const RETRY_PAUSE_MS = 5000;

export interface Pending {
  id: string; // outbound_message id
  chat: string; // the conversation's external id (the group JID)
  body: string;
  attempts: number;
}

export interface OutboxStore {
  nextPending(): Promise<Pending | undefined>;
  markSent(id: string, channelMessageId: string | undefined): Promise<void>;
  // One more attempt; failed when it was the last one allowed.
  markAttemptFailed(id: string, failed: boolean): Promise<void>;
}

// Sends one text; resolves to WhatsApp's id for it, if it gave one.
export type Send = (chat: string, body: string) => Promise<string | undefined>;

export type Round =
  | { kind: "idle" }
  | { kind: "sent"; id: string }
  | { kind: "retry"; id: string; attempts: number; error: string }
  | { kind: "failed"; id: string; error: string };

export async function sendNext(store: OutboxStore, send: Send): Promise<Round> {
  const pending = await store.nextPending();
  if (pending === undefined) return { kind: "idle" };
  let channelMessageId: string | undefined;
  try {
    channelMessageId = await send(pending.chat, pending.body);
  } catch (error) {
    const attempts = pending.attempts + 1;
    const failed = attempts >= MAX_ATTEMPTS;
    await store.markAttemptFailed(pending.id, failed);
    const message = (error as Error).message;
    return failed
      ? { kind: "failed", id: pending.id, error: message }
      : { kind: "retry", id: pending.id, attempts, error: message };
  }
  await store.markSent(pending.id, channelMessageId);
  return { kind: "sent", id: pending.id };
}

// Runs rounds until signal aborts (the connection closed).
export async function runOutbox(
  store: OutboxStore,
  send: Send,
  signal: AbortSignal,
  log: (line: string) => void,
): Promise<void> {
  while (!signal.aborted) {
    let pause = PAUSE_MS;
    try {
      const round = await sendNext(store, send);
      if (round.kind === "sent") log(`sent outbound ${round.id}`);
      if (round.kind === "retry") {
        log(`send failed for outbound ${round.id} (attempt ${round.attempts}): ${round.error}`);
        pause = RETRY_PAUSE_MS;
      }
      if (round.kind === "failed") {
        log(`gave up on outbound ${round.id} after ${MAX_ATTEMPTS} attempts: ${round.error}`);
      }
    } catch (error) {
      log(`outbox unavailable: ${(error as Error).message}`);
      pause = RETRY_PAUSE_MS;
    }
    try {
      await sleep(pause, undefined, { signal });
    } catch {
      return; // aborted while waiting
    }
  }
}

// Baileys' getMessage: the content of a message the bot sent, found by the id
// WhatsApp gave it, for a recipient that could not decrypt it and asks again.
export function resendLookup(
  bodyOf: (channelMessageId: string) => Promise<string | undefined>,
): (key: { id?: string | null }) => Promise<{ conversation: string } | undefined> {
  return async (key) => {
    const body = key.id ? await bodyOf(key.id) : undefined;
    return body === undefined ? undefined : { conversation: body };
  };
}
