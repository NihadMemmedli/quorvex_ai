# Playwright Skill

Execute arbitrary Playwright scripts for complex browser automation scenarios.

## When to Use

Use skill mode (`--skill-mode` or `--run-skill`) when you need:
- **Complex atomic flows** - Multi-step operations that must complete atomically
- **Network interception** - Mocking API responses, request blocking
- **Custom retry logic** - Non-standard waiting patterns
- **Multi-tab scenarios** - Coordinating actions across browser tabs
- **Performance testing** - Measuring page load times, resource usage
- **File downloads** - Handling download dialogs and file saves

## Usage

### Run a Script File
```bash
python orchestrator/cli.py --run-skill /path/to/script.js
```

### Run with Skill Mode (Pipeline)
```bash
python orchestrator/cli.py specs/test.md --skill-mode
```

### Script Format

Scripts receive a pre-configured `page` object:

```javascript
// script.js
const title = await page.title();
console.log('Page title:', title);

await page.click('button[type="submit"]');
await page.waitForURL('**/dashboard');

// Return data (optional)
return { success: true, title };
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HEADLESS` | `false` | Run browser in headless mode |
| `SLOW_MO` | `0` | Slow down actions by N milliseconds |
| `SKILL_TIMEOUT` | `30000` | Script execution timeout (ms) |
| `SKILL_DIR` | `.claude/skills/playwright` | Skill installation directory |

## Helpers

Import helpers for common operations:

```javascript
import { safeClick, screenshot, retry } from './lib/helpers.js';

await safeClick(page, 'button.submit', { timeout: 5000 });
await screenshot(page, 'after-submit');
await retry(() => page.waitForSelector('.loaded'), { attempts: 3 });
```

See `lib/helpers.js` for all available utilities.
