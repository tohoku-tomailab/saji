// saji の外枠（汎用）。tools.json からツール一覧とフォームを組み立てる。
// ツールを追加するときに、このファイルを書き換える必要はない（docs/adding-a-tool.md）。
//
// 汎用フォームで表せない操作が要るツールだけ、web/panels/<tool>.js を置ける（例外）。
// 専用パネルは次の形の ES module にする（docs/decisions/0005-web-panels.md）:
//   export function mount(container, ctx) -> { getParams(): {名前: 値} }
//   ctx = { tool, defaults, getFiles(inputName) -> File[] }
// 処理そのものは専用パネルでも Python の run() が行う。

import { renderFigure } from "./plot.js";

const $ = (id) => document.getElementById(id);
const worker = new Worker("worker.js", { type: "module" });

const state = {
  tools: [],
  tool: null,
  files: {},        // 入力名 → [{name, file}]
  panel: null,      // 専用パネルのインスタンス
  engineReady: false,
  running: false,
  runId: 0,
  zipUrl: null,
};

// ============================================================ Worker
worker.onmessage = (ev) => {
  const m = ev.data;
  if (m.type === "status") setEngine("loading", m.message);
  else if (m.type === "ready") {
    state.engineReady = true;
    setEngine("ready", `準備完了（Python ${m.pyodideVersion ? "Pyodide " + m.pyodideVersion : ""}）`);
    updateRunState();
  } else if (m.type === "prepared") {
    if (state.engineReady && !state.running) setEngine("ready", "準備完了");
  } else if (m.type === "result") onResult(m);
  else if (m.type === "error") {
    if (m.id !== undefined) onResult({ id: m.id, summary: { ok: false, kind: "internal", error: m.message } });
    else setEngine("error", m.message);
  }
};
worker.onerror = (e) => setEngine("error", `Worker を起動できません: ${e.message || e}`);

function setEngine(stateName, text) {
  $("engine").dataset.state = stateName;
  $("engine-text").textContent = text;
  $("engine").title = text;
}

// ============================================================ 起動
init();

async function init() {
  try {
    const [tools, version] = await Promise.all([
      fetch("dist/tools.json", { cache: "no-cache" }).then((r) => r.json()),
      fetch("dist/version.json", { cache: "no-cache" }).then((r) => r.json()),
    ]);
    state.tools = tools;
    $("version").textContent = `saji ${version.version}` +
      (version.git_commit ? ` (${version.git_commit})` : "") + ` / Pyodide ${version.pyodide_version}`;
    renderToolList();
    const fromHash = decodeURIComponent(location.hash.slice(1));
    if (tools.some((t) => t.name === fromHash)) selectTool(fromHash);
  } catch (err) {
    setEngine("error", "dist/ が見つかりません。scripts/build_web.py でビルドしてください。");
  }
}

window.addEventListener("hashchange", () => {
  const name = decodeURIComponent(location.hash.slice(1));
  if (name && name !== state.tool?.name && state.tools.some((t) => t.name === name)) selectTool(name);
});

function renderToolList() {
  const ul = $("tools");
  const sel = $("toolselect");
  ul.replaceChildren();
  sel.replaceChildren(new Option("ツールを選ぶ…", ""));
  for (const t of state.tools) {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.tool = t.name;
    b.innerHTML = `<span class="t-name"></span><span class="t-sum"></span>`;
    b.querySelector(".t-name").textContent = t.name;
    if (!t.web) b.querySelector(".t-name").insertAdjacentHTML("beforeend", `<span class="badge">CLI専用</span>`);
    b.querySelector(".t-sum").textContent = t.summary;
    b.addEventListener("click", () => { location.hash = t.name; selectTool(t.name); });
    li.append(b);
    ul.append(li);
    sel.append(new Option(t.name + (t.web ? "" : "（CLI専用）"), t.name));
  }
  sel.addEventListener("change", () => { if (sel.value) { location.hash = sel.value; selectTool(sel.value); } });
}

