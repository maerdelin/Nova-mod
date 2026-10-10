# NOVA 6.5.5 Network UI R17

R17 以用户已确认好用的 **R16** 为稳定基准，只做两组增量修改：

1. **统一为手机/平板（Classic / Tablet-Phone）界面**
   - `UiChoiceDialog.applicationIsInLeanbackMode()` 固定返回 `false`，因此 Android TV 也进入 R16 的经典界面，而不是 Leanback/TV UI。
   - 禁用经典主页自动弹出的 TV UI 选择提示。
   - 设置页隐藏 `uimode_leanback` 模式选择，以及 Android TV 专用的 `always_leanback_on_tv_key` 选项，避免出现已经无效的 TV UI 切换入口。

2. **隐藏视频详情页“添加到库中”大按钮**
   - 播放器右上角仍可进入视频详情页。
   - `Add to library / 添加到库中` 按钮在 `res/GE.xml` 中被折叠为 0×0，不再显示或占用可见空间。

## 稳定链路保护

R17 未修改 R16 的以下关键链路：

- 本地目录点击 / 进入目录
- 视频直接播放
- WebDAV 页面与添加流程
- SMB 页面与添加流程
- WebDAV / SMB 添加按钮
- R16 的 RecyclerView 布局和遥控器 Button 交互

实际用于生成本 APK 的增量构建脚本：

`tools/build_r17_from_r16.py`

> 当前构建环境没有 Android Runtime / ADB / 模拟器，因此这里只能进行 APK/DEX/资源/签名静态校验，不能把这些校验称为 Android 运行测试。
