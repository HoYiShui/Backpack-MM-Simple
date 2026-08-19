# Backpack-MM-Simple 改造路线图

> 状态：执行中（阶段 0）
>
> 产品定位：个人使用、Hyperliquid-first、Backpack-supported
>
> 原则：以已经通过 Testnet 验证的行为为基线，渐进改造，不推倒重写

## 1. 为什么存在这份路线图

当前项目已经完成 Hyperliquid Testnet adapter、真实网格运行验证和第一版 TUI，证明核心交易闭环可用。但项目源自面向多交易所积分活动的上游仓库，runtime、策略、日志、交易所兼容和展示层之间存在较强耦合，与现在的个人长期使用目标并不完全一致。

这份文档用于：

- 固定产品范围，避免继续为不再使用的交易所付出兼容成本；
- 把大规模改造拆成独立、可验收、可暂停的阶段；
- 为每个阶段提供可直接交给 agent 的 Goal 描述；
- 规定验收证据，避免以“代码看起来更整洁”代替行为验证；
- 确保任何阶段结束时，bot 都保持可运行状态。

## 2. 产品边界

### 2.1 支持等级

| 等级 | 交易所 | 维护标准 |
|---|---|---|
| 核心 | Hyperliquid | 完整开发、Testnet 验收、TUI、Sizing/Preflight、持续维护 |
| 次核心 | Backpack | 保留有价值的产品能力，维护接口兼容，后续单独进行小额验证 |
| Legacy | Aster、Paradex、Lighter、Lighter Robinhood、APEX、StandX 等 | 停止适配 API 变化，保存于 Git 历史后移出主运行路径 |

### 2.2 不在当前路线图中的事项

- 不为尚未决定使用的交易所提前设计通用框架；
- 不在没有单独安全评审和资金计划时开放 Hyperliquid Mainnet；
- 不在 runtime 重构完成前支持运行中任意修改网格参数；
- 不为了代码风格一次性重写已经验证过的交易逻辑；
- 不承诺 Legacy 交易所在改造期间继续可用。

### 2.3 必须保持的 Hyperliquid 行为

- 使用官方 Python SDK 作为签名边界；
- 正确处理价格、数量精度和最低订单名义金额；
- 保持 `oid`、`cloid` 和成交 ID 的追踪关系；
- 部分成交按累计成交量补差，不重复处理；
- 平仓订单使用 `reduce-only`；
- `--close-on-exit` 先撤 bot 订单，再按实际仓位平仓；
- 只清理由本 bot 创建的订单，不影响手工订单；
- 没有 `--confirm-live-testnet` 时禁止真实下撤单；
- 现有 Hyperliquid CLI 参数在明确迁移前保持兼容。

## 3. 执行规则

### 3.1 阶段纪律

1. 一次只启动一个阶段 Goal。
2. 每个阶段使用 1–3 个可审查提交，避免巨大 diff。
3. 每个阶段结束后暂停，由用户检查验收证据并决定是否进入下一阶段。
4. 不把下一阶段的架构工作夹带进当前阶段。
5. 如果阶段中发现行为基线不明确，先补测试或文档，不依靠猜测继续移动代码。
6. 真实 Testnet 操作只在阶段验收明确要求时执行。

### 3.2 每阶段统一交付内容

- Goal 完成状态；
- 主要文件变更；
- 明确保持不变的交易行为；
- 自动化测试命令与结果；
- TUI 截图或 Testnet artifact（适用时）；
- 已知限制和遗留问题；
- Git commit；
- 是否建议进入下一阶段。

### 3.3 通用完成条件

除各阶段的专属标准外，每个阶段都必须满足：

- `git diff --check` 通过；
- 相关自动化测试全部通过；
- `.env.hyperliquid`、私钥和账户敏感信息不进入 Git；
- 非目标功能不存在已知回归；
- 文档与实际命令一致；
- 工作区状态和提交范围清楚。

## 4. 阶段总览

