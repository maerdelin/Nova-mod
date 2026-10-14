# Nova V7.14 V6 — 用户实测完美版本（当前主分支基准）

**主分支默认版本：V6 网络存储精准居中 + TV 首页三按钮居中 + 自动 TV/平板模式。**

用户在 2026-10-14 使用蓝叠确认 V6 网络存储页面居中效果完美；此前也确认首页三按钮居中、Android UI 模式自动判定正常。

- **用户实测 APK 文件名：** `Nova_V7_14_Network_Only_Centered_v6_ResourceExactCenter_TEST.apk`
- **用户实测整包 SHA-256：** `957819f313352ff54adcaac9000037d082e2f42a5823e03f5e3eb6dffb344d6d`
- **V6 classes.dex SHA-256：** `1f0194f96282bc3494e0ed17505a52d2cd552782cee5d534584480058b836e38`
- **首页布局 res/Am.xml SHA-256：** `b246497606d126efa7e56156952bfd059538b9ffb18afb7a1c4cc44380293262`
- **共用列表布局 res/mC.xml SHA-256：** `559a5e7d1b679338e5fb9be9eface0ee1edc7ef4ca454651b851ed9084b6a1bc`

## 网络卡片居中的 V6 实现

V6 复用已经成功的 V4 容器居中链路，只将容器宽度公式改为**实际 Android 资源尺寸**：

```
卡片总数 N = 已保存网络快捷方式数量 + 添加网络地址按钮
卡片宽度 = 210dp
卡片间距 = 16dp
列表左右内边距 = 各 56dp
居中容器宽度 = 210*N + 16*(N-1) + 2*56 = 226*N + 96 dp
实际容器宽度 = min(设备可用屏幕宽度, 居中容器宽度)
```

当卡片数量增加到超过屏幕时仍可正常左右滚动。V6 只在网络二级页面更新容器位置，**不会改动已经完美的首页和 Leanback 共用 XML**。内部更新回调的合成按键会被拦截，不会再因空 KeyEvent 调用父类造成闪退。

## 主分支云编译

仓库唯一的主构建流程 ` .github/workflows/v714-exact.yml ` 已改为**编译 V6**。它会：

1. 从固定 SHA 的 V7.14 ARM32 三按钮 APK 与官方 Nova 6.5.5 Universal APK 重建 4 ABI 包。
2. 保持已有 USB、首页布局、隐藏标题与自动模式修复；在此基础上应用 `scripts/network_center_v6.py`。
3. 检查打包和签名后的 `classes.dex` 等于用户实测 V6 的固定 SHA，并检查首页和公共布局的哈希不变。
4. 产出 `NovaTV_V7_14_V6_NetworkCentered_Universal.apk`，上传到 GitHub Actions 构建产物。

**注意：** 构建产物使用的签名证书若与实测 APK 不同，则新 APK 整包 SHA 会变化，也可能无法直接覆盖安装；不能将 DEX 内容一致当作签名一致。为了保护现有用户数据，请注意签名不一致的安装风险。

历史 AutoMode 及早期失败版本不再作为主分支构建目标，但 Git 历史仍保留以便必要时回滚。**不要清空 Git 历史或删除 V6 基准。**

这个仓库交付的是可重复执行的 APK 二进制重建/补丁代码，并不是从 APK 还原出的原始 Java/Kotlin 源码。
