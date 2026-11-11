# 📹 Sistema de Câmeras

Sistema próprio para as câmeras Intelbras, sem propaganda e sem depender do app do fabricante.

- **Ao vivo**: as duas câmeras numa tela só (toque na imagem para tela cheia)
- **Gravação contínua** das duas câmeras, em arquivos de 10 minutos, apagando os mais antigos sozinho
- **Detecção de movimento** com foto de cada evento
- **Dados** 📊: eventos por dia, por horário e por dia da semana, e exportação em **CSV** (pandas, Excel, Power BI)
- **App no celular**: instala na tela inicial e abre direto, como um app de verdade

```
 Câmera 1 ─┐                       ┌─ 📱 celular (app)
           ├─► computador sempre ──┤
 Câmera 2 ─┘   ligado (servidor)   └─ 💻 navegador
               grava, analisa e
               guarda os dados
```

> **Por que precisa de um computador ligado?** O celular não consegue gravar 24h e
> analisar o vídeo (a bateria e o armazenamento não aguentam). O "cérebro" fica num
> computador em casa e o celular só abre o app para ver. Serve um PC/notebook velho,
> um mini PC ou um Raspberry Pi 4/5.

---

## 1. Descobrir o link (RTSP) das câmeras

Toda câmera IP tem um link RTSP, que é por onde o sistema pega o vídeo. Você vai precisar de:

- **IP da câmera** na sua rede (aparece no app, nas informações do dispositivo, ou na
  página do roteador, em "dispositivos conectados"). Ex.: `192.168.1.10`
- **Usuário e senha** da câmera (normalmente `admin` e a senha/código que fica na etiqueta)

Intelbras (padrão da maioria dos modelos):

```
rtsp://admin:SENHA@IP:554/cam/realmonitor?channel=1&subtype=0   ← alta qualidade
rtsp://admin:SENHA@IP:554/cam/realmonitor?channel=1&subtype=1   ← baixa qualidade
```

Se a câmera usa o app **iCSee** (câmeras com protocolo XMeye), o formato costuma ser:

```
rtsp://IP:554/user=admin&password=SENHA&channel=1&stream=0.sdp   ← alta
rtsp://IP:554/user=admin&password=SENHA&channel=1&stream=1.sdp   ← baixa
```

**Testar antes:** abra o [VLC](https://www.videolan.org/) → *Mídia → Abrir fluxo de rede* →
cole o link. Se aparecer a imagem, está certo! ✅

> Se a senha tiver caracteres especiais (`@`, `#`, `:`), troque por códigos:
> `@` → `%40`, `#` → `%23`, `:` → `%3A`.

## 2. Instalar no computador

Precisa de **Python 3.10+** e **ffmpeg**.

**Windows**

```bash
winget install Python.Python.3.12 Gyan.FFmpeg
```

**Linux / Raspberry Pi**

```bash
sudo apt install python3-venv ffmpeg
```

Depois, dentro da pasta `sistema-cameras`:

```bash
python -m venv .venv
```

```bash
# Windows:  .venv\Scripts\activate      Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

Copie `config.exemplo.yaml` para **`config.yaml`** e preencha o nome das câmeras, os links RTSP
e uma senha para o sistema. (O `config.yaml` fica fora do GitHub para proteger as senhas.)

## 3. Rodar

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abra no navegador: `http://localhost:8000`. No celular (no Wi-Fi de casa): `http://IP-DO-COMPUTADOR:8000`.

## 4. Instalar como app no celular

- **Android (Chrome):** menu ⋮ → *Adicionar à tela inicial* / *Instalar app*
- **iPhone (Safari):** botão compartilhar → *Adicionar à Tela de Início*

## 5. Acessar fora de casa (pelo 4G) 🔒

O jeito mais seguro e fácil é o **[Tailscale](https://tailscale.com)** (grátis): cria uma
"rede privada" só sua entre o computador e o celular. Não precisa abrir porta no roteador, e
ninguém de fora consegue chegar nas câmeras.

1. Instale o Tailscale no computador e no celular e entre com a mesma conta.
2. No computador, rode:

```bash
tailscale serve --bg 8000
```

3. Ele mostra um endereço tipo `https://meu-pc.tailXXXX.ts.net`. Abra esse endereço no
   celular e instale como app (passo 4). Com esse endereço `https`, o app funciona completo
   e abre igual dentro e fora de casa.

## 6. Ligar sozinho quando o computador iniciar

- **Windows:** crie um atalho para `iniciar.bat` (abaixo) e coloque na pasta `shell:startup`.

```bat
cd /d C:\caminho\para\sistema-cameras
call .venv\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- **Linux:** crie um serviço do systemd (posso ajudar a montar).

## Ajustes finos

No `config.yaml`, em `movimento`:

| opção | o que faz |
|---|---|
| `sensibilidade` | quanto cada pixel precisa mudar. Muito alarme falso? Aumente (ex.: 35) |
| `area_minima` | % da imagem que precisa mexer. Folhas/sombras disparando? Aumente (ex.: 3) |
| `segundos_fim` | quanto tempo parado para encerrar um evento |

Espaço em disco: cada câmera em alta qualidade usa cerca de **10 a 20 GB por dia**.
Ajuste `dias_guardar` conforme o seu HD. Os **dados** dos eventos nunca são apagados.

## Analisando os dados no Python 🐍

```python
import pandas as pd

df = pd.read_csv("eventos.csv", parse_dates=["inicio", "fim"])  # botão "CSV" na aba Dados
df["hora"] = df["inicio"].dt.hour
df.pivot_table(index="hora", columns="camera", values="id", aggfunc="count").plot(kind="bar")
```

Ou direto no banco: `dados/eventos.db` (SQLite, tabela `eventos`).

## Estrutura

```
app/main.py     servidor web (API, login, estatísticas)
app/camera.py   gravação (ffmpeg) + detecção de movimento (OpenCV)
app/db.py       banco SQLite dos eventos
static/         o app (HTML/CSS/JS, instalável no celular)
```

## Próximas ideias 💡

- Alerta no celular (Telegram) quando houver movimento
- Detectar **pessoas** (não só movimento) com um modelo de IA (YOLO)
- Zonas: ignorar partes da imagem (rua, árvore)
- Linha do tempo das gravações com marcação dos movimentos
