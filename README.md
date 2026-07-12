<div align="center">

# BazaarPlusPlus for Steam Deck

**因热爱而生** · 在 Steam Deck 上安装与管理 [《The Bazaar》](https://www.playthebazaar.com) 的 [BazaarPlusPlus](https://github.com/cauyxy/BazaarPlusPlus) 模组

[English](README_en.md) · [官网](https://bazaarplusplus.com) · [使用教程](https://bazaarplusplus.com/tutorial) · [BazaarPlusPlus 主仓库](https://github.com/cauyxy/BazaarPlusPlus) · [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)

[![Version](https://img.shields.io/badge/version-0.1.0-6dd9a0?style=flat-square)](package.json)
[![License](https://img.shields.io/badge/license-MIT-e8c87a?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Steam%20Deck-c1875a?style=flat-square)](https://store.steampowered.com/steamdeck)
[![Decky Loader](https://img.shields.io/badge/Decky%20Loader-plugin-3d5afe?style=flat-square)](https://github.com/SteamDeckHomebrew/decky-loader)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?style=flat-square)](https://www.python.org)
[![React](https://img.shields.io/badge/React-19-61dafb?style=flat-square)](https://react.dev)

</div>

---

BazaarPlusPlus for Steam Deck 是一个 [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) 插件，负责在 Steam Deck 上安装、更新、修复和卸载《The Bazaar》的 BazaarPlusPlus 模组。卡牌图鉴、对局历史、战斗回放、中文术语等游戏内功能由模组本体提供，其源码与 Windows / macOS 桌面安装器见 [BazaarPlusPlus 主仓库](https://github.com/cauyxy/BazaarPlusPlus)。

本插件不内置模组或安装器源码：安装时它从 BazaarPlusPlus 官方发布源（Cloudflare R2）读取发布清单，下载最新版 Windows x86_64 安装器，用 7-Zip 从中提取 `BepInExSource/BepInEx.zip`，逐项校验后写入 Steam 游戏目录，并为 Proton 配置所需的启动参数。

## 快速开始

1. 安装并至少启动一次《The Bazaar》（Steam 版，App ID `1617400`），然后完全退出游戏。
2. 安装 [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)，并在其开发者设置中启用从 ZIP 安装插件。
3. 下载（或[从源码构建](#从源码构建)）`BazaarPlusPlus-<version>.zip`，通过 Decky 安装。
4. 在快捷菜单中打开 BazaarPlusPlus，选择「安装 BazaarPlusPlus」，等待下载与解包完成。
5. 启动游戏，确认主菜单出现「卡牌图鉴」按钮。

首次安装需要能访问 BazaarPlusPlus 官方发布源和 GitHub。安装完成后，插件会为游戏加入 Proton 所需的启动参数：

```text
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

插件会尽量保留已有启动参数。卸载模组时，如果启动参数仍与插件记录的一致，插件会恢复安装前的原始值。

## 功能概览

- **安装 / 更新 / 重装**：读取官方发布清单，比较本地已装版本，提示并安装最新版。
- **游戏目录检测**：自动在内置存储和 SD 卡中的 Steam 库里定位《The Bazaar》。
- **修复启动参数**：一键恢复被覆盖或丢失的 Proton 启动参数。
- **重置本地数据**：清理 BazaarPlusPlus 的本地对局数据，恢复到干净状态。
- **卸载模组**：移除模组文件；检测到其他 BepInEx 插件时保留共享依赖。
- **进度反馈**：安装过程中实时显示下载与解包进度。

安装、修复、重置和卸载前必须先退出游戏。直接删除 Decky 插件不会删除已写入游戏目录的模组文件；请先在插件面板中执行「卸载模组」。

## 安全措施

插件后端在下载与写入过程中会：

- 只接受 HTTPS 的官方发布主机和固定发布路径
- 拒绝跨主机或异常路径重定向
- 对 7-Zip 工具执行固定 SHA-256 校验
- 限制 manifest、下载文件和解压内容大小
- 拒绝 ZIP 路径穿越和符号链接
- 校验 payload 必需文件及版本号
- 通过临时文件和备份事务写入游戏目录，失败时回滚

## 从源码构建

需要 Node.js、pnpm 9+ 和 Python 3.11+。

```bash
pnpm install --frozen-lockfile
pnpm run bundle
```

`pnpm run bundle` 会依次执行 TypeScript 类型检查、TypeScript / Python 单元测试和 Rollup 构建，成品位于：

```text
out/BazaarPlusPlus-<version>.zip
```

## 仓库结构

```text
.
├── main.py                        # Decky Python 后端：下载、校验、安装事务
├── src/
│   ├── index.tsx                  # Steam Deck 快捷菜单界面
│   ├── launchOptions.ts           # Proton 启动参数规划
│   └── launchOptions.test.ts
├── tests/test_decky_backend.py    # 后端单元测试
├── plugin.json                    # Decky 插件元数据
├── package.json                   # 依赖与构建命令
├── pnpm-lock.yaml                 # 可复现依赖锁定
├── rollup.config.js
├── tsconfig.json
└── scripts/build-plugin.sh        # bundle 打包脚本
```

`dist/`、`out/`、`node_modules/` 和 `__pycache__/` 都是可重新生成的本地产物，不提交到 Git。

## 二次开发须知

如果你计划基于本项目进行二次开发，请务必遵循《The Bazaar》官方 Mod Policy：

[The Bazaar Mod Policy](https://www.playthebazaar.com/mod-policy)

## 致谢

- **模组本体**：[BazaarPlusPlus](https://github.com/cauyxy/BazaarPlusPlus)（by [cauyxy](https://github.com/cauyxy)）
- **运行依赖**：[Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)、[BepInEx](https://github.com/BepInEx/BepInEx)、[7-Zip](https://www.7-zip.org)
- **脚手架**：[Decky Plugin Template](https://github.com/SteamDeckHomebrew/decky-plugin-template)

## License

本项目使用 [MIT License](LICENSE)。Decky Plugin Template 相关部分保留其 BSD 3-Clause License 声明。
