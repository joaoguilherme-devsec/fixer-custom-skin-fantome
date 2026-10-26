import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__, batch, gamepath
from .fixer import GameData


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Fantome Fixer %s" % __version__)
        self.geometry("860x620")
        self.minsize(700, 500)
        self.events = queue.Queue()
        self.worker = None

        pad = {"padx": 8, "pady": 4}

        files = ttk.LabelFrame(self, text="Arquivos .fantome")
        files.pack(fill="both", expand=False, **pad)
        self.listbox = tk.Listbox(files, height=8, selectmode="extended")
        self.listbox.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb = ttk.Scrollbar(files, orient="vertical", command=self.listbox.yview)
        sb.pack(side="left", fill="y", pady=8)
        self.listbox.config(yscrollcommand=sb.set)
        btns = ttk.Frame(files)
        btns.pack(side="left", fill="y", padx=8, pady=8)
        for text, cmd in (("Adicionar arquivos...", self.add_files), ("Adicionar pasta...", self.add_folder),
                          ("Remover selecionados", self.remove_selected), ("Limpar lista", self.clear)):
            ttk.Button(btns, text=text, command=cmd, width=22).pack(fill="x", pady=2)

        game = ttk.LabelFrame(self, text="Pasta do jogo (League of Legends\\Game)")
        game.pack(fill="x", **pad)
        self.game_var = tk.StringVar(value=gamepath.detect() or "")
        ttk.Entry(game, textvariable=self.game_var).pack(side="left", fill="x", expand=True, padx=8, pady=8)
        ttk.Button(game, text="Procurar...", command=self.browse_game).pack(side="left", padx=(0, 8))

        out = ttk.LabelFrame(self, text="Onde salvar os arquivos corrigidos")
        out.pack(fill="x", **pad)
        self.mode_var = tk.StringVar(value="fix")
        r1 = ttk.Frame(out)
        r1.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Radiobutton(r1, text="Em outra pasta:", variable=self.mode_var, value="fix").pack(side="left")
        self.out_var = tk.StringVar(value="")
        self.out_entry = ttk.Entry(r1, textvariable=self.out_var)
        self.out_entry.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(r1, text="Procurar...", command=self.browse_out).pack(side="left")
        ttk.Label(out, text="(vazio = subpasta \"%s\" ao lado de cada arquivo; os originais não são alterados)"
                  % batch.DEFAULT_OUT_DIRNAME, foreground="#666").pack(anchor="w", padx=30)
        ttk.Radiobutton(out, text="Substituir o arquivo original (uma cópia .bak é guardada)",
                        variable=self.mode_var, value="inplace").pack(anchor="w", padx=8, pady=(2, 8))

        actions = ttk.Frame(self)
        actions.pack(fill="x", **pad)
        self.analyze_btn = ttk.Button(actions, text="Analisar", command=lambda: self.start("analyze"))
        self.analyze_btn.pack(side="left")
        self.fix_btn = ttk.Button(actions, text="Corrigir", command=lambda: self.start(None))
        self.fix_btn.pack(side="left", padx=8)
        self.progress = ttk.Progressbar(actions, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=8)

        self.log = ScrolledText(self, height=14, font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True, **pad)

        self.after(100, self.poll)
        if not self.game_var.get():
            self.write("Pasta do jogo não detectada automaticamente: selecione-a acima.")

    # -- file list -------------------------------------------------------
    def items(self):
        return list(self.listbox.get(0, "end"))

    def add_paths(self, paths):
        current = set(self.items())
        for p in batch.expand_inputs(paths):
            if p not in current:
                self.listbox.insert("end", p)
                current.add(p)

    def add_files(self):
        self.add_paths(filedialog.askopenfilenames(
            title="Selecione os arquivos .fantome",
            filetypes=[("Mods fantome", "*.fantome"), ("Todos os arquivos", "*.*")]))

    def add_folder(self):
        d = filedialog.askdirectory(title="Pasta com arquivos .fantome")
        if d:
            before = len(self.items())
            self.add_paths([d])
            if len(self.items()) == before:
                messagebox.showinfo("Fantome Fixer", "Nenhum arquivo .fantome novo nessa pasta.")

    def remove_selected(self):
        for i in reversed(self.listbox.curselection()):
            self.listbox.delete(i)

    def clear(self):
        self.listbox.delete(0, "end")

    def browse_game(self):
        d = filedialog.askdirectory(title="Pasta do League of Legends")
        if d:
            self.game_var.set(gamepath.normalize(d) or d)

    def browse_out(self):
        d = filedialog.askdirectory(title="Pasta de saída")
        if d:
            self.out_var.set(os.path.normpath(d))
            self.mode_var.set("fix")

    # -- running ---------------------------------------------------------
    def start(self, mode):
        if self.worker and self.worker.is_alive():
            return
        files = self.items()
        if not files:
            messagebox.showwarning("Fantome Fixer", "Adicione pelo menos um arquivo .fantome.")
            return
        game_dir = gamepath.normalize(self.game_var.get())
        if not game_dir:
            messagebox.showerror("Fantome Fixer", "Pasta do jogo inválida. Selecione a pasta "
                                 "'League of Legends' ou 'League of Legends\\Game'.")
            return
        self.game_var.set(game_dir)
        mode = mode or self.mode_var.get()
        if mode == "inplace" and not messagebox.askyesno(
                "Fantome Fixer", "Os arquivos originais serão substituídos (uma cópia .bak será criada). Continuar?"):
            return
        out_dir = self.out_var.get().strip() or None
        self.set_busy(True)
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        self.worker = threading.Thread(target=self.work, args=(files, game_dir, mode, out_dir), daemon=True)
        self.worker.start()

    def work(self, files, game_dir, mode, out_dir):
        log = lambda m: self.events.put(("log", m))
        try:
            log("Jogo: %s" % game_dir)
            log("Indexando arquivos do jogo...")
            game = GameData(game_dir)
            batch.run(files, game, mode, out_dir=out_dir, log=log,
                      progress=lambda i, n: self.events.put(("progress", (i, n))))
        except Exception as e:  # surface anything unexpected in the log window
            log("ERRO: %s" % e)
        finally:
            self.events.put(("done", mode))

    def poll(self):
        try:
            while True:
                kind, val = self.events.get_nowait()
                if kind == "log":
                    self.write(val)
                elif kind == "progress":
                    i, n = val
                    self.progress.config(maximum=max(n, 1), value=i)
                elif kind == "done":
                    self.set_busy(False)
                    if val != "analyze":
                        self.write("\nImporte os arquivos corrigidos de novo no Rose (apague a versão antiga do mod antes).")
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def write(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.analyze_btn.config(state=state)
        self.fix_btn.config(state=state)


def main(paths=()):
    app = App()
    app.add_paths(paths)
    app.mainloop()