| 阶段 | 名称 | 用户可见结果 | 是否需要真实 Testnet |
|---:|---|---|:---:|
| 0 | 建立改造基线 | 可回退、可复现实验基线 | 否 |
| 1 | 补齐行为保护测试 | 核心交易行为可自动回归 | 否 |
| 2 | 收缩交易所范围 | 代码和依赖只服务 Hyperliquid/Backpack | 否 |
| 3 | 结构化状态与事件流 | TUI 最近事件不再搬运 INFO 日志 | 否 |
| 4 | 响应式 TUI | 常见终端尺寸可用，可查看订单/成交/事件 | 否 |
| 5 | Sizing Calculator 与 Preflight | 在 TUI 内计算数量、杠杆、费用并确认启动 | 是，10–20 分钟 |
| 6 | 提取 RuntimeController | CLI/TUI 共用可测试的生命周期和清理流程 | 是，10–20 分钟 |
| 7 | 拆解网格策略内部 | 网格、订单、仓位、风险职责清晰 | 是，10–20 分钟 |
| 8 | Backpack 重新验收 | 明确保留能力和实际可用边界 | 视账户条件决定 |

---

## 阶段 0：建立改造基线

### Goal 描述

> 为后续渐进改造建立可复现、可回退的行为基线：记录产品范围、当前 Hyperliquid 启动方式和已经验证的链上证据，为当前可用版本创建 Git tag，并明确后续重构绝对不能改变的交易行为。本阶段不改变交易逻辑。

### 验收标准

- [ ] 当前可用提交已创建并推送基线 tag；
- [ ] 产品范围明确为 Hyperliquid-first、Backpack-supported；
- [ ] Legacy 交易所名单已经记录；
- [ ] 当前 Hyperliquid CLI/TUI 启动命令已固化；
- [ ] 现有 10–20 分钟 Testnet artifact 路径、时长、成交数和退出清理结果已记录；
- [ ] 必须保持的 Hyperliquid 行为形成检查清单；
- [ ] 当前自动化测试全部通过；
- [ ] 本阶段没有修改订单、成交、仓位或清理逻辑。

### 工作范围

- 创建类似 `pre-refactor-multiexchange` 的 Git tag；
- 在文档中记录当前版本、命令和测试证据；
- 检查远端 tag 可见；
- 记录当前核心文件规模和主要耦合点；
- 建立后续阶段的状态更新机制。

### 明确不做

- 不删除任何 adapter；
- 不重排策略类；
- 不修改 TUI；
- 不重新进行真实交易测试，除非现有证据不可用。

### 验收证据

- Git tag 和对应 commit；
- 测试输出；
- 基线命令与 artifact 摘要；
- 文档提交。

---

## 阶段 1：补齐行为保护测试

### Goal 描述

> 在移动或拆分核心代码前，为当前已经运行成功的 Hyperliquid 网格行为建立足够的 characterization tests 和录制数据 fixture，使价格与数量精度、订单追踪、部分成交、平仓重试、成交去重和安全退出能够在不连接真实交易所的情况下稳定回归。

### 验收标准

- [ ] 150 个中性网格的价格生成有确定性测试；
- [ ] Hyperliquid 价格和数量精度、向下取整及最低名义金额有边界测试；
- [ ] `oid` / `cloid` alias 和 bot 订单隔离有测试；
- [ ] 开仓与平仓的部分成交累计均有测试；
- [ ] WS/REST 重复成交不会重复记账；
- [ ] 订单消失、成交历史失败和恢复后的行为有测试；
- [ ] 平仓失败、重试和 `reduce-only` 有测试；
- [ ] 安全退出的撤单、可选平仓和资源清理顺序有测试；
- [ ] 测试不读取真实私钥、不发送真实订单；
- [ ] 所有 fixture 均移除账户敏感信息。

### 工作范围

- 补充 Hyperliquid adapter 单元测试；
- 补充网格状态和部分成交测试；
- 增加脱敏的 API/WS fixture；
- 增加 runtime 清理行为测试；
- 将已验证行为写成测试名称，而不是依赖实现细节。

### 明确不做

