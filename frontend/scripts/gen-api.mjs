#!/usr/bin/env node
import { writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const host = process.env.TRAEFIK_HOSTNAME || "localhost";
const baseUrl =
  host === "localhost"
    ? "http://localhost:8000"
    : `https://${host}`;
const specUrl = `${baseUrl}/api/openapi.json`;

function fixHeaders(obj) {
  if (!obj || typeof obj !== "object") return;
  if (Array.isArray(obj)) {
    obj.forEach(fixHeaders);
    return;
  }
  for (const key of Object.keys(obj)) {
    if (key === "headers" && typeof obj[key] === "object") {
      const headers = obj[key];
      for (const [name, value] of Object.entries(headers)) {
        if (typeof value === "string") {
          headers[name] = {
            description: value,
            schema: { type: "string", example: value },
          };
        }
      }
    } else {
      fixHeaders(obj[key]);
    }
  }
}

const res = await fetch(specUrl);
if (!res.ok) throw new Error(`Failed to fetch ${specUrl}: ${res.status}`);
const spec = await res.json();

fixHeaders(spec);

const tmpDir = mkdtempSync(join(tmpdir(), "openapi-"));
const tmpFile = join(tmpDir, "openapi.json");
try {
  writeFileSync(tmpFile, JSON.stringify(spec, null, 2));
  const result = spawnSync(
    "pnpm",
    [
      "exec",
      "openapi-typescript",
      tmpFile,
      "--output",
      "src/api/types.ts",
      "--root-types",
      "--enum",
    ],
    { stdio: "inherit", cwd: join(import.meta.dirname, "..") }
  );
  process.exit(result.status ?? 1);
} finally {
  rmSync(tmpDir, { recursive: true });
}
