# 从 WorkBuddy 对话孵化沙箱到默认隧穿本地电脑 — 全流程复刻 SOP (Playbook)

> **默认核心架构**：以**个人本地电脑（Windows / Mac / Linux）作为反向隧道的直接终点**。  
> **核心优势**：**0 云服务器费用**、**零公网带宽瓶颈**、本地 `localhost` 极速直连、远程桌面满帧丝滑！  
> （公网跳板机仅作为本地电脑无常开条件时的备选方案保留）。  
> **文档版本**：2026-09-07 终版（默认本地直穿模式）

---

## 核心拓扑架构图（默认模式）

```text
┌──────────────────────────────────────────────┐
│              你的本地电脑 (Windows)          │
│                                              │
│  [OpenSSH Server] (后台监听 22)              │
│    ▲                                         │
│    │ (反向加密隧道建立完成)                   │
│    ├─► 本地端口 :2222 ───► 直通沙箱终端 SSH   │
│    └─► 本地端口 :3389 ───► 直通沙箱 GNOME 桌面│
│                                              │
│  [本地客户端极速秒连]                         │
│  • 终端: ssh -p 2222 root@127.0.0.1          │
│  • 桌面: mstsc ➔ 127.0.0.1:3389 (满帧零延迟) │
│  • Hermes: 直连 127.0.0.1                    │
└──────────────────────▲───────────────────────┘
                       │
       【反向穿透出站连接 (沙箱主动打出)】
       (方式 1: Tailscale 虚拟网 IP 如 100.64.0.2)
       (方式 2: 家用宽带 DDNS 动态域名如 home.xxx.com)
                       │
┌──────────────────────┴───────────────────────┐
│       WorkBuddy 对话孵化的高配沙箱 (内网)     │
│       (32核 CPU / 123G 内存 / Ubuntu 24.04)  │
│                                              │
│ • autossh + tunnel-guard.sh (探活+17s自愈)   │
│ • anti-sleep.py (每20s刷时间戳破300s休眠)    │
│ • xrdp + GNOME 桌面 (D-Bus 容器伪装)         │
│ • PM2 守护 AI 工具链 (Mihomo/CPA/Hermes)     │
└──────────────────────────────────────────────┘
```

---

## 阶段一：本地电脑（Windows）前置就绪准备（仅需配一次）

让你的本地电脑具备安全接收沙箱反向隧道的能力：

### 1. 开启 Windows 原生 OpenSSH 服务端
以**管理员身份**打开 Windows PowerShell，执行：
```powershell
# 安装并启动 OpenSSH 服务
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType "Automatic"
```

### 2. 开启反向端口绑定（核心配置）
编辑 `C:\ProgramData\ssh\sshd_config`（可用管理员记事本打开），在末尾确保包含两行：
```text
GatewayPorts yes
AllowTcpForwarding yes
```
并在 PowerShell 中重启服务：
```powershell
Restart-Service sshd
```

