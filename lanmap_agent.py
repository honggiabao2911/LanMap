"""
LanMap Client Agent v2.0 — Siêu nhẹ RAM, Điều khoản sử dụng, Tự báo danh Server & Điều khiển Từ xa
- Lần đầu mở yêu cầu đọc & đồng ý Điều khoản sử dụng + đặt Tên máy / Chủ máy gửi lên LanMap Server.
- Tự động báo danh qua UDP 55125 để LanMap Server quét là biết ngay máy nào cài Client & của ai.
- Hỗ trợ 1-click kích hoạt Wake-on-LAN (WoL) để Server có thể bật máy từ xa.
- Tối ưu RAM tối đa: chỉ nạp thư viện ảnh (PIL) khi Server thực sự mở xem màn hình, giải phóng bộ nhớ ngay sau mỗi khung hình.
- Đóng gói .exe:
    pyinstaller --onefile --windowed --name LanMap_Client --icon=LanMap-Laptop.ico --add-data "LanMap-Laptop.ico;." --collect-data customtkinter lanmap_agent.py
"""

from __future__ import annotations

import base64
import ctypes
from datetime import datetime
import gc
import io
import json
import os
from pathlib import Path
import platform
import queue
import socket
import subprocess
import sys
import threading
import time
from tkinter import messagebox
from typing import Any
import uuid
import webbrowser

import customtkinter as ctk

try:
    import psutil  # type: ignore
except Exception:
    psutil = None

AGENT_PORT = 55124
DISCOVER_PORT = 55125

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002

VK_MAP: dict[str, int] = {
    "Return": 0x0D, "BackSpace": 0x08, "Tab": 0x09, "Escape": 0x1B, "space": 0x20,
    "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28, "Delete": 0x2E,
    "Home": 0x24, "End": 0x23, "Prior": 0x21, "Next": 0x22, "Win": 0x5B,
}

TERMS_TEXT = """ĐIỀU KHOẢN SỬ DỤNG & QUYỀN QUẢN TRỊ NỘI BỘ (LANMAP CLIENT)

1. Mục đích sử dụng:
   Ứng dụng LanMap Client dùng để kết nối máy tính này vào hệ thống quản trị mạng nội bộ (LanMap Server) của phòng máy / cơ quan.

2. Thông tin được đồng bộ lên LanMap Server:
   - Tên hiển thị & tên chủ máy do bạn tự đặt.
   - Địa chỉ IP, địa chỉ MAC (phục vụ bật máy từ xa Wake-on-LAN) và tên máy tính.
   - Thông số phần cứng (Hệ điều hành, CPU, RAM, ổ đĩa) khi quản trị viên kiểm tra.

3. Quyền kiểm soát & bảo mật của bạn:
   - Mọi kết nối điều khiển (xem màn hình, chuột/bàn phím, CMD, gửi file) đều yêu cầu đúng Mã PIN do bạn cài đặt.
   - Bạn có quyền chọn chế độ hỏi ĐỒNG Ý 1 lần trước khi cấp phiên điều khiển và có nút đỏ "Ngắt Admin" để dừng bất cứ lúc nào.
   - Mọi thao tác từ máy quản trị đều được ghi lại minh bạch trong nhật ký của máy này."""


def now_t() -> str:
    return datetime.now().strftime("%H:%M:%S")


def get_config_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LanMapClient"
    base.mkdir(parents=True, exist_ok=True)
    return base / "client_config.json"


def load_config() -> dict[str, Any]:
    p = get_config_path()
    default = {
        "accepted_terms": False,
        "display_name": socket.gethostname(),
        "owner": os.environ.get("USERNAME", "Nhân viên"),
        "pin": "123456",
        "ask_consent": True,
        "autostart": False,
    }
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                default.update(data)
        except Exception:
            pass
    return default


def save_config(cfg: dict[str, Any]) -> None:
    try:
        get_config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def find_asset(filename: str) -> Path | None:
    cands: list[Path] = []
    if getattr(sys, "_MEIPASS", None):
        cands.append(Path(sys._MEIPASS) / filename)  # type: ignore[attr-defined]
    if getattr(sys, "frozen", False):
        cands.append(Path(sys.executable).resolve().parent / filename)
    try:
        cands.append(Path(__file__).resolve().parent / filename)
    except Exception:
        pass
    cands.append(Path.cwd() / filename)
    for c in cands:
        if c.exists():
            return c
    return None


