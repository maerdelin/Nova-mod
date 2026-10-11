# NOVA 6.5.5 Network UI R23

R23 已确认为新的稳定基准。

## 首页逻辑

- 左侧：最近播放 / 内部存储 / WebDAV / 共享SMB / 系统设置
- 右侧：随左侧焦点同步显示对应的实际内容区
- 不再使用 R22 的单图标纵向首页

## TV 二级页面

- 本地目录进入 Leanback ListingActivity
- WebDAV / SMB 已保存入口进入对应 TV 文件浏览页
- 系统设置进入 VideoSettingsActivity

## R23 主要修改

R23 以 R22 为基底，只修改 6 个方法：

1. EntryActivity.onCreate(Bundle)
2. BrowserByFolder.enterDirectory(MetaFile2)
3. NewRootFragment.onShortcutTap(Uri)
4. MainActivity.startPreference()
5. LocalListingActivity.getStartingName()
6. LocalListingActivity.getStartingUri()

## 保留内容

- 之前双栏首页右侧内容同步逻辑
- 最近播放 / 内部存储 / WebDAV / SMB / 设置五项入口
- R22 其余资源、assets 和 native libraries
- 原版本签名兼容性

## 构建文件

- tools/build_r23.py
- tools/dexdiff.py

R23 已完成 APK、DEX、资源一致性及签名静态校验，并已由用户确认实际版本表现良好。
