import assert from "node:assert/strict";
import { test } from "node:test";

import { MAX_ATTEMPTS, resendLookup, sendNext, type OutboxStore, type Pending, type Send } from "../src/outbox.ts";

// An in-memory outbox with the same rules as the SQL one.
class FakeOutbox implements OutboxStore {
  rows: (Pending & { status: string; channelMessageId?: string | undefined })[] = [];

  add(id: string, body: string): void {
    this.rows.push({ id, chat: "120000000000000001@g.us", body, attempts: 0, status: "pending" });
  }

  async nextPending(): Promise<Pending | undefined> {
    return this.rows.find((r) => r.status === "pending");
  }

  async markSent(id: string, channelMessageId: string | undefined): Promise<void> {
    const row = this.rows.find((r) => r.id === id)!;
    Object.assign(row, { status: "sent", attempts: row.attempts + 1, channelMessageId });
  }

  async markAttemptFailed(id: string, failed: boolean): Promise<void> {
    const row = this.rows.find((r) => r.id === id)!;
    row.attempts += 1;
    if (failed) row.status = "failed";
  }
}

const delivered: Send = async () => "3EB0000000000000000099";
const broken: Send = async () => {
  throw new Error("socket closed");
};

test("a sent message is marked sent with WhatsApp's id", async () => {
  const outbox = new FakeOutbox();
  outbox.add("o1", "L1 registrado");

  assert.deepEqual(await sendNext(outbox, delivered), { kind: "sent", id: "o1" });
  assert.equal(outbox.rows[0]?.status, "sent");
  assert.equal(outbox.rows[0]?.channelMessageId, "3EB0000000000000000099");
});

test("a failure counts an attempt and stays pending", async () => {
  const outbox = new FakeOutbox();
  outbox.add("o1", "L1 registrado");

  const round = await sendNext(outbox, broken);

  assert.equal(round.kind, "retry");
  assert.equal(outbox.rows[0]?.attempts, 1);
  assert.equal(outbox.rows[0]?.status, "pending");
});

test(`the ${MAX_ATTEMPTS}th failure gives the message up`, async () => {
  const outbox = new FakeOutbox();
  outbox.add("o1", "L1 registrado");

  const rounds = [];
  for (let i = 0; i < MAX_ATTEMPTS; i++) rounds.push((await sendNext(outbox, broken)).kind);

  assert.deepEqual(rounds, ["retry", "retry", "retry", "retry", "failed"]);
  assert.equal(outbox.rows[0]?.status, "failed");
});

test("a failing message is never overtaken by the next one", async () => {
  const outbox = new FakeOutbox();
  outbox.add("o1", "proposal");
  outbox.add("o2", "its !ok");
  const sent: string[] = [];
  let calls = 0;
  const flaky: Send = async (_chat, body) => {
    calls += 1;
    if (calls <= 2) throw new Error("not yet");
    sent.push(body);
    return undefined;
  };

  for (let i = 0; i < 4; i++) await sendNext(outbox, flaky);

  assert.deepEqual(sent, ["proposal", "its !ok"]);
});

test("nothing pending, nothing sent", async () => {
  let called = false;
  const round = await sendNext(new FakeOutbox(), async () => {
    called = true;
    return undefined;
  });

  assert.deepEqual(round, { kind: "idle" });
  assert.equal(called, false);
});

test("a resend request finds what the bot said by WhatsApp's id", async () => {
  const lookup = resendLookup(async (id) => (id === "3EB0000000000000000099" ? "L1 registrado" : undefined));

  assert.deepEqual(await lookup({ id: "3EB0000000000000000099" }), { conversation: "L1 registrado" });
  assert.equal(await lookup({ id: "3EB0000000000000000098" }), undefined);
  assert.equal(await lookup({ id: null }), undefined);
});