def get_receive_dir() -> Path:
    d = Path.home() / "Downloads" / "LanMap_Received"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def get_local_mac() -> str:
    ip = get_local_ip()
    if psutil is not None:
        try:
            for _, addrs in psutil.net_if_addrs().items():
                if any(a.address == ip for a in addrs):
                    for a in addrs:
                        if getattr(a, "family", None) == getattr(psutil, "AF_LINK", -1) and a.address:
                            return a.address.replace("-", ":").upper()
        except Exception:
            pass
    node = uuid.getnode()
    return ":".join(f"{(node >> shift) & 0xFF:02X}" for shift in range(40, -1, -8))


def enable_wol_windows() -> tuple[bool, str]:
    """Kích hoạt Wake-on-LAN (Magic Packet) trên card mạng Windows để LanMap Server có thể bật máy từ xa."""
    if sys.platform != "win32":
        return False, "Chỉ hỗ trợ tự động bật Wake-on-LAN trên Windows."
    ps = (
        "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | ForEach-Object { "
        "Enable-NetAdapterPowerManagement -Name $_.Name -WakeOnMagicPacket -ErrorAction SilentlyContinue; "
        "Set-NetAdapterAdvancedProperty -Name $_.Name -DisplayName '*Wake on Magic Packet*' -DisplayValue 'Enabled' -ErrorAction SilentlyContinue "
        "}; Write-Output 'OK'"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
        if r.returncode == 0:
            return True, (
                f"✓ Đã gửi cấu hình bật Wake-on-LAN (Magic Packet) cho card mạng!\n"
                f"Địa chỉ MAC của máy này: {get_local_mac()}\n\n"
                f"Lưu ý: Để bật máy khi tắt hẳn nguồn, hãy đảm bảo trong BIOS/UEFI cũng đã bật 'Wake on LAN' và máy cắm dây LAN."
            )
        return False, "Cần chạy LanMap Client bằng quyền Administrator (Run as administrator) để tự động bật WoL trên card mạng."
    except Exception as exc:
        return False, f"Không cấu hình được WoL: {exc}"


def set_windows_autostart(enable: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        import winreg  # type: ignore
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        if enable:
            cmd = f'"{sys.executable}"' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve()}"'
            winreg.SetValueEx(key, "LanMapClient", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, "LanMapClient")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception:
        pass


def capture_screen_jpeg_b64(max_w: int = 900, quality: int = 50) -> dict[str, Any]:
    """Chỉ nạp Pillow khi Server thực sự yêu cầu xem màn hình -> tiết kiệm tối đa RAM khi chạy nền!"""
    try:
        from PIL import Image, ImageGrab  # type: ignore
    except Exception:
        return {"ok": False, "error": "Máy Client chưa cài Pillow (pip install pillow) để chụp màn hình."}
    try:
        img = ImageGrab.grab().convert("RGB")
        sw, sh = img.size
        if sw > max_w:
            nh = int(sh * (max_w / sw))
            img = img.resize((max_w, nh), Image.Resampling.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        w_out, h_out = img.width, img.height
        img.close()
        buf.close()
        gc.collect()
        return {"ok": True, "sw": sw, "sh": sh, "w": w_out, "h": h_out, "jpg": b64}
    except Exception as exc:
        return {"ok": False, "error": f"Không chụp được màn hình: {exc}"}


def perform_remote_mouse(data: dict[str, Any]) -> None:
    if sys.platform != "win32":
        return
    u32 = ctypes.windll.user32
    sw, sh = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)
    rx = max(0.0, min(1.0, float(data.get("rx", 0.5))))
    ry = max(0.0, min(1.0, float(data.get("ry", 0.5))))
    x, y = int(rx * sw), int(ry * sh)
    ev = str(data.get("ev", "click"))
    u32.SetCursorPos(x, y)
    if ev == "click":
        u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    elif ev == "dblclick":
        for _ in range(2):
            u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.04)
    elif ev == "rclick":
        u32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        u32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    elif ev == "scroll":
        u32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(data.get("delta", 120)), 0)


