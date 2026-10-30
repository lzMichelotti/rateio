import assert from "node:assert/strict";
import { test } from "node:test";

import type { GroupMetadata } from "@whiskeysockets/baileys";

import { formatGroups, formatParticipants, maskPhone } from "../src/listing.ts";

// Fake identifiers only: 55000000000xx numbers, made-up LIDs and group id.
const GROUP = {
  id: "120000000000000001@g.us",
  subject: "Teste",
  addressingMode: "lid",
  owner: undefined,
  participants: [
    { id: "100000000000001@lid", phoneNumber: "5500000000001@s.whatsapp.net", notify: "Lotti", admin: "superadmin" },
    { id: "100000000000002@lid", phoneNumber: "5500000000002@s.whatsapp.net" },
  ],
} as unknown as GroupMetadata;

test("a phone shows only its last four digits", () => {
  assert.equal(maskPhone("5500000000001@s.whatsapp.net"), "•••• 0001");
  assert.equal(maskPhone("5500000000001:12@s.whatsapp.net"), "•••• 0001");
  assert.equal(maskPhone(undefined), "(unknown)");
});

test("participants are listed by LID, with the phone masked", () => {
  const text = formatParticipants(GROUP);

  assert.match(text, /100000000000001@lid {2}phone •••• 0001 {2}Lotti {2}\(superadmin\)/);
  assert.match(text, /100000000000002@lid {2}phone •••• 0002/);
  assert.doesNotMatch(text, /5500000000001/);
});

test("groups are listed by id, name, size and addressing mode", () => {
  assert.equal(
    formatGroups([GROUP]),
    '120000000000000001@g.us  "Teste"  2 people  addressing=lid',
  );
  assert.equal(formatGroups([]), "the bot is in no group yet");
});
