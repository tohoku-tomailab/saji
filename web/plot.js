// 図の JSON（Python が組み立てた Plotly 形式）を Plotly.js で描く汎用の描画器。
// 手法の知識は持たない。図の中身はすべて Python（saji.techniques）が決める。
//
// 主な使い方は「描いて、少しいじって、スクショしてスライドに貼る」なので、
// 凡例と注釈は図の上で直接編集・移動できるようにしてある。

// 図のタイトルと軸名は編集対象にしない（空欄に「Click to enter …」が出てスクショに写るため）。
// 軸名や題はツールのパラメータ（xlabel / title など）で変える。
const EDITS = {
  legendText: true,
  legendPosition: true,
  annotationText: true,
  annotationPosition: true,
  annotationTail: true,
};

function config(name) {
  return {
    displaylogo: false,
    responsive: false,
    edits: EDITS,
    modeBarButtonsToRemove: ["select2d", "lasso2d"],
    toImageButtonOptions: { format: "png", filename: name, scale: 2 },
  };
}

function clone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

// container の中に図と操作ボタンを作る。
export function renderFigure(container, spec, name) {
  const box = document.createElement("div");
  box.className = "plotbox";
  const div = document.createElement("div");
  box.append(div);

  const actions = document.createElement("div");
  actions.className = "plot-actions";
  const mk = (label, onClick) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn";
    b.textContent = label;
    b.addEventListener("click", onClick);
    actions.append(b);
  };
  mk("PNG で保存", () => Plotly.downloadImage(div, { format: "png", filename: name, scale: 2 }));
  mk("SVG で保存", () => Plotly.downloadImage(div, { format: "svg", filename: name }));
  mk("元に戻す", () => Plotly.react(div, clone(spec.data), clone(spec.layout), config(name)));

  container.append(box, actions);
  Plotly.newPlot(div, clone(spec.data), clone(spec.layout), config(name));
  return div;
}