def perform_remote_key(data: dict[str, Any]) -> None:
    if sys.platform != "win32":
        return
    u32 = ctypes.windll.user32
    combo = str(data.get("combo", ""))
    if combo:
        if combo == "Win":
            u32.keybd_event(0x5B, 0, 0, 0)
            u32.keybd_event(0x5B, 0, KEYEVENTF_KEYUP, 0)
        elif combo == "Alt+Tab":
            u32.keybd_event(0x12, 0, 0, 0)
            u32.keybd_event(0x09, 0, 0, 0)
            u32.keybd_event(0x09, 0, KEYEVENTF_KEYUP, 0)
            u32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)
        elif combo.startswith("Ctrl+") and len(combo) == 6:
            vk = ord(combo[-1].upper())
            u32.keybd_event(0x11, 0, 0, 0)
            u32.keybd_event(vk, 0, 0, 0)
            u32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            u32.keybd_event(0x11, 0, KEYEVENTF_KEYUP, 0)
        return
    keysym = str(data.get("keysym", ""))
    char = str(data.get("char", ""))
    if keysym in VK_MAP:
        vk = VK_MAP[keysym]
        u32.keybd_event(vk, 0, 0, 0)
        u32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    elif char and len(char) == 1:
        vk_scan = u32.VkKeyScanW(ord(char))
        if vk_scan != -1:
            vk = vk_scan & 0xFF
            shift = bool((vk_scan >> 8) & 1)
            if shift:
                u32.keybd_event(0x10, 0, 0, 0)
            u32.keybd_event(vk, 0, 0, 0)
            u32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            if shift:
                u32.keybd_event(0x10, 0, KEYEVENTF_KEYUP, 0)


def collect_sysinfo_report(display_name: str, owner: str) -> str:
    lines = [
        "=== THÔNG TIN MÁY TRẠM (LANMAP CLIENT v2.0) ===",
        f"Tên hiển thị   : {display_name}",
        f"Chủ máy / Phòng: {owner}",
        f"Tên Windows    : {socket.gethostname()}",
        f"IP / MAC (WoL) : {get_local_ip()}  |  {get_local_mac()}",
        f"Hệ điều hành   : {platform.system()} {platform.release()}",
    ]
    if psutil is not None:
        cpu = psutil.cpu_percent(interval=0.25)
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\" if sys.platform == "win32" else "/")
        lines.extend([
            f"CPU hiện tại   : {cpu:.1f}% ({psutil.cpu_count(logical=True)} luồng)",
            f"RAM đang dùng  : {vm.used / (1024**3):.2f} / {vm.total / (1024**3):.2f} GB ({vm.percent:.0f}%)",
            f"Ổ đĩa chính    : Trống {disk.free / (1024**3):.1f} / {disk.total / (1024**3):.1f} GB",
        ])
    return "\n".join(lines)


def collect_top_processes() -> str:
    if psutil is None:
        return "Máy Client chưa cài psutil."
    rows: list[tuple[float, str, int]] = []
    for proc in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            mem = float(proc.info.get("memory_percent") or 0.0)
            rows.append((mem, str(proc.info.get("name") or "?"), int(proc.info.get("pid") or 0)))
        except Exception:
            continue
    rows.sort(reverse=True)
    return "=== TOP 20 ỨNG DỤNG ĐANG CHẠY ===\n" + "\n".join(f"  PID {pid:<6} | RAM {mem:5.1f}% | {name}" for mem, name, pid in rows[:20])


