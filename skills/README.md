# Skills

The portable skill sources live under `skills/shared/`. Plugin development
paths under `plugins/mythosaur-workspace/skills/` are symlinks to those sources.
The package builder copies real files and excludes `tests/`.

Plugin skill:

- `google-workspace-router`: Workspace and NotebookLM tool routing

The router supports an optional local NotebookLM index at
`google-workspace-router/references/notebooks.md`. Copy
`notebooks.md.example` to that filename and keep the copy local; it can contain
personal notebook IDs and routing hints. Live availability is checked with
`notebooklm_list_notebooks` when the match is uncertain or the user asks for
the current list.

Generic `action-triage` and `evidence-briefing` remain owned and distributed by
`mythosaur-tools`. The Workspace router uses them when available and falls back
to direct draft-and-review guidance when this plugin is installed alone.

These sources were seeded from `mythosaur-tools` at commit
`8b89ee4f32ae82852ea19021ca0815657545c245`. Future edits in this repository
must keep trigger and behavior fixtures with the skill.
