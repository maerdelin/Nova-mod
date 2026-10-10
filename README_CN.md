# NOVA 6.5.5 Network UI R16

R16 基于已可运行的 R11 基线重新构建，并修复 R15 点击本地目录闪退的问题。

关键修复：
- `BrowserByVideoObjects.onItemClick()` 完全恢复并保持与 R11 逐字节一致，不再把目录对象强制转换成 `Video`。
- 直接播放改到 `displayInfo(int position)` 内部实现；该方法只会在原始 `instanceof Video` 判断通过后触发。
- 因此目录仍走 `BrowserByFolder.enterDirectory()`，视频则直接调用 `startVideo(Video, int)`，跳过详情页。
- 保留 R15 的 WebDAV / SMB 页面、深色圆角添加按钮及宽度增大设置。

`tools/build_r16.py` 是本次 APK 的实际构建脚本。
