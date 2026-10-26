# Fantome Fixer

Corrige skins customizadas (`.fantome`) que **fecham o jogo durante o carregamento** depois do patch 16.21 do League of Legends, ou que **não são aplicadas** porque o loader estoura o tempo de injeção. Funciona com o [Rose](https://github.com/Alban1911/Rose), o cslol-manager e qualquer loader que use `.fantome`.

Analisa e corrige um arquivo ou vários de uma vez, usando os arquivos do **seu** jogo instalado como referência.

## Sintomas

**1. O jogo fecha no carregamento.** Você seleciona a skin customizada, a partida começa a carregar e o jogo fecha. No log do jogo (`League of Legends\Logs\GameLogs\<data>\..._r3dlog.txt`) aparece:

```
ERROR| ALE-9B39AA45 FATAL ERROR. Missing data: 0x0
```

**2. A skin não aparece na partida.** O jogo abre normalmente, mas com a skin padrão. No log do Rose (`%LOCALAPPDATA%\Rose\logs`) aparece:

```
[INJECT] mkoverlay timeout - last output: [INF] Writing wad: DATA/FINAL/Champions/...
CUSTOM MOD INJECTION FAILED
```

## Causa do sintoma 1

A partir do patch 16.21, o jogo guarda parte dos dados de cada skin em arquivos compartilhados novos:

```
DATA/Characters/<Campeão>/<Campeão>_Multi_Skins_*.bin
```

Cada `skins/skinN.bin` do jogo agora lista esses arquivos como *linked files*. Os arquivos antigos que faziam esse papel (`DATA/<Campeão>_Skins_*.bin`) deixaram de existir.

Skins customizadas feitas antes desse patch trazem um `skinN.bin` com a lista de links antiga. O jogo nunca carrega os dados dos arquivos `_Multi_Skins_` e aborta com `Missing data`. Algumas skins ainda incluem uma cópia antiga do `.bin` principal do campeão (ex.: `gangplank.bin`), sem entradas que o jogo atual exige.

## Causa do sintoma 2

Para aplicar um mod, o loader (`mod-tools mkoverlay`) grava cada arquivo do mod em **todos** os WADs do jogo que contêm aquele arquivo, regravando cada WAD inteiro. O Rose desiste depois de **120 segundos** (valor fixo no código, que nenhuma configuração muda).

Algumas skins trazem o WAD do campeão inteiro, com milhares de arquivos idênticos aos do jogo, e às vezes arquivos que nada têm a ver com a skin. Exemplo real, `itachi-zed`:
- 2.815 arquivos idênticos ao jogo (259 MB);
- `assets/recommendations/items/item_metadata.rec`, a recomendação de itens da loja, que existe no WAD de **173 campeões**.

Resultado: 197 WADs (27,8 GB) para regravar, e a injeção falha.

O problema piora com disco cheio ou SSD de entrada (sem DRAM): a velocidade de gravação despenca depois de alguns GB.

## O que o Fantome Fixer faz

Para cada `.bin` dentro do WAD da skin, compara com o mesmo arquivo do jogo instalado e:

1. **Remove links quebrados**: arquivos que não existem nem na skin nem no jogo.
2. **Adiciona os links novos** que o jogo usa hoje (`_Multi_Skins_*.bin`, `Animations/SkinN.bin`, etc.).
3. **Adiciona entradas que faltam**: dados que o `.bin` do jogo tem e o da skin não tem.
4. **Atualiza o `.bin` principal do campeão** quando a cópia da skin está desatualizada. Usa a versão atual do jogo e mantém as entradas que só a skin define.

Depois, **remove arquivos desnecessários** (ligado por padrão). Nada disso afeta o visual da skin:

5. Arquivos **idênticos** à cópia do jogo, tanto no WAD do próprio campeão quanto em todos os outros WADs que os contêm. Arquivos que a skin pega emprestado de outro campeão são mantidos.
6. Arquivos de **recomendação de itens** (`assets/recommendations/items/*.rec`), que não fazem parte de nenhuma skin. A cópia do mod é uma foto antiga; sem ela, o jogo mostra a recomendação atual.
7. O **`.subchunktoc`** do WAD, quando o mod não usa sub-blocos. Se ficasse, ele substituiria o índice de blocos do WAD original.

Arquivos que aparecem em mais de um WAD do mesmo mod nunca são removidos. A limpeza é "melhor esforço": se algo não puder ser lido, o arquivo é mantido e a correção dos `.bin` acontece do mesmo jeito.

O relatório mostra quantos WADs do jogo o loader vai regravar (ex.: `197 -> 8`) e avisa quando ainda são muitos.

### Modo leve (opcional)

Se a skin **ainda não aplicar** depois da correção, ligue o **modo leve**. Ele descarta as alterações em arquivos que o jogo também guarda em **mapas ou em outros campeões**, e assim só os WADs do próprio campeão são regravados. No `itachi-zed`, isso caiu de 8 WADs (5 GB, mais de 4 minutos neste PC) para 2 WADs (0,9 s).

O custo é perder o que esses arquivos compartilhados mudavam. No `itachi-zed`, foram a sombra do Zed (modelo e animações, que o Map11 também carrega) e os ícones do HUD. Corpo, efeitos, voz e animações do campeão continuam customizados.

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
7. Se a skin ainda não aparecer na partida, corrija de novo a partir do **original** com **Modo leve** marcado.

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
| `--lite` | Modo leve: descarta alterações em arquivos compartilhados com mapas ou outros campeões |
| `--no-cleanup` | Não remove arquivos desnecessários (idênticos ao jogo, recomendação de itens, `.subchunktoc`) |

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
- O tempo de injeção depende do disco. Mesmo depois da limpeza, uma skin que altera arquivos compartilhados com mapas obriga o loader a regravar WADs de vários GB. Com pouco espaço livre (menos de ~10%), SSDs de entrada ficam lentos demais para os 120 s do Rose: libere espaço ou use o modo leve.

## Aviso

Projeto independente, sem relação com a Riot Games. Mods de skin alteram arquivos do cliente: use por sua conta e risco.
