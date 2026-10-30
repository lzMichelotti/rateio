// The bridge's settings, read once from the environment (the Makefile loads
// .env). Nothing here is ever logged: the database URL carries a password.

import path from "node:path";

export interface Config {
  databaseUrl: string;
  // The WhatsApp session credentials: whoever holds these files controls the
  // bot's account. Outside git (bridge/auth/ is ignored), never printed.
  authDir: string;
}

export function loadConfig(env: NodeJS.ProcessEnv, bridgeDir: string): Config {
  const databaseUrl = env.DATABASE_URL;
  if (!databaseUrl) {
    throw new Error("DATABASE_URL is not set (copy .env.example to .env)");
  }
  return {
    databaseUrl,
    authDir: path.resolve(bridgeDir, env.BRIDGE_AUTH_DIR ?? "auth"),
  };
}
