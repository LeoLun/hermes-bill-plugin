# Hermes Bill

Hermes Bill 是一个远程优先的 Hermes Agent + Desktop 统一插件。账单解析、校验、SQLite 持久化和统计全部运行在远程 `hermes serve` 主机；Desktop 只通过当前网关的插件作用域 API 渲染原生账单页面。

## 架构

```text
Hermes Desktop（本机）                  Hermes serve（远程）
desktop/plugin.js  ── ctx.rest ─────▶ dashboard/plugin_api.py
       │                                      │
       │ 仅渲染、内存态年月选择                ├─ bill_store.py
       │                                      └─ plugin-data/hermes-bill/bills.sqlite3
       └─ 不读写账单文件                 Agent tools + bill-manager skill
```

插件提供：

- `bill_manage` Agent 工具，通过 `add`、`import`、`update` 三种 action 管理账单。
- `hermes-bill:bill-manager` 解析与分类 skill。
- 只读 `/api/plugins/hermes-bill/overview` API。
- Hermes Desktop 左侧导航栏“账单”入口，在中央区域展示年度/月度筛选、摘要、图表和最近交易。

## 安装

远程 Agent 半部和本机 Desktop 半部必须分别安装。远程主机的插件目录不会自动复制到运行 Desktop 的电脑。

### 1. 远程 Hermes 服务

在运行 `hermes serve` 的主机执行：

```bash
hermes plugins install <仓库 URL> --no-enable
hermes plugins enable hermes-bill
```

随后重启或重新加载 `hermes serve`。在 Capabilities → Plugins 中确认当前远程 profile 的 Agent 开关已经启用。

### 2. Hermes Desktop 本机

在 Capabilities → Plugins 中选择 **Install from Git**，填入同一个仓库 URL，并勾选 Desktop 目标。安装后打开 Desktop 开关；左侧导航栏会出现“账单”入口。也可使用命令面板中的“打开账单”进入账单页面。

## 使用

在连接远程 Hermes 服务的聊天中直接描述账单，并明确要求使用 `hermes-bill:bill-manager`：

```text
使用 hermes-bill:bill-manager 记录：2026 年 9 月 24 日午餐 28.5 元，微信支付，商户是食堂。
```

复杂流水先要求 dry-run，核对结果后再正式导入。面板只读，不支持新增、删除、编辑或上传。

首次验证建议新增一条虚构记录，然后在左侧导航栏打开“账单”并点击“刷新”。新账本默认为空；本项目不会读取或迁移其他账本。

## 数据与备份

权威数据库位于远程主机：

```text
<HERMES_HOME>/plugin-data/hermes-bill/bills.sqlite3
```

数据库启用 WAL。在线备份建议使用 SQLite backup 命令，不要只复制主文件而忽略 `-wal`：

```bash
sqlite3 "$HERMES_HOME/plugin-data/hermes-bill/bills.sqlite3" ".backup '/安全路径/hermes-bill-backup.sqlite3'"
```

Desktop 不持久化 API 返回内容，也不会在本机创建账单数据库。`HERMES_BILL_DATA_DIR` 仅供自动化测试或受控部署覆盖远程数据目录。

## 更新

在远程 Agent 主机更新插件，并在 Desktop 的 Plugins 页面 Rescan/Update Desktop 半部。Python 后端更新后重启 `hermes serve`；Desktop 单文件插件支持热重载。

## 故障排查

- `404`：远程主机未安装 Agent 半部，或 `dashboard/manifest.json` 未被加载。
- `401`：Desktop 的当前远程网关登录已失效；在 Settings → Gateways 重新登录。
- “插件未启用”：Agent 和 Desktop 是两个独立开关，分别确认当前远程 profile 和本机 Desktop 开关。
- 连接失败：确认 `hermes serve` 正在远程主机监听，Desktop 当前连接确实指向该网关。
- 面板为空：这是新账本的正常状态；历史账单不会自动迁移。

## 开发与测试

```bash
python3 -m unittest discover -s tests -v
node --check desktop/plugin.js
```

测试通过 `HERMES_BILL_DATA_DIR` 使用临时目录，所有记录均为虚构数据。
