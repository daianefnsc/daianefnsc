# 📹 Sistema de Câmeras

Sistema próprio para as câmeras (iCSee / Intelbras), sem propaganda e sem depender do app do fabricante.

- **Ao vivo**: as câmeras numa tela só (toque na imagem para tela cheia)
- **Gravação** por câmera: 24h, só quando tem movimento, ou sem gravar
- **Detecção de movimento** com foto de cada evento
- **Dados** 📊: eventos por dia, por horário e por dia da semana, e exportação em **CSV** (pandas, Excel, Power BI)
- **App no celular**: instala na tela inicial e abre direto, como um app de verdade
- **Nunca enche o disco**: apaga os vídeos mais antigos sozinho

```
 Câmera Sala ────┐                         ┌─ 📱 celular (app)
 (sem cartão)    ├─► tablet em casa ───────┤
 Câmera Garagem ─┘   (servidor 24h)        └─ 💻 navegador
 (com cartão)        grava, analisa e
                     guarda os dados
```

> **Por que precisa de um aparelho ligado em casa?** As câmeras só são acessíveis pelo
> Wi-Fi de casa (é isso que as protege). O "cérebro" fica em casa, e o celular só abre o
> app para ver. Pode ser um tablet Android, um notebook velho, um mini PC ou um Raspberry Pi.

---

## 1. Descobrir o link (RTSP) das câmeras

O link RTSP é por onde o sistema pega o vídeo. Você vai precisar de:

- **IP da câmera** na sua rede (no app iCSee, em configurações da câmera → informações
  de rede, ou na página do roteador, em "dispositivos conectados"). Ex.: `192.168.1.10`
- **Usuário e senha** da câmera (usuário normalmente `admin`)

Câmeras do app **iCSee**:

```
rtsp://IP:554/user=admin&password=SENHA&channel=1&stream=0.sdp   ← alta qualidade
rtsp://IP:554/user=admin&password=SENHA&channel=1&stream=1.sdp   ← baixa qualidade
```

Outras Intelbras (apps Mibo/iSIC):

```
rtsp://admin:SENHA@IP:554/cam/realmonitor?channel=1&subtype=0
rtsp://admin:SENHA@IP:554/cam/realmonitor?channel=1&subtype=1
```

**Testar antes:** instale o app **VLC** no celular → *Fluxo de rede* → cole o link.
Se aparecer a imagem, está certo! ✅

> ⚠️ **Troque a senha padrão das câmeras** no iCSee se ainda não trocou.
> Se a senha tiver caracteres especiais, troque por códigos: `@` → `%40`, `#` → `%23`, `&` → `%26`.

> 💡 Configure o roteador para dar sempre o **mesmo IP** para as câmeras e para o tablet
> ("reserva de DHCP" / "IP fixo"). Assim os links não mudam.

## 2. Configurar

Copie `config.exemplo.yaml` para **`config.yaml`** e preencha: nome das câmeras, links RTSP,
uma senha para o sistema e como cada câmera grava:

| `gravar:` | quando usar |
|---|---|
| `"continuo"` | câmera **sem cartão**: o sistema grava 24h |
| `"movimento"` | câmera **com cartão**: ela já grava 24h, o sistema guarda só os trechos com movimento |
| `"nao"` | só ao vivo + detecção + dados |

Espaço que cada câmera ocupa gravando 24h (aproximado):

| `qualidade:` | por dia | com 50 GB livres dá |
|---|---|---|
| `"alta"` (padrão) | ~10–20 GB | ~3 dias |
| `"baixa"` | ~2–4 GB | ~2 semanas |

O `config.yaml` **não vai para o GitHub** (tem senhas). Os vídeos e dados também não.

---

## 3A. Instalar no tablet Android (Xiaomi / Redmi Pad) 📟