- 不删除 Legacy adapter；
- 不重构大循环；
- 不改变现有 CLI/TUI；
- 不追求所有旧交易所的测试覆盖。

### 验收证据

- 新增测试列表；
- 全套测试输出；
- fixture 脱敏检查；
- 覆盖到的关键交易行为清单。

---

## 阶段 2：收缩交易所范围

### Goal 描述

> 在 Git 历史和行为测试已经提供回退保障后，将主运行路径收缩为 Hyperliquid 和 Backpack，移除停止维护的交易所 adapter、WebSocket、配置分支、依赖和文档，同时保持 Hyperliquid 现有 CLI、订单行为和 Backpack 核心入口可用。

### 验收标准

- [ ] `run.py --help` 只列出 Hyperliquid 和 Backpack；
- [ ] Aster、Paradex、Lighter、Lighter Robinhood、APEX、StandX 不再进入主运行路径；
- [ ] 对应 SDK 和无用依赖已从 requirements 删除；
- [ ] 对应环境变量、示例和文档已清理；
- [ ] 从空虚拟环境可以成功安装依赖；
- [ ] Hyperliquid 和 Backpack 模块可正常导入；
- [ ] Hyperliquid 全套行为测试通过；
- [ ] 当前 Hyperliquid CLI/TUI 命令保持兼容；
- [ ] 被删除代码可以从基线 tag 找回。

### 工作范围

- 清理 `api/`、`ws_client/`、`config.py` 和 `run.py`；
- 清理交易所专属工具和第三方 SDK；
- 更新 README 的产品定位、安装方法和项目结构；
- 收窄 exchange factory，但不进行过度抽象。

### 明确不做

- 不拆分 `MarketMaker` / `PerpGridStrategy`；
- 不改变 Hyperliquid 网格算法；
- 不在同一提交中重做 TUI；
- 不承诺 Backpack 已完成真实交易重新验收。

### 验收证据

- 删除和保留的模块清单；
- 新环境安装记录；
- 自动化测试输出；
- CLI help 输出；
- 依赖前后对比。

---

## 阶段 3：结构化状态与事件流

### Goal 描述

> 建立稳定的 `RuntimeSnapshot` 与 `RuntimeEvent` 边界，让策略/runtime 主动发布结构化状态和交易事件，TUI 与文件审计日志作为消费者使用这些数据；移除 TUI 对 INFO 日志关键词和策略内部可变字段的依赖，同时保持详细调试日志继续写入文件。

### 验收标准

- [ ] 存在明确、带类型的 `RuntimeSnapshot`；
- [ ] 存在明确、带类型的 `RuntimeEvent`；
- [ ] 关键连接、订单、成交、网格、风险和退出行为均有事件类型；
- [ ] 每个交易事件包含所需的时间、symbol、方向、价格、数量及关联 ID；
- [ ] 完成网格事件包含毛利润、费用和可计算的净收益；
- [ ] TUI 最近事件不再读取或解析 `logging.LogRecord`；
- [ ] TUI 不直接遍历策略内部订单字典；
- [ ] 文件日志仍保留足够的诊断信息；
- [ ] CLI 非 TUI 模式行为不变；
- [ ] 事件顺序和去重有自动化测试。

### 最低事件集合

- `connection_changed`
- `grid_initialized`
- `opening_order_placed`
- `opening_order_filled`
- `closing_order_placed`
- `grid_cycle_completed`
- `order_cancelled`
- `close_retry_scheduled`
- `risk_warning`
- `shutdown_started`
- `shutdown_completed`
- `runtime_failed`

### 明确不做

- 不加入运行中自由修改参数；
- 不提取 RuntimeController；
- 不拆解网格算法；
- 不以删除所有 `logger.info` 为目标。

### 验收证据

- 事件 schema；
- 事件序列测试；
- 新旧日志对比；
- TUI 最近事件截图；
- 证明 TUI 未引用策略私有字段的代码检查。

---

## 阶段 4：响应式 TUI

### Goal 描述

