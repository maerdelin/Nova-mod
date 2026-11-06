# 天翼云盘：NOVA 6.6.4 网络连接 UI 接入要求

## 确认的用户界面（2026-11-06）

用户提供的实际“服务器”弹窗截图是本功能的权威布局参照。

- 左侧协议列表的显示顺序：FTP、SFTP、FTPS、SSHJ、SMB、**天翼云盘**、SMBJ、WebDAV、WebDAVS。
- 切换到“天翼云盘”后，右侧连接配置区域**仅显示一个天翼云盘登录二维码**。隐藏服务器地址、端口、路径、用户名、密码、域、显示密码及保存密码等所有原输入框。
- 必须在二维码旁/下方不干扰扫码的位置呈现最小必要的状态文字：等待扫码、手机确认中、登录成功、二维码过期（可刷新）、网络异常、需要重新登录。若用户明确要求二维码单独显示，初始状态应只显示二维码；临时反馈可通过 Toast。
- 手机用天翼云盘客户端扫码确认。成功后**自动**添加名称为“天翼云盘”的网络快捷方式；不要求再点“确定”，也不要求输入地址、端口、账号或密码。
- 快捷方式默认是个人云根目录（OpenList 189CloudPC 的 RootFolderID = `-11`）；进入快捷方式的文件和目录 UI 复用 NOVA WebDAV 现有列表与播放链路。
- 取消/切换协议应取消尚未完成的二维码轮询任务，禁止在用户离开后意外创建快捷方式。

## 关键兼容规则（不能遗漏）

现有源码 `res/values/arrays.xml` 数组索引：
```
0 FTP
1 SFTP
2 FTPS
3 SSHJ
4 SMB
5 SMBJ
6 WebDAV
7 WebDAVS
```

新数组插入索引 5，仅改变**视觉选择索引**，不能改变其余代码原有协议类型的持久编号：

```java
static final int UI_TIANYI_INDEX = 5;
static final int TYPE_TIANYI_SENTINEL = 8;

int uiIndexToLegacyProtocolType(int uiIndex) {
    if (uiIndex == UI_TIANYI_INDEX) return TYPE_TIANYI_SENTINEL;
    return uiIndex > UI_TIANYI_INDEX ? uiIndex - 1 : uiIndex;
}
int legacyProtocolTypeToUiIndex(int legacyType) {
    if (legacyType == TYPE_TIANYI_SENTINEL) return UI_TIANYI_INDEX;
    return legacyType >= UI_TIANYI_INDEX ? legacyType + 1 : legacyType;
}
```

这些转换至少覆盖 `NetworkServerCredentialsDialog` 的初始选择、onItemSelected、确认按钮、最后一次协议选择的 SharedPreferences、`NetworkRootFragment` 的回调、移动端 `ServerCredentialsDialog`、`UriUtils` 以及其他直接读取 `@array/protocol_types` 索引的路径。不要在未审核所有调用点前将新 UI 索引传给 `UriUtils.getTypeUri`，因为索引 5 原先代表 SMBJ。

## OpenList 源码基线（截至 2026-11-06）

- 项目：`OpenListTeam/OpenList`
- 最新稳定 Release：`v4.2.9`（2026-10-25）
- 使用 `drivers/189pc`，**不要**使用不带 refresh-token 的 `drivers/189` 来实现长期扫码会话。
- 代码参考：
  - `drivers/189pc/utils.go` 中的 `initBaseParams`、`initQRCodeParam`、`checkQRCodeState`、`getSessionByRedirectURL`、`refreshSessionWithRetry`、`refreshTokenWithRetry`、`keepAlive`、`getFilesWithPage`。
  - `drivers/189pc/help.go` 中的 `signatureOfHmac`、`clientSuffix`、`getHttpDateStr`。
  - `drivers/189pc/driver.go` 中的 `Init`、`List`、`Link`、`Drop`。
  - `drivers/189pc/meta.go` 中的 `DefaultRoot: "-11"`、token/device fields。
- 二维码状态成功值为 0；-106 是未扫码，-11002 是已扫码待确认，-11001 是过期。
- OpenList 登录二维码包含服务端 UUID；不能自行生成一个静态“天翼云盘”图片冒充授权二维码。
- 登录成功交换出 AccessToken 和 RefreshToken，必须立即安全持久化，处理 token 轮换。
- 获取 PC Session 和刷新 token 是两个不同的动作；本地保活无法保证账号在服务端永久有效，撤销授权、风控/设备验证和长期离线后要引导重新扫码。

## 架构与生命周期

1. NOVA UI 专用扫码状态控制器：由弹窗激活，异步获取真实 QR UUID、生成位图并在后台轮询（不得阻塞 UI 线程）。
2. 天翼账号驱动：调用天翼云盘 API，保存并定期刷新 AccessToken/RefreshToken、SessionKey/SessionSecret；以 AndroidKeyStore 加密持久化，禁止日志打印。
3. 本地仅 loopback WebDAV 适配器：绑定 `127.0.0.1`，代理个人云文件列表/文件 GET/Range；不能绑定 `0.0.0.0` 暴露账号。复用现有 NOVA 的 WebDAV 列表和播放器数据流，而不是将 token 嵌在 URL。
4. 快捷方式：存稳定的、本地专用高熵路径 capability（不是 bearer token），确保应用重启后端口和快捷方式恢复，并核对本地同进程 server 的可用性。
5. 播放器生命周期：在浏览和播放需要时可启动本地服务。Android 后台执行限制下不能依赖进程常驻来保持登录；下一次打开/播放应先按需刷新再服务请求。WebDAV Range、重定向过期、HTTP 401/403 应有有限重试；播放取消时不得堵塞主线程。
6. 一律不影响 SMB、WebDAV 原路径、128 MiB RAW、双路传输、全局日志开关及 Run393 的销毁/退出修复。

## 验收（未通过前不能标记交付）

- 原有所有协议的旧快捷方式仍可访问，尤其 SMBJ/WebDAV/WebDAVS。
- UI 新选项精确位于 SMB 下方；选择时仅有真实可扫码二维码。
- 初次扫码，确认后自动生成快捷方式；浏览个人云根目录、翻页、进入子文件夹。
- 播放 MP4/MKV/TS/ISO 并执行前进后退 Seek、重复打开、退出；逐项记录是否支持及失败原因。
- 杀进程、重启安卓设备、断网多日后恢复联网、令牌刷新、扫码过期、授权被撤销，都不能产生静默损坏。
- 检查账户信息不进入日志、网络快捷方式 URI 或应用明文首选项。
- Android 11 + Android 14 APK 构建和真实设备扫码回归；成功前仅能称为源码开发，不能称为可用 APK。

## 当前进度（2026-11-06）

- 已核验现有 NOVA 构建是官方 v6.6.4 APK + 指令/Smali 补丁，`main` 与 `Always-new` 基线相同。
- 已核验 OpenList 最新稳定版与其 `189CloudPC` 扫码及会话刷新源代码。
- 当前仅在独立功能分支写入 `TianyiStore.java` 的 AndroidKeyStore 凭据安全持久化基础代码，并记录本 UI/集成需求；**尚未接入二维码接口、WebDAV HTTP 适配服务、NOVA UI/Smali、构建 workflow，也没有可安装 APK。**
- 不应修改主分支或发布 Release，直到上述测试通过。
