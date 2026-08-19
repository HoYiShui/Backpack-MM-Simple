# 阶段 0：改造基线

> 记录日期：2026-08-19（Asia/Shanghai）
>
> 代码锚点：`2cf68d6 feat: add terminal trading dashboard`
>
> 基线 tag：`pre-refactor-multiexchange-2026-08-19`
>
> 目的：冻结当前已经可用的交易行为，为后续渐进改造提供回退点和比较基准

## 1. 产品范围

后续产品定位为：

- **Hyperliquid-first**：主要开发、Testnet 验收、TUI、Sizing/Preflight 和长期维护对象；
- **Backpack-supported**：保留其有价值的产品能力，待 Hyperliquid 主路径完成改造后单独复验；
- **Legacy / 停止维护**：Aster、Paradex、Lighter、Lighter Robinhood、APEX、StandX 等；这些实现先由本基线 tag 和 Git 历史归档，后续从主运行路径移除。

当前版本仍是多交易所版本。交易所清理属于路线图阶段 2，不在阶段 0 执行。

## 2. 当前可复现入口

### 2.1 长时间 Hyperliquid Testnet 中性网格

这是当前计划继续使用的 150 格 BTC 参数。`.env.hyperliquid` 会由 `config.py` 自动加载，并已被 Git 忽略。

```bash
.venv/bin/python run.py \
  --exchange hyperliquid \
  --confirm-live-testnet \
  --close-on-exit \
  --symbol BTC \
  --market-type perp \
  --strategy perp_grid \
  --grid-type neutral \
  --auto-price \
  --price-range 5 \
  --grid-num 150 \
  --quantity 0.00099 \
  --target-position 0 \
  --max-position 0.075 \
  --duration 999999 \
  --interval 10 \
  --disable-db
```

### 2.2 同参数 TUI 入口

在上述命令末尾加入：

```bash
  --tui
```

TUI 当前属于只读运行监控层：

- 不改变策略和订单参数；
- 普通日志继续写入文件；
- `Ctrl+C` 或 `q` 请求安全退出；
- 退出仍复用策略原有的撤单、可选平仓和资源清理流程。

## 3. 已有 Hyperliquid Testnet 证据

### 3.1 最终 CLI 验收

Artifact：[`artifacts/hyperliquid-cli-final-1787050899000.json`](../../artifacts/hyperliquid-cli-final-1787050899000.json)

| 项目 | 结果 |
|---|---:|
| 网络 | Hyperliquid Testnet |
| 入口 | `run.py` |
| Symbol | BTC |
| 开始时间 | 2026-08-18 11:01:39 UTC |
| 结束时间 | 2026-08-18 11:11:55 UTC |
| CLI 报告运行时间 | 603 秒 |
| 成交数（含退出平仓） | 18 |
| 唯一 L1 hash | 11 |
| 成交方向 | BUY、SELL |
| 仓位方向 | Open Long、Open Short、Close Long、Close Short |
| 总成交数量 | 0.01342 BTC |
| 风险限制 API 拒绝 | 0 |
| 退出后 bot open orders | 0 |
| 退出后仓位 | 0 |
| 进程退出码 | 0 |

该 artifact 保存 11 个可验证 L1 transaction hash。它不包含私钥或 signer secret。

Artifact 中的 `max_order_notional_usdc=100` 是当时验收版本的历史参数。当前代码已经删除本地单笔名义金额和活跃订单数量限制，仅保留 HyperCore 规则及用户显式传入的 `--max-position`。

### 3.2 独立验证器验收

Artifact：[`artifacts/hyperliquid-testnet-1787044794608.json`](../../artifacts/hyperliquid-testnet-1787044794608.json)

| 项目 | 结果 |
|---|---:|
| 持续时间 | 608.828 秒 |
| 证据成交数 | 6 |
| 唯一 transaction hash | 5 |
| 唯一成交 ID | 6 |
| 退出后 bot open orders | 0 |
| 退出后仓位 | 0 |

该文件包含公开的 Testnet account address、订单 ID、成交 ID、`cloid` 和 transaction hash，不包含任何私钥。

## 4. 自动化测试基线

基线命令：

```bash
.venv/bin/python -m pytest -q
```

2026-08-19 结果：

```text
38 passed
```

阶段 0 不通过重新下单验证代码；真实交易证据使用上述已经完成的 10 分钟 Testnet artifact。

## 5. 代码规模与已知耦合

代码锚点 `2cf68d6` 的核心规模：

| 文件 | 行数 |
|---|---:|
| `run.py` | 543 |
| `strategies/market_maker.py` | 2,805 |
| `strategies/perp_market_maker.py` | 797 |
| `strategies/perp_grid_strategy.py` | 2,881 |
| `tui/` 合计 | 532 |
| 上述文件合计 | 7,558 |

