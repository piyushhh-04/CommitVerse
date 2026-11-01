"""Command-line interface for CommitVerse Core."""

import argparse
import sys
from pathlib import Path
from typing import Sequence

from commitverse_core.index import read_index
from commitverse_core.objects import read_object, write_object
from commitverse_core.repository import (
    RepositoryError,
    discover_repository,
    initialize_repository,
)
from commitverse_core.staging import add_paths
from commitverse_core.trees import write_tree


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cv",
        description="Initialize repositories, stage files, and inspect Git-compatible objects.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="initialize a repository")
    init_parser.add_argument(
        "path", nargs="?", help="repository path (default: current directory)"
    )

    hash_parser = commands.add_parser("hash-object", help="write a blob object")
    hash_parser.add_argument(
        "-w", action="store_true", required=True, help="write the object"
    )
    hash_parser.add_argument("file", help="file whose bytes will be stored")

    cat_parser = commands.add_parser("cat-file", help="inspect a stored object")
    cat_format = cat_parser.add_mutually_exclusive_group(required=True)
    cat_format.add_argument("-t", action="store_true", help="print the object type")
    cat_format.add_argument("-s", action="store_true", help="print the payload size")
    cat_format.add_argument("-p", action="store_true", help="write the payload bytes")
    cat_parser.add_argument("object_id", help="40-character lowercase SHA-1 object ID")

    add_parser = commands.add_parser("add", help="stage working-tree files")
    add_parser.add_argument(
        "-A",
        "--all",
        action="store_true",
        help="stage additions, modifications, and deletions",
    )
    add_parser.add_argument("paths", nargs="*", help="file or directory paths to stage")

    commands.add_parser("write-tree", help="write a tree from the current index")
    commands.add_parser("ls-files", help="list staged paths")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its process exit status."""
    parser = _build_parser()
    arguments = parser.parse_args(argv)

    try:
        if arguments.command == "init":
            repository_path = Path.cwd() if arguments.path is None else arguments.path
            repository = initialize_repository(repository_path)
            action = "Initialized" if repository.created else "Reinitialized"
            print(f"{action} CommitVerse repository in {repository.root}")
            return 0

        if arguments.command == "hash-object":
            repository = discover_repository()
            payload = Path(arguments.file).expanduser().read_bytes()
            print(write_object(repository.objects_dir, "blob", payload))
            return 0

        if arguments.command == "add":
            repository = discover_repository()
            add_paths(
                repository,
                arguments.paths,
                all=arguments.all,
            )
            return 0

        if arguments.command == "write-tree":
            repository = discover_repository()
            index = read_index(repository.git_dir / "index")
            print(write_tree(repository.objects_dir, index.entries))
            return 0

        if arguments.command == "ls-files":
            repository = discover_repository()
            index = read_index(repository.git_dir / "index")
            seen: set[bytes] = set()
            for entry in index.entries:
                if entry.path not in seen:
                    sys.stdout.buffer.write(entry.path + b"\n")
                    seen.add(entry.path)
            sys.stdout.buffer.flush()
            return 0

        repository = discover_repository()
        object_type, payload = read_object(repository.objects_dir, arguments.object_id)
        if arguments.t:
            print(object_type)
        elif arguments.s:
            print(len(payload))
        else:
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()
        return 0
    except (OSError, RepositoryError, ValueError) as error:
        print(f"cv: error: {error}", file=sys.stderr)
        return 1