class OnboardingDialog(ctk.CTkToplevel):
    """Hộp thoại Điều khoản sử dụng & Đặt tên máy khi lần đầu cài/mở LanMap Client."""

    def __init__(self, master: ctk.CTk, cfg: dict[str, Any]) -> None:
        super().__init__(master)
        self.title("Thiết lập lần đầu & Điều khoản sử dụng — LanMap Client")
        self.geometry("560x530")
        self.minsize(520, 480)
        self.accepted = False
        self.cfg = dict(cfg)
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        ctk.CTkLabel(self, text="Thiết lập máy trạm LanMap Client", font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w", padx=18, pady=(14, 2))
        ctk.CTkLabel(self, text="Đặt tên gợi nhớ để LanMap Server nhận ra ngay máy này là của ai khi quét mạng:", font=ctk.CTkFont(size=12), text_color=("gray35", "gray70")).pack(anchor="w", padx=18, pady=(0, 8))

        form = ctk.CTkFrame(self, corner_radius=8)
        form.pack(fill="x", padx=18, pady=(0, 8))
        r1 = ctk.CTkFrame(form, fg_color="transparent")
        r1.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(r1, text="Tên máy hiển thị:", width=125, anchor="w", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
        self.name_e = ctk.CTkEntry(r1, placeholder_text="VD: Máy Kế toán 01 - A.Bảo")
        self.name_e.insert(0, str(cfg.get("display_name", socket.gethostname())))
        self.name_e.pack(side="left", fill="x", expand=True)

        r2 = ctk.CTkFrame(form, fg_color="transparent")
        r2.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(r2, text="Chủ máy / Phòng:", width=125, anchor="w", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
        self.owner_e = ctk.CTkEntry(r2, placeholder_text="VD: Gia Bảo - Tầng 2")
        self.owner_e.insert(0, str(cfg.get("owner", "")))
        self.owner_e.pack(side="left", fill="x", expand=True)

        r3 = ctk.CTkFrame(form, fg_color="transparent")
        r3.pack(fill="x", padx=10, pady=(4, 8))
        ctk.CTkLabel(r3, text="Mã PIN bảo vệ:", width=125, anchor="w", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
        self.pin_e = ctk.CTkEntry(r3, width=130)
        self.pin_e.insert(0, str(cfg.get("pin", "123456")))
        self.pin_e.pack(side="left")

        box = ctk.CTkTextbox(self, height=170, font=ctk.CTkFont(size=11))
        box.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        box.insert("1.0", TERMS_TEXT)
        box.configure(state="disabled")

        self.agree_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="Tôi đã đọc và ĐỒNG Ý với điều khoản kết nối quản trị mạng nội bộ", variable=self.agree_var, font=ctk.CTkFont(size=12, weight="bold"), command=self._toggle_btn).pack(anchor="w", padx=18, pady=(0, 8))

        brow = ctk.CTkFrame(self, fg_color="transparent")
        brow.pack(fill="x", padx=18, pady=(0, 14))
        ctk.CTkButton(brow, text="Thoát", width=84, fg_color="transparent", border_width=1, text_color=("gray15", "gray90"), command=self.destroy).pack(side="right", padx=(8, 0))
        self.ok_btn = ctk.CTkButton(brow, text="✓ Đồng ý & Bắt đầu chạy Client", width=210, height=34, state="disabled", fg_color="#0f766e", font=ctk.CTkFont(size=12, weight="bold"), command=self._save)
        self.ok_btn.pack(side="right")

    def _toggle_btn(self) -> None:
        self.ok_btn.configure(state="normal" if self.agree_var.get() else "disabled")

    def _save(self) -> None:
        self.cfg["accepted_terms"] = True
        self.cfg["display_name"] = self.name_e.get().strip() or socket.gethostname()
        self.cfg["owner"] = self.owner_e.get().strip() or "Nhân viên"
        self.cfg["pin"] = self.pin_e.get().strip() or "123456"
        self.accepted = True
        self.destroy()


class LanMapClientApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_config()
        self.title("LanMap Client Agent v2.0 — Nhẹ, Mượt & Tự Báo Danh")
        self.geometry("560x500")
        self.minsize(500, 440)
        self._stop = threading.Event()
        self._ui_q: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._approved_admins: set[str] = set()
        self._my_mac = get_local_mac()

        ico = find_asset("LanMap-Laptop.ico")
        if ico and ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass

        if not self.cfg.get("accepted_terms"):
            self.withdraw()
            dlg = OnboardingDialog(self, self.cfg)
            self.wait_window(dlg)
            if not dlg.accepted:
                self.destroy()
                sys.exit(0)
            self.cfg = dlg.cfg
            save_config(self.cfg)
            self.deiconify()

        head = ctk.CTkFrame(self, corner_radius=0, fg_color="#0f2a52")
        head.pack(fill="x")
        ctk.CTkLabel(head, text="LanMap Client Agent v2.0", font=ctk.CTkFont(size=18, weight="bold"), text_color="#ffffff").pack(anchor="w", padx=16, pady=(10, 2))
        ctk.CTkLabel(head, text=f"IP: {get_local_ip()}  |  MAC (WoL): {self._my_mac}  |  Cổng: {AGENT_PORT}", font=ctk.CTkFont(size=11), text_color="#bae6fd").pack(anchor="w", padx=16, pady=(0, 10))

        cfg_box = ctk.CTkFrame(self, corner_radius=8)
        cfg_box.pack(fill="x", padx=14, pady=(10, 6))

        r1 = ctk.CTkFrame(cfg_box, fg_color="transparent")
        r1.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(r1, text="Tên báo Server:", width=102, anchor="w", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        self.name_var = ctk.StringVar(value=str(self.cfg.get("display_name", socket.gethostname())))
        ctk.CTkEntry(r1, textvariable=self.name_var, height=28).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkLabel(r1, text="Chủ máy:", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=(2, 4))
        self.owner_var = ctk.StringVar(value=str(self.cfg.get("owner", "")))
        ctk.CTkEntry(r1, textvariable=self.owner_var, width=110, height=28).pack(side="left")

        r2 = ctk.CTkFrame(cfg_box, fg_color="transparent")
        r2.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(r2, text="Mã PIN:", width=56, anchor="w", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        self.pin_var = ctk.StringVar(value=str(self.cfg.get("pin", "123456")))
        ctk.CTkEntry(r2, textvariable=self.pin_var, width=82, height=28).pack(side="left", padx=(0, 6))
        ctk.CTkButton(r2, text="💾 Lưu & Báo Server", width=132, height=28, fg_color="#0284c7", command=self._save_and_announce).pack(side="left", padx=(0, 6))
        ctk.CTkButton(r2, text="⚡ Bật WoL (Bật máy từ xa)", width=155, height=28, fg_color="#b45309", hover_color="#92400e", command=self._setup_wol).pack(side="right")

        r3 = ctk.CTkFrame(cfg_box, fg_color="transparent")
        r3.pack(fill="x", padx=10, pady=(2, 8))
        self.consent_var = ctk.BooleanVar(value=bool(self.cfg.get("ask_consent", True)))
        ctk.CTkCheckBox(r3, text="Hỏi đồng ý 1 lần/phiên", variable=self.consent_var, font=ctk.CTkFont(size=11), command=self._save_opts).pack(side="left", padx=(0, 12))
        self.auto_var = ctk.BooleanVar(value=bool(self.cfg.get("autostart", False)))
        ctk.CTkCheckBox(r3, text="Chạy cùng Windows", variable=self.auto_var, font=ctk.CTkFont(size=11), command=self._save_opts).pack(side="left")
        ctk.CTkButton(r3, text="📂 Thư mục nhận", width=108, height=24, fg_color="#0f766e", font=ctk.CTkFont(size=11), command=self._open_recv_dir).pack(side="right", padx=(4, 0))
        self.revoke_btn = ctk.CTkButton(r3, text="⛔ Ngắt Admin", width=92, height=24, fg_color="#dc2626", font=ctk.CTkFont(size=11), state="disabled", command=self._revoke_all)
        self.revoke_btn.pack(side="right")

        self.stat_lbl = ctk.CTkLabel(self, text="● Đang phát tín hiệu báo danh tới LanMap Server (chế độ tiết kiệm RAM)...", font=ctk.CTkFont(size=11, weight="bold"), text_color="#16a34a", anchor="w")
        self.stat_lbl.pack(fill="x", padx=16, pady=(2, 4))

        self.log_box = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Consolas", size=11))
        self.log_box.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self._log(f"Đang chạy nhẹ nhàng | Tên báo Server: '{self.name_var.get()}' | MAC: {self._my_mac}")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self._server_loop, daemon=True).start()
        threading.Thread(target=self._discovery_beacon_loop, daemon=True).start()
        self.after(150, self._poll_ui)

    def _beacon_payload(self) -> bytes:
        return json.dumps({
            "app": "LanMapClient",
            "name": self.name_var.get().strip() or socket.gethostname(),
            "owner": self.owner_var.get().strip() or "Nhân viên",
            "hostname": socket.gethostname(),
            "ip": get_local_ip(),
            "mac": self._my_mac,
            "port": AGENT_PORT,
        }, ensure_ascii=False).encode("utf-8")

    def _broadcast_presence(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(self._beacon_payload(), ("255.255.255.255", DISCOVER_PORT))
        except Exception:
            pass

    def _discovery_beacon_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", DISCOVER_PORT))
            sock.settimeout(2.0)
        except Exception:
            sock = None

        last_bcast = 0.0
        while not self._stop.is_set():
            now_m = time.monotonic()
            if now_m - last_bcast >= 10.0:
                self._broadcast_presence()
                last_bcast = now_m
            if sock is not None:
                try:
                    data, addr = sock.recvfrom(1024)
                    if b"DISCOVER_LANMAP_CLIENT" in data:
                        sock.sendto(self._beacon_payload(), addr)
                except socket.timeout:
                    continue
                except Exception:
                    pass
            else:
                time.sleep(2.0)
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    def _save_opts(self) -> None:
        self.cfg["ask_consent"] = self.consent_var.get()
        self.cfg["autostart"] = self.auto_var.get()
        save_config(self.cfg)
        set_windows_autostart(self.auto_var.get())

    def _save_and_announce(self) -> None:
        self.cfg["display_name"] = self.name_var.get().strip() or socket.gethostname()
        self.cfg["owner"] = self.owner_var.get().strip() or "Nhân viên"
        self.cfg["pin"] = self.pin_var.get().strip() or "123456"
        save_config(self.cfg)
        self._broadcast_presence()
        self._log(f"✓ Đã lưu & gửi tên '{self.cfg['display_name']}' ({self.cfg['owner']}) lên LanMap Server!")

    def _setup_wol(self) -> None:
        ok, msg = enable_wol_windows()
        self._log(msg.splitlines()[0])
        messagebox.showinfo("Wake-on-LAN (Bật máy từ xa)", msg) if ok else messagebox.showwarning("Wake-on-LAN", msg)

    def _open_recv_dir(self) -> None:
        if sys.platform == "win32":
            os.startfile(str(get_receive_dir()))  # type: ignore[attr-defined]

    def _log(self, msg: str) -> None:
        self.log_box.insert("end", f"[{now_t()}] {msg}\n")
        if int(self.log_box.index("end-1c").split(".")[0]) > 150:
            self.log_box.delete("1.0", "30.0")
        self.log_box.see("end")

    def _revoke_all(self) -> None:
        self._approved_admins.clear()
        self.revoke_btn.configure(state="disabled")
        self.stat_lbl.configure(text="● Đã ngắt phiên Admin — Đang chạy nền tiết kiệm RAM...", text_color="#16a34a")
        self._log("⛔ Đã ngắt quyền điều khiển của Admin.")

    def _ask_session_consent(self, sender: str, admin_ip: str) -> bool:
        if not self.consent_var.get() or admin_ip in self._approved_admins:
            self._approved_admins.add(admin_ip)
            return True
        ev = threading.Event()
        res = {"allow": False}
        self._ui_q.put(("confirm_session", (sender, admin_ip, ev, res)))
        ev.wait(20.0)
        if res["allow"]:
            self._approved_admins.add(admin_ip)
        return res["allow"]

    def _server_loop(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("", AGENT_PORT))
            srv.listen(16)
            srv.settimeout(1.0)
            while not self._stop.is_set():
                try:
                    conn, addr = srv.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self._handle_client, args=(conn, addr[0]), daemon=True).start()
        except Exception as exc:
            self._ui_q.put(("log", f"Lỗi mở cổng {AGENT_PORT}: {exc}"))
        finally:
            try:
                srv.close()
            except Exception:
                pass

    def _handle_client(self, conn: socket.socket, admin_ip: str) -> None:
        try:
            conn.settimeout(15.0)
            chunks: list[bytes] = []
            total_len = 0
            while total_len < 75 * 1024 * 1024:
                ch = conn.recv(65536)
                if not ch:
                    break
                chunks.append(ch)
                total_len += len(ch)
                if b"\n" in ch:
                    break
            req = json.loads(b"".join(chunks).decode("utf-8", errors="ignore").strip())
            act = str(req.get("action", "sysinfo"))
            if act == "hello":
                resp: dict[str, Any] = {
                    "ok": True,
                    "app": "LanMapClient",
                    "name": self.name_var.get().strip() or socket.gethostname(),
                    "owner": self.owner_var.get().strip() or "Nhân viên",
                    "mac": self._my_mac,
                }
            elif str(req.get("pin", "")) != self.pin_var.get().strip():
                resp = {"ok": False, "error": "Sai mã PIN ghép nối!"}
                self._ui_q.put(("log", f"Từ chối kết nối từ {admin_ip} (sai mã PIN)."))
            else:
                sender = str(req.get("from", admin_ip))
                payload = str(req.get("payload", "")).strip()
                dname = self.name_var.get().strip() or socket.gethostname()
                owner = self.owner_var.get().strip() or "Nhân viên"

                if act == "auth":
                    if self._ask_session_consent(sender, admin_ip):
                        self._ui_q.put(("approved", (sender, admin_ip)))
                        resp = {"ok": True, "host": dname, "report": collect_sysinfo_report(dname, owner)}
                    else:
                        resp = {"ok": False, "error": f"Người dùng trên '{dname}' đã TỪ CHỐI phiên kết nối."}
                elif admin_ip not in self._approved_admins and self.consent_var.get():
                    resp = {"ok": False, "error": "Phiên điều khiển đã bị ngắt hoặc chưa xác nhận PIN."}
                elif act == "sysinfo":
                    resp = {"ok": True, "report": collect_sysinfo_report(dname, owner)}
                elif act == "procs":
                    resp = {"ok": True, "report": collect_top_processes()}
                elif act == "notify":
                    self._ui_q.put(("notify", (sender, admin_ip, payload)))
                    resp = {"ok": True, "report": f"✓ Đã hiện thông báo trên '{dname}'."}
                elif act == "open_url":
                    webbrowser.open(payload)
                    self._ui_q.put(("log", f"🌐 Mở link từ {sender}: {payload}"))
                    resp = {"ok": True, "report": f"✓ Đã mở: {payload}"}
                elif act == "lock_screen":
                    if sys.platform == "win32":
                        ctypes.windll.user32.LockWorkStation()
                    self._ui_q.put(("log", f"🔒 Khóa màn hình theo lệnh của {sender}."))
                    resp = {"ok": True, "report": f"✓ Đã khóa màn hình '{dname}'."}
                elif act == "send_file":
                    fobj = json.loads(payload)
                    fname = Path(str(fobj.get("name", "file.bin"))).name
                    fbytes = base64.b64decode(str(fobj.get("b64", "")))
                    dest = get_receive_dir() / fname
                    cnt = 1
                    while dest.exists():
                        dest = get_receive_dir() / f"{dest.stem}_{cnt}{dest.suffix}"
                        cnt += 1
                    dest.write_bytes(fbytes)
                    sz_kb = len(fbytes) / 1024.0
                    self._ui_q.put(("file_received", (sender, fname, str(dest), sz_kb)))
                    resp = {"ok": True, "report": f"✓ Đã gửi '{fname}' ({sz_kb:.1f} KB) thành công!\nLưu tại: {dest}"}
                elif act == "cmd":
                    self._ui_q.put(("log", f"💻 CMD ({sender}): {payload}"))
                    try:
                        run_r = subprocess.run(payload, shell=True, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
                        out_txt = (run_r.stdout or "") + (("\n[STDERR]\n" + run_r.stderr) if run_r.stderr else "")
                        resp = {"ok": True, "report": f"> {payload}\n" + "-" * 50 + f"\n{(out_txt.strip() or '(Xong)')[:8000]}"}
                    except Exception as exc:
                        resp = {"ok": False, "error": f"Lỗi CMD: {exc}"}
                elif act == "screen":
                    resp = capture_screen_jpeg_b64()
                elif act == "mouse":
                    perform_remote_mouse(json.loads(payload) if payload else {})
                    resp = {"ok": True}
                elif act == "key":
                    perform_remote_key(json.loads(payload) if payload else {})
                    resp = {"ok": True}
                elif act == "virus_scan":
                    self._ui_q.put(("log", f"🦠 Server ({sender}) yêu cầu quét Virus & kết nối ra ngoài"))
                    try:
                        n1 = psutil.net_io_counters(); time.sleep(0.5); n2 = psutil.net_io_counters()
                        up_kb = (n2.bytes_sent - n1.bytes_sent) / 0.5 / 1024.0
                        sus = []
                        for c in psutil.net_connections(kind="inet"):
                            if c.raddr and not str(c.raddr.ip).startswith(("10.", "192.168.", "127.", "172.")):
                                if c.raddr.port in (4444, 1337, 31337, 6667, 5555, 9001, 9050):
                                    pn = psutil.Process(c.pid).name() if c.pid else "System"
                                    sus.append(f"{pn} -> {c.raddr.ip}:{c.raddr.port}")
                        inf = bool(sus or up_kb > 3500)
                        rep = f"Upload: {up_kb:.1f} KB/s | Kết nối cổng C2 đáng ngờ: {len(sus)}"
                        if sus:
                            rep += "\n  • " + "\n  • ".join(sus[:5])
                        resp = {"ok": True, "infected": inf, "report": rep}
                    except Exception as exc:
                        resp = {"ok": False, "error": str(exc)}
                elif act == "isolate_net":
                    self._ui_q.put(("log", f"🚫 Admin ({sender}) kích hoạt CÔ LẬP MẠNG máy này!"))
                    subprocess.run("ipconfig /release", shell=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
                    resp = {"ok": True, "report": "🚫 Đã thu hồi IP (ipconfig /release) — máy trạm đã được cô lập khỏi mạng!"}
                elif act == "restore_net":
                    self._ui_q.put(("log", f"🔌 Admin ({sender}) khôi phục kết nối mạng!"))
                    subprocess.run("ipconfig /renew", shell=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
                    resp = {"ok": True, "report": "🔌 Đã khôi phục IP động (ipconfig /renew) cho máy trạm!"}
                else:
                    resp = {"ok": False, "error": f"Lệnh không hỗ trợ: {act}"}
            conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _poll_ui(self) -> None:
        try:
            while True:
                kind, data = self._ui_q.get_nowait()
                if kind == "log":
                    self._log(str(data))
                elif kind == "approved":
                    sender, ip = data
                    self.revoke_btn.configure(state="normal")
                    self.stat_lbl.configure(text=f"🔴 Admin {sender} ({ip}) đang kết nối phiên điều khiển!", text_color="#dc2626")
                    self._log(f"✓ Đã cấp quyền phiên cho Admin {sender} ({ip}).")
                elif kind == "notify":
                    sender, ip, msg = data
                    self._log(f"💬 Thông báo từ {sender}: {msg}")
                    messagebox.showinfo(f"💬 Thông báo từ Admin ({sender})", msg)
                elif kind == "file_received":
                    sender, fname, fpath, sz_kb = data
                    self._log(f"📥 Nhận file từ {sender}: {fname} ({sz_kb:.1f} KB)")
                    if messagebox.askyesno("📥 Nhận file mới qua LAN", f"Admin {sender} gửi file: {fname} ({sz_kb:.1f} KB)\nLưu tại: {fpath}\n\nMở thư mục ngay?"):
                        self._open_recv_dir()
                elif kind == "confirm_session":
                    sender, ip, ev, res = data
                    ok = messagebox.askyesno("Yêu cầu kết nối phiên điều khiển (LanMap)", f"Máy Quản trị {sender} ({ip}) muốn kết nối phiên điều khiển (màn hình, chuột/phím, gửi file, CMD).\n\nBạn có ĐỒNG Ý cho phiên này không?")
                    res["allow"] = ok
                    self._log(f"Phiên điều khiển từ {sender} → {'ĐỒNG Ý' if ok else 'TỪ CHỐI'}.")
                    ev.set()
        except queue.Empty:
            pass
        if not self._stop.is_set():
            self.after(150, self._poll_ui)

    def _on_close(self) -> None:
        self._stop.set()
        self.destroy()


if __name__ == "__main__":
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    LanMapClientApp().mainloop()