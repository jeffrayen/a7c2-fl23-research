# PhotoLUT 照片風格套用

在 Windows 上把 3D LUT（`.cube`）風格批次套用到 JPEG 照片。完全離線，**不連接、不修改相機**，原始照片也不會被改動。

內建風格：**HNCS**（以 Sony A7C II 的 ST 外觀為基礎的哈蘇風格近似，來源見 [NOTICE.md](NOTICE.md)）。

## 拍攝設定（使用內建 HNCS 時）

| 設定 | 建議 |
| --- | --- |
| 創意外觀 | **ST**，對比、亮部、暗部、褪色、飽和度、清晰度等參數全部 0 |
| 色彩空間 | **sRGB**（Adobe RGB 的照片在清單中會標示 ⚠） |
| 圖片設定檔（PP）、HLG | 關閉 |
| DRO／自動 HDR | 建議關閉，或固定同一設定 |
| 拍攝模式、光圈、快門、ISO、白平衡 | 自由調整 |

## 使用方式

1. 執行 `PhotoLUT.exe`。
2. 拖入照片或資料夾，或按「加入照片」「加入資料夾」。
3. 選擇風格，調整強度（50% 約等於先前的 Lite 版）。
4. 用預覽下方的滑桿比較原圖與套用後。
5. 選擇輸出資料夾，按「開始處理」。輸出檔名為 `原檔名_後綴.jpg`，已存在時自動加編號，不會覆蓋。

輸出會保留原照片的 EXIF（拍攝時間、光圈、快門等）和 ICC 色彩描述檔。EXIF 內嵌的小縮圖仍是原圖，部分看圖軟體在載入前可能先顯示原色縮圖。

## 加入自己的風格

按「開啟風格資料夾」，把 `.cube` 檔放進去，再按「重新載入」。支援 2–129 格的 3D LUT；1D LUT 不支援。LUT 的輸入色彩空間必須和你的照片相符，S-Log3 等影片 LUT 不能直接用在一般照片上。

## 從原始碼執行與建置

需要 64 位元 Python 3.11。

```text
python -m pip install -r requirements-dev.txt
python -m pytest -q
python PhotoLUT.py
python build.py
```

`build.py` 會產生 `dist/PhotoLUT/PhotoLUT.exe`，並在 Windows 上另外打包成 `dist/PhotoLUT-Windows-x64.zip`。推送到 `photolut-app` 分支時，GitHub Actions（`.github/workflows/build-windows.yml`）會在 Windows 上測試、建置並上傳 zip。

安裝包沒有程式碼簽章，第一次執行時 Windows SmartScreen 可能會警告。
