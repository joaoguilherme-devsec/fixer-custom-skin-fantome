import argparse
import sys

from . import __version__, batch, gamepath
from .fixer import GameData


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="FantomeFixer",
        description="Analisa e corrige skins customizadas (.fantome) para o patch atual do League of Legends.")
    p.add_argument("command", choices=["analyze", "fix"], help="analyze = só verifica; fix = corrige")
    p.add_argument("paths", nargs="+", help="arquivos .fantome e/ou pastas contendo .fantome")
    p.add_argument("--game", help="pasta do jogo (ex.: \"C:\\Riot Games\\League of Legends\\Game\"); detectada automaticamente se omitida")
    p.add_argument("--out", help="pasta de saída (padrão: subpasta 'Corrigidas' ao lado de cada arquivo)")
    p.add_argument("--in-place", action="store_true", help="substitui o arquivo original (o original é salvo como .bak)")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    args = p.parse_args(argv)

    game_dir = gamepath.normalize(args.game) if args.game else gamepath.detect()
    if not game_dir:
        print("Pasta do League of Legends não encontrada. Informe com --game.", file=sys.stderr)
        return 2
    files = batch.expand_inputs(args.paths)
    if not files:
        print("Nenhum arquivo .fantome encontrado.", file=sys.stderr)
        return 2
    print("Jogo: %s" % game_dir)
    game = GameData(game_dir)
    mode = "analyze" if args.command == "analyze" else ("inplace" if args.in_place else "fix")
    reports = batch.run(files, game, mode, out_dir=args.out)
    return 1 if any(r.error for r in reports) else 0
