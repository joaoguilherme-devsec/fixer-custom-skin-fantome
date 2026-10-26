# Fantome Fixer

Corrige skins customizadas (`.fantome`) que **fecham o jogo durante o carregamento** depois do patch 16.21 do League of Legends. Funciona com o [Rose](https://github.com/Alban1911/Rose), o cslol-manager e qualquer loader que use `.fantome`.

Analisa e corrige um arquivo ou vários de uma vez, usando os arquivos do **seu** jogo instalado como referência.

## Sintoma

Você seleciona a skin customizada, a partida começa a carregar e o jogo fecha. No log do jogo (`League of Legends\Logs\GameLogs\<data>\..._r3dlog.txt`) aparece:

```
ERROR| ALE-9B39AA45 FATAL ERROR. Missing data: 0x0
```

## Causa

A partir do patch 16.21, o jogo guarda parte dos dados de cada skin em arquivos compartilhados novos:

```
DATA/Characters/<Campeão>/<Campeão>_Multi_Skins_*.bin
```

Cada `skins/skinN.bin` do jogo agora lista esses arquivos como *linked files*. Os arquivos antigos que faziam esse papel (`DATA/<Campeão>_Skins_*.bin`) deixaram de existir.

Skins customizadas feitas antes desse patch trazem um `skinN.bin` com a lista de links antiga. O jogo nunca carrega os dados dos arquivos `_Multi_Skins_` e aborta com `Missing data`. Algumas skins ainda incluem uma cópia antiga do `.bin` principal do campeão (ex.: `gangplank.bin`), sem entradas que o jogo atual exige.

## O que o Fantome Fixer faz

Para cada `.bin` dentro do WAD da skin, compara com o mesmo arquivo do jogo instalado e:

1. **Remove links quebrados**: arquivos que não existem nem na skin nem no jogo.
2. **Adiciona os links novos** que o jogo usa hoje (`_Multi_Skins_*.bin`, `Animations/SkinN.bin`, etc.).
3. **Adiciona entradas que faltam**: dados que o `.bin` do jogo tem e o da skin não tem.
4. **Atualiza o `.bin` principal do campeão** quando a cópia da skin está desatualizada. Usa a versão atual do jogo e mantém as entradas que só a skin define.

Todo o resto (modelos, texturas, VFX, sons, `META/info.json`) é copiado byte a byte, sem alteração. O arquivo original **nunca** é alterado, a não ser que você escolha "Substituir o original" (nesse caso fica uma cópia `.bak`).

## Download

Baixe na página de [Releases](https://github.com/joaoguilherme-devsec/fixer-custom-skin-fantome/releases):

| Arquivo | Para quê |
|---|---|
| `FantomeFixer.exe` | Interface gráfica (recomendado) |
| `FantomeFixer-cli.exe` | Linha de comando / scripts |

Não precisa instalar Python. O Windows SmartScreen pode avisar que o app é desconhecido (o executável não é assinado): clique em **Mais informações → Executar assim mesmo**.

## Como usar (interface gráfica)

1. Abra o `FantomeFixer.exe`. Você também pode arrastar arquivos `.fantome` para cima do ícone.
2. **Adicionar arquivos...** ou **Adicionar pasta...** para escolher as skins.
3. Confira a **pasta do jogo**. Ela é detectada sozinha pelo Rose, pelo Riot Client ou por `C:\Riot Games\League of Legends\Game`.
4. **Analisar** mostra o que precisa ser corrigido, sem gravar nada.
5. **Corrigir** grava as versões corrigidas. Por padrão elas vão para a subpasta `Corrigidas`, ao lado de cada arquivo.
6. No Rose, **apague a versão antiga** da skin e **importe o arquivo corrigido**.

> Rode a correção de novo sempre que um patch do LoL voltar a quebrar as skins: a referência é sempre o jogo instalado no momento. Uma skin que já está compatível aparece como "OK" e não é regravada.

## Como usar (linha de comando)

```bash
FantomeFixer-cli.exe analyze "C:\Skins"
```

```bash
FantomeFixer-cli.exe fix "C:\Skins\Batman-1.1.fantome" "C:\Skins\Guts-v1.0.0-Darius.fantome" --out "C:\Skins\Corrigidas"
```

```bash
FantomeFixer-cli.exe fix "C:\Skins" --in-place
```

| Opção | Descrição |
|---|---|
| `analyze` / `fix` | Só verificar / verificar e corrigir |
| `--game <pasta>` | Pasta `League of Legends` ou `League of Legends\Game` (detectada automaticamente se omitida) |
| `--out <pasta>` | Pasta de saída (padrão: `Corrigidas` ao lado de cada arquivo) |
| `--in-place` | Substitui o original e guarda uma cópia `<arquivo>.fantome.bak` |

Código de saída: `0` = sucesso, `1` = algum arquivo deu erro, `2` = jogo ou arquivos não encontrados.

## Rodar a partir do código

Requer Python 3.10+.

```bash
pip install -r requirements.txt
```

```bash
python -m fantome_fixer
```

Sem argumentos, abre a interface gráfica. Com argumentos, funciona como a CLI acima.

## Gerar os executáveis

```bash
pip install -r requirements.txt pyinstaller
```

```bash
python -m PyInstaller --noconfirm --clean --onefile --windowed --name FantomeFixer --collect-binaries zstandard run.py
```

```bash
python -m PyInstaller --noconfirm --onefile --console --name FantomeFixer-cli --collect-binaries zstandard run.py
```

Ou rode `build.ps1`, que faz os três passos. Os `.exe` ficam em `dist\`.

## Estrutura

| Arquivo | Função |
|---|---|
| `fantome_fixer/wad.py` | Leitura e regravação de WAD v3 (`.wad.client`, zstd/gzip, hashes xxh64/xxh3) |
| `fantome_fixer/binfile.py` | Contêiner `.bin` (PROP/PTCH): lista de links e entradas, preservadas byte a byte |
| `fantome_fixer/fixer.py` | Análise e correção |
| `fantome_fixer/gamepath.py` | Detecção da pasta do jogo |
| `fantome_fixer/batch.py` | Processamento em lote (compartilhado entre GUI e CLI) |
| `fantome_fixer/gui.py`, `cli.py` | Interface gráfica (Tkinter) e linha de comando |

## Limitações

- Corrige incompatibilidade de **estrutura** (links e entradas faltando). Não recria modelos, animações ou texturas que um patch tenha mudado de formato. Se uma skin continuar fechando o jogo depois da correção, ela precisa ser atualizada pelo autor.
- WADs no formato antigo v2 não são suportados (todos os mods atuais usam v3).
- Funciona com o jogo instalado e atualizado. A correção é feita contra a versão do jogo que estiver na sua máquina.

## Aviso

Projeto independente, sem relação com a Riot Games. Mods de skin alteram arquivos do cliente: use por sua conta e risco.
