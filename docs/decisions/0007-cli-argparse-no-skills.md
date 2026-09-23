# 0007 CLI は argparse で生成し、AgentSkill は移植しない

- 日付: 2026-09-23

## 決定
- CLI は標準ライブラリの argparse で TOOL 定義から生成する。Typer はデコレータで書く前提で、
  定義から動的に組み立てるのに向かない（依存も1つ減る）。
- kaiseki-tool の `.claude/skills/`（ツールごとの AgentSkill）は移植しない。AGENTS.md と
  `saji list` / `saji <tool> --help` で足りる。スキルは Claude Code 専用で、ツール定義と二重管理になる。
- kaiseki-tool の `config list/init`（設定 JSON の雛形）は、`--params` と manifest.json の再利用で置き換える。
