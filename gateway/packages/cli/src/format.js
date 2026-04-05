/**
 * Terminal output formatting for @dingdawg/cli
 *
 * ANSI escape codes, spinners, markdown rendering, and structured blocks.
 * Zero dependencies — uses only process.stdout.write and ANSI codes.
 */

// ---------------------------------------------------------------------------
// ANSI colour helpers
// ---------------------------------------------------------------------------

const ANSI = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  italic: '\x1b[3m',

  // Foreground colours
  black: '\x1b[30m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  white: '\x1b[37m',
  gray: '\x1b[90m',

  // Background colours
  bgBlue: '\x1b[44m',
  bgGreen: '\x1b[42m',
};

/** True if terminal supports colour output. */
const SUPPORTS_COLOR =
  process.stdout.isTTY !== false &&
  !process.env.NO_COLOR &&
  process.env.TERM !== 'dumb';

/**
 * Wrap text in ANSI codes (no-op if colours not supported).
 *
 * @param {string} text
 * @param {...string} codes
 * @returns {string}
 */
function color(text, ...codes) {
  if (!SUPPORTS_COLOR) return text;
  return codes.join('') + text + ANSI.reset;
}

export const bold = (t) => color(t, ANSI.bold);
export const dim = (t) => color(t, ANSI.dim);
export const italic = (t) => color(t, ANSI.italic);
export const green = (t) => color(t, ANSI.green);
export const red = (t) => color(t, ANSI.red);
export const yellow = (t) => color(t, ANSI.yellow);
export const cyan = (t) => color(t, ANSI.cyan);
export const blue = (t) => color(t, ANSI.blue);
export const gray = (t) => color(t, ANSI.gray);
export const magenta = (t) => color(t, ANSI.magenta);
export const success = (t) => color(t, ANSI.green, ANSI.bold);
export const error = (t) => color(t, ANSI.red, ANSI.bold);
export const warn = (t) => color(t, ANSI.yellow, ANSI.bold);
export const info = (t) => color(t, ANSI.cyan);

// ---------------------------------------------------------------------------
// Print helpers
// ---------------------------------------------------------------------------

/** Write a line to stdout. */
export function println(text = '') {
  process.stdout.write(text + '\n');
}

/** Write without newline. */
export function print(text) {
  process.stdout.write(text);
}

/** Write a line to stderr. */
export function eprintln(text = '') {
  process.stderr.write(text + '\n');
}

/** Print a success message with green checkmark. */
export function printSuccess(text) {
  println(green('  ' + text));
}

/** Print an error message with red X. */
export function printError(text) {
  eprintln(red('  Error: ') + text);
}

/** Print a warning message. */
export function printWarn(text) {
  println(yellow('  Warning: ') + text);
}

/** Print an info line in cyan. */
export function printInfo(text) {
  println(cyan('  ' + text));
}

// ---------------------------------------------------------------------------
// Spinner (ora-like, hand-rolled)
// ---------------------------------------------------------------------------

const SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
const SPINNER_INTERVAL_MS = 80;

/**
 * Create and start a terminal spinner.
 *
 * @param {string} text - Initial spinner message
 * @returns {{ stop: (finalText?: string) => void, update: (text: string) => void }}
 */
export function createSpinner(text) {
  if (!process.stdout.isTTY) {
    // Non-TTY (piped output): print once and return no-op
    process.stdout.write(text + '...\n');
    return {
      stop: () => {},
      update: () => {},
    };
  }

  let frame = 0;
  let currentText = text;
  let stopped = false;

  const render = () => {
    const spinner = color(SPINNER_FRAMES[frame % SPINNER_FRAMES.length], ANSI.cyan);
    const line = `\r${spinner} ${currentText}`;
    process.stdout.write(line);
    frame++;
  };

  render();
  const interval = setInterval(render, SPINNER_INTERVAL_MS);

  return {
    /**
     * Stop the spinner.
     * @param {string} [finalText] - If provided, replaces spinner with this text.
     */
    stop(finalText) {
      if (stopped) return;
      stopped = true;
      clearInterval(interval);
      // Clear the spinner line
      process.stdout.write('\r' + ' '.repeat((currentText || '').length + 4) + '\r');
      if (finalText !== undefined) {
        println(finalText);
      }
    },
    /**
     * Update spinner text.
     * @param {string} newText
     */
    update(newText) {
      currentText = newText;
    },
  };
}

// ---------------------------------------------------------------------------
// Markdown rendering (terminal subset)
// ---------------------------------------------------------------------------

/**
 * Render a subset of markdown for terminal output.
 *
 * Supported:
 *   **bold**, `code`, _italic_, # heading, - list, numbered list
 *
 * @param {string} text
 * @returns {string}
 */