> 在结构化状态和事件边界之上打磨只读运行界面，使 Overview、Orders、Fills、Events 和 Help 在常见终端尺寸下可用，提供稳定的键盘导航、事件滚动和安全退出，但不允许在运行中直接改变交易参数。

### 验收标准

- [ ] `80×24`、`100×30`、`120×35`、`160×45` 均无面板重叠；
- [ ] 关键仓位、实际杠杆、连接状态和退出状态始终可见；
- [ ] 窄终端使用紧凑布局、单栏或分页，不静默截断关键风险信息；
- [ ] Overview、Orders、Fills、Events、Help 可以通过键盘访问；
- [ ] Events 支持滚动并保持结构化格式；
- [ ] `Ctrl+C` 和 `q` 始终进入安全退出流程；
- [ ] 非 TTY 环境仍明确拒绝 `--tui`；
- [ ] 各目标尺寸有无头截图测试或等价布局测试；
- [ ] 普通 CLI 模式不受 TUI 依赖影响。

### 推荐交互

- `Tab` / `Shift+Tab`：切换页面或焦点；
- 方向键、`PageUp`、`PageDown`：滚动；
- `o`：订单页；
- `f`：成交页；
- `e`：事件页；
- `?`：帮助；
- `Ctrl+C` / `q`：安全退出。

### 明确不做

- 不修改运行中的数量、范围或网格数；
- 不从 TUI 发送任意手工订单；
- 不在该阶段实现 Sizing Calculator；
- 不改变策略循环。

### 验收证据

- 四种目标尺寸截图；
- 键盘导航测试；
- 安全退出生命周期测试；
- CLI/TUI 回归测试。

---

## 阶段 5：Sizing Calculator 与 Preflight

### Goal 描述

> 提供与 UI 无关、使用 `Decimal` 的网格 sizing 和手续费计算模块，并在 TUI 中加入 Setup 与 Preflight 流程。用户可以输入或读取账户权益、杠杆上限、资金使用比例、价格范围和网格数量，得到每单数量、总挂单额度、单边最大仓位、实际杠杆和费用覆盖检查；明确确认后复用现有 runtime 启动 Testnet bot。

### 验收标准

- [ ] `SizingRequest → SizingResult` 是不依赖 Textual 和交易执行的纯计算；
- [ ] 金额、价格和数量计算使用 `Decimal`；
- [ ] 能区分总挂单名义额度与单边最大实际仓位杠杆；
- [ ] 能根据交易所精度向下取整订单数量；
- [ ] 检查最低订单名义金额、最大仓位和保证金缓冲；
- [ ] 计算 Maker/Maker、Maker/Taker 和 Taker/Taker 的单格收益；
- [ ] 给出盈亏平衡所需最小网格间距；
- [ ] 固定样例复现 `0.00099 BTC/单` 和约 `0.075 BTC` 最大仓位；
- [ ] Preflight 明确显示 Testnet、`close-on-exit`、风险警告和最终命令；
- [ ] 未确认前不创建任何真实订单；
- [ ] 确认后仍使用现有策略/runtime，不实现第二套交易逻辑；
- [ ] 完成一次 10–20 分钟 Hyperliquid Testnet 验收并安全清理。

### 固定验收样例

| 输入 | 值 |
|---|---:|
| 账户权益 | 800 USDC |
| BTC 杠杆上限 | 40x |
| 计划使用比例 | 30% |
| 参考价格 | 64,150 USDC |
| 网格范围 | ±5% |
| 网格数量 | 150 |

预期核心结果：

- 理论每格数量约 `0.00099766 BTC`；
- 按 BTC 5 位数量精度向下取整为 `0.00099 BTC`；
- 实际总挂单名义金额约 `9,526.28 USDC`；
- 中性网格建议最大仓位约 `0.075 BTC`；
- 展示单边最坏情况下的实际杠杆，而不是把 40x 上限误称为实际杠杆。

### 明确不做

- 不允许运行中直接编辑网格；
- 不自动替用户选择资金使用比例；
- 不绕过 `--confirm-live-testnet`；
- 不开放 Mainnet。

### 验收证据

