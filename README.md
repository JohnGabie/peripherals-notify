# Attack Shark X6 — Battery Notifier

Notificador de bateria para o mouse **Attack Shark X6** via dongle 2.4 GHz.  
Funciona em **Windows** e **Linux** sem precisar do software oficial aberto.

---

## Como foi descoberto o protocolo

### 1. Identificação do dispositivo

O dongle do Attack Shark X6 aparece como:

| Campo       | Valor                       |
|-------------|-----------------------------|
| Fabricante  | Beken Corporation           |
| VID         | `0x1D57`                    |
| PID         | `0xFA60`                    |
| Descrição   | `2.4G Wireless Device`      |

O software original (`D:\Program Files (x86)\Attack SharkX6Mouse\X6.exe`)
usa `hidapi.dll` internamente — o que confirmou que a comunicação é via HID padrão.

### 2. Mapeamento das interfaces HID

O dongle expõe 7 interfaces. Usando `hid.enumerate()`:

| Interface | usage_page | usage  | Descrição               | Acesso          |
|-----------|------------|--------|-------------------------|-----------------|
| MI_00     | `0x0001`   | `0x0006` | Keyboard                | Exclusivo (OS)  |
| MI_01     | `0x0001`   | `0x0002` | Mouse                   | Exclusivo (OS)  |
| MI_02 Col01 | `0x0001` | `0x0080` | System Control          | Aberto, sem dados |
| MI_02 Col02 | `0x000C` | `0x0001` | Consumer Control        | Aberto, sem dados |
| **MI_02 Col03** | **`0x000A`** | **`0x0000`** | **Vendor (bateria!)** | **Dados disponíveis** |
| MI_02 Col04 | `0x000B` | `0x0000` | Vendor (bloqueado)      | Exclusivo (OS)  |
| MI_03     | `0x0001`   | `0x0006` | Keyboard 2              | Exclusivo (OS)  |

### 3. Captura dos dados

Com o software oficial **fechado**, a interface `usage_page=0x000A` envia
pacotes periódicos de 5 bytes:

```
[0x03, 0x10, 0x40, 0x01, 0x04]
  │     │     │     │     └─ desconhecido
  │     │     │     └─────── desconhecido
  │     │     └───────────── BATERIA (BCD)
  │     └─────────────────── desconhecido
  └───────────────────────── Report ID = 3
```

### 4. Codificação BCD

O byte de bateria usa **BCD (Binary Coded Decimal)**:

| Valor HEX | BCD decode | Bateria |
|-----------|------------|---------|
| `0x40`    | 40         | 40%     |
| `0x25`    | 25         | 25%     |
| `0x10`    | 10         | 10%     |
| `0x64`    | 64         | 64%     |

```python
def bcd_to_int(value: int) -> int:
    return int(f"{value:02X}")
```

Confirmado com o software oficial mostrando **40%** enquanto o byte capturado era `0x40`.

---

## Instalação

```bash
pip install -r requirements.txt
```

> **Linux**: instale também `libhidapi-hidraw0` e `notify-osd`:
> ```bash
> sudo apt install libhidapi-hidraw0 libnotify-bin
> # Permitir acesso ao HID sem sudo:
> echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1d57", ATTRS{idProduct}=="fa60", MODE="0666"' \
>   | sudo tee /etc/udev/rules.d/99-attack-shark.rules
> sudo udevadm control --reload-rules && sudo udevadm trigger
> ```

---

## Uso

```bash
# Leitura única da bateria
python mouse_battery.py --once

# Monitor contínuo (padrão: alertas em 30%, 20%, 10%)
python mouse_battery.py

# Customizar thresholds e intervalo de polling
python mouse_battery.py --thresholds 40 20 5 --poll 30
```

---

## Compilar executável

### Windows
```bat
pyinstaller --onefile --noconsole --name mouse-battery mouse_battery.py
```
O executável fica em `dist\mouse-battery.exe`.

### Linux
```bash
pyinstaller --onefile --name mouse-battery mouse_battery.py
```

> Para compilar para **ambas** as plataformas, rode o PyInstaller em cada SO separadamente.

---

## Inicialização automática

### Windows — Startup
1. Pressione `Win + R` → `shell:startup`
2. Crie um atalho para `dist\mouse-battery.exe`

### Linux — systemd (usuário)
```ini
# ~/.config/systemd/user/mouse-battery.service
[Unit]
Description=Attack Shark X6 Battery Monitor

[Service]
ExecStart=/home/$USER/.local/bin/mouse-battery
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```
```bash
systemctl --user enable --now mouse-battery
```

---

## Estrutura do projeto

```
mouse-battery-notifier/
├── mouse_battery.py    # script principal
├── requirements.txt
└── README.md
```
