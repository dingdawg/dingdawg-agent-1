#!/usr/bin/env node
/**
 * @dingdawg/cli — Entry point
 *
 * Parses raw process.argv and delegates to the command router in src/index.js.
 * Zero dependencies — uses only Node.js built-ins (>=18).
 */

import { run } from '../src/index.js';

run(process.argv.slice(2)).catch((err) => {
  process.stderr.write(`\x1b[31mFatal error: ${err.message}\x1b[0m\n`);
  process.exit(1);
});