// ============================================================ ツールの表示
async function selectTool(name) {
  const tool = state.tools.find((t) => t.name === name);
  state.tool = tool;
  state.files = Object.fromEntries(tool.inputs.map((i) => [i.name, []]));
  state.panel = null;
  document.querySelectorAll(".toollist button").forEach((b) =>
    b.setAttribute("aria-current", String(b.dataset.tool === name)));
  $("toolselect").value = name;
  $("welcome").hidden = true;
  $("tool").hidden = false;
  $("result").hidden = true;
  $("tool-name").textContent = tool.name;
  $("tool-summary").textContent = tool.summary;
  $("tool-desc").textContent = tool.description;
  $("tool-desc-wrap").hidden = !tool.description;

  const cli = $("cli-only");
  if (!tool.web) {
    cli.hidden = false;
    cli.replaceChildren();
    const p = document.createElement("p");
    p.textContent = "このツールは CLI 専用です。" + (tool.cli_only_reason || "");
    cli.append(p);
    const pre = document.createElement("pre");
    pre.textContent = (tool.examples.length ? tool.examples : [`saji ${tool.name} --help`]).join("\n");
    cli.append(pre);
    $("form").hidden = true;
    return;
  }
  cli.hidden = true;
  $("form").hidden = false;
  renderInputs(tool);
  if (tool.panel) {
    const mod = await import(`./panels/${tool.name}.js`);
    state.panel = mod.mount($("params"), {
      tool,
      defaults: Object.fromEntries(tool.params.map((p) => [p.name, p.default])),
      getFiles: (input) => (state.files[input] || []).map((f) => f.file),
    });
  } else {
    renderParams(tool);
  }
  worker.postMessage({ type: "prepare", tool: tool.name });
  updateRunState();
}

// ============================================================ 入力ファイル
function accepts(spec, name) {
  if (!spec.accept.length) return true;
  const i = name.lastIndexOf(".");
  return i >= 0 && spec.accept.includes(name.slice(i).toLowerCase());
}

function renderInputs(tool) {
  const root = $("inputs");
  root.replaceChildren();
  for (const spec of tool.inputs) {
    const fs = document.createElement("fieldset");
    const lg = document.createElement("legend");
    lg.textContent = spec.name + (spec.required ? "" : "（任意）");
    fs.append(lg);

    const drop = document.createElement("div");
    drop.className = "drop";
    const row = document.createElement("div");
    row.className = "drop-row";
    const accept = spec.accept.join(",");
    row.append(pickerButton("ファイルを選ぶ", { multiple: spec.multiple, accept }, spec));
    if (spec.multiple) row.append(pickerButton("フォルダを選ぶ", { directory: true }, spec));
    const help = document.createElement("span");
    help.className = "drop-help";
    help.textContent = `${spec.help}（${spec.accept.join(" / ") || "任意の形式"}${spec.multiple ? "、複数可" : ""}）。ここにドラッグ＆ドロップもできます。`;
    row.append(help);
    const list = document.createElement("ul");
    list.className = "filelist";
    list.id = `files-${spec.name}`;
    drop.append(row, list);
    fs.append(drop);
    root.append(fs);

    drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("over"));
    drop.addEventListener("drop", async (e) => {
      e.preventDefault();
      drop.classList.remove("over");
      addFiles(spec, await filesFromDrop(e.dataTransfer), true);
    });
    renderFileList(spec);
  }
}

function pickerButton(label, { multiple, accept, directory }, spec) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "btn";
  b.textContent = label;
  const input = document.createElement("input");
  input.type = "file";
  input.hidden = true;
  if (multiple) input.multiple = true;
  if (accept) input.accept = accept;
  if (directory) input.webkitdirectory = true;
  input.addEventListener("change", () => {
    addFiles(spec, [...input.files], Boolean(directory));
    input.value = "";
  });
  b.addEventListener("click", () => input.click());
  b.append(input);
  return b;
}

// ドロップされたファイル・フォルダを（フォルダは中まで）File の配列にする。
async function filesFromDrop(dt) {
  const entries = [...dt.items].map((it) => it.webkitGetAsEntry && it.webkitGetAsEntry()).filter(Boolean);
  if (!entries.length) return [...dt.files];
  const out = [];
  const walk = async (entry) => {
    if (entry.isFile) out.push(await new Promise((res, rej) => entry.file(res, rej)));
    else if (entry.isDirectory) {
      const reader = entry.createReader();
      let batch;
      do {
        batch = await new Promise((res, rej) => reader.readEntries(res, rej));
        for (const e of batch) await walk(e);
      } while (batch.length);
    }
  };
  for (const e of entries) await walk(e);
  return out;
}

// fromFolder=true のときは、対応する拡張子のファイルだけを拾う（CLI のフォルダ指定と同じ）。
function addFiles(spec, files, fromFolder) {
  let picked = files;
  if (fromFolder) picked = files.filter((f) => accepts(spec, f.name));
  picked.sort((a, b) => (a.webkitRelativePath || a.name).localeCompare(b.webkitRelativePath || b.name, "ja"));
  const cur = spec.multiple ? state.files[spec.name] : [];
  for (const f of spec.multiple ? picked : picked.slice(0, 1)) cur.push({ name: f.name, file: f });
  state.files[spec.name] = cur;
  renderFileList(spec);
  updateRunState();
}

