from pathlib import Path
def write_utf8_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp"); tmp.write_text(content,encoding="utf-8"); tmp.replace(path)
