// One line per event, key=value, the same shape as the worker's (src/core/log.py).
//
// Every line about a message carries its inbound_message id or its
// outbound_message id (and, for a reply, the inbound id it answers), so grep
// over both processes follows one message end to end. Never logged: message
// text, names, LIDs, phone numbers, group ids, the database URL.

export type Fields = Record<string, string | number | undefined>;

export function line(event: string, fields: Fields = {}, at: Date = new Date()): string {
  const pairs = Object.entries(fields)
    .filter(([, value]) => value !== undefined)
    .map(([key, value]) => `${key}=${value}`)
    .join(" ");
  return `${at.toISOString()} bridge ${event}${pairs ? ` ${pairs}` : ""}`;
}

export function log(event: string, fields: Fields = {}): void {
  console.log(line(event, fields));
}

// The inbound_message a reply answers, read from its dedupe key reply:<id>.
export function inboundOf(dedupeKey: string): string | undefined {
  return dedupeKey.startsWith("reply:") ? dedupeKey.slice("reply:".length) : undefined;
}

// Error messages come from Baileys and may quote a JID: never let one reach a log.
export function scrub(text: string): string {
  return text.replace(/[\d:.-]{5,}@[a-z.]+/g, "<jid>");
}