- 纯计算单元测试；
- 固定样例输出；
- Setup/Preflight 截图；
- 生成的等价 CLI 命令；
- Testnet artifact 和退出清理结果。

---

## 阶段 6：提取 RuntimeController

### Goal 描述

> 从巨型策略 `run()` 中提取统一的 RuntimeController，集中管理初始化、调度、停止信号、异常、撤单、可选平仓和资源关闭，让 CLI、TUI 和测试使用同一个生命周期入口；策略只处理市场状态和订单意图，不再自行拥有无限循环与休眠。

### 验收标准

- [ ] 存在明确的 runtime 状态机；
- [ ] 至少支持 `CREATED → INITIALIZING → RUNNING → STOPPING → STOPPED`；
- [ ] 任意阶段失败都进入 `FAILED` 并执行统一清理；
- [ ] `request_stop()` 能立即打断等待，而非等待完整 interval；
- [ ] shutdown 可重复调用且不会重复下单、重复平仓或破坏状态；
- [ ] 撤单、`close-on-exit`、WS 和数据库关闭顺序集中管理；
- [ ] CLI 和 TUI 使用同一个 RuntimeController；
- [ ] 旧 Hyperliquid CLI 参数保持兼容；
- [ ] 模拟时钟下可运行确定性 tick 测试；
- [ ] 异常注入测试证明仍然安全清理；
- [ ] 完成一次 10–20 分钟 Hyperliquid Testnet 验收。

### 推荐状态机

```text
CREATED
  → INITIALIZING
  → RUNNING
  → STOPPING
  → STOPPED

任意活动状态 → FAILED → STOPPING
```

### 目标职责

RuntimeController：

- 生命周期和调度；
- 停止信号；
- 异常边界；
- 资源清理；
- 状态和事件发布。

Strategy：

- 初始化网格；
- 处理行情和成交；
- 产生订单意图；
- 更新策略状态。

### 明确不做

- 不同时完整拆解 `PerpGridStrategy`；
- 不加入任意运行中参数热更新；
- 不改变已经锁定的成交与平仓语义；
- 不在同一阶段重新设计 exchange adapter。

### 验收证据

- 状态机测试；
- 停止延迟测试；
- 异常注入和幂等 shutdown 测试；
- CLI/TUI 共同入口证明；
- Testnet artifact 与清理结果。

---

## 阶段 7：拆解网格策略内部

### Goal 描述

> 在 RuntimeController 和行为保护测试稳定后，逐步把 `PerpGridStrategy` 中的网格计算、订单追踪、平仓累计、仓位核对、风险策略和盈亏统计拆成可组合组件。重构前后对同一输入和成交序列必须产生等价订单意图与最终状态。

### 验收标准

- [ ] `GridEngine` 只负责网格层级和订单意图；
- [ ] `OrderTracker` 负责 `oid`、`cloid`、alias 和订单状态；
- [ ] `CloseOrderManager` 负责部分平仓累计、重试和 reduce-only 请求；
- [ ] `PositionTracker` 负责 venue 仓位与本地成交核对；
- [ ] `RiskPolicy` 负责最大仓位、实际杠杆和停止条件；
- [ ] `PnLTracker` 负责网格利润、手续费和净收益；
- [ ] 核心组件通过组合协作，不继续加深策略继承层级；
- [ ] 同样输入生成同样的 canonical 网格价格；
- [ ] 同样成交序列生成同样的平仓数量和重试行为；
- [ ] 部分成交、重复事件和恢复场景结果等价；
- [ ] 完成一次 10–20 分钟 Hyperliquid Testnet 验收；
- [ ] 退出后 bot open orders 为 0，仓位符合 `close-on-exit` 预期。

### 建议拆分顺序

1. `PnLTracker`；
2. `GridEngine`；
3. `OrderTracker`；
4. `CloseOrderManager`；
5. `PositionTracker`；
6. `RiskPolicy`。

每次只提取一个组件，测试通过并提交后再继续。

### 明确不做

