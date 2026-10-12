# Nova TV 稳定基准版 V6.3

**当前唯一维护基线：V6.3。** 用户已在蓝叠上确认 V6.3 界面和交互正常，退出时暂未再出现“屡次停止运行”弹窗。以 2026-10-12 的反馈为准；不代表所有 Android TV 设备均已完成测试。

本仓库仅保留 V6.3 的最终有效修改，不继续保留早期的 R16/R17/R23、V1–V6.2 实验构建代码。后续功能都应基于本版推进，不回退到曾出现空白或闪退的版本。

## 最终功能

- 基于 Nova Video Player **6.5.5** 官方 APK，强制原生 Android TV 界面。
- 首页仅保留原生一行四卡片：**网络、内部存储、播放列表、首选项**，所有按钮沿用原版点击功能。
- 保留 Leanback `HEADERS_ENABLED`，仅将 `lb_browse_headers_width` 和 `lb_browse_rows_margin_start` 设为 `0dp`；不使用曾导致空白页的 `HEADERS_DISABLED` / `HEADERS_HIDDEN`。
- 启动默认焦点位于右侧第一个“网络”卡片，左右切换保持真实卡片焦点；返回首页时重新恢复右侧焦点，隐藏的左栏不能抢焦点。
- 关闭 `setHeadersTransitionOnBackEnabled`，避免返回键尝试展开零宽 Header。V6.3 的蓝叠退出体验已由使用者确认正常。

## 版本固定校验值

| 项目 | SHA-256 |
|---|---|
| 官方基准 `nova(1).apk` | `2912258dafe8e5bb7e057885b7e2228c581d8a30682ced87036ee11db409443e` |
| **最终可安装 V6.3 APK** | `0978bbf6b8e54ee83fe9c5df221e994c0f3942a574817742f1fda874c7221231` |
| 最终交付 ZIP | `4848fc0bddd47482d36840ca416f111dda460c38f287ba0ea9c8e2495e44f857` |
| `classes.dex` | `923c098958b91877f1da7e84c04556b1aa019048d674e208d01bfd8dab6a40ae` |
| `resources.arsc` | `e6b1e698d366582c9fe4fda32094f945ff70f2aaa61033034da94ee1ae7caa19` |
| 当前 APK 签名证书 | `665ac18c38c750ad258e769795c73667219229e74971a0422a470d29cf6cf0ec` |

## 重建与验证

本仓库的 `tools/rebuild_unsigned.py` 保存了相对于 **唯一指定的官方 APK** 的精确字节差异，以免把中途失败的构建历史作为后续基础。运行：

```sh
python3 tools/rebuild_unsigned.py 'nova(1).apk' NovaTV-V6.3-unsigned.apk
```

工具会强制检查官方 APK SHA-256，并生成与稳定版 **逐字节一致的 `classes.dex` 和 `resources.arsc`**。该产物是**未签名 APK**，不能直接安装。须用自己合法持有的签名密钥签名；用新密钥签名不能覆盖现有 V6.3。

**重要：** 最终已签名、经用户验证的安装包存在原 ChatGPT 对话交付附件 `NovaTV_V6_3_ExitCrash_Fix_ZIP.zip` 中。本次 GitHub 连接器仅能上传文本 / Git 对象，无法从本地工作环境直接上传约 30 MB 的 APK 二进制；因此此 Git 记录以精确二进制补丁、校验值及可复现的未签名内容为准，**不虚称 APK 本体已存进仓库**。不上传私有签名密钥。

## 发布原则

今后每次变更均以本版本为唯一基准，测试启动、遥控器焦点、网络 / 本地存储 / 播放列表 / 设置，以及返回首页与退出场景。静态检查通过不能代替蓝叠运行验证。