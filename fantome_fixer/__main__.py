"""Entry point.

With a console (python -m fantome_fixer / FantomeFixer-cli.exe) arguments run
the command line. In the windowed build (FantomeFixer.exe) arguments are the
files dropped on the icon, which are preloaded into the GUI.
"""
import os
import sys


def main():
    args = sys.argv[1:]
    if args and sys.stdout is not None:
        from .cli import main as cli_main
        sys.exit(cli_main(args))
    from .gui import main as gui_main
    gui_main([a for a in args if os.path.exists(a)])


if __name__ == "__main__":
    main()
