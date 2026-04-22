# Attack Shark Keyboard — Battery Notifier

Notificador de bateria para o **Attack Shark Keyboard** (ROYUAN 2.4G Wireless Keyboard)
via dongle 2.4 GHz.  
Funciona em **Windows** lendo o servidor gRPC interno do driver oficial.

---

## Como foi descoberto o protocolo

### 1. Identificação do dispositivo

| Campo      | Valor                          |
|------------|--------------------------------|
| Fabricante | ROYUAN                         |
| VID        | `0x3151`                       |
| PID        | `0x4011`                       |
| Descrição  | `2.4G Wireless Keyboard`       |

### 2. Arquitetura do software oficial

O **Attack Shark Driver v4** é um app **Electron** localizado em:
```
C:\Users\<user>\AppData\Local\Programs\Attack Shark Driver v4\
```

O código-fonte JS (não minificado o suficiente para esconder lógica) revelou que
o app **não** se comunica com o HID diretamente. Em vez disso, ele delega para
um processo separado via **gRPC**:

```
Electron UI  →  gRPC-Web  →  iot_driver_v215.exe  →  HID  →  Teclado
```

### 3. Descoberta do servidor gRPC

No arquivo `dist/js/index.b078bf5f.js`:
```js
const i = new gR({ baseUrl: "http://127.0.0.1:3814" });
e.client = new kR(i);
```

O `iot_driver_v215.exe` é um servidor **gRPC-Web** rodando na porta **3814**.

### 4. Serviço gRPC

Extraído do mesmo arquivo JS:
```js
const Ip = new w3("driver.DriverGrpc", [
  { name: "watchDevList", serverStreaming: true, I: Empty, O: DeviceList },
  { name: "sendMsg",      I: SendMsg,  O: ResSend },
  { name: "readMsg",      I: ReadMsg,  O: ResRead },
  ...
]);
```

| Método         | Tipo              | Entrada | Saída        |
|----------------|-------------------|---------|--------------|
| `watchDevList` | Server streaming  | Empty   | DeviceList   |
| `sendMsg`      | Unary             | SendMsg | ResSend      |
| `readMsg`      | Unary             | ReadMsg | ResRead      |

### 5. Estrutura protobuf da bateria

Decodificando a resposta bruta do `watchDevList`, a bateria do teclado
segue este caminho de campos:

```
DeviceList
  └─ [field=1] repeated items
       └─ [field=2] DangleC  (dispositivo 24G — identificado por VID/PID)
            ├─ [field=7] vid  = 0x3151
            ├─ [field=8] pid  = 0x4011
            └─ [field=1] keyboard
                 └─ [field=2] dangleDev.status  (Status24)
                       ├─ [field=1] battery  uint32  ← percentual 0-100
                       └─ [field=2] isOnline bool
```

### 6. Mapeamento de barras → porcentagem

O UI (arquivo `dist/js/66255e89.js`) converte assim:

```js
n >= 100 → EQ_100  (5 barras)
n >= 80  → EQ_80   (4 barras)  ← teclado estava aqui: 88%
n >= 60  → EQ_60   (3 barras)
n >= 40  → EQ_40   (2 barras)
n >= 20  → EQ_20   (1 barra)
default  → EQ_0    (0 barras)
```

Confirmado: software mostrava **4/5 barras**, gRPC retornou **88%** (≥80%).

### 7. Chamada gRPC-Web manual (sem biblioteca)

O protocolo usa HTTP/1.1 com Transfer-Encoding chunked:

```
POST http://127.0.0.1:3814/driver.DriverGrpc/watchDevList
Content-Type: application/grpc-web+proto
X-Grpc-Web: 1

\x00\x00\x00\x00\x00    ← gRPC-Web frame: flags=0, length=0 (Empty message)
```

Resposta: stream de frames gRPC-Web com `DeviceList` em protobuf.

---

## Requisito

O **Attack Shark Driver v4** deve estar aberto (ele inicia o `iot_driver.exe`
automaticamente). O script não precisa de acesso HID direto.

```bash
pip install plyer
```

---

## Uso

```bash
# Leitura única
python keyboard_battery.py --once

# Monitor contínuo (alertas em 30%, 20%, 10%)
python keyboard_battery.py

# Customizar
python keyboard_battery.py --thresholds 40 20 5 --poll 30
```

---

## Compilar executável

### Windows
```bat
pyinstaller --onefile --noconsole --name keyboard-battery keyboard_battery.py
```

### Linux

O `iot_driver.exe` é um executável Windows. No Linux, a abordagem via gRPC
**não funciona** sem Wine ou driver equivalente.

Para Linux será necessário comunicação HID direta com o dongle — ainda não
mapeada para este dispositivo.

---

## Estrutura do projeto

```
mouse-battery-notifier/
├── mouse_battery.py       # Attack Shark X6 mouse (HID direto)
├── keyboard_battery.py    # Attack Shark Keyboard (gRPC via iot_driver)
├── requirements.txt
├── README.md              # Documentação do mouse
└── README_keyboard.md     # Documentação do teclado (este arquivo)
```
