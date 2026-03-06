from __future__ import annotations

import shutil

from rich.console import Console

from storycraftr.utils.core import load_book_config
from storycraftr.utils.paths import resolve_project_paths
from storycraftr.utils.project_lock import project_write_lock

console = Console()


def cleanup_vector_stores(book_path: str) -> None:
    """
    Remove the embedded Chroma vector store for the given project path.
    """

    config = load_book_config(book_path)
    vector_dir = resolve_project_paths(book_path, config=config).vector_store_root
    with project_write_lock(book_path, config=config):
        if vector_dir.exists():
            shutil.rmtree(vector_dir, ignore_errors=True)
            console.print(
                f"[green]Local vector store removed from {vector_dir}[/green]"
            )
        else:
            console.print(f"[yellow]No vector store found at {vector_dir}[/yellow]")
