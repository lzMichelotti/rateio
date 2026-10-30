import assert from "node:assert/strict";
import { test } from "node:test";

import { DisconnectReason } from "@whiskeysockets/baileys";

import { afterClose } from "../src/reconnect.ts";

test("a session ended from the phone is not reconnected", () => {
  assert.deepEqual(afterClose(DisconnectReason.loggedOut, 0), {
    action: "stop",
    reason: "logged_out",
  });
});

test("a session taken over by another bridge is not fought for", () => {
  assert.equal(afterClose(DisconnectReason.connectionReplaced, 0).action, "stop");
});

test("a forbidden account is not insisted on", () => {
  assert.equal(afterClose(DisconnectReason.forbidden, 3).action, "stop");
});

test("the restart after pairing reconnects at once", () => {
  assert.deepEqual(afterClose(DisconnectReason.restartRequired, 5), {
    action: "reconnect",
    delayMs: 0,
  });
});

test("other closes wait longer each time, up to 30 seconds", () => {
  const waits = [0, 1, 2, 3, 4, 5, 6, 10].map((attempt) => {
    const next = afterClose(DisconnectReason.connectionLost, attempt);
    assert.equal(next.action, "reconnect");
    return next.action === "reconnect" ? next.delayMs : -1;
  });

  assert.deepEqual(waits, [1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000]);
});

test("a close with no status code is retried", () => {
  assert.equal(afterClose(undefined, 0).action, "reconnect");
});
