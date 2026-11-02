"""Build yaYUL + yaAGC from the pinned virtualagc submodule and assemble a rope.

Modern virtualagc builds via top-level CMake (add_executable(yaYUL ...) / (yaAGC ...) in
yaYUL/CMakeLists.txt and yaAGC/CMakeLists.txt) -- there is no per-directory Makefile to
`make -C` into anymore. This wraps that CMake invocation plus the yaYUL assemble step so
`make agc` (or `python -m luminary_agent.agc.build`) is a single command.

Background for a Python-only reader:
  * yaAGC  -- a C program (the Apollo Guidance Computer *emulator*). It must be compiled.
  * yaYUL  -- a C program (the AGC *assembler*): turns the 1969 assembly source of the flight
              software (`Luminary099/*.agc`) into a binary "rope" file (`MAIN.agc.bin`) that
              yaAGC loads, the way the real AGC had its program woven into core-rope memory.
  * CMake  -- the C build tool: `cmake -S src -B build` configures, `cmake --build` compiles.
  * git submodule -- `external/virtualagc` is a *separate* git repo pinned to one commit inside
              this one. It is not copied into this repo; `git submodule update --init` fetches it.
  * git worktree  -- a second checkout of the same repo in another folder. We patch that copy
              instead of the submodule so the pinned submodule stays pristine.

Pipeline: submodule -> worktree copy -> apply patches/*.patch -> cmake build -> yaYUL
assembles the rope. Outputs: results/cache/agc/build/yaAGC/yaAGC (emulator),
results/cache/agc/build/Luminary099.lst (listing), <worktree>/Luminary099/MAIN.agc.bin (rope).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

# This file is src/luminary_agent/agc/build.py -> parents[3] is the repository root.
REPO_ROOT = Path(__file__).resolve().parents[3]
# The pinned (unmodified) VirtualAGC source, fetched as a git submodule.
VIRTUALAGC = REPO_ROOT / "external" / "virtualagc"
# Where all build output goes. Override with the environment variable LUMINARY_AGC_CACHE
# (e.g. `LUMINARY_AGC_CACHE=/tmp/agc make agc`) to build somewhere else.
AGC_CACHE_ROOT = Path(os.environ.get("LUMINARY_AGC_CACHE", REPO_ROOT / "results" / "cache" / "agc"))
PATCHED_SOURCE_DIR = AGC_CACHE_ROOT / "virtualagc-free-run"  # patched copy of the submodule
BUILD_DIR = AGC_CACHE_ROOT / "build"  # compiled binaries + the assembler listing
PATCHES = REPO_ROOT / "patches"  # *.patch files applied to the copy (emulator only)


def ensure_submodule() -> None:
    """Download the VirtualAGC submodule if a plain `git clone` (without --recursive) left
    `external/virtualagc` empty. Equivalent to running the git command below by hand."""
    subprocess.run(
        ["git", "submodule", "update", "--init", "--recursive", "external/virtualagc"],
        cwd=REPO_ROOT,
        check=True,
    )


def source_dir() -> Path:
    """The source tree to build from: the patched copy if it exists, else the raw submodule."""
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
        # Preferred: a cheap git worktree (shares the submodule's .git objects, no full copy).
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(PATCHED_SOURCE_DIR), "HEAD"],
            cwd=VIRTUALAGC,
            check=True,
        )
    except subprocess.CalledProcessError:
        # git refused (e.g. the worktree is already registered). If the folder is there, use it;
        # otherwise fall back to a plain file copy without build output and git metadata.
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
        # `git apply --reverse --check` succeeds only if the patch could be *un*-applied, i.e. it
        # is already applied. That makes running `make agc` twice safe (idempotent).
        applied = subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=src)
        if applied.returncode == 0:
            continue  # already in the tree
        subprocess.run(["git", "apply", str(patch)], cwd=src, check=True)
        print(f"applied {patch.name}")


def build_binaries() -> None:
    """Compile only the two C programs we need (yaYUL, yaAGC) in Release (optimised) mode.
    Requires `cmake` and a C compiler (Xcode command-line tools on macOS, gcc on Linux)."""
    # Step 1, configure: read CMakeLists.txt in the source tree, write build files to BUILD_DIR.
    subprocess.run(
        ["cmake", "-S", str(source_dir()), "-B", str(BUILD_DIR), "-DCMAKE_BUILD_TYPE=Release"],
        check=True,
    )
    # Step 2, compile.
    subprocess.run(
        ["cmake", "--build", str(BUILD_DIR), "--target", "yaYUL", "yaAGC"],
        check=True,
    )


def listing_path(rope: str = "Luminary099") -> Path:
    """The assembler's text listing: every source line with its memory address. symbols.py reads
    variable addresses from it (e.g. where the AGC stores its altitude estimate)."""
    return BUILD_DIR / f"{rope}.lst"


def assemble(rope: str = "Luminary099", main_file: str = "MAIN.agc") -> Path:
    """Assemble `main_file` in the given rope directory, producing <main_file>.bin.

    The assembler's listing (which contains the full symbol table) is saved next to the
    build, so agc/symbols.py can resolve names to addresses instead of anyone copying them.
    """
    ya_yul = BUILD_DIR / "yaYUL" / "yaYUL"  # the compiled assembler
    rope_dir = source_dir() / rope  # the cache worktree: the submodule tree stays untouched
    result = subprocess.run(
        [str(ya_yul), "--unpound-page", main_file],
        cwd=rope_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    listing_path(rope).write_text(result.stdout)  # yaYUL prints the listing on stdout
    return rope_dir / f"{main_file}.bin"


def rope_bin_path(rope: str = "Luminary099", main_file: str = "MAIN.agc") -> Path:
    """The assembled flight-software binary that yaAGC loads."""
    return source_dir() / rope / f"{main_file}.bin"


def yaagc_path() -> Path:
    """The compiled emulator executable."""
    return BUILD_DIR / "yaAGC" / "yaAGC"


def main() -> None:
    """`make agc` / `luminary agc build` / `python -m luminary_agent.agc.build [--rope R]`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rope", default="Luminary099")
    parser.add_argument("--main-file", default="MAIN.agc")
    args = parser.parse_args()

    # The whole pipeline, in order. Each step is safe to re-run.
    ensure_submodule()
    apply_patches()
    build_binaries()
    bin_path = assemble(args.rope, args.main_file)
    print(f"yaAGC:  {yaagc_path()}")
    print(f"rope:   {bin_path}")


if __name__ == "__main__":
    main()
