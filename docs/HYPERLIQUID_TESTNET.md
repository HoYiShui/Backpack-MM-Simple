# Hyperliquid Testnet 永續網格

本適配使用 Hyperliquid 官方 `hyperliquid-python-sdk`。簽名、action encoding 與 nonce 由官方 SDK 處理；行情、訂單、成交與倉位則轉換為本項目既有的統一數據結構。

## 安全邊界

- 默認只接受 `https://api.hyperliquid-testnet.xyz`，Mainnet 未提供 CLI 解鎖入口。
- 沒有 `--confirm-live-testnet` 時拒絕一切下單與撤單。
- 每張 bot 訂單使用 16-byte `cloid`，固定前綴為 `0x42504d47`；撤單與退出清理只管理此前綴，手工訂單不在清理範圍。
- 本地不限制单笔名义金额或活跃订单数量，由 HyperCore 的订单、保证金与用户额度规则约束。`--max-position` 仍作为用户显式配置的策略敞口上限。
- 风控计算包含实际净仓位、所有未成交开仓单以及即将批量提交的订单。
- 平仓腿在 Hyperliquid 上始终为 `reduce-only`；`--close-on-exit` 会先撤 bot 订单，再按实际净仓位执行 reduce-only 市价平仓。
- REST 成交对账按累计成交量补差额；请求失败时保持未决，不把网络错误当作成交或撤单。

## 配置

复制 `.env.hyperliquid.example` 为 `.env.hyperliquid`，填写主账户地址、API wallet signer 地址和私钥。文件已被 Git 忽略；不要把主账户私钥放进项目。

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

## 日常运行

下面的示例是小额 BTC Testnet 中性网格。`0.0002 BTC` 在 BTC 约 50,000 USDC 以上时满足最低 10 USDC 名义金额。

```bash
.venv/bin/python run.py \
  --exchange hyperliquid \
  --confirm-live-testnet \
  --close-on-exit \
  --symbol BTC \
  --strategy perp_grid \
  --market-type perp \
  --auto-price \
  --price-range 0.05 \
  --grid-num 6 \
  --grid-type neutral \
  --quantity 0.0002 \
  --target-position 0 \
  --max-position 0.001 \
  --position-threshold 0.0002 \
  --duration 600 \
  --interval 5 \
  --disable-db
```

在同一條命令末尾加入 `--tui` 可啟用只讀 Textual 儀表盤。策略參數、下單流程和退出清理均不改變；普通運行日志仍寫入配置的日志文件，終端只顯示實時狀態。按 `Ctrl+C` 或 `q` 後，界面會等待撤單、可選平倉及 WebSocket 清理完成再退出。

```bash
.venv/bin/python run.py [原有策略參數] --tui
```

`--tui` 需要互動式終端，不適用於把 stdout 重定向到文件的後台任務。

## 验收

自动化测试：

```bash
.venv/bin/python -m pytest -q
```

10–20 分钟真实 Testnet 验证器：

```bash
.venv/bin/python -m scripts.hyperliquid_testnet_validation --duration 600
```

验证器只接受 `600–1200` 秒，结束后在 `artifacts/` 写入不含密钥的 JSON。每笔成交保存：

- `oid`：交易所订单 ID
- `cloid`：本 bot 的客户端订单 ID
- `tid`：成交 ID；去重键使用 `(timestamp, coin, tid)`
- `hash`：Hyperliquid 返回的 L1 transaction hash
- 成交方向、数量、价格、手续费、maker/taker 与 closed PnL

通过的最低清理条件是：持续运行不少于 10 分钟、退出后 bot open orders 为 0、退出后仓位为 0。若 10 分钟成交样本不足，应把同一次验收运行调整为 900 或 1200 秒。

官方参考：[API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api)、[Python SDK](https://github.com/hyperliquid-dex/hyperliquid-python-sdk)。
