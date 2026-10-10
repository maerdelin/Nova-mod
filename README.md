# NOVA 6.5.5 Network UI — R16 Baseline

这是当前确认可用的基准版本（R16）。

## 基准说明

R16 基于可运行的 R11 链路重新构建，并修复了此前点击本地目录闪退的问题。

关键点：

- `BrowserByVideoObjects.onItemClick()` 保持与 R11 一致，不再把目录对象强制转换为 `Video`。
- 视频直播放改到 `displayInfo(int position)` 内部实现，只会在原始 `instanceof Video` 判断通过后触发。
- 本地目录继续走原来的 `BrowserByFolder.enterDirectory()`。
- 视频文件直接调用 `startVideo(Video, int)`，跳过详情页直接播放。
- 保留 WebDAV / SMB 独立页面。
- 保留深色圆角“添加 WebDAV / SMB”按钮及加宽设置。
- 遥控器焦点与确认键点击仍使用 Android 原生 Button 交互链路。

## 基准构建脚本

实际构建逻辑：

`tools/build_r16.py`

## 重要说明

- 不上传任何签名私钥、证书或密码。
- 该仓库用于保存后续修改的稳定基准。
- 后续版本应从 R16 基准继续做最小增量修改，避免重新引入此前的目录点击、WebDAV/SMB 和 DEX VerifyError 问题。
