// One process per WhatsApp session. Two connections with the same credentials
// knock each other off (connectionReplaced), so the bridge marks the session
// as in use, and the operator commands refuse to start while it is.

import fs from "node:fs";
import path from "node:path";

export function runningPid(authDir: string): number | undefined {
  try {
    const pid = Number(fs.readFileSync(path.join(authDir, "bridge.pid"), "utf8"));
    process.kill(pid, 0); // throws if no such process
    return pid;
  } catch {
    return undefined;
  }
}

export function holdSession(authDir: string): void {
  fs.mkdirSync(authDir, { recursive: true });
  const file = path.join(authDir, "bridge.pid");
  fs.writeFileSync(file, String(process.pid));
  const release = (): void => {
    try {
      if (fs.readFileSync(file, "utf8") === String(process.pid)) fs.rmSync(file);
    } catch {
      // already gone
    }
  };
  process.on("exit", release);
  for (const signal of ["SIGINT", "SIGTERM"] as const) {
    process.on(signal, () => process.exit(0));
  }
}
