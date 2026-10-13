# Nova Video Player V7.14 — 14TV 实测正常版本的修复记录

本 Git 仓库的 `main` **保存 V7.11 已确认 UI 与 14TV 实测 V7.14 启动修复代码**，不再保存 V6.3、V7.1–V7.10 等旧版补丁、测试构建包、APK 或整套官方代码。

## 目录结构

```text
.github/workflows/build-release.yml   # GitHub Actions 云编译、签名和单 APK Release
ui/apply.py                           # V7.14 源码重建：UI + Rows 初始化 + 焦点保护
upstream/locked.xml                   # 锁定官方 Nova 6.5.5 全部 21 个底层源码仓库版本
scripts/verify_apk.py                 # APK ZIP、classes.dex、签名检查
tests/test_overlay.py                 # 补丁安全性和 V7.14 回归测试
scripts/verify_v714_source.py         # 源码编译前防回退检查
scripts/v714_patch_dex.py             # 完全复现真机验证过的 V7.14 字节码修复
```

## 当前 UI 修改

- 首页：原生 Android TV 单行网络/内部存储/播放列表/首选项四卡片；支持动态 USB 卡片；在创建视图前禁用 Leanback headers，先创建 Rows Fragment；首次焦点在布局完成后选中网络卡片；隐藏首页搜索图标（保留 Logo）。
- 网络：保存的快捷方式在前，添加网络地址按钮在后；无快捷方式时只显示一个按钮；保存目录后刷新快捷方式；进入已保存目录时直达内容而不是详情页。
- 目录：视频点击后直接播放（不跳详情页）；快捷方式显示相对服务器端点的完整多级路径，不改变真实 URI。
- 协议：WebDAV、SMB 排最前，默认 WebDAV，内部实际协议 ID 正确映射；协议输入框扩大到 160dip。
- 文案和裁切：浏览网络共享改为添加网络地址；标题取消对齐底部约束，按搜索圆按钮 52dp 的 10% 上移 **5.2dp**。

## 云构建说明

GitHub Actions 每次在 `main` 更新或手动运行时会：

1. 使用官方 [Nova Video Player 6.5.5](https://github.com/nova-video-player/aos-AVP/tree/v6.5.5) 的多仓库 `repo` 工具拉取代码。
2. 使用 `upstream/locked.xml` 固定 21 个项目的精确 Git SHA（不会随官方主分支意外升级）。`ui/apply.py` 校验 10 个 UI 源文件原始 Git blob SHA，任何不匹配立即停止，避免错改底层。
3. 执行源码级 UI + V7.14 防蓝屏补丁并校验，然后用 Gradle `-Puniversal assembleNoamazonRelease` 生成一个通用 release APK。
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

## V7.14 实测结论（2026-10-13）

- 用户确认独立修复的 **V7.14 APK 已在 14TV 上正常工作**，此前的启动崩溃和蓝屏只有 Logo 均已解决。
- 经过本地 SHA-256 校验，用户确认版 APK 是：`c9977d28e57b6a58e2f4d09da959a1b41db2028020d3175facfe792e108e77ff`。
- **准确的二进制修复**：首次进入 Leanback 的 `createMainFragment` 时，原始 V7.13 在 adapter 尚未赋值的分支直接返回，不创建 Rows Fragment。经验证的 V7.14 改写原有分支，指向已有的 Rows 创建逻辑。脚本 `scripts/v714_patch_dex.py` 可对 **SHA 严格锁定的 V7.13 APK** 生成相同的 V7.14 未签名 APK；此前已在本地复现，未签名输出 SHA-256 为 `8d4e01caa3ba2df2d5e01c956864637da47a526c52a6bea8e19fabd9194912cd`。
- **源码等效保护**：`ui/apply.py` 在 `MainFragment.onCreate` 且在 Leanback 创建视图之前禁用 Headers，使空适配器情况下 Rows Fragment 仍被建立；焦点设置改为事件队列后在 `RowsSupportFragment` 上执行，避免 `BrowseSupportFragment` 禁用 Headers 后触发异常。
- **注意**：GitHub 自动生成 APK 是另一份源码重编译产品，不等同于用户真机验证的二进制 APK；原 V7.14 的私有签名与字节级结果不能由 GitHub CI 自动保证，必须经过真机复测。不要提交证书/密码。
