"""Build yaYUL + yaAGC from the pinned virtualagc submodule and assemble a rope.

Modern virtualagc builds via top-level CMake (add_executable(yaYUL ...) / (yaAGC ...) in
yaYUL/CMakeLists.txt and yaAGC/CMakeLists.txt) -- there is no per-directory Makefile to
`make -C` into anymore. This wraps that CMake invocation plus the yaYUL assemble step so
`make agc` (or `python -m luminary_agent.agc.build`) is a single command.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VIRTUALAGC = REPO_ROOT / "external" / "virtualagc"
AGC_CACHE_ROOT = Path(os.environ.get("LUMINARY_AGC_CACHE", REPO_ROOT / "results" / "cache" / "agc"))
PATCHED_SOURCE_DIR = AGC_CACHE_ROOT / "virtualagc-free-run"
BUILD_DIR = AGC_CACHE_ROOT / "build"
PATCHES = REPO_ROOT / "patches"


def ensure_submodule() -> None:
    subprocess.run(
        ["git", "submodule", "update", "--init", "--recursive", "external/virtualagc"],
        cwd=REPO_ROOT,
        check=True,
    )


def source_dir() -> Path:
    return PATCHED_SOURCE_DIR if PATCHED_SOURCE_DIR.exists() else VIRTUALAGC


def ensure_patch_worktree() -> Path:
    """Create/update a detached VirtualAGC worktree for host-side yaAGC patches.

    This keeps the submodule pin immutable for future builds. If the cache cannot be created, the
    caller can still hash the dirty submodule diff in provenance; this function does not delete or
    reset user edits.
    """
    if PATCHED_SOURCE_DIR.exists():
        return PATCHED_SOURCE_DIR
    PATCHED_SOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(PATCHED_SOURCE_DIR), "HEAD"],
            cwd=VIRTUALAGC,
            check=True,
        )
    except subprocess.CalledProcessError:
        if PATCHED_SOURCE_DIR.exists():
            return PATCHED_SOURCE_DIR
        shutil.copytree(
            VIRTUALAGC,
            PATCHED_SOURCE_DIR,
            ignore=shutil.ignore_patterns("build", ".git"),
        )
    return PATCHED_SOURCE_DIR


def apply_patches() -> None:
    """Apply this repo's patches to a build-cache worktree (idempotent).

    The pinned submodule is not edited by this build path; the changes live in
    `patches/*.patch` and are applied here so a clean clone builds the same emulator. Only the
    *emulator* is patched -- the flight software is untouched, which is the claim that matters.
    `patches/yaagc-free-run.patch` adds `--free-run`: without it every debugger command costs
    ~11 ms (a 10 ms sleep in the command reader) and the engine refuses to run faster than real
    time, which together capped a descent at ~0.6x real time. With it: 0.5 ms per command and
    ~30x real time at the step size the simulation uses.
    """
    src = ensure_patch_worktree()
    for patch in sorted(PATCHES.glob("*.patch")):
        applied = subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=src)
        if applied.returncode == 0:
            continue  # already in the tree
        subprocess.run(["git", "apply", str(patch)], cwd=src, check=True)
        print(f"applied {patch.name}")


def build_binaries() -> None:
    subprocess.run(
        ["cmake", "-S", str(source_dir()), "-B", str(BUILD_DIR), "-DCMAKE_BUILD_TYPE=Release"],
        check=True,
    )
    subprocess.run(
        ["cmake", "--build", str(BUILD_DIR), "--target", "yaYUL", "yaAGC"],
        check=True,
    )


def listing_path(rope: str = "Luminary099") -> Path:
    return BUILD_DIR / f"{rope}.lst"


def assemble(rope: str = "Luminary099", main_file: str = "MAIN.agc") -> Path:
    """Assemble `main_file` in the given rope directory, producing <main_file>.bin.

    The assembler's listing (which contains the full symbol table) is saved next to the
    build, so agc/symbols.py can resolve names to addresses instead of anyone copying them.
    """
    ya_yul = BUILD_DIR / "yaYUL" / "yaYUL"
    rope_dir = source_dir() / rope  # the cache worktree: the submodule tree stays untouched
    result = subprocess.run(
        [str(ya_yul), "--unpound-page", main_file],
        cwd=rope_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    listing_path(rope).write_text(result.stdout)
    return rope_dir / f"{main_file}.bin"


def rope_bin_path(rope: str = "Luminary099", main_file: str = "MAIN.agc") -> Path:
    return source_dir() / rope / f"{main_file}.bin"


def yaagc_path() -> Path:
    return BUILD_DIR / "yaAGC" / "yaAGC"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rope", default="Luminary099")
    parser.add_argument("--main-file", default="MAIN.agc")
    args = parser.parse_args()

    ensure_submodule()
    apply_patches()
    build_binaries()
    bin_path = assemble(args.rope, args.main_file)
    print(f"yaAGC:  {yaagc_path()}")
    print(f"rope:   {bin_path}")


if __name__ == "__main__":
    main()