function renderFileList(spec) {
  const list = $(`files-${spec.name}`);
  list.replaceChildren();
  const files = state.files[spec.name];
  files.forEach((f, i) => {
    const li = document.createElement("li");
    const n = document.createElement("span");
    n.className = "fname";
    n.textContent = f.name + (accepts(spec, f.name) ? "" : "（想定外の拡張子）");
    const s = document.createElement("span");
    s.className = "fsize";
    s.textContent = formatSize(f.file.size);
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "linkbtn";
    rm.textContent = "×";
    rm.title = "外す";
    rm.setAttribute("aria-label", `${f.name} を外す`);
    rm.addEventListener("click", () => { files.splice(i, 1); renderFileList(spec); updateRunState(); });
    const right = document.createElement("span");
    right.append(s, rm);
    li.append(n, right);
    list.append(li);
  });
  if (files.length > 1) {
    const li = document.createElement("li");
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "linkbtn";
    clear.textContent = `すべて外す（${files.length} 個）`;
    clear.addEventListener("click", () => { state.files[spec.name] = []; renderFileList(spec); updateRunState(); });
    li.append(clear);
    list.append(li);
  }
}

function formatSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

// ============================================================ パラメータ
function renderParams(tool) {
  const root = $("params");
  root.replaceChildren();
  const basic = tool.params.filter((p) => !p.advanced);
  const advanced = tool.params.filter((p) => p.advanced);
  root.append(...groupsOf(basic));
  if (advanced.length) {
    const d = document.createElement("details");
    d.className = "advanced";
    const s = document.createElement("summary");
    s.textContent = `詳細設定（${advanced.length}）`;
    d.append(s, ...groupsOf(advanced));
    root.append(d);
  }
}

function groupsOf(params) {
  const groups = new Map();
  for (const p of params) {
    if (!groups.has(p.group)) groups.set(p.group, []);
    groups.get(p.group).push(p);
  }
  return [...groups].map(([name, ps]) => {
    const sec = document.createElement("div");
    sec.className = "pgroup";
    if (name) {
      const h = document.createElement("h3");
      h.textContent = name;
      sec.append(h);
    }
    const grid = document.createElement("div");
    grid.className = "pgrid";
    grid.append(...ps.map(field));
    sec.append(grid);
    return sec;
  });
}

function field(p) {
  const wrap = document.createElement("div");
  wrap.className = "field";
  wrap.dataset.param = p.name;
  const id = `p-${p.name}`;
  const label = document.createElement("label");
  label.htmlFor = id;
  label.textContent = p.label;
  if (p.unit) {
    const u = document.createElement("span");
    u.className = "unit";
    u.textContent = ` [${p.unit}]`;
    label.append(u);
  }
  if (p.label !== p.name) {
    const n = document.createElement("span");
    n.className = "pname";
    n.textContent = p.name;
    n.title = "CLI・パラメータJSONでの名前";
    label.append(n);
  }
  const help = document.createElement("div");
  help.className = "help";
  help.textContent = p.help + (p.default === null && p.type !== "bool" ? "（空欄なら使わない）" : "");

  let control;
  if (p.type === "bool") {
    wrap.classList.add("check");
    control = document.createElement("input");
    control.type = "checkbox";
    control.checked = Boolean(p.default);
    control.id = id;
    wrap.append(control, label, help);
    return wrap;
  }
  if (p.type === "choice") {
    control = document.createElement("select");
    for (const c of p.choices) control.append(new Option(c, c, false, c === p.default));
  } else if (p.type === "range") {
    control = document.createElement("div");
    control.className = "range";
    const [lo, hi] = p.default || [null, null];
    const a = numberInput(null, lo, "下限");
    const b = numberInput(null, hi, "上限");
    a.id = id;
    const sep = document.createElement("span");
    sep.textContent = "〜";
    control.append(a, sep, b);
  } else if (p.type === "json") {
    control = document.createElement("textarea");
    control.value = p.default === null ? "" : JSON.stringify(p.default, null, 1);
    control.placeholder = "JSON";
    control.spellcheck = false;
  } else if (p.type === "int" || p.type === "float") {
    control = numberInput(p, p.default, p.default === null ? "未指定" : "");
  } else {
    control = document.createElement("input");
    control.type = "text";
    control.value = p.default ?? "";
  }
  if (!control.id) control.id = id;
  wrap.append(label, control, help);
  return wrap;
}

function numberInput(p, value, placeholder) {
  const el = document.createElement("input");
  el.type = "number";
  el.step = p && p.type === "int" ? "1" : "any";
  if (p && p.min !== null) el.min = p.min;
  if (p && p.max !== null) el.max = p.max;
  if (value !== null && value !== undefined) el.value = value;
  el.placeholder = placeholder || "";
  return el;
}

