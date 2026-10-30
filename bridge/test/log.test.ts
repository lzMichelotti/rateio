import assert from "node:assert/strict";
import { test } from "node:test";

import { inboundOf, line, scrub } from "../src/log.ts";

const AT = new Date("2026-10-30T14:01:12.950Z");

test("a line is timestamp, process, event and key=value pairs", () => {
  assert.equal(
    line("outbound.sent", { outbound: "o-1", inbound: "i-1", attempt: 1 }, AT),
    "2026-10-30T14:01:12.950Z bridge outbound.sent outbound=o-1 inbound=i-1 attempt=1",
  );
});

test("fields without a value are left out", () => {
  assert.equal(line("session.connected", { code: undefined }, AT), "2026-10-30T14:01:12.950Z bridge session.connected");
});

test("a reply's dedupe key gives back the message it answers", () => {
  assert.equal(inboundOf("reply:5c47a952-f922-46e9-9dea-0f2c21d58680"), "5c47a952-f922-46e9-9dea-0f2c21d58680");
  assert.equal(inboundOf("dunning:x:2026-10-30"), undefined);
});

test("JIDs are scrubbed from free text", () => {
  assert.equal(scrub("bad 5500000000001@s.whatsapp.net and 100000000000001:3@lid"), "bad <jid> and <jid>");
});