已知边界问题：

- `run.py` 同时处理参数、交易所配置、策略装配、Telegram 和运行模式；
- `MarketMaker` 与 `PerpGridStrategy` 同时承担生命周期、状态同步、交易逻辑、统计和日志职责；
- 策略依赖较深的继承层级；
- 第一版 TUI 直接读取策略对象的可变字段；
- 第一版 TUI 的最近事件仍通过筛选 INFO 日志生成；
- 第一版 TUI 还没有完成多尺寸响应式打磨；
- Legacy adapter 和 SDK 增加了主运行路径的条件分支与安装成本。

这些问题是后续阶段的改造对象，不代表阶段 0 应修改它们。

## 6. 不可改变的交易行为清单

后续阶段必须以测试或 Testnet 证据证明以下行为没有意外变化。

### 6.1 签名与网络安全

- Hyperliquid 签名和 action encoding 由官方 Python SDK 处理；
- CLI 默认使用 Testnet endpoint；
- 没有 `--confirm-live-testnet` 时拒绝真实下撤单；
- Mainnet 没有隐式解锁路径；
- `.env.hyperliquid`、signer private key 和其他 secret 不进入 Git、日志或 artifact。

### 6.2 精度与下单

- 价格满足 Hyperliquid tick/有效数字规则；
- 数量满足 symbol size precision；
- 订单满足 HyperCore 最低名义金额；
- 网格 canonical price 不因重复取整产生重复订单；
- 开仓订单保持 post-only 语义；
- 平仓订单始终带 `reduce-only`；
- SDK/HyperCore 的真实限制不被本地伪限制替代。

### 6.3 订单身份与隔离

- 每张 bot 订单使用约定前缀的 16-byte `cloid`；
- 本地 ID、`cloid` 和交易所 `oid` 可以互相对齐；
- 撤单和退出清理只管理 bot 自己的订单；
- 手工订单不因 bot 退出被取消。

### 6.4 成交与网格状态

- WS 与 REST 成交按交易 ID 去重；
- 部分成交按累计成交量补差，不重复增加仓位或利润；
- 成交历史请求失败时订单保持未决，不把网络错误当作取消或成交；
- 开仓成交产生正确方向和数量的平仓需求；
- 平仓成交正确释放 locked grid；
- 平仓失败或取消后只重试剩余数量；
- 网格毛利润、手续费和净利润使用一致的成交数据。

### 6.5 风险与退出

- `--max-position` 继续作为用户显式设置的策略敞口上限；
- 风险计算包含实际仓位和相关未成交敞口；
- `--close-on-exit` 先撤 bot 订单，再按实际净仓位执行 reduce-only 平仓；
- 关闭流程完成后关闭 WebSocket 和数据库资源；
- 成功验收的终态是 bot open orders 为 0，仓位符合 `close-on-exit` 预期；
- `Ctrl+C`、TUI 退出和正常 duration 结束最终进入同一安全清理语义。

## 7. 基线文件完整性

代码锚点 `2cf68d6` 的关键文件 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `requirements.txt` | `1cc986b641e4731ef2f074fcbf77280b32ae3d3d9dc7509927e68df448c16536` |
| `run.py` | `ae83dfa911d660df4142de938f65ca23e694aadd7ed80296802c627fc2914356` |
| `strategies/perp_grid_strategy.py` | `05c213d270627743e3190a8ecbaf43d0f87e9b9c402629fbc76e48b9819451b3` |

如后续出现难以解释的行为差异，可以检出计划 tag 并使用上述 hash 确认关键文件。

## 8. 阶段 0 退出条件

阶段 0 只有在以下条件全部满足后才能标记为 `READY_FOR_REVIEW`：

- 基线文档已提交并推送；
- 基线 tag 指向 `2cf68d6` 并已推送到用户 fork；
- `38 passed` 测试基线可复现；
- 路线图阶段 0 状态已更新；
- 工作区干净；
- 没有交易逻辑变更；
- 用户收到 tag、commit、测试和 artifact 摘要，并决定是否接受。

## 9. 阶段 0 执行记录

| 项目 | 结果 |
|---|---|
| 状态 | `READY_FOR_REVIEW` |
| 代码基线 | `2cf68d6` |
| 基线 tag | `pre-refactor-multiexchange-2026-08-19` |
| 路线图与基线文档提交 | `5e2776a` |
| 自动化测试 | `38 passed` |
| 真实交易 | 本阶段未产生新订单；复用 2026-08-18 的两份 Testnet artifact |
| 交易逻辑变更 | 无 |

阶段 0 尚未标记为 `ACCEPTED`。用户检查上述证据并明确通过后，才能关闭阶段 0 Goal；进入阶段 1 需要单独授权。
