#!/usr/bin/env node
// Flatten CJS build: copy dist/cjs/*.js → dist/*.cjs
const fs = require('fs');
const path = require('path');

const cjsDir = path.join(__dirname, '../dist/cjs');
const outDir = path.join(__dirname, '../dist');

if (!fs.existsSync(cjsDir)) { console.error('No dist/cjs found'); process.exit(1); }

for (const f of fs.readdirSync(cjsDir)) {
    if (f.endsWith('.js')) {
        const src = path.join(cjsDir, f);
        const dst = path.join(outDir, f.replace('.js', '.cjs'));
        let content = fs.readFileSync(src, 'utf8');
        // Fix requires: strip .js extension from require() calls for CJS compat
        content = content.replace(/require\("(\.\.?\/[^"]+)\.js"\)/g, 'require("$1")');
        fs.writeFileSync(dst, content);
    }
}
fs.rmSync(cjsDir, { recursive: true });
console.log('CJS build flattened to dist/*.cjs');
