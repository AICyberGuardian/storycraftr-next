import os
import click
from storycraftr.utils.core import load_book_config
from storycraftr.agent.story.chapters import (
    generate_chapter,
    generate_cover,
    generate_back_cover,
    generate_epilogue,
)
from rich.console import Console

console = Console()


@click.group()
def chapters():
    """
    Manage chapters of the book.

    This command group provides functionality to generate chapters, covers,
    and the epilogue of the book by interacting with the storycraftr agent.
    """
    pass


@chapters.command()
@click.argument("chapter_number", type=int)
@click.argument("prompt", type=str)
@click.option("--book-path", type=click.Path(), help="Path to the book directory")
@click.option(
    "--unsafe-direct-write",
    is_flag=True,
    default=False,
    help=(
        "Allow legacy direct chapter markdown writes that bypass book runtime "
        "validators. Prefer 'storycraftr book'."
    ),
)
def chapter(
    chapter_number: int,
    prompt: str,
    book_path: str = None,
    unsafe_direct_write: bool = False,
):
    """
    Generate a new chapter for the book.

    Args:
        chapter_number (int): The number of the chapter to generate.
        prompt (str): The prompt to guide the generation of the chapter.
        book_path (str, optional): The path to the book's directory. Defaults to the current working directory.
    """
    book_path = book_path or os.getcwd()

    allow_unsafe = os.getenv("STORYCRAFTR_ALLOW_UNSAFE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if not unsafe_direct_write:
        raise click.ClickException(
            "Direct chapter generation is disabled by default because it bypasses "
            "validator-gated runtime checks. Use 'storycraftr book' or pass "
            "--unsafe-direct-write explicitly."
        )

    if not allow_unsafe:
        raise click.ClickException(
            "Unsafe direct chapter writes are disabled. Set "
            "STORYCRAFTR_ALLOW_UNSAFE=1 for developer-only bypass usage."
        )

    # Load book configuration and proceed only if successful
    if not load_book_config(book_path):
        console.print("[red bold]Error:[/red bold] Failed to load book configuration.")
        return

    generate_chapter(book_path, chapter_number, prompt)


@chapters.command()
@click.argument("prompt", type=str)
@click.option("--book-path", type=click.Path(), help="Path to the book directory")
def cover(prompt: str, book_path: str = None):
    """
    Generate the cover of the book.

    Args:
        prompt (str): The prompt to guide the generation of the cover.
        book_path (str, optional): The path to the book's directory. Defaults to the current working directory.
    """
    book_path = book_path or os.getcwd()

    # Load book configuration and proceed only if successful
    if not load_book_config(book_path):
        console.print("[red bold]Error:[/red bold] Failed to load book configuration.")
        return

    generate_cover(book_path, prompt)


@chapters.command()
@click.argument("prompt", type=str)
@click.option("--book-path", type=click.Path(), help="Path to the book directory")
def back_cover(prompt: str, book_path: str = None):
    """
    Generate the back cover of the book.

    Args:
        prompt (str): The prompt to guide the generation of the back cover.
        book_path (str, optional): The path to the book's directory. Defaults to the current working directory.
    """
    book_path = book_path or os.getcwd()

    # Load book configuration and proceed only if successful
    if not load_book_config(book_path):
        console.print("[red bold]Error:[/red bold] Failed to load book configuration.")
        return

    generate_back_cover(book_path, prompt)


@chapters.command()
@click.argument("prompt", type=str)
@click.option("--book-path", type=click.Path(), help="Path to the book directory")
def epilogue(prompt: str, book_path: str = None):
    """
    Generate the epilogue of the book.

    Args:
        prompt (str): The prompt to guide the generation of the epilogue.
        book_path (str, optional): The path to the book's directory. Defaults to the current working directory.
    """
    book_path = book_path or os.getcwd()

    # Load book configuration and proceed only if successful
    if not load_book_config(book_path):
        console.print("[red bold]Error:[/red bold] Failed to load book configuration.")
        return

    generate_epilogue(book_path, prompt)
