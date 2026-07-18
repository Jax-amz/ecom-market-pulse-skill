# 分类体系（v1.0.0）

文章只允许一个 `primaryCategory`，并选择一至三个 `impactDimensions`。分类根据卖家需要作出的主要经营决策，而不是信源栏目或标题关键词。

| 枚举 | 中文名称 | 主要判断边界 |
| --- | --- | --- |
| `amazon-policy` | Amazon 官方政策与卖家公告 | Amazon 全局卖家规则、站点开放或全局公告；能归更具体业务类时不用本类。 |
| `amazon-fba-fulfillment` | FBA、仓储、配送与退货 | 入仓、库存、仓储、配送、退货、AWD、MCF 等 Amazon 仓内履约动作。 |
| `fee-margin-tax` | 平台费用、利润、税务与关税 | 费率、计费公式、税负、关税、汇率、结算和利润核算。 |
| `ads-traffic` | 广告与流量 | Sponsored Ads、DSP、AMC、归因、竞价、预算和广告 API 的经营变化。 |
| `listing-seo-voc` | Listing、SEO、评论与 VOC | 商品内容、自然搜索、评论、买家反馈、退货原因和转化。 |
| `account-compliance-ip` | 账号健康、合规与知识产权 | KYC、认证、受限商品、产品安全、EPR、侵权、停售、下架和封号风险。 |
| `crossborder-logistics` | 跨境物流、供应链与海关 | 海空运、港口、清关、承运商、海外仓和外部尾程。 |
| `competitor-marketplaces` | 竞品平台动态 | Walmart、Shopify、TikTok Shop、Temu、eBay 等非 Amazon 平台变化。 |
| `ai-ops-tools` | AI 工具与运营自动化 | AI Agent、ERP、BI、客服、SP-API、Ads API 和可量化运营效率工具。 |
| `seller-community-signal` | 卖家社区与异常信号 | 多个独立卖家复现但尚未获得官方确认的异常；确认后改归对应业务类。 |

## 冲突顺序

分类冲突时，依次判断：合规/账号风险 → 费用利润税务 → Amazon FBA 履约 → 跨境物流 → 广告流量 → Listing/SEO/VOC → 工具效率 → 非 Amazon 竞品平台 → 未确认社区信号 → Amazon 全局公告。

## 卖家影响维度

| 枚举 | 中文 | 适用含义 |
| --- | --- | --- |
| `money` | 钱 | 费用、利润、税务、关税、汇率、结算或现金流。 |
| `goods` | 货 | 库存、补货、仓储、运输、清关、配送或退货。 |
| `account` | 号 | 账号健康、销售资格、产品合规、认证或知识产权。 |
| `traffic` | 流量 | 广告、搜索、Listing、评论、曝光、点击或转化。 |
| `efficiency` | 效率 | API、AI、ERP、BI、客服或运营自动化。 |
| `competition` | 竞争 | 新渠道机会、非 Amazon 平台布局或竞争态势。 |
