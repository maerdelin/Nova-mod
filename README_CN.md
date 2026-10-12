# Nova Video Player V7.11 — 唯一维护版本

本 Git 仓库的 `main` **只保留 V7.11 的一套 UI 改动代码**，不再保存 V6.3、V7.1–V7.10 等旧版补丁、测试构建包、APK 或整套官方代码。

## 目录结构

```text
.github/workflows/build-release.yml   # GitHub Actions 云编译、签名和单 APK Release
ui/apply.py                           # V7.11 唯一 UI 逻辑补丁，校验上游代码版本
upstream/locked.xml                   # 锁定官方 Nova 6.5.5 全部 21 个底层源码仓库版本
scripts/verify_apk.py                 # APK ZIP、classes.dex、签名检查
tests/test_overlay.py                 # 补丁安全性和清单单元测试
```

## 当前 UI 修改

- 首页：原生 Android TV 单行网络/内部存储/播放列表/首选项四卡片；支持动态 USB 卡片；保留 Leanback headers enabled 但宽度和偏移 0dp，焦点初始化在网络卡片，返回时不展开左侧栏；隐藏首页搜索图标（保留 Logo）。
- 网络：保存的快捷方式在前，添加网络地址按钮在后；无快捷方式时只显示一个按钮；保存目录后刷新快捷方式；进入已保存目录时直达内容而不是详情页。
- 目录：视频点击后直接播放（不跳详情页）；快捷方式显示相对服务器端点的完整多级路径，不改变真实 URI。
- 协议：WebDAV、SMB 排最前，默认 WebDAV，内部实际协议 ID 正确映射；协议输入框扩大到 160dip。
- 文案和裁切：浏览网络共享改为添加网络地址；标题取消对齐底部约束，按搜索圆按钮 52dp 的 10% 上移 **5.2dp**。

## 云构建说明

GitHub Actions 每次在 `main` 更新或手动运行时会：

1. 使用官方 [Nova Video Player 6.5.5](https://github.com/nova-video-player/aos-AVP/tree/v6.5.5) 的多仓库 `repo` 工具拉取代码。
2. 使用 `upstream/locked.xml` 固定 21 个项目的精确 Git SHA（不会随官方主分支意外升级）。`ui/apply.py` 校验 10 个 UI 源文件原始 Git blob SHA，任何不匹配立即停止，避免错改底层。
3. 执行源码级 UI 补丁，然后用 Gradle `-Puniversal assembleNoamazonRelease` 生成一个通用 release APK。
4. 检查 APK、用你自己的稳定证书签名；仅当签名 Secrets 已配置时，发布到唯一的滚动 Release `current`，资产文件名为 **`Nova Video Player.apk`**；不会额外上传 ZIP / 源码附件 / 第二个 APK。GitHub 自动生成的“Source code (zip/tar.gz)”是平台内置下载入口，无法通过 Release 文件过滤去除。

### 首次配置私有签名（必须）

在仓库 **Settings → Secrets and variables → Actions → New repository secret** 添加这四项：

| Secret | 值 |
|---|---|
| `NOVA_KEYSTORE_BASE64` | 本地 `.jks` 文件的 Base64 全文 |
| `NOVA_STORE_PASSWORD` | keystore 密码 |
| `NOVA_KEY_ALIAS` | 证书别名 |
| `NOVA_KEY_PASSWORD` | key 密码 |

Windows PowerShell 生成 Base64：

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\\path\\to\\nova-release.jks"))
```

没有签名密钥时，仅进行 UI 补丁验证及云编译，**不会假装已发布可安装 APK**。不要提交 keystore 或密码到代码仓库。

**关于更新安装：** 本次已验证 V7.11 APK 使用之前的开发签名，当前仓库没有该签名私钥。采用新签名后，**不能直接覆盖安装原版 V7.11**，需要先备份数据、卸载旧包再安装。要保持无缝升级必须使用原证书私钥。

**关于“同一个 APK”：** 这是从固定官方源码重编译的 *源码等效方案*，不是原 V7.11 APK 的字节复制。即便构建成功，也必须在电视/模拟器验证首页焦点、USB、WebDAV/SMB 和字幕/标题显示，不能把静态检查当成运行验收。