// フォームの値を集める。空欄は送らない（Python 側で既定値になる）。
function collectParams(tool) {
  if (state.panel) return state.panel.getParams();
  const out = {};
  const errors = [];
  for (const p of tool.params) {
    const wrap = document.querySelector(`.field[data-param="${CSS.escape(p.name)}"]`);
    wrap.classList.remove("invalid");
    if (p.type === "bool") out[p.name] = wrap.querySelector("input").checked;
    else if (p.type === "range") {
      const [a, b] = wrap.querySelectorAll("input");
      if (a.value !== "" || b.value !== "") out[p.name] = [a.value === "" ? null : Number(a.value), b.value === "" ? null : Number(b.value)];
    } else if (p.type === "json") {
      const v = wrap.querySelector("textarea").value.trim();
      if (v) {
        try { out[p.name] = JSON.parse(v); } catch { errors.push(`${p.name}: JSON として読めません`); wrap.classList.add("invalid"); }
      }
    } else {
      const el = wrap.querySelector("input, select");
      if (el.value === "") continue;
      if (el.type === "number" && !el.checkValidity()) { errors.push(`${p.name}: ${el.validationMessage}`); wrap.classList.add("invalid"); continue; }
      out[p.name] = el.type === "number" ? Number(el.value) : el.value;
    }
  }
  if (errors.length) throw new Error(errors.join("\n"));
  return out;
}

// ============================================================ 実行
function missingInputs() {
  const t = state.tool;
  return t ? t.inputs.filter((i) => i.required && !state.files[i.name].length).map((i) => i.name) : [];
}

function updateRunState() {
  const btn = $("run");
  const missing = missingInputs();
  let hint = "";
  if (state.running) hint = "実行中…";
  else if (missing.length) hint = `入力 ${missing.join("、")} を選んでください`;
  else if (!state.engineReady) hint = "Python の準備ができたら実行できます";
  btn.disabled = state.running || missing.length > 0 || !state.engineReady;
  $("run-hint").textContent = hint;
}

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const tool = state.tool;
  let params;
  try {
    params = collectParams(tool);
  } catch (err) {
    showResult({ ok: false, kind: "input", error: err.message });
    return;
  }
  state.running = true;
  updateRunState();
  const files = [];
  const transfer = [];
  for (const [input, list] of Object.entries(state.files)) {
    for (const f of list) {
      const data = new Uint8Array(await f.file.arrayBuffer());
      files.push({ input, name: f.name, data });
      transfer.push(data.buffer);
    }
  }
  state.runId += 1;
  worker.postMessage({
    type: "run", id: state.runId, tool: tool.name, files, params,
    tzOffset: -new Date().getTimezoneOffset(),
  }, transfer);
});

function onResult(m) {
  if (m.id !== state.runId) return;
  state.running = false;
  setEngine(state.engineReady ? "ready" : "error", state.engineReady ? "準備完了" : "エラー");
  updateRunState();
  showResult(m.summary, m.zip);
}

function showResult(summary, zip) {
  $("result").hidden = false;
  const msgs = $("messages");
  msgs.replaceChildren();
  $("previews").replaceChildren();
  $("files").replaceChildren();
  const dl = $("download");
  dl.hidden = true;
  if (state.zipUrl) URL.revokeObjectURL(state.zipUrl);
  state.zipUrl = null;

  const msg = (cls, text) => {
    const d = document.createElement("div");
    d.className = `msg ${cls}`;
    d.textContent = text;
    msgs.append(d);
  };
  if (!summary.ok) {
    msg("err", (summary.kind === "input" ? "入力を確認してください: " : "処理中にエラーが起きました: ") + summary.error);
    if (summary.traceback) console.error(summary.traceback);
    $("result").scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  for (const w of summary.warnings) msg("warn", "警告: " + w);
  if (summary.logs.length) msg("log", summary.logs.join("\n"));

  const blob = new Blob([zip], { type: "application/zip" });
  state.zipUrl = URL.createObjectURL(blob);
  dl.hidden = false;
  dl.onclick = () => {
    const a = document.createElement("a");
    a.href = state.zipUrl;
    a.download = summary.zip_name;
    a.click();
  };
  dl.textContent = `zip をダウンロード（${summary.files.length} ファイル）`;

  for (const f of summary.files) {
    const li = document.createElement("li");
    li.textContent = f;
    $("files").append(li);
  }
  for (const pv of summary.previews) {
    const sec = document.createElement("div");
    sec.className = "preview";
    const h = document.createElement("h3");
    h.textContent = pv.name;
    sec.append(h);
    $("previews").append(sec);
    renderFigure(sec, pv.spec, pv.name);
  }
  $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}
