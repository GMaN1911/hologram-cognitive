"""Enable `python -m hologram …` as a PATH-independent entry point.

If the `hologram` console script isn't on PATH (common right after a
`pip install --user` before the shell PATH is refreshed), every command
still works via `python -m hologram <args>`.
"""
from hologram.cli import main

if __name__ == "__main__":
    main()