export function renderMarkdown(text) {
  if (!SUPPORTS_COLOR) return text;

  return text
    // Bold: **text**
    .replace(/\*\*(.+?)\*\*/g, (_, t) => bold(t))
    // Inline code: `code`
    .replace(/`([^`]+)`/g, (_, t) => color(t, ANSI.cyan, ANSI.dim))
    // Italic: _text_
    .replace(/_(.+?)_/g, (_, t) => italic(t))
    // H1: # Heading
    .replace(/^# (.+)$/gm, (_, t) => bold(cyan(t)))
    // H2: ## Heading
    .replace(/^## (.+)$/gm, (_, t) => bold(t))
    // H3: ### Heading
    .replace(/^### (.+)$/gm, (_, t) => bold(dim(t)))
    // List items: - item or * item
    .replace(/^[*-] (.+)$/gm, (_, t) => `  ${cyan('•')} ${t}`)
    // Numbered list: 1. item
    .replace(/^(\d+)\. (.+)$/gm, (_, n, t) => `  ${cyan(n + '.')} ${t}`);
}

// ---------------------------------------------------------------------------
// Structured output blocks
// ---------------------------------------------------------------------------

/** Draw a horizontal rule using box-drawing characters. */
export function printHRule(width = 50, char = '─') {
  println(gray(char.repeat(width)));
}

/**
 * Print a structured data block (like an appointment card).
 *
 * @param {string} title
 * @param {Object} fields  - key: value pairs
 */
export function printDataBlock(title, fields) {
  println('');
  println('  ' + bold(title));
  printHRule(40);
  const maxKey = Math.max(...Object.keys(fields).map((k) => k.length));
  for (const [key, value] of Object.entries(fields)) {
    const paddedKey = key.padEnd(maxKey);
    println(`  ${cyan(paddedKey)}  ${value}`);
  }
  printHRule(40);
  println('');
}

/**
 * Print a table of rows.
 *
 * @param {string[]} columns   - Column headers
 * @param {Array[]} rows       - Array of value arrays
 */
export function printTable(columns, rows) {
  // Calculate column widths
  const widths = columns.map((c, i) => {
    const maxRow = rows.reduce((m, r) => Math.max(m, String(r[i] || '').length), 0);
    return Math.max(c.length, maxRow);
  });

  // Header
  const header = columns.map((c, i) => bold(c.padEnd(widths[i]))).join('  ');
  println('  ' + header);
  printHRule(widths.reduce((s, w) => s + w + 2, 0) + 2);

  // Rows
  for (const row of rows) {
    const line = row.map((v, i) => String(v || '').padEnd(widths[i])).join('  ');
    println('  ' + line);
  }
  println('');
}

// ---------------------------------------------------------------------------
// Special output
// ---------------------------------------------------------------------------

/**
 * Print the DingDawg CLI header/logo.
 */
export function printHeader() {
  if (!SUPPORTS_COLOR) {
    println('DingDawg CLI v0.1.0');
    return;
  }
  println('');
  println(bold(cyan('  DingDawg CLI')) + gray(' v0.1.0'));
  println(gray('  Yeah! We\'ve Got An Agent For That!'));
  println('');
}

/**
 * Print a formatted whoami/status output.
 *
 * @param {Object} info
 * @param {string} info.email
 * @param {string} info.user_id
 * @param {string} [info.default_agent]
 */
export function printWhoami(info) {
  println('');
  println('  ' + bold('Authenticated as'));
  printHRule(30);
  println(`  ${cyan('Email')}     ${info.email || '(unknown)'}`);
  println(`  ${cyan('User ID')}   ${dim(info.user_id || '(unknown)')}`);
  if (info.default_agent) {
    println(`  ${cyan('Default')}   ${info.default_agent}`);
  }
  println('');
}

/**
 * Print formatted agent info.
 *
 * @param {Object} agent
 */
export function printAgentInfo(agent) {
  printDataBlock(`Agent: @${agent.handle}`, {
    Name: agent.name || '(unnamed)',
    Type: agent.agent_type || '',
    Industry: agent.industry_type || '',
    Status: agent.status === 'active' ? green(agent.status) : yellow(agent.status),
    Tier: agent.subscription_tier || 'free',
    'Agent ID': dim(agent.id || ''),
  });
}

/**
 * Print a list of agents.
 *
 * @param {Object[]} agents
 */
export function printAgentList(agents) {
  if (!agents || agents.length === 0) {
    println(yellow('  No agents found. Run: dd agents create'));
    return;
  }
  println('');
  println('  ' + bold('Your Agents'));
  printHRule(50);
  for (const a of agents) {
    const statusTag = a.status === 'active' ? green(a.status) : yellow(a.status);
    println(`  ${bold('@' + a.handle).padEnd(30)}  ${a.name || ''}  ${statusTag}`);
  }
  println('');
}

/**
 * Print a list of skills.
 *
 * @param {string} handle
 * @param {Object[]} skills
 */
export function printSkillList(handle, skills) {
  println('');
  println(`  ${bold('Skills for @' + handle)}`);
  printHRule(40);
  if (!skills || skills.length === 0) {
    println(gray('  No skills registered.'));
  } else {
    for (const s of skills) {
      const score = s.reputation_score != null
        ? dim(` (score: ${(s.reputation_score * 100).toFixed(0)}%)`)
        : '';
      println(`  ${cyan('•')} ${bold(s.name)}${score}`);
    }
  }
  println('');
}

/**
 * Print the device flow prompt for browser confirmation.
 *
 * @param {string} userCode
 * @param {string} verificationUrl
 */
export function printDevicePrompt(userCode, verificationUrl) {
  println('');
  println(bold('  To authenticate, open this URL in your browser:'));
  println('');
  println(`  ${cyan(verificationUrl)}`);
  println('');
  println(`  Or go to ${cyan('https://app.dingdawg.com/device')} and enter:`);
  println('');
  println(`  ${bold(yellow('  ' + userCode))}`);
  println('');
  println(dim('  Waiting for browser confirmation...'));
}