### 3. 获取本地电脑的“沙箱可达地址”（2 选 1）
* **方案 A（最省心，无需公网IP）：Tailscale / 虚拟内网**
  * 本地电脑安装登录 [Tailscale](https://tailscale.com/)，获得一个固定的内网虚拟 IP（如 `100.64.0.2`）。
* **方案 B（传统模式）：家用宽带公网 IP / IPv6 + DDNS**
  * 路由器配置 DDNS（如 `home.yourdomain.com`）并将外部端口转发至本地电脑的 22 端口。

---

## 阶段二：借由头触发 — 让 WorkBuddy 动态孵化高配沙箱

1. **打开 WorkBuddy 应用**（个人 AI 智能体对话界面）。
2. **下发项目构建任务（“借由头”）**：
   在聊天框中向 WorkBuddy 发送一条能触发其拉取代码、安装环境与长期运行的任务 Prompt，例如：
   > *“帮我从 GitHub 部署开源项目 memorycore：拉取代码并安装 Python 依赖，启动服务并保持运行。”*
3. **沙箱分配与就绪**：
   * WorkBuddy 收到任务后，后台会自动触发资源编排，秒级调度并启动一个 **32 核 CPU / 123G 内存 / 256G 磁盘** 的 Ubuntu 24.04 容器沙箱。
   * Agent 会开始在沙箱 `/workspace` 内执行 `git clone` 和代码分析。
   * **此时，豪华硬件沙箱已正式诞生！**

---

## 阶段三：下发初始化指令 — 在沙箱内植入基础环境

在 WorkBuddy 对话框中直接命令它执行，或者在 WorkBuddy 提供的内置终端中运行以下单条命令：

```bash
# 1. 设置 root 密码为 xinxin123 并安装穿透与桌面套件
echo 'root:xinxin123' | chpasswd
apt-get update -y
apt-get install -y openssh-server xrdp ubuntu-desktop-minimal ttyd autossh sshpass locales language-pack-zh-hans fonts-wqy-microhei

# 2. 开启 sshd 密码登录
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
service ssh start

# 3. 解决容器无 systemd 权限：伪装 D-Bus 系统总线 (彻底根除 GNOME 桌面秒退)
mkdir -p /run/dbus
dbus-daemon --session --address=unix:path=/run/dbus/system_bus_socket --fork --nopidfile

# 4. 配置 GNOME 桌面入口并调优性能 (16位色直降 50% 数据流，关闭 CPU 软解动效)
cat << "EOF" > /root/.xsession
#!/bin/bash
export LANG=zh_CN.UTF-8
export LANGUAGE=zh_CN:zh
export LC_ALL=zh_CN.UTF-8
export XDG_CURRENT_DESKTOP=ubuntu:GNOME
export XDG_SESSION_TYPE=x11
export XDG_CONFIG_DIRS=/etc/xdg/xdg-ubuntu:/etc/xdg
export XDG_DATA_DIRS=/usr/share/ubuntu:/usr/local/share:/usr/share
export GNOME_SHELL_SESSION_MODE=ubuntu

(
    sleep 2
    gsettings set org.gnome.desktop.interface enable-animations false 2>/dev/null || true
    gsettings set org.gnome.desktop.interface color-scheme "prefer-dark" 2>/dev/null || true
    gsettings set org.gnome.desktop.interface gtk-theme "Yaru-dark" 2>/dev/null || true
) &

dbus-run-session -- gnome-session --session=ubuntu
EOF
chmod +x /root/.xsession

# 调优 xrdp.ini
sed -i "s/^max_bpp=.*/max_bpp=16/" /etc/xrdp/xrdp.ini
sed -i "s/^crypt_level=.*/crypt_level=none/" /etc/xrdp/xrdp.ini
sed -i "s/^#\?tcp_send_buffer_bytes=.*/tcp_send_buffer_bytes=4194304/" /etc/xrdp/xrdp.ini
sed -i "s/^#\?tcp_recv_buffer_bytes=.*/tcp_recv_buffer_bytes=4194304/" /etc/xrdp/xrdp.ini
service xrdp start
```

---

## 阶段四：沙箱免密绑定本地电脑

在沙箱终端中生成密钥，并将其绑定到你的本地电脑（以 Tailscale 虚拟 IP `100.64.0.2`、Windows 用户名 `e-pengyang.DU` 为例）：

```bash
# 1. 生成沙箱自身密钥
[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519

# 2. 将沙箱公钥自动安装至你本地电脑 (替换为你的本地电脑 IP 与登录密码)
LOCAL_PC="100.64.0.2"
LOCAL_USER="e-pengyang.DU"
ssh-copy-id -o StrictHostKeyChecking=no $LOCAL_USER@$LOCAL_PC
```

---

## 阶段五：部署永续双守护（反休眠 + 隧穿直达本地）

### 1. 部署防休眠守护 (`anti-sleep.py`)
原地覆盖更新 `sessions.json` 时间戳，永久破解 WorkBuddy 300 秒空闲回收：
```bash
mkdir -p /workspace/webtty

cat << "EOF" > /workspace/webtty/anti-sleep.py
#!/usr/bin/env python3
import time, json, os, urllib.request, fcntl

LOCK_FILE = "/tmp/anti-sleep.lock"
SESSION_FILE = "/root/proxy/data/sessions.json"

def acquire_lock():
    f = open(LOCK_FILE, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        f.write(str(os.getpid()))
        f.flush()
        return f
    except BlockingIOError:
        return None

def touch_sessions():
    if not os.path.exists(SESSION_FILE):
        return
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        now_ns = int(time.time() * 1e9)
        for s in data.get("sessions", []):
            s["lastPromptTime"] = now_ns
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def ping_health():
    try:
        urllib.request.urlopen("http://127.0.0.1:3000/", timeout=3)
    except Exception:
        pass

def main():
    lock = acquire_lock()
    if not lock:
        return
    while True:
        touch_sessions()
        ping_health()
        time.sleep(20)

if __name__ == "__main__":
    main()
EOF
chmod +x /workspace/webtty/anti-sleep.py
```

### 2. 部署直通本地电脑的隧道轮询守护 (`tunnel-guard.sh`)
将目标设置为你本地电脑的地址，每 20 秒双条件探活，断线 17 秒内自愈：
```bash
cat << "EOF" > /workspace/webtty/tunnel-guard.sh
#!/bin/bash
# 目标换成你本地电脑的 IP (如 Tailscale 虚拟 IP 或 DDNS 域名)
TARGET_HOST="100.64.0.2"
TARGET_USER="e-pengyang.DU"
LOG="/tmp/guard.log"

tunnel_alive() {
  ss -tn 2>/dev/null | grep -q "$TARGET_HOST:22" && \
  timeout 6 bash -c "exec 3<>/dev/tcp/$TARGET_HOST/3389" 2>/dev/null
}

start_tunnel() {
  echo "[$(date '+%F %T')] 隧道丢失，清理僵尸进程..." >> "$LOG"
  for p in $(pgrep -f "ExitOnForwardFailure=yes -N -R 0.0.0.0" 2>/dev/null); do
    [ "$p" != "$$" ] && kill -9 "$p" 2>/dev/null
  done
  sleep 2
  echo "[$(date '+%F %T')] 发起 autossh 反向穿透至本地电脑..." >> "$LOG"
  autossh -M 0 -f -o StrictHostKeyChecking=no -o ServerAliveInterval=20 \
    -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -N \
    -R 0.0.0.0:2222:localhost:22 -R 0.0.0.0:3389:localhost:3389 $TARGET_USER@$TARGET_HOST
}

while true; do
  if ! tunnel_alive; then
    start_tunnel
    sleep 15
  fi
  sleep 20
done
EOF
chmod +x /workspace/webtty/tunnel-guard.sh
```

### 3. 利用 WorkBuddy“发布应用”固化开机自愈链
```bash
cd /root/.codebuddy/skills/发布为应用 && node scripts/publish.js \
  --dir /workspace/webtty \
  --language python \
  --install-cmd "" \
  --start-cmd 'bash -c "{ pgrep -x sshd >/dev/null || (service ssh start || /usr/sbin/sshd); }; { ls /run/dbus/system_bus_socket >/dev/null 2>&1 || (mkdir -p /run/dbus && dbus-daemon --session --address=unix:path=/run/dbus/system_bus_socket --fork --nopidfile); }; { pgrep -x xrdp >/dev/null || (service xrdp start || (xrdp-sesman; xrdp)); }; { ps -eo args | grep \"[a]nti-sleep.py\" >/dev/null || (nohup python3 /workspace/webtty/anti-sleep.py >/dev/null 2>&1 &); }; { ps -eo args | grep \"[t]unnel-guard\" >/dev/null || (nohup bash /workspace/webtty/tunnel-guard.sh > /tmp/guard.log 2>&1 &); }; exec ttyd -p $PORT --writable bash"'
```

---

## 阶段六：本地电脑极致秒连验收（享受零公网延迟）

反向隧道打通后，沙箱的端口已**直接绑定在你的本地电脑上**！

### 1. SSH 终端本地直入
在你本地 Windows 终端/PowerShell 直接执行：
```bash
ssh -p 2222 root@127.0.0.1
# 输入密码 xinxin123，瞬间直连！
```

### 2. Windows 远程桌面 (MSTSC) 本地秒开
* 打开 Windows **远程桌面连接 (mstsc)**。
* 计算机地址直接输入：
  ```text
  127.0.0.1:3389
  ```
* 用户名：`root`，密码：`xinxin123`。
* **画面走本地总线传输，延迟低于 2ms，告别任何公网卡顿与限速！**

### 3. Hermes Desktop 一键直通
在 Windows 端的 `connections.json` 中配置：
* `host`: `"127.0.0.1"`
* `port`: `2222`
* `user`: `"root"`
* 点击即可在 Hermes Desktop 中一键操控沙箱内的大脑！