- 不一次性重写整个策略；
- 不把 adapter 特例移入 domain 组件；
- 不为了未来交易所提前增加抽象；
- 不在等价性测试缺失时移动高风险逻辑。

### 验收证据

- 每个组件的接口和测试；
- 重构前后等价性测试；
- 核心类体积和职责前后对比；
- Testnet artifact；
- 最终清理结果。

---

## 阶段 8：Backpack 重新验收

### Goal 描述

> 在 Hyperliquid 主路径完成结构化改造后，重新检查 Backpack adapter 与新 runtime、事件、snapshot 和 sizing 接口的兼容性，明确哪些 Backpack 产品能力继续受支持，并在账户与测试条件允许时完成一轮受控的小额验证。

### 验收标准

- [ ] Backpack 支持的市场类型和策略范围已明确；
- [ ] adapter capability 与 Hyperliquid 差异已记录；
- [ ] Backpack 不需要通过伪装成 Hyperliquid 语义来接入 core；
- [ ] 价格、数量、订单 ID、成交和退出行为有离线测试；
- [ ] CLI/TUI 能正确显示 Backpack 状态；
- [ ] 不支持的功能明确报错，而不是静默降级；
- [ ] 如果具备测试账户和资金，完成受控小额验收；
- [ ] 如果不具备真实测试条件，文档明确标注“离线验证，尚未实盘复验”。

### 明确不做

- 不恢复其他 Legacy 交易所；
- 不要求 Backpack 和 Hyperliquid 具有完全相同的能力；
- 不因 Backpack 兼容而污染 Hyperliquid 已验证行为；
- 不在缺乏授权和测试资金时执行真实订单。

### 验收证据

- capability 对比；
- 离线测试结果；
- TUI/CLI 截图；
- 可用时提供小额验证记录；
- 最终支持边界文档。

## 5. 计划中的目标架构

```text
run.py / composition root
  │
  ├── presentation/
  │     ├── cli
  │     └── tui
  │           ├── setup
  │           ├── preflight
  │           └── runtime views
  │
  ├── runtime/
  │     ├── controller
  │     ├── state / snapshot
  │     └── events
  │
  ├── strategy/
  │     ├── sizing
  │     ├── grid engine
  │     ├── order tracker
  │     ├── position tracker
  │     ├── close order manager
  │     ├── risk policy
  │     └── pnl tracker
  │
  └── exchange/
        ├── capabilities / interface
        ├── hyperliquid
        └── backpack
```

依赖方向：

```text
Presentation → RuntimeController → Strategy → Exchange interface
                         │
                         └→ RuntimeSnapshot / RuntimeEvent
```

约束：

- Presentation 不读取策略私有字段；
- Strategy 不依赖 Textual、CLI 或 logger 文本；
- 交易所精度、签名和 venue 特例留在 adapter/capability 边界；
- RuntimeController 不包含网格算法；
- Sizing 模块可以脱离交易所和 UI 进行纯计算测试。

## 6. 阶段状态维护

阶段状态使用以下枚举：

- `PLANNED`：尚未启动；
- `IN_PROGRESS`：Goal 已创建并正在开发；
- `READY_FOR_REVIEW`：实现完成，等待用户验收；
- `ACCEPTED`：用户确认验收通过；
- `BLOCKED`：存在明确阻塞条件。

| 阶段 | 状态 | Goal/提交 | 验收备注 |
|---:|---|---|---|
| 0 | IN_PROGRESS | 阶段 0 Goal 已创建 | 建立代码、测试、Testnet 证据与不可变行为基线 |
| 1 | PLANNED | — | — |
| 2 | PLANNED | — | — |
| 3 | PLANNED | — | — |
| 4 | PLANNED | — | — |
| 5 | PLANNED | — | — |
| 6 | PLANNED | — | — |
| 7 | PLANNED | — | — |
| 8 | PLANNED | — | — |

启动某个阶段时，只更新该阶段状态和对应 Goal；完成后记录提交、测试、artifact 和用户验收结论。不得因为后续阶段已经规划，就默认获得执行后续阶段或真实交易的授权。
