"""Shared batch driver used by both the CLI and the GUI."""
import glob
import os

from . import fixer

DEFAULT_OUT_DIRNAME = "Corrigidas"


def expand_inputs(paths):
    """Files are kept as given; folders contribute their *.fantome files."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            out.extend(sorted(glob.glob(os.path.join(p, "*.fantome"))))
        else:
            out.append(p)
    seen = set()
    return [p for p in out if not (os.path.normcase(os.path.abspath(p)) in seen
                                   or seen.add(os.path.normcase(os.path.abspath(p))))]


def output_path(src, out_dir):
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.abspath(src)), DEFAULT_OUT_DIRNAME)
    return os.path.join(out_dir, os.path.basename(src))


def run(files, game, mode, out_dir=None, log=print, progress=lambda i, n: None):
    """mode: 'analyze', 'fix' (to out_dir) or 'inplace'. Returns list of reports."""
    reports = []
    for i, src in enumerate(files):
        progress(i, len(files))
        log("== %s" % os.path.basename(src))
        if mode == "analyze":
            rep = fixer.process(src, game, log=log)
        elif mode == "inplace":
            rep = fixer.fix_in_place(src, game, log=log)
        else:
            dst = output_path(src, out_dir)
            if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(src)):
                rep = fixer.FantomeReport(src)
                rep.error = "a pasta de saída é a mesma do arquivo original; use 'substituir original'"
            else:
                rep = fixer.process(src, game, output=dst, log=log)
        for line in rep.summary_lines():
            log(line)
        if not rep.error:  # errors were already printed by summary_lines()
            if not rep.needs_fix:
                log("  OK: já compatível com o patch atual, nada a corrigir")
            elif mode == "analyze":
                log("  PRECISA DE CORREÇÃO")
            elif rep.output:
                log("  CORRIGIDO -> %s" % rep.output)
        reports.append(rep)
    progress(len(files), len(files))

    broken = sum(1 for r in reports if r.error)
    needs = sum(1 for r in reports if not r.error and r.needs_fix)
    log("")
    if mode == "analyze":
        log("Resumo: %d arquivo(s), %d precisam de correção, %d OK, %d com erro"
            % (len(reports), needs, len(reports) - needs - broken, broken))
    else:
        log("Resumo: %d arquivo(s), %d corrigido(s), %d já estavam OK, %d com erro"
            % (len(reports), needs, len(reports) - needs - broken, broken))
    return reports
