// mpt-cycle のゴールデンを、移植元 mpt-cycle-extractor-webui の index.html の関数そのもので作る。
//
//   git clone https://github.com/tohoku-tomailab/mpt-cycle-extractor-webui <dir>   （commit d4b755f で作った）
//   node tests/golden/mpt-cycle/from_webui.mjs <dir>/index.html
//
// index.html の <script> から「気体定数」〜「設定の localStorage 保存」の手前（readTextWithFallback・
// extractMpt と補助関数）を取り出し、画面の要素を触る部分（byId〜plotPanel）を除いて Node で実行する。
// 出力: <ケース>/<出力CSV>（移植元のダウンロードと同じく先頭に BOM）、cases.json（条件・行数・エラー文）、
// format_g10.json（formatG10 の入出力）。ケースの意味は tests/test_mpt_cycle.py を参照。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const fixDir = path.join(here, '..', '..', 'fixtures', 'eclab');
const html = fs.readFileSync(process.argv[2], 'utf8');
let src = html.slice(html.indexOf('  // 気体定数'), html.indexOf('  // ---- 設定の localStorage 保存'));
src = src.replace(/  const byId = [\s\S]*?const plotPanel = byId\('plot-panel'\);\n/, '');
const api = new Function(`${src}\n return { extractMpt, readTextWithFallback, formatG10 };`)();

const CASES = {
  'utf8-rhe': ['cv_utf8.mpt', { cycle: 2, addRhe: true, ph: 14, refVsSHE: 0.105, tempC: 25 }],
  'utf8-norhe-cycle1': ['cv_utf8.mpt', { cycle: 1, addRhe: false, ph: NaN, refVsSHE: 0.105, tempC: 25 }],
  'utf8-rhe-custom': ['cv_utf8.mpt', { cycle: 3, addRhe: true, ph: 7.4, refVsSHE: 0.2, tempC: 25 }],
  'comma-rhe': ['cv_comma.mpt', { cycle: 2, addRhe: true, ph: 13, refVsSHE: 0.197, tempC: 30 }],
  'comma-missing-cycle': ['cv_comma.mpt', { cycle: 5, addRhe: true, ph: 13, refVsSHE: 0.197, tempC: 25 }],
  'not-eclab': ['not_eclab.mpt', { cycle: 2, addRhe: true, ph: 13, refVsSHE: 0.197, tempC: 25 }],
};
const summary = {};
for (const [name, [file, opts]] of Object.entries(CASES)) {
  const buf = fs.readFileSync(path.join(fixDir, file));
  const text = await api.readTextWithFallback({ arrayBuffer: async () => buf });
  try {
    const r = api.extractMpt(text, file, opts);
    fs.mkdirSync(path.join(here, name), { recursive: true });
    fs.writeFileSync(path.join(here, name, r.outputName), `\uFEFF${r.csv}`);
    summary[name] = { file, opts, output: r.outputName, rows: r.rows };
  } catch (e) {
    summary[name] = { file, opts, error: e.message };
  }
}
const json = (v) => `${JSON.stringify(v, (k, x) => (Number.isNaN(x) ? null : x), 2)}\n`;
fs.writeFileSync(path.join(here, 'cases.json'), json(summary));

const values = [0, 1, -1, 0.5, 0.9333308956123, 1.23456789012345, -0.000123456789, 0.0001,
  0.00009999999999, 1e-7, -3.14159265358979e-12, 12345.6789012345, 9999999999.4, 1e10,
  -2.5e15, 1.7976931348623157e308, 5e-324, 0.1 + 0.2, 1 / 3, 2 / 3, 123456789.987654321];
fs.writeFileSync(path.join(here, 'format_g10.json'),
  json(values.map((v) => [v, api.formatG10(v)])));