**Apps** (instale pela loja **F-Droid**, em https://f-droid.org; a versão do Termux da Play Store é antiga e não funciona):
- **Termux**: onde o sistema roda
- **Termux:Boot**: liga o sistema sozinho quando o tablet reinicia

No **Termux**, rode um bloco de cada vez:

```bash
pkg update && pkg upgrade -y
```

```bash
pkg install -y python ffmpeg git python-numpy opencv-python
```

```bash
pip install starlette uvicorn pyyaml
```

```bash
git clone -b claude/elegant-einstein-ehotk8 https://github.com/daianefnsc/daianefnsc.git
```

```bash
cd daianefnsc/sistema-cameras && cp config.exemplo.yaml config.yaml && nano config.yaml
```

(No `nano`: edite, depois `Ctrl+O`, `Enter` para salvar e `Ctrl+X` para sair. O Termux tem uma
barra com a tecla `Ctrl`.)

Rodar:

```bash
termux-wake-lock && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Ligar sozinho quando o tablet reiniciar

```bash
mkdir -p ~/.termux/boot && cp ~/daianefnsc/sistema-cameras/iniciar-android.sh ~/.termux/boot/ && chmod +x ~/.termux/boot/iniciar-android.sh
```

Depois abra o app **Termux:Boot** uma vez.

### Configurações da Xiaomi (importante!)

A Xiaomi fecha apps em segundo plano para economizar bateria. Para o sistema não parar:

1. **Configurações → Apps → Termux**: *Inicialização automática* **ligada**, e em
   *Economia de bateria* escolha **Sem restrições**. Faça o mesmo para o **Termux:Boot**.
2. Abra os apps recentes, segure o Termux e toque no **cadeado** 🔒 para fixá-lo.
3. **Bateria**: o tablet vai ficar sempre na tomada. Se existir a opção de proteger a
   bateria / limitar a carga em *Configurações → Bateria*, ative.
4. Deixe a tela apagar normalmente. O `termux-wake-lock` mantém o sistema rodando.

## 3B. Instalar no computador (Windows / Linux) 💻

Precisa de **Python 3.10+** e **ffmpeg**.

```bash
winget install Python.Python.3.12 Gyan.FFmpeg
```

(No Linux: `sudo apt install python3-venv ffmpeg`.) Depois, dentro da pasta `sistema-cameras`:

```bash
pip install -r requirements.txt
```

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## 4. Abrir no celular e instalar como app 📱

No Wi-Fi de casa, abra `http://IP-DO-TABLET:8000` no navegador do celular (o IP do tablet
fica em *Configurações → Wi-Fi → sua rede*).

- **Android (Chrome):** menu ⋮ → *Adicionar à tela inicial*
- **iPhone (Safari):** botão compartilhar → *Adicionar à Tela de Início*

## 5. Acessar fora de casa (pelo 4G) 🔒

Use o **[Tailscale](https://tailscale.com)** (grátis): uma rede privada só sua entre o tablet
e o celular. Não precisa abrir porta no roteador, e ninguém de fora consegue chegar nas câmeras.

1. Instale o app Tailscale no **tablet** e no **celular** e entre com a mesma conta.
2. No app do Tailscale, veja o IP do tablet (começa com `100.`).
3. No celular, abra `http://100.x.x.x:8000` e adicione à tela inicial.
   Esse endereço funciona **dentro e fora de casa**, então pode usar só ele.

## Ajustes finos

No `config.yaml`, em `movimento`:

| opção | o que faz |
|---|---|
| `sensibilidade` | quanto cada pixel precisa mudar. Muito alarme falso? Aumente (ex.: 35) |
| `area_minima` | % da imagem que precisa mexer. Folhas/sombras disparando? Aumente (ex.: 3) |
| `segundos_fim` | quanto tempo parado para encerrar um evento |

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
app/main.py     servidor web (API, login, estatísticas, limpeza de espaço)
app/camera.py   gravação (ffmpeg) + detecção de movimento (OpenCV)
app/db.py       banco SQLite dos eventos
static/         o app (HTML/CSS/JS, instalável no celular)
```

## Próximas ideias 💡

- Alerta no celular (Telegram) quando houver movimento, com a foto
- Detectar **pessoas** (não só movimento) com IA
- Zonas: ignorar partes da imagem (rua, árvore)
- Linha do tempo das gravações com marcação dos movimentos
