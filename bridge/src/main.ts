// make bridge: keep the WhatsApp session alive. Receiving and sending are wired
// in as the stage goes; for now it pairs and stays connected.

import path from "node:path";
import { fileURLToPath } from "node:url";

import { loadConfig } from "./config.ts";
import { holdSession, runningPid } from "./pidfile.ts";
import { runSession } from "./session.ts";

const bridgeDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const config = loadConfig(process.env, bridgeDir);
if (runningPid(config.authDir) !== undefined) {
  console.error("another bridge is already running on this session");
  process.exit(1);
}
holdSession(config.authDir);
await runSession(config);
