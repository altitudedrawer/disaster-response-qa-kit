"""Pull public function signatures + docstrings out of a module WITHOUT importing it
(uses `ast`, so no side effects), and fill them into the prompt template.

    python experiments/llm_tests/extract_signatures.py src/pipeline/clean.py > prompt_clean.txt
    python experiments/llm_tests/extract_signatures.py src/pipeline/geo.py --functions geodesic_buffer

The LLM sees ONLY signatures and docstrings, not function bodies, on purpose: we want to
know whether the docs alone describe the behaviour well enough to test it.
"""
import argparse
import ast
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "prompt_template.md"


def extract(path: Path, only: set[str] | None = None) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    chunks = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.ClassDef)) or node.name.startswith("_"):
            continue
        if only and node.name not in only:
            continue
        doc = ast.get_docstring(node) or "(no docstring)"
        if isinstance(node, ast.FunctionDef):
            ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            header = f"def {node.name}({ast.unparse(node.args)}){ret}:"
        else:
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            header = f"class {node.name}({bases}):" if bases else f"class {node.name}:"
        body = "\n".join("    " + line if line else "" for line in doc.splitlines())
        # for (data)classes, show annotated fields so the LLM doesn't have to guess attributes
        fields = ([f"    {ast.unparse(n)}" for n in node.body if isinstance(n, ast.AnnAssign)]
                  if isinstance(node, ast.ClassDef) else [])
        tail = "\n".join(fields) if fields else "    ..."
        chunks.append(f'{header}\n    """\n{body}\n    """\n{tail}')
    if not chunks:
        raise SystemExit(f"no public functions found in {path}" + (f" matching {sorted(only)}" if only else ""))
    return "\n\n\n".join(chunks)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("module", help="path to a .py file, e.g. src/pipeline/clean.py")
    p.add_argument("--functions", nargs="*", help="only these names")
    a = p.parse_args(argv)
    path = Path(a.module)
    module_name = ".".join(path.with_suffix("").parts[1:]) if path.parts[0] == "src" else path.stem
    filled = TEMPLATE.read_text(encoding="utf-8").replace("{module_name}", module_name)
    filled = filled.replace("{signatures}", extract(path, set(a.functions) if a.functions else None))
    print(filled)


if __name__ == "__main__":
    main()
