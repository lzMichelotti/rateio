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
