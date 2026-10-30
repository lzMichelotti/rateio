// make bridge-groups [GROUP=<id>]: the groups the bot is in, or one group's
// participants with their LIDs, so the operator can register them with the
// make admin commands. Uses the saved session; needs make bridge stopped.

import path from "node:path";
import { fileURLToPath } from "node:url";

import { loadConfig } from "./config.ts";
import { formatGroups, formatParticipants, maskPhone } from "./listing.ts";
import { holdSession, runningPid } from "./pidfile.ts";
import { runSession } from "./session.ts";

const bridgeDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const config = loadConfig(process.env, bridgeDir);
const groupId = process.env.GROUP || undefined;

if (runningPid(config.authDir) !== undefined) {
  console.error("make bridge is running: stop it first (two connections would knock each other off)");
  process.exit(1);
}
holdSession(config.authDir);

await runSession(config, {
  onOpen: async (sock) => {
  try {
    console.log(`the bot: ${sock.user?.lid ?? "(lid unknown)"}  phone ${maskPhone(sock.user?.id)}`);
    if (groupId === undefined) {
      console.log(formatGroups(Object.values(await sock.groupFetchAllParticipating())));
    } else {
      console.log(formatParticipants(await sock.groupMetadata(groupId)));
    }
    } finally {
      process.exit(0);
    }
  },
});
