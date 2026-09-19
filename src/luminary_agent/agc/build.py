"""Build yaYUL + yaAGC from the pinned virtualagc submodule and assemble a rope.

Modern virtualagc builds via top-level CMake (add_executable(yaYUL ...) / (yaAGC ...) in
yaYUL/CMakeLists.txt and yaAGC/CMakeLists.txt) -- there is no per-directory Makefile to
`make -C` into anymore. This wraps that CMake invocation plus the yaYUL assemble step so
`make agc` (or `python -m luminary_agent.agc.build`) is a single command.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VIRTUALAGC = REPO_ROOT / "external" / "virtualagc"
BUILD_DIR = VIRTUALAGC / "build"


def ensure_submodule() -> None:
    subprocess.run(
        ["git", "submodule", "update", "--init", "--recursive", "external/virtualagc"],
        cwd=REPO_ROOT,
        check=True,
    )


def build_binaries() -> None:
    subprocess.run(
        ["cmake", "-S", str(VIRTUALAGC), "-B", str(BUILD_DIR), "-DCMAKE_BUILD_TYPE=Release"],
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
    rope_dir = VIRTUALAGC / rope
    result = subprocess.run(
        [str(ya_yul), "--unpound-page", main_file],
        cwd=rope_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    listing_path(rope).write_text(result.stdout)
    return rope_dir / f"{main_file}.bin"


def yaagc_path() -> Path:
    return BUILD_DIR / "yaAGC" / "yaAGC"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rope", default="Luminary099")
    parser.add_argument("--main-file", default="MAIN.agc")
    args = parser.parse_args()

    ensure_submodule()
    build_binaries()
    bin_path = assemble(args.rope, args.main_file)
    print(f"yaAGC:  {yaagc_path()}")
    print(f"rope:   {bin_path}")


if __name__ == "__main__":
    main()
