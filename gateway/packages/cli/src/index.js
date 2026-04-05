/**
 * Main command router for @dingdawg/cli
 *
 * Parses args and dispatches to the appropriate command handler.
 * Zero dependencies — uses only Node.js 18+ built-ins.
 *
 * Global flags (parsed before dispatch):
 *   --help, -h      Show help text
 *   --version, -v   Show version
 *   --json          Output machine-readable JSON to stdout
 *   --no-color      Disable ANSI colour codes (also honoured via NO_COLOR env)
 *
 * Supported commands:
 *   dd login [--api-key <key>]
 *   dd logout
 *   dd whoami
 *   dd @handle <message>
 *   dd @handle --skill <skill> [<message>]
 *   dd config set <key> <value>
 *   dd config get <key>
 *   dd config list
 *   dd agents list
 *   dd agents info @handle
 *   dd agents skills @handle
 *   dd status @handle
 *   dd --help
 *   dd --version
 */

import { cmdLogin, cmdLogout, cmdWhoami } from './auth.js';
import { streamInvoke } from './stream.js';
import { get, parseJson, assertOk } from './api.js';
import {
  loadConfig,
  saveConfig,
  getConfigValue,
  setConfigValue,
  isAuthenticated,
} from './config.js';
import {
  println,
  printError,
  printInfo,
  printSuccess,
  printHeader,
  printAgentInfo,
  printAgentList,
  printSkillList,
  printDataBlock,
  printTable,
  bold,
  cyan,
  gray,
  dim,
  green,
  yellow,
} from './format.js';

// ---------------------------------------------------------------------------
// Version
// ---------------------------------------------------------------------------

const VERSION = '0.1.0';

// ---------------------------------------------------------------------------
// Help text
// ---------------------------------------------------------------------------

function printHelp() {
  printHeader();
  println(bold('Usage:'));
  println('  dd <command> [options]');
  println('');
  println(bold('Agent interaction:'));
  println(`  dd ${cyan('@handle')} ${gray('<message>')}             Chat with an agent`);
  println(`  dd ${cyan('@handle')} ${gray('--skill <name> <msg>')}  Invoke a specific skill`);
  println('');
  println(bold('Authentication:'));
  println(`  dd ${cyan('login')}                         Open browser for OAuth device flow`);
  println(`  dd ${cyan('login')} --api-key ${gray('<key>')}        Direct API key auth`);
  println(`  dd ${cyan('logout')}                        Clear credentials`);
  println(`  dd ${cyan('whoami')}                        Show current user`);
  println('');
  println(bold('Agent management:'));
  println(`  dd ${cyan('agents list')}                   List your agents`);
  println(`  dd ${cyan('agents info')} ${gray('@handle')}          Agent details`);
  println(`  dd ${cyan('agents skills')} ${gray('@handle')}        Available skills`);
  println('');
  println(bold('Configuration:'));
  println(`  dd ${cyan('config set')} ${gray('<key> <value>')}      Set a config value`);
  println(`  dd ${cyan('config get')} ${gray('<key>')}              Get a config value`);
  println(`  dd ${cyan('config list')}                   List all config values`);
  println('');
  println(bold('Status:'));
  println(`  dd ${cyan('status')} ${gray('@handle')}               Agent health summary`);
  println('');
  println(bold('Global options:'));
  println(`  ${cyan('--help, -h')}     Show this help`);
  println(`  ${cyan('--version, -v')}  Show version`);
  println(`  ${cyan('--json')}         Output machine-readable JSON (for scripting/piping)`);
  println(`  ${cyan('--no-color')}     Disable ANSI colour codes`);
  println('');
  println(dim('  Examples:'));
  println(dim('    dd @mybusiness "schedule a meeting for Monday at 3pm"'));
  println(dim('    dd @mybusiness --skill appointments list'));
  println(dim('    dd login --api-key sk_live_abc123'));
  println(dim('    dd --json agents list'));
  println('');
}

// ---------------------------------------------------------------------------
// JSON output helper
// ---------------------------------------------------------------------------

/**
 * Emit a JSON result to stdout.
 * Used when --json flag is active.
 *
 * @param {unknown} data
 */
function emitJson(data) {
  process.stdout.write(JSON.stringify(data) + '\n');
}

// ---------------------------------------------------------------------------
// Config commands
// ---------------------------------------------------------------------------

