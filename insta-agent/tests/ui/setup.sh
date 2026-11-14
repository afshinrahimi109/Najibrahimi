#!/bin/sh
# One-time setup for the browser checks: a headless Chromium that needs nothing from the system.
#   sh setup.sh        then        python3 serve.py flows.mjs demo
# If a Chrome/Chromium is already installed, skip the unpacking and run with CHROME_PATH=/path/to/chrome instead.
set -e
cd "$(dirname "$0")"
npm install --no-audit --no-fund --silent
SCRATCH="${IA_UI_SCRATCH:-/tmp/ia-ui}"
mkdir -p "$SCRATCH"
node - "$SCRATCH" <<'JS'
const fs = require('fs'), path = require('path'), zlib = require('zlib'), cp = require('child_process');
const scratch = process.argv[2], bin = path.join(process.cwd(), 'node_modules/@sparticuz/chromium/bin');
for (const name of ['al2023', 'swiftshader']) {            // the shared libraries Chromium is linked against
  const dir = path.join(scratch, name);
  if (fs.existsSync(dir)) continue;
  fs.mkdirSync(dir, {recursive: true});
  const tar = path.join(scratch, name + '.tar');
  fs.writeFileSync(tar, zlib.brotliDecompressSync(fs.readFileSync(path.join(bin, name + '.tar.br'))));
  cp.execFileSync('tar', ['-xf', tar, '-C', dir]);
  fs.unlinkSync(tar);
}
JS
# a font with Persian letters, where this Chromium build looks for fonts
mkdir -p /tmp/fonts
for d in /usr/share/fonts/truetype/dejavu /usr/share/fonts/truetype/vazir /usr/share/fonts/TTF; do
  [ -d "$d" ] && cp -r "$d" /tmp/fonts/ || true
done
echo "ready: libraries in $SCRATCH"
