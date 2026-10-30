// Formatting the groups the bot is in, for the operator to register one.
// Pure, so it is tested without WhatsApp. Phone numbers are never shown in
// full: the last four digits are enough to tell people apart, and a full
// number has no use here. Output goes to the terminal only, never to a log.

import type { GroupMetadata } from "@whiskeysockets/baileys";

// "5500000000001@s.whatsapp.net" or "5500000000001:12@s.whatsapp.net" -> "•••• 0001"
export function maskPhone(jid: string | undefined): string {
  if (!jid) return "(unknown)";
  const digits = (jid.split("@")[0] ?? "").split(":")[0] ?? "";
  return digits.length >= 4 ? `•••• ${digits.slice(-4)}` : "(unknown)";
}

export function formatGroups(groups: GroupMetadata[]): string {
  if (groups.length === 0) return "the bot is in no group yet";
  return groups
    .map(
      (g) =>
        `${g.id}  "${g.subject}"  ${g.participants.length} people` +
        `  addressing=${g.addressingMode ?? "?"}`,
    )
    .join("\n");
}

export function formatParticipants(group: GroupMetadata): string {
  const lines = [`${group.id}  "${group.subject}"  addressing=${group.addressingMode ?? "?"}`];
  for (const p of group.participants) {
    const lid = p.lid ?? (p.id.endsWith("@lid") ? p.id : undefined);
    lines.push(
      `  ${lid ?? p.id}  phone ${maskPhone(p.phoneNumber ?? (p.id.endsWith("@s.whatsapp.net") ? p.id : undefined))}` +
        `  ${p.notify ?? ""}${p.admin ? `  (${p.admin})` : ""}`,
    );
  }
  return lines.join("\n");
}
