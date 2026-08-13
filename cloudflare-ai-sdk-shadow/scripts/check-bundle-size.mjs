import { readdir, stat } from "node:fs/promises";
import { join } from "node:path";

const outputDirectory = new URL("../.wrangler-dist/", import.meta.url).pathname;
const maximumBytes = 3 * 1024 * 1024;

async function bundleBytes(directory) {
  let total = 0;
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) total += await bundleBytes(path);
    else if (/\.(js|mjs|wasm|bin)$/.test(entry.name)) total += (await stat(path)).size;
  }
  return total;
}

const bytes = await bundleBytes(outputDirectory);
console.log(`shadow bundle: ${bytes} bytes (${(bytes / 1024 / 1024).toFixed(2)} MiB)`);
if (bytes > maximumBytes) {
  throw new Error(`shadow bundle exceeds the ${maximumBytes}-byte Sift limit`);
}
