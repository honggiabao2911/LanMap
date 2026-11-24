# LanMap

Ứng dụng Windows quản lý và giám sát thiết bị mạng nội bộ. LanMap hiển thị sơ đồ thiết bị, theo dõi trạng thái và hỗ trợ kiểm tra dịch vụ trong LAN.

## Tải LanMap cho Windows

[Tải LanMap.exe](https://github.com/honggiabao2911/LanMap/releases/latest/download/LanMap.exe) · [Xem các bản phát hành](https://github.com/honggiabao2911/LanMap/releases)

Tải một file `LanMap.exe` trong phần **Assets** và mở trên Windows 11 x64. Khi mở, LanMap sẽ báo đang chuẩn bị ứng dụng rồi hiện thanh tiến độ. Nếu dùng bản cũ, vào **Công cụ → Kiểm tra cập nhật (GitHub)**, kiểm tra repo `honggiabao2911/LanMap` và tải bản được đề xuất. Đóng LanMap trước khi thay file cũ.

## Chạy từ mã nguồn

Dùng Python 3.13 x64 trên Windows. Mở Terminal của PyCharm với môi trường `.venv` đã kích hoạt.

```powershell
python -m pip install -r requirements.txt
python lanmap.py
```

## Đóng gói và phát hành

1. Cập nhật `APP_VERSION` trong `lanmap.py` và `CLIENT_VERSION` trong `lanmap_agent.py` theo cùng phiên bản. Đưa mã nguồn lên nhánh `main`.
2. Dùng hai lệnh dưới đây để tạo `dist\LanMap.exe` và `dist\LanMap_Client.exe`. Chép từng file EXE sang máy Windows 11 x64 chưa cài Python để thử mở bằng tài khoản thường và kiểm tra nút cập nhật.
3. GitHub → **Releases → Draft a new release**. Tạo tag tương ứng, ví dụ `v3.9.2`, chọn nhánh `main`, đính kèm cả hai file EXE rồi chọn **Set as the latest release** trước khi bấm **Publish release**.

```powershell
python -m PyInstaller --noconfirm LanMap.spec
python -m PyInstaller --noconfirm LanMap_Client.spec
```

## LanMap Client

[Tải LanMap_Client.exe](https://github.com/honggiabao2911/LanMap/releases/latest/download/LanMap_Client.exe)

LanMap Client chạy trên máy Windows cần được quản lý trong LAN. Từ v3.9.2, bấm **Kiểm tra cập nhật** ngay trong cửa sổ Client. Khi có phiên bản mới, Client sẽ mở link tải sau khi bạn xác nhận. Đóng Client rồi thay file cũ bằng file mới.
