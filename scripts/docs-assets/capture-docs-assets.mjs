/**
 * Capture UI screenshots for documentation.
 *
 * Usage:
 *   node scripts/docs-assets/capture-docs-assets.mjs --base-url http://127.0.0.1:3100
 *   node scripts/docs-assets/capture-docs-assets.mjs --base-url http://127.0.0.1:3100 --update-docs-assets
 */

import { chromium } from 'playwright';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, '..', '..');

function parseCliOptions() {
  const options = {
    baseUrl: process.env.DOCS_VISUAL_BASE_URL || 'http://127.0.0.1:3000',
    outputDir: process.env.DOCS_VISUAL_OUTPUT_DIR || path.join(__dirname, 'output'),
    manifest: path.join(REPO_ROOT, 'docs/assets/ui/visual-assets.manifest.json'),
    updateDocsAssets: false,
  };

  const args = process.argv.slice(2);
  for (let index = 0; index < args.length; index++) {
    const arg = args[index];
    if (arg === '--base-url') {
      options.baseUrl = args[++index] || options.baseUrl;
    } else if (arg === '--output-dir') {
      options.outputDir = args[++index] || options.outputDir;
    } else if (arg === '--manifest') {
      options.manifest = args[++index] || options.manifest;
    } else if (arg === '--update-docs-assets') {
      options.updateDocsAssets = true;
    } else if (arg === '--help' || arg === '-h') {
      console.log(
        'Usage: node scripts/docs-assets/capture-docs-assets.mjs [--base-url URL] [--output-dir DIR] [--manifest PATH] [--update-docs-assets]',
      );
      process.exit(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  options.baseUrl = options.baseUrl.replace(/\/$/, '');
  options.outputDir = path.resolve(options.outputDir);
  options.manifest = path.resolve(options.manifest);
  return options;
}

function readManifest(manifestPath) {
  return JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
}

function outputPathFor(options, asset) {
  if (options.updateDocsAssets) {
    return path.join(REPO_ROOT, asset.path);
  }
  return path.join(options.outputDir, path.basename(asset.path));
}

async function preparePage(page) {
  await page.addStyleTag({
    content: `
      * {
        caret-color: transparent !important;
      }

      [data-nextjs-toast], nextjs-portal {
        display: none !important;
      }
    `,
  });
}

async function captureScreenshot(page, options, asset, viewport) {
  const target = outputPathFor(options, asset);
  fs.mkdirSync(path.dirname(target), { recursive: true });

  await page.setViewportSize(asset.viewport || viewport);
  await page.goto(`${options.baseUrl}${asset.route}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await preparePage(page);
  await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => undefined);
  await page.waitForTimeout(1200);
  await page.screenshot({ path: target, fullPage: false });
  console.log(`captured ${asset.id} -> ${path.relative(REPO_ROOT, target)}`);
}

function ensureGifAsset(options, asset) {
  const target = outputPathFor(options, asset);
  fs.mkdirSync(path.dirname(target), { recursive: true });

  const existingDemoGif = path.join(REPO_ROOT, 'docs/assets/demo.gif');
  if (!fs.existsSync(existingDemoGif)) {
    throw new Error(`Cannot seed ${asset.id}; missing ${path.relative(REPO_ROOT, existingDemoGif)}`);
  }

  fs.copyFileSync(existingDemoGif, target);
  console.log(`seeded ${asset.id} -> ${path.relative(REPO_ROOT, target)}`);
}

async function main() {
  const options = parseCliOptions();
  const manifest = readManifest(options.manifest);

  const browser = await chromium.launch({
    headless: true,
    args: ['--disable-gpu', '--no-sandbox'],
  });
  const page = await browser.newPage({
    viewport: manifest.defaultViewport,
    deviceScaleFactor: 1,
    colorScheme: 'dark',
  });

  try {
    for (const asset of manifest.assets) {
      if (asset.kind === 'gif') {
        ensureGifAsset(options, asset);
        continue;
      }
      await captureScreenshot(page, options, asset, manifest.defaultViewport);
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
