import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

import type { WAMessage } from "@whiskeysockets/baileys";

import { toInbound, type Context } from "../src/inbound.ts";

// Fake identifiers only: 55000000000xx numbers, made-up LIDs and group id.
const GROUP = "120000000000000001@g.us";
const fixture = (name: string): WAMessage =>
  JSON.parse(fs.readFileSync(new URL(`fixtures/${name}.json`, import.meta.url), "utf8"));

const ctx: Context = {
  registered: new Map([[GROUP, new Date(1792999000 * 1000)]]),
  // The bot's own LID comes with a device suffix.
  botIds: ["100000000000009:17@lid", "5500000000009:17@s.whatsapp.net"],
};

function edit(base: WAMessage, change: (m: WAMessage) => void): WAMessage {
  const copy = structuredClone(base);
  change(copy);
  return copy;
}

test("a command in a registered chat becomes an inbound row", () => {
  const row = toInbound(fixture("command"), ctx);

  assert.ok(!("skip" in row));
  assert.equal(row.channel, "whatsapp_unofficial");
  assert.equal(row.conversationExternalId, GROUP);
  assert.equal(row.senderExternalId, "100000000000001@lid");
  assert.equal(row.channelMessageId, "3EB0000000000000000001");
  assert.equal(row.dedupeKey, `wa:${GROUP}:3EB0000000000000000001`);
  assert.deepEqual(row.receivedAt, new Date(1793000000 * 1000));
  assert.deepEqual((row.rawPayload as WAMessage).message, { conversation: "!gasto 300 gasolina" });
});

test("a mention of the bot is addressed to it, device suffix and all", () => {
  const row = toInbound(fixture("mention"), ctx);

  assert.ok(!("skip" in row));
  assert.deepEqual(
    (row.rawPayload as WAMessage).message?.extendedTextMessage?.contextInfo?.mentionedJid,
    ["100000000000009@lid"],
  );
});

test("a chat nobody registered leaves no row", () => {
  const other = edit(fixture("command"), (m) => (m.key.remoteJid = "120000000000000002@g.us"));

  assert.deepEqual(toInbound(other, ctx), { skip: "not_registered" });
});

test("the bot never lands its own messages", () => {
  const mine = edit(fixture("command"), (m) => (m.key.fromMe = true));

  assert.deepEqual(toInbound(mine, ctx), { skip: "from_me" });
});

test("a message older than the chat's registration is not replayed", () => {
  const old = edit(fixture("command"), (m) => (m.messageTimestamp = 1792998999));

  assert.deepEqual(toInbound(old, ctx), { skip: "before_registration" });
});

test("ordinary conversation is never stored", () => {
  const chat = edit(fixture("command"), (m) => (m.message = { conversation: "bora jantar?" }));
  const otherMention = edit(fixture("mention"), (m) => {
    m.message!.extendedTextMessage!.contextInfo!.mentionedJid = ["100000000000002@lid"];
  });

  assert.deepEqual(toInbound(chat, ctx), { skip: "not_addressed" });
  assert.deepEqual(toInbound(otherMention, ctx), { skip: "not_addressed" });
});

test("a message with no text is skipped", () => {
  const photo = edit(fixture("command"), (m) => (m.message = { imageMessage: {} }));

  assert.deepEqual(toInbound(photo, ctx), { skip: "no_text" });
});

test("a timestamp that arrives as a protobuf Long is read", () => {
  const long = edit(fixture("command"), (m) => {
    m.messageTimestamp = { toString: () => "1793000000" } as unknown as WAMessage["messageTimestamp"];
  });
  const row = toInbound(long, ctx);

  assert.ok(!("skip" in row));
  assert.deepEqual(row.receivedAt, new Date(1793000000 * 1000));
});

test("a message without an id is skipped", () => {
  const noId = edit(fixture("command"), (m) => (m.key.id = null));

  assert.deepEqual(toInbound(noId, ctx), { skip: "no_id" });
});
