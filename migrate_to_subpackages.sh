#!/usr/bin/env bash
set -euo pipefail

PKG="src/codepilot"

if [[ ! -d "$PKG" ]]; then
  echo "Error: $PKG not found. Run this from the project root." >&2
  exit 1
fi
if [[ -d "$PKG/core" ]]; then
  echo "Error: $PKG/core already exists; migration appears to have already run." >&2
  echo "To redo, revert first: git checkout -- src scripts && git clean -fd $PKG" >&2
  exit 1
fi

GROUP_NAMES=(core github explorer agents memory orchestration ui)
GROUP_MODS=(
  "config tokens streaming task"
  "github_client classifier pr_agent gates"
  "workspace repo_map retrieval"
  "coder diffing guardrails test_agent verify_loop skills"
  "memory_working memory_episodic memory_semantic"
  "orchestrator orchestrator_loop pipeline"
  "tui"
)

git_mv() {
  if git ls-files --error-unmatch "$1" >/dev/null 2>&1; then
    git mv "$1" "$2"
  else
    mv "$1" "$2"
  fi
}

echo "==> Moving modules into subpackages"
for i in "${!GROUP_NAMES[@]}"; do
  group="${GROUP_NAMES[$i]}"
  mkdir -p "$PKG/$group"
  touch "$PKG/$group/__init__.py"
  for m in ${GROUP_MODS[$i]}; do
    if [[ -f "$PKG/$m.py" ]]; then
      git_mv "$PKG/$m.py" "$PKG/$group/$m.py"
      echo "   $m.py -> $group/"
    else
      echo "   WARN: $PKG/$m.py not found (skipping)"
    fi
  done
done

echo "==> Rewriting imports"
if sed --version >/dev/null 2>&1; then
  sed_i() { sed -i "$@"; }
else
  sed_i() { sed -i '' "$@"; }
fi

SED_EXPR=()
for i in "${!GROUP_NAMES[@]}"; do
  group="${GROUP_NAMES[$i]}"
  for m in ${GROUP_MODS[$i]}; do
    SED_EXPR+=(-e "s/from codepilot\.${m} /from codepilot.${group}.${m} /g")
    SED_EXPR+=(-e "s/from codepilot\.${m}\$/from codepilot.${group}.${m}/g")
    SED_EXPR+=(-e "s/import codepilot\.${m}\$/import codepilot.${group}.${m}/g")
    SED_EXPR+=(-e "s/import codepilot\.${m} /import codepilot.${group}.${m} /g")
  done
done

while IFS= read -r -d '' file; do
  sed_i "${SED_EXPR[@]}" "$file"
done < <(find "$PKG" scripts -name "*.py" -print0)

echo "==> Verifying imports"
if PYTHONPATH=src python3 - <<'PYEOF'
import importlib
groups = {
    "core": ["config","tokens","streaming","task"],
    "github": ["github_client","classifier","pr_agent","gates"],
    "explorer": ["workspace","repo_map","retrieval"],
    "agents": ["coder","diffing","guardrails","test_agent","verify_loop","skills"],
    "memory": ["memory_working","memory_episodic","memory_semantic"],
    "orchestration": ["orchestrator","orchestrator_loop","pipeline"],
    "ui": ["tui"],
}
failed = []
for g, mods in groups.items():
    for m in mods:
        try:
            importlib.import_module(f"codepilot.{g}.{m}")
        except Exception as e:
            failed.append((f"codepilot.{g}.{m}", repr(e)))
if failed:
    print("FAILED imports:")
    for n, e in failed:
        print(f"  {n}: {e}")
    raise SystemExit(1)
print(f"OK: all {sum(len(v) for v in groups.values())} modules import cleanly.")
PYEOF
then
  echo ""
  echo "Migration complete. Next:"
  echo "  uv run python scripts/smoke_test.py"
else
  echo "Import verification FAILED. Undo with:" >&2
  echo "  git checkout -- src scripts && git clean -fd $PKG" >&2
  exit 1
fi