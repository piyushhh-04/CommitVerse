"""Command-line interface for CommitVerse Core."""

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

from commitverse_core.commit_service import create_commit
from commitverse_core.commits import read_commit
from commitverse_core.checkout import CheckoutError, checkout_commit, switch_branch
from commitverse_core.diff import generate_diff
from commitverse_core.history import (
    format_commit_date,
    format_commit_message,
    walk_history,
)
from commitverse_core.index import read_index
from commitverse_core.merge import MergeError, merge_branch
from commitverse_core.merge_base import is_ancestor
from commitverse_core.objects import read_object, write_object
from commitverse_core.refs import (
    Head,
    ReferenceError,
    create_branch,
    delete_branch,
    current_branch,
    list_branches,
    read_head,
    resolve_branch,
    resolve_head,
)
from commitverse_core.repository import (
    RepositoryError,
    discover_repository,
    initialize_repository,
)
from commitverse_core.staging import add_paths
from commitverse_core.status import RepositoryStatus, display_path, get_status
from commitverse_core.trees import write_tree


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cv",
        description="Initialize, stage, commit, and inspect CommitVerse repositories.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="initialize a repository")
    init_parser.add_argument(
        "path", nargs="?", help="repository path (default: current directory)"
    )
    init_parser.add_argument(
        "--bare", action="store_true", help="initialize without a working tree"
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

    commit_parser = commands.add_parser("commit", help="record the staged snapshot")
    commit_parser.add_argument("-m", "--message", required=True, help="commit message")

    branch_parser = commands.add_parser("branch", help="list or create local branches")
    branch_parser.add_argument("--list", action="store_true", help="list local branches")
    branch_parser.add_argument("-d", "--delete", action="store_true", help="delete a merged branch")
    branch_parser.add_argument("name", nargs="?", help="new local branch name")

    switch_parser = commands.add_parser("switch", help="switch to a local branch")
    switch_parser.add_argument("branch", help="local branch name")
    checkout_parser = commands.add_parser("checkout", help="checkout a branch or full commit ID")
    checkout_parser.add_argument("revision", help="HEAD, local branch, or full commit ID")
    merge_parser = commands.add_parser("merge", help="merge a local branch")
    merge_parser.add_argument("branch", help="local branch name")

    rev_parse_parser = commands.add_parser(
        "rev-parse", help="resolve HEAD, a local branch, or a full commit ID"
    )
    rev_parse_parser.add_argument("revision", help="revision to resolve")

    commands.add_parser("log", help="show commit history from HEAD")
    commands.add_parser("status", help="show staged, unstaged, and untracked changes")
    diff_parser = commands.add_parser("diff", help="show working-tree or staged changes")
    diff_parser.add_argument(
        "--cached",
        action="store_true",
        help="compare the index with HEAD instead of the working tree",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its process exit status."""
    parser = _build_parser()
    arguments = parser.parse_args(argv)

    try:
        if arguments.command == "init":
            repository_path = Path.cwd() if arguments.path is None else arguments.path
            repository = initialize_repository(repository_path, bare=arguments.bare)
            action = "Initialized" if repository.created else "Reinitialized"
            kind = "bare " if repository.bare else ""
            print(f"{action} {kind}CommitVerse repository in {repository.root}")
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

        if arguments.command == "commit":
            repository = discover_repository()
            result = create_commit(repository, arguments.message)
            location = result.branch_name or "detached HEAD"
            root_marker = " (root-commit)" if result.parent_id is None else ""
            subject = arguments.message.partition("\n")[0]
            print(f"[{location}{root_marker} {result.object_id}] {subject}")
            print(f"{result.path_count} staged path(s) committed")
            return 0

        if arguments.command == "branch":
            repository = discover_repository()
            if arguments.name is not None:
                if arguments.list and not arguments.delete:
                    raise ReferenceError("cv branch --list does not accept a branch name")
                if arguments.delete:
                    current = resolve_head(repository)
                    if current is None:
                        raise ReferenceError("cannot delete a branch before the first commit")
                    target = resolve_branch(repository, arguments.name)
                    if not is_ancestor(repository, target, current):
                        raise ReferenceError(
                            f"branch {arguments.name!r} is not fully merged into the current branch"
                        )
                    delete_branch(repository, arguments.name)
                    print(f"Deleted branch {arguments.name}")
                    return 0
                object_id = resolve_head(repository)
                if object_id is None:
                    raise ReferenceError("cannot create a branch before the first commit")
                create_branch(repository, arguments.name, object_id)
                print(f"Created branch {arguments.name} at {object_id}")
                return 0
            branches = {
                branch.name: branch.object_id for branch in list_branches(repository)
            }
            current = current_branch(repository)
            if current is not None and current not in branches:
                if resolve_head(repository) is not None:
                    raise ReferenceError(f"HEAD branch {current!r} has no reference")
                branches[current] = ""
            for name in sorted(branches, key=lambda value: value.encode("utf-8")):
                marker = "* " if name == current else "  "
                print(f"{marker}{name}")
            return 0

        if arguments.command == "switch":
            repository = discover_repository()
            object_id = resolve_branch(repository, arguments.branch)
            switch_branch(repository, arguments.branch, object_id)
            print(f"Switched to branch {arguments.branch}")
            return 0

        if arguments.command == "checkout":
            repository = discover_repository()
            revision = arguments.revision
            if revision == "HEAD":
                object_id = resolve_head(repository)
                if object_id is None:
                    raise ReferenceError("HEAD is unborn and does not resolve to a commit")
                head = read_head(repository)
            elif re.fullmatch(r"[0-9a-f]{40}", revision):
                read_commit(repository.objects_dir, revision)
                object_id = revision
                head = None
            else:
                object_id = resolve_branch(repository, revision)
                head = Head(
                    symbolic_ref=f"refs/heads/{revision}"
                )
            checkout_commit(repository, object_id, head=head)
            print(f"Checked out {revision}")
            return 0

        if arguments.command == "merge":
            repository = discover_repository()
            result, object_id = merge_branch(repository, arguments.branch)
            if result == "already-up-to-date":
                print("Already up to date.")
            elif result == "fast-forward":
                print(f"Fast-forwarded to {object_id}")
            else:
                print(f"Merge made by CommitVerse: {object_id}")
            return 0

        if arguments.command == "rev-parse":
            repository = discover_repository()
            revision = arguments.revision
            if revision == "HEAD":
                object_id = resolve_head(repository)
                if object_id is None:
                    raise ReferenceError("HEAD is unborn and does not resolve to a commit")
            elif re.fullmatch(r"[0-9a-f]{40}", revision):
                try:
                    read_commit(repository.objects_dir, revision)
                except (OSError, ValueError) as error:
                    raise ReferenceError(
                        f"commit object {revision} does not exist or is invalid: {error}"
                    ) from error
                object_id = revision
            else:
                object_id = resolve_branch(repository, revision)
            print(object_id)
            return 0

        if arguments.command == "log":
            repository = discover_repository()
            commits = list(walk_history(repository))
            if not commits:
                print("No commits yet.")
                return 0
            for object_id, commit in commits:
                print(f"commit {object_id}")
                if commit.parent_ids:
                    print("Parents: " + " ".join(commit.parent_ids))
                print(f"Author: {commit.author.name} <{commit.author.email}>")
                print(f"Date:   {format_commit_date(commit)}")
                print()
                message = format_commit_message(commit.message)
                lines = message.splitlines()
                if not lines and not message:
                    print("    ")
                else:
                    for line in lines:
                        print(f"    {line}")
                print()
            return 0

        if arguments.command == "status":
            repository = discover_repository()
            status = get_status(repository)
            _print_status(status)
            return 0

        if arguments.command == "diff":
            repository = discover_repository()
            sys.stdout.write(generate_diff(repository, cached=arguments.cached))
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
    except (OSError, RepositoryError, CheckoutError, MergeError, ValueError) as error:
        print(f"cv: error: {error}", file=sys.stderr)
        return 1


def _print_status(status: RepositoryStatus) -> None:
    """Write a deterministic human-readable summary of repository status."""
    if status.branch_name is not None:
        print(f"On branch {status.branch_name}")
    elif status.head_id is not None:
        print(f"HEAD detached at {status.head_id[:12]}")
    else:
        print("HEAD detached (unborn)")

    if status.unborn:
        print("No commits yet.")

    if status.staged:
        print("\nChanges to be committed:")
        for change in status.staged:
            print(f"  {change.kind + ':':<9}   {display_path(change.path)}")

    if status.unstaged:
        print("\nChanges not staged for commit:")
        for change in status.unstaged:
            print(f"  {change.kind + ':':<9}   {display_path(change.path)}")

    if status.untracked:
        print("\nUntracked files:")
        for path in status.untracked:
            print(f"  {display_path(path)}")

    if status.clean:
        print("nothing to commit, working tree clean")
