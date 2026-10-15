# Nova Video Player mod — V9.8.2

**唯一基准**：用户在 BlueStacks 实测确认的 `Nova_V9_8_2_WebDAV_TVList_VerifyErrorFix_TEST.apk`。

- 测试 APK SHA-256: `71573d545b08fcbef7e5398694ed43c6b099dae9fda0389350573c3280c2a5c9`
- 测试 DEX SHA-256: `e300b79795b813e20e4c71f2fcdf6880e6bc2454da26fc6c2b4e15843a41f4d3`
- V9.8.2 包含 WebDAV 视频大小显示、TV 列表修复、WebDAV 多级目录居中及之前用户认可的功能。
- GitHub Actions 唯一工作流：**Nova Video Player mod**。

构建方法：固定官方 Nova 6.5.5 Universal APK 下载后，SHA 校验，然后将仓库中 `baseline/parts` 完整原版功能资源补丁覆盖到官方四架构 APK，执行逐文件 SHA-256 校验，`zipalign` 并签名，再验证签名及资源对齐，最后上传 Artifact 和 Release。Release 只保留最近 3 个，删除更早的 Release 及其 tag。

**重要区别**：这是可重复的 **APK 二进制重建**，不是从 APK 复原的原生 Java/Kotlin/Gradle 工程；重新签名的云端 APK 的整包哈希和签名不一定等于你实测的原始 V9.8.2。若需不卸载直接覆盖，请在仓库 Secrets 配置与设备当前 APK 同一证书对应的 `NOVA_KEYSTORE_BASE64`、`NOVA_STORE_PASSWORD`、`NOVA_KEY_ALIAS`、`NOVA_KEY_PASSWORD`。未配置时会临时签名，仅供新装测试。

保留的 Git 历史不会因清空 `main` 工作目录而被擦除。历史 release 清理不可逆，仓库 Tags 若被 Release 清理同时移除，请先确认有备份。