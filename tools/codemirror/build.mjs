// SPDX-FileCopyrightText: 2026 Beomjoon Kim
// SPDX-License-Identifier: AGPL-3.0-only
/* CodeMirror 6 묶음 만들기: `npm ci && npm run build` → web/vendor/codemirror/codemirror.min.js(전역 CM)와
   licenses/codemirror/(묶음에 든 패키지마다 LICENSE 원문). 앱을 실행하거나 배포할 때는 npm이 필요 없다. */
import { build } from "esbuild";
import { readFileSync, writeFileSync, mkdirSync, readdirSync, existsSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..", "..");
const outFile = join(root, "web", "vendor", "codemirror", "codemirror.min.js");

const result = await build({
  entryPoints: [join(here, "entry.js")],
  bundle: true, minify: true, format: "iife", globalName: "CM", target: ["es2019"],
  legalComments: "none", metafile: true, write: false,
});
// 묶음에 실제로 들어간 패키지(이름·버전·라이선스)
const pkgs = new Map();
for (const input of Object.keys(result.metafile.inputs)) {
  const m = input.match(/node_modules\/((?:@[^/]+\/)?[^/]+)\//);
  if (!m || pkgs.has(m[1])) continue;
  const dir = join(here, "node_modules", m[1]);
  const meta = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
  const lic = readdirSync(dir).find((f) => /^(LICEN[CS]E|COPYING)/i.test(f));
  pkgs.set(m[1], { version: meta.version, license: meta.license, file: lic ? join(dir, lic) : null });
}
const names = [...pkgs.keys()].sort();
const banner = "/* POSCHAT Code editor bundle — CodeMirror 6 and related packages (MIT). See THIRD_PARTY_NOTICES.md and licenses/codemirror/.\n" +
  names.map((n) => ` * ${n}@${pkgs.get(n).version} (${pkgs.get(n).license})`).join("\n") + " */\n";
mkdirSync(dirname(outFile), { recursive: true });
writeFileSync(outFile, banner + result.outputFiles[0].text);

const licDir = join(root, "licenses", "codemirror");
if (existsSync(licDir)) rmSync(licDir, { recursive: true });
mkdirSync(licDir, { recursive: true });
const missing = [];
for (const n of names) {
  const p = pkgs.get(n);
  if (!p.file) { missing.push(n); continue; }
  writeFileSync(join(licDir, n.replace("/", "__") + "-LICENSE.txt"), readFileSync(p.file));
}
writeFileSync(join(licDir, "PACKAGES.txt"), names.map((n) => `${n}@${pkgs.get(n).version} ${pkgs.get(n).license}`).join("\n") + "\n");
console.log(`${outFile}: ${((banner.length + result.outputFiles[0].text.length) / 1024).toFixed(0)} KB, ${names.length} packages`);
if (missing.length) { console.error("LICENSE 파일이 없는 패키지:", missing.join(", ")); process.exit(1); }
