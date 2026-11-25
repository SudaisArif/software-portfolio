import { cp, mkdir, readdir, rm } from "node:fs/promises";
import { dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const output = join(root, "public");

await rm(output, { recursive: true, force: true });
await mkdir(join(output, "data"), { recursive: true });
for (const name of ["index.html", "app.js", "squad-finances.js", "styles.css"]) {
  await cp(join(root, name), join(output, name));
}
await cp(join(root, "assets"), join(output, "assets"), { recursive: true });
for (const name of await readdir(join(root, "data"))) {
  if ([".json", ".csv"].includes(extname(name))) {
    await cp(join(root, "data", name), join(output, "data", name));
  }
}
console.log("Built Cloudflare static assets in public/.");
