# Latest Live Validation

## 2026-08-17

- consent: 已提供 `.live-data-consent`
- command: `python -m pytest backend/tests/live/test_phase1d1_live.py --run-live -v -p no:cacheprovider`
- result: `BLOCKED`
- failed provider: `akshare-eastmoney`
- safe error code: `AKSHARE_FETCH_FAILED`
- cause: 访问 `17.push2.eastmoney.com` 时代理连接被远端关闭（`ProxyError / RemoteDisconnected`）
- conclusion: 未获得行业/概念行情，未进入新闻双来源验收；没有使用 Fixture 冒充成功。

恢复代理或外网访问后，重新运行同一命令即可继续验收。
