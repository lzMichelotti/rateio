// make bridge: keep the WhatsApp session alive. Receiving and sending are wired
// in as the stage goes; for now it pairs and stays connected.

import path from "node:path";
import { fileURLToPath } from "node:url";

import { loadConfig } from "./config.ts";
import { runSession } from "./session.ts";

const bridgeDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
await runSession(loadConfig(process.env, bridgeDir));
