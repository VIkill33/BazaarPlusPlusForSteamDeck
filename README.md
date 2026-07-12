# BazaarPlusPlus for Steam Deck

[English](README_en.md)

这是一个 Decky Loader 插件，用于在 Steam Deck 上安装、更新、修复和卸载《The Bazaar》的 BazaarPlusPlus 模组。

插件本身不包含 BazaarPlusPlus 模组或桌面安装器源码。安装时，它会读取 BazaarPlusPlus 官方 R2 发布清单，下载最新版 Windows x86_64 安装器，用 7-Zip 从安装器中提取 `BepInExSource/BepInEx.zip`，校验内容后写入 Steam 游戏目录。

## 使用要求

- Steam 版《The Bazaar》（App ID `1617400`）
- 已安装 [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
- 首次安装时可以访问 BazaarPlusPlus 官方发布源和 GitHub

## 安装

1. 安装并至少启动一次《The Bazaar》，然后完全退出游戏。
2. 在 Decky Loader 开发者设置中启用从 ZIP 安装插件。
3. 下载或自行构建 `BazaarPlusPlus-<version>.zip`。
4. 通过 Decky 安装 ZIP，在快捷菜单中打开 BazaarPlusPlus。
5. 选择“安装 BazaarPlusPlus”。

安装完成后，插件会为游戏加入 Proton 所需的启动参数：

```text
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

插件会尽量保留已有启动参数。卸载模组时，如果启动参数仍与插件记录的一致，插件会恢复安装前的原始值。

## 功能

- 从内置存储和 SD 卡中的 Steam 库查找游戏
- 检查远端最新版
- 安装、更新或重新安装 BazaarPlusPlus
- 修复 Steam 启动参数
- 重置 BazaarPlusPlus 本地数据
- 卸载模组，并在存在其他 BepInEx 插件时保留共享依赖
- 在安装过程中显示下载和解包进度

安装、修复、重置和卸载前必须先退出游戏。直接删除 Decky 插件不会删除已经写入游戏目录的模组文件；请先在插件面板中执行“卸载模组”。

## 安全措施

后端会：

- 只接受 HTTPS 的官方 R2 主机和固定发布路径
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

成品位于：

```text
out/BazaarPlusPlus-<version>.zip
```

`pnpm run bundle` 会依次执行 TypeScript 类型检查、Python 单元测试和 Rollup 构建。

## 仓库结构

```text
.
├── main.py                    # Decky Python 后端
├── src/index.tsx              # Steam Deck 快捷菜单界面
├── tests/test_decky_backend.py
├── plugin.json                # Decky 插件元数据
├── package.json               # 依赖与构建命令
├── pnpm-lock.yaml             # 可复现依赖锁定
├── rollup.config.js
├── tsconfig.json
└── scripts/build-plugin.sh
```

`dist/`、`out/`、`node_modules/` 和 `__pycache__/` 都是可重新生成的本地产物，不提交到 Git。

## License

本项目使用 [MIT License](LICENSE)。Decky Plugin Template 相关部分保留其 BSD 3-Clause License 声明。
