# Run Bugline on your own repo

Back to the [README](../README.md).

`bugline.toml` at the repo root names the project the agents work on. The expense splitter is the
shipped value. The front desk, the coders and `scripts/bootstrap.py` all read it, and
`agents/common/project.py` checks it at start and names any bad key. To point Bugline at your app:

1. Copy `bugline.toml` and change `[project]`: the repo URL and branch, the folder each coder
   clones it into, where the app sits in the clone, the test command, the scratch folder the
   reproducer may write to, the files neither coder may edit, and the user guide the front desk
   answers from (a file on this machine, relative to the TOML file).
2. Change `[report]`: the fields a complete bug report needs. The front desk asks for a missing
   field by its `label` and lists it on the ticket under its `heading`. `title` must stay.
3. Change `[tickets] prefix` (1 to 5 capital letters) and the room and agent names if you want.
4. Point `BUGLINE_CONFIG` at your file in every shell that runs an agent or a script. It is read
   from the shell, not from the agents' `.env` files.
5. Clone your repo into each coder's working directory as `<CODER_WORKDIR>\<clone_dir>`, then run
   `scripts/bootstrap.py`. It fills the room instructions and documents with your names and
   passes your repo URL to the room template.

```powershell
$env:BUGLINE_CONFIG = "C:\path\to\my-app.toml"
python scripts\bootstrap.py --dry-run
```

```bash
export BUGLINE_CONFIG=~/my-app.toml
python scripts/bootstrap.py --dry-run
```

What still assumes the demo:

- Nothing in the code assumes Python: the test command is a shell line.
- `switch/docs/repro-checklist.md` sets up a Python venv and writes the scratch script with
  FastAPI's `TestClient`; `switch/docs/fix-policy.md` names the demo's layout (`app/`, `SCHEMA`,
  `seed.py`) and runs ruff. Edit both for another stack.
- The examples of each kind of message in `switch/docs/intake-rules.md` come from the expense
  splitter. Replace them with your app's.
- The seeded faults, `scripts/reset_demo.py` and the `demo-app` service in `docker-compose.yml`
  are the demo.
- The defaults inside `switch/*.template.yaml` still name the demo, because Switch reads those
  files without `bugline.toml`. Bootstrap passes every value as an input, so they only matter if
  you import a template by hand.
