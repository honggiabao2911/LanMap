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

1. Đổi `APP_VERSION` trong `lanmap.py` rồi commit và push mã nguồn lên `main`.
2. Dùng lệnh dưới đây để tạo `dist\LanMap.exe`. Kiểm tra bằng cách chép riêng file EXE sang một máy Windows 11 x64 chưa cài Python và mở bằng tài khoản thường. Kiểm tra splash, sơ đồ và cửa sổ Kiểm tra cập nhật.
3. GitHub → **Releases → Draft a new release**. Tạo tag tương ứng với mã nguồn đã đẩy, ví dụ `v3.9.1`, chọn nhánh `main`. Gắn `dist\LanMap.exe` và chọn **Set as the latest release** trước khi bấm **Publish release**.

```powershell
python -m PyInstaller --noconfirm LanMap.spec
```

`lanmap_agent.py` và `LanMap_Client.spec` dùng cho LanMap Client. Bản phát hành ứng dụng quản trị dùng asset `LanMap.exe`.
