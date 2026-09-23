// Pyodide を動かす Web Worker（module worker）。UI スレッドでは Python を実行しない。
//
// app.js とのやりとり（postMessage）:
//   → {type: "prepare", tool}                        ツールの追加パッケージを読み込む
//   → {type: "run", id, tool, files, params, tzOffset} ツールを実行する
//   ← {type: "status", stage, message}                読み込みの進み具合
//   ← {type: "ready", pyodideVersion}                 Pyodide と saji の準備完了
//   ← {type: "prepared", tool}
//   ← {type: "result", id, summary, zip}              summary は Python が返した JSON
//   ← {type: "error", id?, message}
//
// ここにはツールごとの知識を置かない。処理はすべて Python（saji.web）が行う。

let pyodide = null;
let sajiWeb = null;
let version = null;
let tools = null;          // tools.json（ツール名 → 定義）。読み込むパッケージはここから決める
const loaded = new Set();
const ready = init();

function status(stage, message) {
  postMessage({ type: "status", stage, message });
}

async function init() {
  try {
    status("loading", "設定を読み込み中…");
    version = await (await fetch("dist/version.json", { cache: "no-cache" })).json();
    const list = await (await fetch("dist/tools.json", { cache: "no-cache" })).json();
    tools = Object.fromEntries(list.map((t) => [t.name, t]));
    status("loading", `Python（Pyodide ${version.pyodide_version}）を読み込み中…`);
    const base = `https://cdn.jsdelivr.net/pyodide/v${version.pyodide_version}/full/`;
    const { loadPyodide } = await import(base + "pyodide.mjs");
    pyodide = await loadPyodide({ indexURL: base });
    status("loading", "saji を読み込み中…");
    await unpackWheel(version.saji_wheel);
    sajiWeb = pyodide.pyimport("saji.web");
    postMessage({ type: "ready", pyodideVersion: pyodide.version });
  } catch (err) {
    postMessage({ type: "error", message: `読み込みに失敗しました: ${err}` });
    throw err;
  }
}

async function unpackWheel(path) {
  const buf = await (await fetch("dist/" + path)).arrayBuffer();
  const site = pyodide.runPython("import site; site.getsitepackages()[0]");
  pyodide.unpackArchive(buf, "wheel", { extractDir: site });
}

async function preparePackages(tool) {
  const names = tools[tool].packages;
  const vendored = version.vendored_wheels || {};
  const fromPyodide = names.filter((n) => !(n in vendored) && !loaded.has(n));
  if (fromPyodide.length) {
    status("packages", `パッケージを読み込み中: ${fromPyodide.join(", ")}`);
    await pyodide.loadPackage(fromPyodide);
    fromPyodide.forEach((n) => loaded.add(n));
  }
  for (const n of names.filter((n) => n in vendored && !loaded.has(n))) {
    await unpackWheel(vendored[n]);
    loaded.add(n);
  }
}

// 同じツールの準備を二重に走らせない
const preparing = new Map();
function prepare(tool) {
  if (!preparing.has(tool)) preparing.set(tool, ready.then(() => preparePackages(tool)));
  return preparing.get(tool);
}

self.onmessage = async (event) => {
  const msg = event.data;
  try {
    if (msg.type === "prepare") {
      await prepare(msg.tool);
      postMessage({ type: "prepared", tool: msg.tool });
    } else if (msg.type === "run") {
      await prepare(msg.tool);
      status("running", "実行中…");
      const files = pyodide.toPy(msg.files);
      const params = pyodide.toPy(msg.params);
      let text;
      try {
        text = sajiWeb.run_tool(msg.tool, files, params, msg.tzOffset);
      } finally {
        files.destroy();
        params.destroy();
      }
      const summary = JSON.parse(text);
      const zip = summary.ok ? sajiWeb.last_zip() : null;
      postMessage({ type: "result", id: msg.id, summary, zip }, zip ? [zip.buffer] : []);
    }
  } catch (err) {
    postMessage({ type: "error", id: msg.id, message: String(err) });
  }
};
