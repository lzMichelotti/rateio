import assert from "node:assert/strict";
import { test } from "node:test";

import { loadConfig } from "../src/config.ts";

test("the auth folder defaults to bridge/auth", () => {
  const config = loadConfig({ DATABASE_URL: "postgresql://x" }, "/repo/bridge");

  assert.equal(config.authDir, "/repo/bridge/auth");
});

test("the auth folder can be moved", () => {
  const config = loadConfig(
    { DATABASE_URL: "postgresql://x", BRIDGE_AUTH_DIR: "/var/lib/rateio/auth" },
    "/repo/bridge",
  );

  assert.equal(config.authDir, "/var/lib/rateio/auth");
});

test("a missing database URL is refused", () => {
  assert.throws(() => loadConfig({}, "/repo/bridge"), /DATABASE_URL is not set/);
});

test("the pairing phone is digits only with the country code", () => {
  const config = loadConfig(
    { DATABASE_URL: "postgresql://x", BRIDGE_PAIRING_PHONE: "5500000000000" },
    "/repo/bridge",
  );

  assert.equal(config.pairingPhone, "5500000000000");
});

test("a formatted pairing phone is refused without echoing it", () => {
  assert.throws(
    () =>
      loadConfig(
        { DATABASE_URL: "postgresql://x", BRIDGE_PAIRING_PHONE: "+55 (00) 0000-0000" },
        "/repo/bridge",
      ),
    (error: Error) => /digits only/.test(error.message) && !error.message.includes("(00)"),
  );
});

test("no pairing phone is fine once the session is registered", () => {
  assert.equal(loadConfig({ DATABASE_URL: "postgresql://x" }, "/repo/bridge").pairingPhone, undefined);
});
