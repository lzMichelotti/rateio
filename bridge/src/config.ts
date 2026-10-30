// The bridge's settings, read once from the environment (the Makefile loads
// .env). Nothing here is ever logged: the database URL carries a password.

import path from "node:path";

export interface Config {
  databaseUrl: string;
  // The WhatsApp session credentials: whoever holds these files controls the
  // bot's account. Outside git (bridge/auth/ is ignored), never printed.
  authDir: string;
  // The bot's own number, digits only with the country code. When set, an
  // unregistered session asks for a pairing code instead of showing a QR.
  // Never logged.
  pairingPhone: string | undefined;
}

export function loadConfig(env: NodeJS.ProcessEnv, bridgeDir: string): Config {
  const databaseUrl = env.DATABASE_URL;
  if (!databaseUrl) {
    throw new Error("DATABASE_URL is not set (copy .env.example to .env)");
  }
  const pairingPhone = env.BRIDGE_PAIRING_PHONE || undefined;
  // WhatsApp refuses +, spaces and dashes; the number itself is not echoed.
  if (pairingPhone !== undefined && !/^\d{10,15}$/.test(pairingPhone)) {
    throw new Error(
      "BRIDGE_PAIRING_PHONE must be digits only, with the country code (e.g. 5500000000000)",
    );
  }
  return {
    databaseUrl,
    authDir: path.resolve(bridgeDir, env.BRIDGE_AUTH_DIR ?? "auth"),
    pairingPhone,
  };
}
