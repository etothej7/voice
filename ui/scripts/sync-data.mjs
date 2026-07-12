// Bundle analysis outputs into public/data/scorecards.json for the UI.
// In production this becomes an API endpoint; the JSON shape is the contract.
import { readFileSync, readdirSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const analysis = resolve(here, '../../analysis');
const outDir = resolve(here, '../public/data');

const readJsonDir = (dir) =>
  readdirSync(dir)
    .filter((f) => f.endsWith('.json'))
    .map((f) => JSON.parse(readFileSync(join(dir, f), 'utf8')));

const bundle = {
  config: JSON.parse(readFileSync(join(analysis, 'sellers.json'), 'utf8')),
  scorecards: readJsonDir(join(analysis, 'scorecards')),
  ledgers: readJsonDir(join(analysis, 'ledger')),
};

mkdirSync(outDir, { recursive: true });
writeFileSync(join(outDir, 'scorecards.json'), JSON.stringify(bundle));
console.log(
  `synced ${bundle.scorecards.length} scorecards, ${bundle.ledgers.length} ledgers -> public/data/scorecards.json`
);
