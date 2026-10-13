# Nova TV V7.14 — 已实测 14TV APK 的精确恢复基线

**唯一可信功能基准：** `NovaTV_V7_14_Rows_Fragment_Fix_Test.apk`，29,767,890 字节，SHA-256 `c9977d28e57b6a58e2f4d09da959a1b41db2028020d3175facfe792e108e77ff`。

本仓库 `main` 不再使用旧的 `ui/apply.py`、旧的发布工作流或把未经真机验证的 Java 近似改动误称为 V7.14。此版的优先目标是**保证交付的 APK 与真正通过 14TV 测试的 APK 每一字节都相同**。

## 重建方式（严格区分源码编译与 APK 重建）

`./scripts/v714_exact.py` 是完整可执行的**精确 APK 重建代码**，使用官方 6.5.5 `armeabi-v7a` 发布包作为不可变基底，将从已测试 V7.14 提取的修改原样重放：

- DEX：还原完整的 Java/Dalvik 字节码差异，共 22 个发生变化的方法（`reference/v714-parity-manifest.json` 记录方法级 SHA256）。包括 14TV 启动、网络页面、存储、首页卡片、文件/播放列表等改动。
- Android 资源：还原 7 处文案、资源表中的相关索引及两个布局 XML 的精确字节改动。
- 重新打包：使用原本的 ZIP 顺序、对齐和压缩方式，并恢复**用户原来已测试 APK 的 Android 签名块**，不是生成一套新证书。
- 最后必须完全满足原测试 APK 的 29,767,890 字节和整包 SHA-256。任何不一致立即失败，不发布。

官方输入：`https://github.com/nova-video-player/aos-AVP/releases/tag/v6.5.5`，特定 `armeabi-v7a` APK 的 SHA-256 固定为 `2912258dafe8e5bb7e057885b7e2228c581d8a30682ced87036ee11db409443e`。

手动离线重建：

```sh
python3 scripts/v714_exact.py /path/to/official-armeabi-v7a.apk /path/to/NovaTV_V7_14_14TV_Exact.apk
```

需要 Python 3 与 `zstd` CLI。GitHub Actions 自动下载官方包、重建、做哈希与 Android 签名验证，再上传到 `current` Release。`upstream/locked.xml` 仅记录当初官方 21 个 Git 仓库的固定版本以备源码审计，不参与这条精确重建链。

## 重要技术限制

1. **APK 不能逆向出开发者最初写的、完全相同的 Java/Kotlin 源码。** 当前仓库交付的是官方开源基线引用 + 22 个方法/Android 资源的**完整、可重复执行的精确二进制改动代码**，可重新生成字节完全一致的成品，不应误称为完整原始 Java 源代码。
2. 此 V7.14 基准 APK 只支持 **ARM 32 位（armeabi-v7a）**。这保证 14TV 实测行为与成品一致；对 X86TV/ARM64/Universal 的修改仍需要**独立验证**。不能把从另一架构 Gradle 编译得到的 APK 冒充同一实测版。
3. 稳定性结论只适用于用户此前测试的 14TV APK；`classes.dex` 与 APK 整包哈希一致可证明字节一致，但不能替代新平台的运行验证。
4. Git 历史提交可追溯；旧的脚本、旧发布工作流已从 `main` 当前文件树清理，不做危险的历史强制改写。

## 版本回归防护

`tests/test_v714_reference.py` 固定：四个被修改的 ZIP 成员、22 个 DEX 方法、原始与目标哈希、完整原始签名以及唯一发布工作流。云端验证不通过绝不会替换 Release。