async function cmdConfig(args, jsonMode) {
  const sub = args[0];

  if (!sub || sub === 'list') {
    const cfg = loadConfig();
    if (jsonMode) {
      // Mask sensitive values in JSON output too
      const safe = {};
      for (const [key, value] of Object.entries(cfg)) {
        safe[key] = ['api_key', 'access_token'].includes(key)
          ? '•'.repeat(8) + (String(value).slice(-4) || '')
          : value;
      }
      emitJson({ config: safe });
      return;
    }
    if (Object.keys(cfg).length === 0) {
      println(gray('  No configuration set.'));
      return;
    }
    println('');
    println(bold('  Configuration'));
    println('  ' + '─'.repeat(40));
    for (const [key, value] of Object.entries(cfg)) {
      // Mask sensitive values
      const display = ['api_key', 'access_token'].includes(key)
        ? '•'.repeat(8) + (String(value).slice(-4) || '')
        : String(value);
      println(`  ${cyan(key.padEnd(20))}  ${display}`);
    }
    println('');
    return;
  }

  if (sub === 'set') {
    const key = args[1];
    const value = args[2];
    if (!key || value === undefined) {
      if (jsonMode) {
        emitJson({ error: 'Usage: dd config set <key> <value>' });
        process.exit(1);
      }
      printError('Usage: dd config set <key> <value>');
      process.exit(1);
    }
    setConfigValue(key, value);
    if (jsonMode) {
      emitJson({ ok: true, key, value });
      return;
    }
    printSuccess(`Config set: ${key} = ${value}`);
    return;
  }

  if (sub === 'get') {
    const key = args[1];
    if (!key) {
      if (jsonMode) {
        emitJson({ error: 'Usage: dd config get <key>' });
        process.exit(1);
      }
      printError('Usage: dd config get <key>');
      process.exit(1);
    }
    const value = getConfigValue(key);
    if (jsonMode) {
      emitJson({ key, value: value === undefined ? null : value });
      return;
    }
    if (value === undefined) {
      println(gray(`  (not set)`));
    } else {
      println(`  ${cyan(key)}: ${value}`);
    }
    return;
  }

  if (jsonMode) {
    emitJson({ error: `Unknown config subcommand: ${sub}` });
    process.exit(1);
  }
  printError(`Unknown config subcommand: ${sub}`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Agents commands
// ---------------------------------------------------------------------------

async function cmdAgents(args, jsonMode) {
  const sub = args[0];

  if (!sub || sub === 'list') {
    if (!isAuthenticated()) {
      if (jsonMode) {
        emitJson({ error: 'Not logged in. Run: dd login' });
        process.exit(1);
      }
      printError('Not logged in. Run: dd login');
      process.exit(1);
    }

    let resp;
    try {
      resp = await get('/api/v1/cli/agents');
      await assertOk(resp, 'Failed to list agents');
    } catch (err) {
      if (jsonMode) {
        emitJson({ error: err.message });
        process.exit(1);
      }
      printError(err.message);
      process.exit(1);
    }

    const data = await parseJson(resp);
    if (jsonMode) {
      emitJson({ agents: data.agents || [] });
      return;
    }
    printAgentList(data.agents || []);
    return;
  }

  if (sub === 'info') {
    const handle = args[1];
    if (!handle) {
      if (jsonMode) {
        emitJson({ error: 'Usage: dd agents info @handle' });
        process.exit(1);
      }
      printError('Usage: dd agents info @handle');
      process.exit(1);
    }
    if (!isAuthenticated()) {
      if (jsonMode) {
        emitJson({ error: 'Not logged in. Run: dd login' });
        process.exit(1);
      }
      printError('Not logged in. Run: dd login');
      process.exit(1);
    }

    const cleanHandle = handle.replace('@', '');

    let resp;
    try {
      // Use the list endpoint filtered by handle (the info is in the list)
      resp = await get('/api/v1/cli/agents');
      await assertOk(resp, 'Failed to fetch agent info');
    } catch (err) {
      if (jsonMode) {
        emitJson({ error: err.message });
        process.exit(1);
      }
      printError(err.message);
      process.exit(1);
    }

    const data = await parseJson(resp);
    const agent = (data.agents || []).find(
      (a) => a.handle === cleanHandle || a.handle === handle.replace('@', '')
    );

    if (!agent) {
      if (jsonMode) {
        emitJson({ error: `Agent not found: ${handle}` });
        process.exit(1);
      }
      printError(`Agent not found: ${handle}`);
      process.exit(1);
    }
    if (jsonMode) {
      emitJson({ agent });
      return;
    }
    printAgentInfo(agent);
    return;
  }

  if (sub === 'skills') {
    const handle = args[1];
    if (!handle) {
      if (jsonMode) {
        emitJson({ error: 'Usage: dd agents skills @handle' });
        process.exit(1);
      }
      printError('Usage: dd agents skills @handle');
      process.exit(1);
    }
    if (!isAuthenticated()) {
      if (jsonMode) {
        emitJson({ error: 'Not logged in. Run: dd login' });
        process.exit(1);
      }
      printError('Not logged in. Run: dd login');
      process.exit(1);
    }

    const cleanHandle = handle.replace('@', '');

    let resp;
    try {
      resp = await get(`/api/v1/cli/agents/${encodeURIComponent(cleanHandle)}/skills`);
      await assertOk(resp, 'Failed to fetch skills');
    } catch (err) {
      if (jsonMode) {
        emitJson({ error: err.message });
        process.exit(1);
      }
      printError(err.message);
      process.exit(1);
    }

    const data = await parseJson(resp);
    if (jsonMode) {
      emitJson({ agent_handle: data.agent_handle || cleanHandle, skills: data.skills || [] });
      return;
    }
    printSkillList(data.agent_handle || cleanHandle, data.skills || []);
    return;
  }

  if (jsonMode) {
    emitJson({ error: `Unknown agents subcommand: ${sub}` });
    process.exit(1);
  }
  printError(`Unknown agents subcommand: ${sub}`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Status command
// ---------------------------------------------------------------------------

async function cmdStatus(handle, jsonMode) {
  if (!handle) {
    if (jsonMode) {
      emitJson({ error: 'Usage: dd status @handle' });
      process.exit(1);
    }
    printError('Usage: dd status @handle');
    process.exit(1);
  }
  if (!isAuthenticated()) {
    if (jsonMode) {
      emitJson({ error: 'Not logged in. Run: dd login' });
      process.exit(1);
    }
    printError('Not logged in. Run: dd login');
    process.exit(1);
  }

  const cleanHandle = handle.replace('@', '');

  let agentsResp, skillsResp;
  try {
    agentsResp = await get('/api/v1/cli/agents');
    await assertOk(agentsResp, 'Failed to fetch agent info');
  } catch (err) {
    if (jsonMode) {
      emitJson({ error: err.message });
      process.exit(1);
    }
    printError(err.message);
    process.exit(1);
  }

  const agentsData = await parseJson(agentsResp);
  const agent = (agentsData.agents || []).find((a) => a.handle === cleanHandle);

  if (!agent) {
    if (jsonMode) {
      emitJson({ error: `Agent not found: ${handle}` });
      process.exit(1);
    }
    printError(`Agent not found: ${handle}`);
    process.exit(1);
  }

  let skillCount = 0;
  try {
    skillsResp = await get(`/api/v1/cli/agents/${encodeURIComponent(cleanHandle)}/skills`);
    if (skillsResp.ok) {
      const skillsData = await parseJson(skillsResp);
      skillCount = (skillsData.skills || []).length;
    }
  } catch {
    // Non-fatal
  }

  if (jsonMode) {
    emitJson({
      handle: cleanHandle,
      name: agent.name || null,
      status: agent.status,
      agent_type: agent.agent_type || null,
      industry: agent.industry_type || null,
      tier: agent.subscription_tier || 'free',
      skill_count: skillCount,
      agent_id: agent.id || null,
    });
    return;
  }

  printDataBlock(`Status: @${cleanHandle}`, {
    Name: agent.name || '(unnamed)',
    Status: agent.status === 'active' ? green(agent.status) : yellow(agent.status),
    Type: agent.agent_type || '',
    Industry: agent.industry_type || '',
    Tier: agent.subscription_tier || 'free',
    Skills: String(skillCount),
    'Agent ID': dim(agent.id || ''),
  });
}

// ---------------------------------------------------------------------------
// Agent invocation (@handle command)
// ---------------------------------------------------------------------------

async function cmdInvokeAgent(handle, args, jsonMode) {
  if (!isAuthenticated()) {
    if (jsonMode) {
      emitJson({ error: 'Not logged in. Run: dd login' });
      process.exit(1);
    }
    printError('Not logged in. Run: dd login');
    process.exit(1);
  }

  // Parse --skill and message from remaining args
  let skill = null;
  let action = null;
  const parameters = {};
  const messageParts = [];

  let i = 0;
  while (i < args.length) {
    if (args[i] === '--skill' && i + 1 < args.length) {
      skill = args[i + 1];
      i += 2;
    } else if (args[i] === '--action' && i + 1 < args.length) {
      action = args[i + 1];
      i += 2;
    } else {
      messageParts.push(args[i]);
      i++;
    }
  }

  const message = messageParts.join(' ').trim();

  if (!message && !skill) {
    if (jsonMode) {
      emitJson({ error: 'Provide a message or --skill. Example: dd @mybusiness "hello"' });
      process.exit(1);
    }
    printError('Provide a message or --skill. Example: dd @mybusiness "hello"');
    process.exit(1);
  }

  // Note: streamInvoke always outputs to stdout as a stream.
  // In JSON mode the caller should pipe through a JSON SSE collector;
  // the stream itself is SSE, not JSON lines. We still honour the flag
  // by noting it here — future implementations could buffer + emit JSON.
  await streamInvoke({
    handle,
    message: message || `Run skill: ${skill}`,
    skill,
    action,
    parameters,
  });
}

// ---------------------------------------------------------------------------
// COMMANDS dispatch map
// ---------------------------------------------------------------------------

/**
 * Map of top-level command names → handler functions.
 *
 * Each handler receives (args: string[], jsonMode: boolean).
 * The @ prefix shorthand is handled separately before this map is consulted.
 */
const COMMANDS = {
  login: (args, jsonMode) => cmdLogin(args),
  logout: (_args, _jsonMode) => cmdLogout(),
  whoami: (_args, _jsonMode) => cmdWhoami(),
  config: (args, jsonMode) => cmdConfig(args, jsonMode),
  agents: (args, jsonMode) => cmdAgents(args, jsonMode),
  status: (args, jsonMode) => cmdStatus(args[0], jsonMode),
};

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

/**
 * Parse args and dispatch to the correct command.
 *
 * Global flags are stripped from argv before dispatch:
 *   --json       → jsonMode = true
 *   --no-color   → NO_COLOR env is set (format.js reads it)
 *   --help/-h    → print help and exit
 *   --version/-v → print version and exit
 *
 * @param {string[]} argv - process.argv.slice(2)
 * @returns {Promise<void>}
 */
export async function run(argv) {
  if (!argv || argv.length === 0) {
    printHelp();
    return;
  }

  // -------------------------------------------------------------------------
  // Strip and consume global flags before command dispatch
  // -------------------------------------------------------------------------
  let jsonMode = false;
  const filtered = [];

  for (const arg of argv) {
    if (arg === '--json') {
      jsonMode = true;
    } else if (arg === '--no-color') {
      process.env.NO_COLOR = '1';
    } else if (arg === '--help' || arg === '-h' || arg === 'help') {
      printHelp();
      return;
    } else if (arg === '--version' || arg === '-v') {
      println(`@dingdawg/cli v${VERSION}`);
      return;
    } else {
      filtered.push(arg);
    }
  }

  if (filtered.length === 0) {
    printHelp();
    return;
  }

  const cmd = filtered[0];
  const rest = filtered.slice(1);

  // -------------------------------------------------------------------------
  // @ prefix — agent invocation shorthand
  // -------------------------------------------------------------------------
  if (cmd.startsWith('@')) {
    await cmdInvokeAgent(cmd, rest, jsonMode);
    return;
  }

  // -------------------------------------------------------------------------
  // Dispatch table lookup — MUST come before bare-handle fallback so that
  // known command names (config, agents, status, etc.) are never mistaken
  // for agent handle shorthand.
  // -------------------------------------------------------------------------
  const handler = COMMANDS[cmd];
  if (handler) {
    await handler(rest, jsonMode);
    return;
  }

  // -------------------------------------------------------------------------
  // Bare handle without @ (alphanumeric + hyphens with remaining args)
  // Only reached if cmd is NOT a known COMMANDS entry.
  // -------------------------------------------------------------------------
  if (/^[a-z0-9][a-z0-9-]*$/.test(cmd) && rest.length > 0) {
    const cfg = loadConfig();
    if (cfg.default_agent && cmd !== cfg.default_agent.replace('@', '')) {
      if (jsonMode) {
        emitJson({ error: `Unknown command: ${cmd}`, hint: 'Run: dd --help' });
        process.exit(1);
      }
      printError(`Unknown command: ${cmd}. Run: dd --help`);
      process.exit(1);
    }
    await cmdInvokeAgent('@' + cmd, rest, jsonMode);
    return;
  }

  // -------------------------------------------------------------------------
  // Unknown command
  // -------------------------------------------------------------------------
  if (jsonMode) {
    emitJson({ error: `Unknown command: ${cmd}`, hint: 'Run: dd --help' });
    process.exit(1);
  }
  printError(`Unknown command: ${cmd}. Run: dd --help`);
  process.exit(1);
}
