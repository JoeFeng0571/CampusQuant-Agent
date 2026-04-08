// CampusQuant 投教文章数据库
// 共 12 篇精选文章，按分类组织。
// 供 resources.html 和 article_detail.html 共同使用。

window.CAMPUSQUANT_ARTICLES = [
// ══════════════════ 财商基础 ══════════════════
{
id: 'basic-etf-first',
category: 'basic',
title: '为什么大学生更应该先学指数基金，而不是先找十倍股',
summary: '先建立长期账户和定投习惯，再去研究个股，能显著降低情绪交易和高频犯错的概率。文章会讲清楚指数基金适合新手的底层原因。',
date: '2026-04-06',
views: '4,812',
readTime: '8 分钟',
level: '新手友好',
content: `
<p>大学生进入股市的第一个念头，往往是"能不能找到下一只十倍股"。这种想法本身没错，但它通常意味着三件几乎必然发生的事：第一，你会花大量时间研究你并不熟悉的行业；第二，你会高估自己对企业的判断能力；第三，在持仓过程中，你会因为几次波动反复怀疑自己，最终卖在低点。</p>

<p>这些都不是"研究不够"的问题，而是阶段错位——你把一件需要 10 年经验积累的事，放在了经验为零的阶段。</p>

<h3>指数基金帮你绕开了最难的那一步</h3>
<p>指数基金的本质是"一篮子股票"。比如沪深 300 指数基金，持有的就是 A 股市值最大的 300 家公司。你买一份，相当于同时成为这 300 家公司的微量股东。它的三个核心优势对新手特别关键：</p>

<p><strong>1. 它帮你解决了"买什么"的问题。</strong>你不需要判断哪家公司会在 5 年后翻倍。指数会自动淘汰掉不行的公司，纳入成长起来的公司——这个过程是免费给你做的。</p>

<p><strong>2. 它的持仓是透明且稳定的。</strong>主动基金经理可能在某个季度突然重仓白酒或新能源，你作为持有人却要等到季报才知道。而宽基指数的成分是公开的，不会一夜之间大变。</p>

<p><strong>3. 它的费率极低。</strong>主流宽基 ETF 的综合年费率在 0.15%~0.5%，主动基金往往是 1.5%~2%。你可能觉得差别不大，但 30 年复利下来，这 1% 的差距会吞掉你三分之一的收益。</p>

<h3>先建立长期账户的习惯</h3>
<p>大学生的最大资产不是钱，而是<strong>时间</strong>。你和 35 岁第一次投资的人相比，有额外的 13~15 年复利空间，这在后期会放大到非常惊人的差距。但要把这份优势兑现，你需要做一件事：<em>趁早建立一个"不会被花掉"的长期账户，坚持定投进去</em>。</p>

<p>指数基金定投是最适合承担这个角色的工具：金额小（每月 100~500 元都可以）、操作简单（设置自动扣款就行）、不需要看盘、不会让你频繁做决策。它的回报不会让你今年暴富，但它会让你在 30 岁的时候账户里有一笔你无法通过工资快速复制的资金。</p>

<h3>为什么要把选股留到后面</h3>
<p>选股不是"坏事"，它只是对阶段有要求。一个合格的选股流程至少包括：能读懂三张报表、能判断行业竞争格局、能估算企业内在价值、能在股价下跌 30% 时保持理性。这四项能力，大学生在刚开始的半年到一年里几乎都不具备。</p>

<p>贸然选股的结果通常是：你在牛市追涨被套，在熊市恐慌割肉。几次下来你会觉得"股市就是赌博"，然后彻底离开市场——这才是最大的损失。</p>

<div style="background:rgba(89,240,194,.08);border-left:3px solid #59f0c2;padding:16px 18px;border-radius:10px;margin:18px 0">
<strong>一个务实的起步路径：</strong><br>
用前 6 个月完全定投宽基指数，在这期间只做一件事——熟悉账户操作、熟悉市场情绪、熟悉自己在浮盈和浮亏时的真实反应。等这份"感觉"建立起来之后，再拿出账户 10%~20% 的资金去尝试个股，这时候你犯错的代价也小得多。
</div>

<h3>最后一句大实话</h3>
<p>指数基金听起来"无聊"，所以大部分新手看不上它。但过去 20 年的数据显示：80% 以上的主动基金经理长期跑不赢宽基指数，更别说绝大多数散户。在你还没有证明自己属于那 20% 之前，先做一个诚实的长期持有者——这不是保守，这是最锐利的理性。</p>
`
},
{
id: 'basic-market-diff',
category: 'basic',
title: 'A 股、港股、美股到底有什么区别：交易规则、税费和流动性一次看懂',
summary: '从交易时间、涨跌幅限制、印花税、分红税和市场结构出发，建立跨市场的基本认知，避免简单把不同市场混成一个逻辑。',
date: '2026-04-03',
views: '3,905',
readTime: '10 分钟',
level: '新手友好',
content: `
<p>很多大学生接触股市时，会把"A 股思维"不加区分地套到港股和美股上，结果在交易规则、估值逻辑、流动性上吃大亏。这三个市场表面看都是"股票市场"，但底层规则差别巨大。</p>

<h3>先看最直观的差异</h3>
<table style="width:100%;border-collapse:collapse;margin:14px 0;font-size:13px">
<thead><tr style="background:rgba(111,215,255,.08);color:#6fd7ff"><th style="padding:10px;text-align:left">维度</th><th style="padding:10px;text-align:left">A 股</th><th style="padding:10px;text-align:left">港股</th><th style="padding:10px;text-align:left">美股</th></tr></thead>
<tbody>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">T+几</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">T+1</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">T+0</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">T+0</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">涨跌幅限制</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">±10% (主板)</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">无限制</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">无限制（有熔断）</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">最小交易单位</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">100 股</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">按股票定（常见 100/500/1000）</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">1 股（甚至零股）</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">印花税</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">卖出 0.05%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">双向 0.1%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">无</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">分红税</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">差别化（持有&gt;1年免税）</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">20%（内地投资者）</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">10%（中美协定预扣）</td></tr>
<tr><td style="padding:10px">盘前盘后</td><td style="padding:10px">无</td><td style="padding:10px">无</td><td style="padding:10px">各 4 小时</td></tr>
</tbody>
</table>

<h3>T+1 vs T+0：不只是交易速度</h3>
<p>A 股的 T+1 意味着当天买入的股票当天卖不掉。乍一看是个小限制，但它对交易风格有根本影响：<strong>A 股几乎不存在真正意义上的日内短线</strong>，你做错方向就只能硬扛一晚。这反而在某种程度上保护了新手——它让你不能频繁操作。</p>

<p>港股和美股的 T+0 允许日内反复交易，但这也意味着波动会被情绪放大。美股尤其明显，一些热门股一天波动 10%~15% 都很正常。新手在 T+0 市场如果没有严格的仓位和止损纪律，很容易被打爆。</p>

<h3>涨跌幅限制带来的错觉</h3>
<p>A 股的 ±10% 涨跌停制度是一种"保护"，但也制造了错觉。新手看到一只股票涨停，常常以为"明天肯定还要涨"，实际上涨停板之后走弱的概率同样存在。更要命的是跌停——一旦跌停无法卖出，你会被迫持有到第二天开盘继续跌。</p>

<p>港股没有涨跌停，极端行情中你可能看到单日 ±30% 的波动。这不是"出事了"，而是正常。所以港股的仓位和止损管理反而要比 A 股更严格。</p>

<h3>港股的"仙股"现象</h3>
<p>港股里有很多股价长期低于 1 港元的"仙股"。一部分是真烂公司跌下来的，还有一大批是几乎没人交易的"僵尸股"。它们的成交量极低，一个稍大的买单就能拉涨几十个百分点，反之亦然——极易被操纵。</p>

<p>新手应该严格回避仙股，哪怕它看起来"便宜得离谱"。港股通制度本身也把大部分这类股票排除在外，只保留了主流蓝筹，这对内地投资者其实是个保护。</p>

<h3>美股的特殊规则：PDT</h3>
<p>如果你用保证金账户在 5 个交易日内进行了 4 次或以上的"日内往返交易"，你会被标记为 Pattern Day Trader（PDT）。一旦被标记，账户权益必须保持在 25000 美元以上，否则交易会被限制 90 天。</p>

<p>大学生的账户几乎不可能达到这个门槛。所以在美股做任何策略都应该是<strong>中长线</strong>——不要频繁进出，否则连交易权限都会被剥夺。</p>

<h3>费用结构差异</h3>
<p>A 股的交易成本是"佣金 + 过户费 + 印花税"。印花税只在卖出时收取，单边 0.05%。如果你频繁交易，光印花税就能显著吃掉你的收益。</p>

<p>港股的印花税是双向的，每次买卖都要交 0.1%，频繁交易成本更高。另外分红的 20% 红利税对于内地投资者来说也是一个长期损耗。</p>

<p>美股没有印花税，佣金也被大部分券商压到零或极低水平，这是美股最大的成本优势。但对于内地投资者，分红会被预扣 10% 股息税。</p>

<h3>给大学生的实用建议</h3>
<ul style="list-style:none;display:grid;gap:10px;margin:14px 0">
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>先从 A 股开始。开户门槛低，交易规则相对友好，T+1 强制给你"冷静期"。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>港股建议等有 50 万资金后通过港股通开通，不要为了港股去境外券商开户。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>美股如果想接触，通过富途、老虎等正规境外券商入门即可，起步资金可以很小（1000 美元以内）。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>永远记住：规则不同 = 策略不同。不要把 A 股的习惯搬到港美股，也不要倒过来。</li>
</ul>
`
},
{
id: 'basic-kline-5q',
category: 'basic',
title: '看不懂 K 线时，先看这 5 个问题而不是盯着红绿柱',
summary: '从趋势、位置、量能、催化和风险回撤五个角度切入，让技术图形回到交易决策框架，而不是把图表当作神谕。',
date: '2026-03-30',
views: '5,286',
readTime: '9 分钟',
level: '入门',
content: `
<p>新手打开一张 K 线图时，第一反应往往是"这根是红的还是绿的，后面会涨还是会跌"。这种看法让 K 线变成了一种玄学——涨了就"看多"，跌了就"看空"，完全没有决策价值。</p>

<p>真正有效的看图方式，是把 K 线当作"企业 + 市场情绪"的可视化，而不是预测工具。下面是五个问题，按顺序问一遍，你对一张图的理解会深很多。</p>

<h3>问题 1：它现在处在什么趋势里？</h3>
<p>最基础但最被忽略的问题。判断趋势只需要三条均线：20 日（短期）、60 日（中期）、200 日（长期）。</p>
<ul style="list-style:none;display:grid;gap:8px;margin:10px 0">
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span><strong>上升趋势</strong>：价格在 200 日均线之上，20 日 &gt; 60 日 &gt; 200 日，均线都向上。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ffd37c">▸</span><strong>震荡</strong>：价格在三条均线附近反复穿越，均线纠缠。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span><strong>下降趋势</strong>：价格在 200 日均线之下，20 日 &lt; 60 日 &lt; 200 日，均线都向下。</li>
</ul>
<p>很多新手喜欢"抄底"下降趋势里的股票——这几乎是胜率最低的操作。下降趋势里最好的态度是"观望"，不要试图当英雄。</p>

<h3>问题 2：当前位置是哪里？</h3>
<p>同样是涨了 10%，在趋势起点和趋势末端意义完全不同。判断"位置"的几个工具：</p>
<p><strong>52 周高低点</strong>：股价距离 52 周最高点多远？离最高 3% 以内是相对高位，离最低 5% 以内是相对低位。</p>
<p><strong>历史估值分位</strong>：当前 PE 或 PB 在过去 5~10 年的什么位置？30% 分位以下偏低，70% 分位以上偏高。</p>
<p><strong>前期重要支撑和压力</strong>：看图中有没有明显的横向突破或跌破——这些位置往往会再次起作用。</p>
<p>位置判断不是预测，而是让你知道"如果我现在买，我站在哪里"。</p>

<h3>问题 3：成交量在说什么？</h3>
<p>价格是表象，成交量是真相。一根上涨的 K 线如果没有成交量配合，它的含金量要大打折扣。几个典型信号：</p>
<ul style="list-style:none;display:grid;gap:8px;margin:10px 0">
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span><strong>放量上涨</strong>：有资金真金白银在买入，趋势可信度高。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span><strong>缩量上涨</strong>：只是抛压减少，不是真的有人买，随时可能回落。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span><strong>放量下跌</strong>：恐慌抛售，短期会继续探底。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ffd37c">▸</span><strong>缩量下跌</strong>：抛压衰竭，可能接近底部。</li>
</ul>
<p>"量在价先"这句老话有一定道理——成交量往往会先于价格给出信号。</p>

<h3>问题 4：有没有实质性催化？</h3>
<p>如果一只股票突然启动上涨，你要问自己一个问题："为什么是现在？"</p>
<p>健康的催化剂通常是：业绩预告超预期、行业政策变化、新产品发布、重要合作、估值被研报上调。这些催化剂有持续性，支持的涨幅也更扎实。</p>
<p>可疑的催化剂是：莫名其妙的"消息面利好"、各种群里的"内部消息"、没有源头的传闻。这些即使短期有效，往往一两天后就会被证伪，跟风的人会成为接盘者。</p>

<h3>问题 5：最大的风险在哪里？</h3>
<p>这是最容易被跳过的问题，但它决定了你能不能扛过下跌。具体要看三件事：</p>
<p><strong>向下空间</strong>：最近的支撑位在哪里？如果跌到那里，你亏多少？能不能接受？</p>
<p><strong>基本面雷区</strong>：公司有没有已知的风险点（商誉减值、诉讼、监管、大股东减持）？</p>
<p><strong>系统性风险</strong>：当前大盘的位置？宏观有没有明显的下行风险？</p>
<p>只有当你能清楚回答"最坏情况我会怎样"，你买入后才能真正拿得住。否则你只是在赌运气。</p>

<div style="background:rgba(111,215,255,.08);border-left:3px solid #6fd7ff;padding:16px 18px;border-radius:10px;margin:18px 0">
<strong>把这 5 个问题做成你的决策模板：</strong><br>
下次你想买一只股票时，拿出纸笔按顺序回答一遍。如果有任何一个你答不上来，就说明这笔交易你还没想清楚——最好的做法是<em>不做</em>。学会"不交易"和学会"交易"一样重要。
</div>

<h3>结语</h3>
<p>K 线图的意义不是算命，而是信息的压缩可视化。当你把它和基本面、估值、量能、催化连起来看时，它就从"玄学"变成了"决策辅助"。反过来，如果你只盯着红绿柱想"明天涨不涨"——那无论多少根 K 线都救不了你。</p>
`
},

// ══════════════════ 分析方法 ══════════════════
{
id: 'analysis-5-metrics',
category: 'analysis',
title: '一张财报先看哪 5 个指标：营收、毛利率、净利率、现金流、负债率',
summary: '把常见财报指标按阅读顺序串起来，帮助你快速判断一家企业是暂时遇冷，还是商业模式本身正在恶化。',
date: '2026-04-07',
views: '2,764',
readTime: '12 分钟',
level: '中级',
content: `
<p>读财报最容易犯的错，是上来就看"净利润同比增长多少"，看到一个亮眼的数字就下结论。但净利润是财报里最容易被"美化"的数字——它可以通过会计调整、一次性收益、资产出售等方式被临时推高。要判断一家公司真正的经营质量，需要按顺序看这 5 个指标。</p>

<h3>指标 1：营业收入——判断增长的起点</h3>
<p>营收是最难造假的数字之一（虽然不是不可能），它反映了公司业务规模。</p>
<p><strong>看什么</strong>：</p>
<ul style="list-style:none;display:grid;gap:8px;margin:10px 0">
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>同比增长率（YoY）：和去年同期相比增长多少。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>季度环比（QoQ）：是否逐季加速或减速。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>分业务营收结构：主营业务占比是否稳定。</li>
</ul>
<p><strong>警报信号</strong>：营收停滞但利润暴涨——这往往是通过"降本增效"或"节省研发投入"做出来的，不可持续。</p>

<h3>指标 2：毛利率——商业模式的体检</h3>
<p>毛利率 = (营收 - 销售成本) / 营收。它反映的是这家公司"本行生意"的盈利能力，不受期间费用和所得税影响。</p>
<p>一个健康的公司，毛利率应该是<strong>稳定的或者缓慢提升的</strong>。毛利率下滑通常意味着三种情况之一：</p>
<ul style="list-style:none;display:grid;gap:8px;margin:10px 0">
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span>原材料或人力成本上涨，而终端售价没能同步提升——竞争力在减弱。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span>行业进入价格战，公司不得不降价保量。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span>产品结构变差，低毛利业务占比上升。</li>
</ul>
<p>不同行业的毛利率基准差别巨大：白酒 60%~90%、互联网 50%~80%、家电 20%~30%、零售 10%~20%。比较要在同行业内做，跨行业比毛利率毫无意义。</p>

<h3>指标 3：净利率——最终的盈利能力</h3>
<p>净利率 = 净利润 / 营收。它告诉你"每 100 元收入里最终能留下多少钱"。</p>
<p>净利率反映的是整体经营效率——包括毛利率、期间费用（销售、管理、研发、财务）、税率。一个有意思的事实是：<strong>高毛利不等于高净利</strong>。有些公司毛利 50% 但销售费用就吃掉 30%（广告型企业），这种公司的实际赚钱能力要打折扣。</p>
<p><strong>需要警惕的情况</strong>：净利率远高于同行但毛利率接近——这往往是"少做了事"导致的（少投研发、少搞销售），短期好看，长期会透支竞争力。</p>

<h3>指标 4：经营性现金流——真金白银的检验</h3>
<p>这是最重要的一个指标。利润是"账面"的，现金才是"到账"的。经营性现金流净额 / 净利润这个比率，如果长期低于 1（特别是低于 0.8），就要非常警惕。</p>
<p><strong>为什么会出现"有利润没现金"</strong>：</p>
<ul style="list-style:none;display:grid;gap:8px;margin:10px 0">
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span>应收账款大幅增加——卖出去的东西钱没收回来。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span>存货大幅增加——生产出来的产品卖不动。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span>会计收入确认激进——收入"记在了账上"但客户还没付钱。</li>
</ul>
<p>这三种情况任何一个持续两三年以上，公司基本面都在恶化。相反，经营现金流大于净利润的公司（比率 &gt; 1.2），往往有强大的议价能力——比如能做到预收款、能压供应商账期。</p>

<h3>指标 5：资产负债率——安全垫的厚度</h3>
<p>资产负债率 = 总负债 / 总资产。这个比率衡量的是公司的财务杠杆和偿债压力。不同行业的基准差别也很大：</p>
<table style="width:100%;border-collapse:collapse;margin:12px 0;font-size:13px">
<thead><tr style="background:rgba(111,215,255,.08);color:#6fd7ff"><th style="padding:10px;text-align:left">行业</th><th style="padding:10px;text-align:left">合理区间</th><th style="padding:10px;text-align:left">警戒线</th></tr></thead>
<tbody>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">消费品（白酒、饮料）</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">20%~40%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">&gt;60%</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">制造业</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">40%~60%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">&gt;70%</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">房地产</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">60%~80%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">&gt;85%</td></tr>
<tr><td style="padding:10px">银行金融</td><td style="padding:10px">90% 左右（行业特性）</td><td style="padding:10px">看核心资本充足率</td></tr>
</tbody>
</table>
<p>更细一步可以看<strong>有息负债率</strong>（只看需要付利息的借款）。如果有息负债率 &gt; 40% 且持续上升，公司就存在流动性风险——一旦行业下行或融资收紧，很容易出问题。</p>

<h3>把 5 个指标串起来</h3>
<p>五个指标不能孤立看，要串起来判断一家公司的真实状态：</p>
<div style="background:rgba(89,240,194,.08);border-left:3px solid #59f0c2;padding:16px 18px;border-radius:10px;margin:18px 0">
<strong>健康成长型</strong>：营收增长 &gt; 15%，毛利率稳定或微升，净利率稳定，经营现金流/净利润 &gt; 1，负债率合理——这是最理想的。<br><br>
<strong>风险堆积型</strong>：营收增长但增速放缓，毛利率在下滑，经营现金流跟不上利润，负债率在上升——这是"爆雷前夜"，再好的历史业绩也不要买。<br><br>
<strong>困境反转型</strong>：营收下滑但毛利率稳住，经营现金流没断，负债可控——这种公司如果行业回暖，反弹弹性很大，但需要判断行业拐点。
</div>

<p>财报分析最大的价值不是"找到黑马"，而是"帮你过滤掉 80% 不该碰的公司"。只要你能坚持用这 5 个指标筛选，你的胜率会比随便看财经新闻的人高出一大截。</p>
`
},
{
id: 'analysis-low-pe-trap',
category: 'analysis',
title: 'PE 很低为什么不一定便宜：估值陷阱最容易骗新手的三种情况',
summary: '低估值可能来自行业下行、盈利见顶或资产质量变差。文章会讲清"便宜"和"有问题"之间的区别。',
date: '2026-04-02',
views: '3,192',
readTime: '11 分钟',
level: '中级',
content: `
<p>新手学完 PE（市盈率）这个概念后，最常得出的结论是："我要找低 PE 的股票买"。这种想法对了一半，错了一半。低 PE 确实可能意味着"便宜"，但也可能意味着"有问题"。真正的考验是区分这两者——这就是<strong>价值陷阱</strong>的本质。</p>

<h3>先复习一下 PE 的定义</h3>
<p>PE = 股价 / 每股收益，或者换算为 PE = 总市值 / 净利润。它的经济含义是："假设公司盈利不变，你几年能回本。"PE 20 意味着 20 年回本（年化 5% 的收益率），PE 10 意味着 10 年回本（年化 10%）。</p>
<p>从这个角度看，PE 越低越有"吸引力"。但问题是：它假设了<em>盈利不变</em>——这个假设往往不成立。</p>

<h3>陷阱 1：周期顶部的高盈利低 PE</h3>
<p>这是最常见的陷阱。想象一家煤炭公司，在煤价大涨的那一年，净利润飙升 5 倍，股价也涨了 2 倍。这时它的 PE 可能只有 5~6 倍——看起来极度便宜。但问题是：这份利润建立在<strong>不可持续的高煤价</strong>之上。</p>
<p>当煤价从高点回落，净利润可能从 100 亿掉到 20 亿，PE 瞬间从 6 倍变成 30 倍。这时你才发现，原来当初"便宜"的不是股票，而是"短期虚高的盈利"。</p>
<p><strong>典型的周期行业</strong>：煤炭、钢铁、有色金属、化工、航运、猪肉、面板。这些行业的盈利波动极大，用单一年份的 PE 判断估值会严重失真。</p>
<div style="background:rgba(255,142,142,.08);border-left:3px solid #ff8e8e;padding:16px 18px;border-radius:10px;margin:18px 0">
<strong>正确的处理方式：</strong>对周期行业，不要看 PE，要看 PB（市净率）。在行业底部，PB 会被压到 0.5~0.8 倍，是周期股的真正低估区域。周期行业的经典口诀是"高 PE 买入，低 PE 卖出"——反直觉，但对。
</div>

<h3>陷阱 2：行业永久性衰退</h3>
<p>第二种陷阱是行业本身正在被时代淘汰。比如 2010 年代的胶卷公司、功能机制造商、DVD 出租连锁店、传统报纸。它们可能依然有利润，PE 也确实很低（8~10 倍），但这些利润正在<strong>一年比一年萎缩</strong>。</p>
<p>买这种公司的人觉得自己在"抄底价值股"，实际上是在买一份正在融化的冰块。时间不是你的朋友——拖得越久，你亏得越多。</p>
<p><strong>如何识别</strong>：看营收趋势，而不是只看利润。如果营收连续 3~5 年下滑，无论利润表现如何，都要认定它处于"永久性衰退"。这时低 PE 不是机会，是警告。</p>

<h3>陷阱 3：会计利润 vs 真实盈利</h3>
<p>第三种陷阱最难识别：公司的"低 PE"来自于会计层面的美化，而不是真实的赚钱能力。几种常见手法：</p>
<p><strong>1. 一次性收益</strong>：出售子公司、出售土地、政府补贴、投资收益。这些不是主营业务利润，不具有可持续性。新手看到 PE 从 30 降到 10 会觉得便宜，实际上是去年一次性卖资产产生了一笔横财。</p>
<p><strong>2. 放松应收账款</strong>：为了冲业绩，公司放宽赊销政策，大量销售没收到钱的商品。账上显示收入和利润都增长，但经营现金流大幅落后。</p>
<p><strong>3. 递延费用</strong>：推迟某些研发投入或销售费用的确认时点，让当期利润变好看。但这种操纵的空间有限，最终会反噬。</p>
<p><strong>如何识别</strong>：拿起利润表和现金流量表对比看。如果净利润和经营性现金流长期背离（经营性现金流/净利润 &lt; 0.8），那你看到的利润就是有水分的。</p>

<h3>正确使用 PE 的几个准则</h3>
<div style="background:rgba(111,215,255,.08);border-left:3px solid #6fd7ff;padding:16px 18px;border-radius:10px;margin:18px 0">
<strong>第一，看滚动 PE（TTM），不看静态 PE。</strong>静态 PE 用的是上一年度数据，滞后太多。TTM 使用过去四个季度的累计利润，更能反映当前状态。<br><br>
<strong>第二，看历史分位，不看绝对值。</strong>一家互联网公司 PE 30 倍可能是低估（因为它历史均值是 45 倍），一家白酒公司 PE 30 倍可能是高估（因为它历史均值是 25 倍）。重点是看当前 PE 在过去 5~10 年的分位。<br><br>
<strong>第三，看同行比较。</strong>在同一个行业内横向比较才有意义。一家 PE 15 的银行和一家 PE 15 的 SaaS 公司，估值含义完全不同。<br><br>
<strong>第四，结合 PEG 看成长性。</strong>PEG = PE / 盈利增速。一家 PE 40、增速 50% 的公司（PEG = 0.8），比一家 PE 15、增速 5% 的公司（PEG = 3）更划算。<br><br>
<strong>第五，现金流比利润可靠。</strong>优先选择现金流稳定、主业清晰的公司，哪怕 PE 不是最低的。
</div>

<h3>什么样的"低 PE"才是真便宜</h3>
<p>真正的便宜通常满足几个条件：</p>
<ul style="list-style:none;display:grid;gap:8px;margin:10px 0">
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>公司处在稳定或上升的行业，不是夕阳行业。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>净利润来自可持续的主营业务，不是一次性收益。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>经营性现金流充沛，甚至大于净利润。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>负债率合理，没有短期债务危机。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>PE 处于公司自身历史低分位（&lt; 30%）。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>低估的原因是"市场短期情绪"（比如行业风波、宏观恐慌），而不是"基本面恶化"。</li>
</ul>
<p>这六个条件同时满足的情况很少——但这才是价值投资真正要找的东西。遇到时你应该敢于重仓，而不是因为"低 PE 到处都是"就随便买。</p>

<h3>最后的提醒</h3>
<p>估值是一门"感觉的艺术 + 数据的纪律"。PE 只是一个起点，不是终点。当你看到一个"便宜得让你心动"的 PE 时，最应该做的事是：停下来问自己三遍——<em>为什么它这么便宜？市场是不是看到了我没看到的风险？</em>只有排除了这些问题，便宜才是真便宜。</p>
`
},
{
id: 'analysis-company-frame',
category: 'analysis',
title: '如何把一家公司讲清楚：商业模式、竞争优势、增长路径、风险点',
summary: '这是个股研究的最小闭环。只要你能把这四件事说清楚，基本面分析就已经摆脱了"凭感觉"阶段。',
date: '2026-03-28',
views: '2,410',
readTime: '14 分钟',
level: '中级',
content: `
<p>新手常常抱怨"不知道从哪里研究一家公司"。财报 100 多页，研报几十份，新闻每天一大堆——读完依然说不出"这家公司到底怎么样"。其实你不需要读完所有资料，你只需要能回答四个问题：商业模式、竞争优势、增长路径、风险点。</p>
<p>这四个问题构成了基本面分析的最小闭环。把它们说清楚，你就已经超过 90% 的散户。</p>

<h3>问题 1：商业模式——它靠什么赚钱？</h3>
<p>商业模式回答的是"公司的赚钱机器长什么样"。你需要用一句话说出来：<em>"它以 X 为客户，通过 Y 方式提供 Z 产品/服务，客户为此付费。"</em></p>
<p>比如：</p>
<ul style="list-style:none;display:grid;gap:10px;margin:12px 0">
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong style="color:#fff">茅台</strong>：以中高收入人群和商务场景为客户，通过经销商渠道销售茅台酒，客户为品牌和稀缺性支付溢价。</li>
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong style="color:#fff">腾讯</strong>：以数亿月活用户为基础，通过游戏、广告、金融科技、云业务变现，核心是"流量池 + 多场景变现"。</li>
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong style="color:#fff">苹果</strong>：以全球高端消费者为客户，通过硬件（iPhone、Mac）+ 服务（App Store、iCloud）双轮驱动，硬件引流，服务收高毛利。</li>
</ul>
<p>能不能用一句话说清楚，决定了你对这家公司的理解深度。如果说不出来，你就还没理解它——更不要谈买它。</p>

<h3>问题 2：竞争优势——为什么别人抢不走它的生意？</h3>
<p>竞争优势在巴菲特的话里叫"护城河"。它是公司长期盈利能力的保证——没有护城河的公司，可能短期赚钱，但长期会被竞争抹平利润。常见的护城河有五种：</p>
<p><strong>1. 品牌溢价</strong>：消费者愿意为同样的产品支付更高价格。典型：茅台、LV、Tiffany。品牌护城河最持久，但建立起来也最慢。</p>
<p><strong>2. 规模经济</strong>：公司规模大到一定程度后，单位成本显著低于竞争对手。典型：沃尔玛、亚马逊、京东物流、格力。规模护城河常见于零售、制造、物流业。</p>
<p><strong>3. 网络效应</strong>：用户越多，产品对每个用户越有价值。典型：微信、Facebook、Visa、淘宝。网络效应护城河最"硬"，一旦形成几乎不可撼动。</p>
<p><strong>4. 转换成本</strong>：客户一旦使用就很难换到竞争对手。典型：企业级 SaaS（用友、金蝶）、银行账户、Adobe。这种护城河让公司享有稳定的续费收入。</p>
<p><strong>5. 特许经营/监管壁垒</strong>：因为牌照、专利或特许权形成的垄断。典型：中国石化、长江电力、各种专利药企。这种护城河最稳但也最容易被政策改变。</p>
<p>你要做的是：<strong>明确说出这家公司属于哪一种护城河，并举例证明它确实存在</strong>。如果你找不到任何一种护城河，这家公司就不属于"好生意"的范畴。</p>

<h3>问题 3：增长路径——它未来 3~5 年的钱从哪里来？</h3>
<p>一家好公司不仅当前要赚钱，还要有可见的增长空间。分析增长路径，问三个问题：</p>
<p><strong>1. 市场天花板有多高？</strong>这家公司目前的市场份额是多少？行业整体天花板是多少？如果它已经占了 80% 市场份额，增长空间就很有限；如果只占 5%，还有大量空间。</p>
<p><strong>2. 增长来自什么地方？</strong>具体来说有四种典型增长来源：</p>
<ul style="list-style:none;display:grid;gap:8px;margin:10px 0">
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span><strong>提价</strong>：老业务涨价（茅台每隔几年提一次价）。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span><strong>提量</strong>：老业务卖更多（海底捞开更多门店）。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span><strong>新品类</strong>：开辟新产品线（比亚迪从电池到整车）。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span><strong>出海</strong>：进入新地区（小米、字节的海外扩张）。</li>
</ul>
<p><strong>3. 管理层的资本配置能力如何？</strong>增长需要钱，钱从哪里来、花得对不对？看公司过去几年的 ROE（净资产收益率）。长期 ROE 大于 15% 的公司，说明管理层在有效使用股东的钱；长期 ROE 低于 10% 的，说明要么行业太差，要么管理层在浪费资源。</p>

<h3>问题 4：风险点——它可能死在什么地方？</h3>
<p>这是最容易被跳过、但最关键的一问。没有风险的公司不存在，只有"你没看到的风险"。强迫自己列出至少 3 个最有可能击垮这家公司的风险：</p>
<p><strong>常见的风险类型</strong>：</p>
<ul style="list-style:none;display:grid;gap:8px;margin:10px 0">
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span><strong>监管/政策风险</strong>：教培、游戏、互联网平台都受过监管重击。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span><strong>行业周期风险</strong>：地产、航运、半导体都有周期波动。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span><strong>技术颠覆风险</strong>：传统汽车被电车冲击、胶卷被数码淘汰。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span><strong>核心人物风险</strong>：董事长出事、核心技术人员流失。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span><strong>财务风险</strong>：现金流断裂、债务违约、商誉爆雷。</li>
</ul>
<p>列出风险后，更关键的问题是：<em>如果这些风险真的发生，公司会怎样？我买入的逻辑还成立吗？</em>如果答案是"股价腰斩"，那你进场前就应该想好"腰斩我能不能扛"——扛不了就不要买。</p>

<h3>用一页纸写完你的研究</h3>
<p>下次研究一家公司时，用一页纸（A4 就够了）按顺序写：</p>
<div style="background:rgba(89,240,194,.08);border-left:3px solid #59f0c2;padding:18px 20px;border-radius:10px;margin:18px 0">
<strong>【公司名称】一页研究备忘录</strong><br><br>
<strong>1. 商业模式（一句话）</strong>：<br>
<strong>2. 核心护城河</strong>：品牌 / 规模 / 网络 / 转换成本 / 特许经营（选一个或多个，说明证据）<br>
<strong>3. 未来 3 年增长逻辑</strong>：提价 / 提量 / 新品类 / 出海（具体说）<br>
<strong>4. 当前估值</strong>：PE 多少，处于历史什么分位，和同行对比如何<br>
<strong>5. 最大的 3 个风险</strong>：<br>
<strong>6. 我买入的理由</strong>：<br>
<strong>7. 我会在什么条件下卖出</strong>：<br><br>
<em>写不满这页纸 = 你还没研究明白，不要买。</em>
</div>

<h3>一个练习建议</h3>
<p>挑一家你最熟悉的公司（你日常用的产品、你父母工作的公司、你感兴趣的品牌），按这个框架写一页研究备忘录。你会立刻发现自己有多少问题答不上来——那些答不上来的地方，就是你下一步要研究的方向。</p>
<p>坚持写 10 家公司，你的基本面分析能力会彻底脱离"凭感觉"的阶段。这 10 家不需要都是你打算买的，重点是练习<strong>"把一家公司说清楚"这个能力</strong>。</p>
`
},

// ══════════════════ 风险控制 ══════════════════
{
id: 'risk-stop-loss',
category: 'risk',
title: '止损为什么不是认输，而是交易系统的一部分',
summary: '把止损从情绪动作变成规则动作。文章会说明固定比例止损、结构位止损和时间止损分别适用于什么场景。',
date: '2026-04-05',
views: '6,104',
readTime: '10 分钟',
level: '必修',
content: `
<p>新手最讨厌的词是"止损"。它让人联想到"我错了""我亏了""我要承认失败"。但在有经验的交易者眼里，止损和"认输"没有任何关系——它是交易系统的<strong>基础设施</strong>，和"买入"一样重要。</p>
<p>不设止损的交易者，迟早会把一次亏损拖成"永久损失"。这不是技术问题，是数学问题。</p>

<h3>为什么不止损会让你永远回不来</h3>
<p>先看一个残酷的数字：你亏损 20% 后，需要涨 25% 才能回本；亏损 50% 后，需要涨 100% 才能回本；亏损 80% 后，需要涨 400% 才能回本。</p>
<table style="width:100%;border-collapse:collapse;margin:14px 0;font-size:13px">
<thead><tr style="background:rgba(255,142,142,.08);color:#ff8e8e"><th style="padding:10px;text-align:left">亏损幅度</th><th style="padding:10px;text-align:left">回本所需涨幅</th></tr></thead>
<tbody>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">10%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">11.1%</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">20%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">25%</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">30%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">42.9%</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">50%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">100%</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">70%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">233%</td></tr>
<tr><td style="padding:10px">90%</td><td style="padding:10px">900%</td></tr>
</tbody>
</table>
<p>这个表格揭示了止损的数学本质：<strong>亏损越大，回本越难，难度不是线性而是指数增长</strong>。把亏损控制在 10% 以内，你需要的反弹力度不算大；一旦超过 30%，你就需要相当罕见的大牛市才可能回本。</p>

<h3>止损的本质：让你保留下次进场的权利</h3>
<p>交易不是一次性博弈，而是无数次的重复。你的任务不是"这次一定要赢"，而是"让自己永远还能下一次"。止损就是让你保留下一次下注权利的最低代价——只要你还在市场里，你就有翻身的机会。</p>
<p>真正完蛋的不是那些止损过几次的交易者，而是<strong>那些不肯止损、最终账户腰斩之后彻底离开的人</strong>。</p>

<h3>止损的三种方式</h3>
<p><strong>1. 固定比例止损</strong></p>
<p>最简单也最常用。你给自己定一条规则："任何买入的股票，亏损达到 8% 无条件卖出。"这种止损的优点是纪律强、简单易执行；缺点是没有考虑个股波动性差异——一只高波动的科技股，日波动 5% 很常见，用 8% 止损会频繁被打。</p>
<p><strong>适用场景</strong>：新手起步阶段、仓位较重的主力持仓、不熟悉的标的。固定比例一般建议 5%~10%，太紧会被频繁止损，太松意义不大。</p>
<p><strong>2. 结构位止损（技术止损）</strong></p>
<p>根据图形上的关键支撑位设置止损。比如你在 20 元买入一只股票，看图发现 18.5 元是前期重要支撑位。你的止损位就设在 18 元左右（跌破支撑，趋势走坏）。</p>
<p>这种止损更有逻辑——你止损不是因为"亏了多少钱"，而是因为"原来买入的理由已经不成立了"。</p>
<p><strong>适用场景</strong>：有一定技术分析基础的交易者、趋势跟随策略。关键是要在入场前就确定止损位，不能亏到一半才去找支撑位——那是自欺欺人。</p>
<p><strong>3. 时间止损</strong></p>
<p>这是最容易被忽视的一种。规则是：<em>"如果我买入后 X 天内股票没有按预期方向走，无论亏损与否，卖出。"</em></p>
<p>为什么这样做？因为你买入时通常有一个"催化剂"预期——比如业绩预告、行业政策、关键时点。如果这些催化剂兑现了但股价没反应，说明市场不认账——你的逻辑错了，哪怕没亏也要走。</p>
<p><strong>适用场景</strong>：事件驱动型交易、短线和波段。时间窗口一般 5~15 个交易日。</p>

<h3>止损的心理障碍</h3>
<p>道理都懂，但绝大多数人还是执行不了止损。原因有三个：</p>
<p><strong>沉没成本心理</strong>：你会觉得"已经亏了这么多，再亏一点没什么"，然后不断给自己找理由往后拖。但股价不会因为你的成本而"应该"反弹——它只对未来负责，不对你的买入价负责。</p>
<p><strong>反弹期待</strong>："再等等，肯定会反弹的"——这是最经典的自我安慰。问题是：如果你设定的条件已经破坏，反弹的概率就比跌下去低得多。</p>
<p><strong>自我形象保护</strong>：卖出止损等于承认"我错了"，而承认错误对很多人来说是痛苦的。解决方法是：重新定义"错"——你不是错在买错了，而是错在<em>不执行规则</em>。</p>

<div style="background:rgba(89,240,194,.08);border-left:3px solid #59f0c2;padding:18px 20px;border-radius:10px;margin:18px 0">
<strong>克服止损心理障碍的实操方法：</strong><br><br>
1. <strong>买入前写下止损位</strong>：用笔写在纸上，或者在券商 App 里设置条件单。让它变成"已经做出的决定"，而不是临时判断。<br><br>
2. <strong>把止损看作"保险费"</strong>：每次止损就当你为这笔交易交了保险。偶尔被"打"掉一点无所谓，保的是不爆仓的安全。<br><br>
3. <strong>复盘时不惩罚"被止损后反弹"</strong>：如果你止损后股价反弹了，不要自责——规则做对了，结果只是运气。如果你因此动摇规则，下一次大跌时你就扛不住了。<br><br>
4. <strong>连续 3 次止损后冷静</strong>：这往往不是运气差，而是市场环境不适合你的策略。暂停一周，重新审视。
</div>

<h3>最重要的一件事</h3>
<p>止损规则必须在你<strong>入场之前</strong>就决定好。入场后才去"研究要不要止损"的人，99% 会拖到跌无可跌。这不是意志力问题，这是人性——人对已经发生的损失有非理性的厌恶。</p>
<p>所以养成一个习惯：每次下单前问自己三个问题：</p>
<ul style="list-style:none;display:grid;gap:8px;margin:10px 0">
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>我的止损位是多少？跌到多少我无条件卖？</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>如果止损被打到，我会亏多少钱？我能接受吗？</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>如果答案是"不能接受"，说明仓位太大了——立刻减仓。</li>
</ul>
<p>做到这一步的人不多，但一旦做到，你就摆脱了"赌博型交易"的阶段，真正进入"系统化交易"。</p>
`
},
{
id: 'risk-position-size',
category: 'risk',
title: '仓位管理比选股更重要：新手最常见的 4 种致命错误',
summary: '满仓梭哈、亏损加仓、连续重仓同一行业、没有总回撤上限，是学生账户最常见的崩盘原因。',
date: '2026-03-31',
views: '5,488',
readTime: '9 分钟',
level: '必修',
content: `
<p>交易界有句老话："新手关注选股，老手关注仓位，高手关注系统。"这不是鸡汤。选一只好股票并不难，难的是在选对的情况下用合适的仓位把收益兑现，而不是一次错误就把前面积累的成果全部清零。</p>
<p>下面是大学生账户爆仓的四种最常见方式。每一种都不罕见，每一种都可以避免。</p>

<h3>错误 1：满仓梭哈</h3>
<p>"我看好这只股票，我就全买了"——这是最常见也最致命的错误。满仓意味着你没有任何容错空间：一次判断失误，你就失去了下一次交易的弹药。</p>
<p>更糟糕的是，满仓会放大你的情绪。涨了你兴奋得睡不着，跌了你焦虑得不吃不喝。情绪一旦失控，后面的决策会连环出错。</p>
<p><strong>正确的做法</strong>：把资金分成多个批次。不同的投资风格对应不同的仓位策略，但有一个通用原则：<em>任何单只股票的持仓不超过总资金的 20%~30%</em>。哪怕你极度看好，也要留出其他部分用于：备用资金、分散到其他标的、应对意外。</p>

<h3>错误 2：亏损加仓（摊薄成本）</h3>
<p>这是第二大致命错误。逻辑听起来很有吸引力："股价跌了 20%，我再买一份，成本就摊薄到只亏 10%，这样反弹更容易回本。"</p>
<p>但这种逻辑有两个致命缺陷：</p>
<p><strong>第一，你在和趋势对抗</strong>。股价下跌往往不是无缘无故的——要么公司出了问题，要么行业出了问题，要么大盘出了问题。继续加仓等于说"我比市场更聪明"，这个判断对的概率很低。</p>
<p><strong>第二，你让亏损在复利</strong>。原本你只亏 20%（假设单份），加仓后仓位翻倍，如果再跌 20%，你的总损失是 36%（不是 20%+10%）。每一次亏损加仓都会把"最大可能亏损"放大一倍。</p>
<p>真正的加仓逻辑应该是"盈利加仓"——确认方向正确后增加仓位，让赢家做大。而不是赌一个输家会翻身。</p>

<div style="background:rgba(255,142,142,.08);border-left:3px solid #ff8e8e;padding:16px 18px;border-radius:10px;margin:18px 0">
<strong>"金字塔加仓"的正确形态</strong>：不是跌了加，而是涨了加。第一笔买入 100 股确认方向；涨了 5% 加 50 股；再涨 5% 加 30 股；再涨加 20 股。这样你的成本始终接近低位，而仓位随着胜算增加而扩大。
</div>

<h3>错误 3：连续重仓同一行业</h3>
<p>"我研究了新能源，新能源前景光明，我全仓买新能源"——这种想法看起来很专注，实际上是把分散的资金又集中成了单点风险。</p>
<p>同一行业的股票相关性极高。一旦行业出现利空（政策、需求下滑、原材料涨价），你买的所有股票会同时下跌。你以为自己分散了（买了 5 只不同公司），实际上和满仓一只没什么区别。</p>
<p>真正的分散应该是<strong>跨行业分散</strong>。一个健康的股票组合至少覆盖 3~5 个低相关行业：消费、科技、金融、医药、能源、公用事业等。</p>
<p><strong>一个简单的检查方法</strong>：看你持仓的前三大股票是不是属于同一行业。如果是，你的分散就是假分散。</p>

<h3>错误 4：没有总账户的回撤上限</h3>
<p>这是最被忽视的一条。很多人会给单只股票设止损，但从来不给<strong>整个账户</strong>设止损。结果是：单笔亏损你都执行了止损，但账户整体一路往下，直到归零。</p>
<p>职业交易员和机构投资者都有一条"账户级止损线"。典型的规则是：</p>
<ul style="list-style:none;display:grid;gap:10px;margin:12px 0">
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>单月亏损超过总资金的 5% → 减仓至 50%，降低交易频率。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>单月亏损超过总资金的 10% → 清仓观望一个月。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>总体回撤超过 20% → 无条件停手，重新复盘整个交易系统。</li>
</ul>
<p>这样做的意义：当你进入"手感很差"的阶段，你能强制自己停下来，而不是越输越想扳回来。</p>

<h3>一个务实的仓位分层模型</h3>
<p>对大学生来说，不需要搞得太复杂。把你的资金分成三层：</p>
<div style="background:rgba(111,215,255,.08);border-left:3px solid #6fd7ff;padding:18px 20px;border-radius:10px;margin:18px 0">
<strong>核心仓（50%~60%）</strong>：长期持有的宽基 ETF 或蓝筹股。这部分不频繁操作，定投买入，遇到大跌不慌。<br><br>
<strong>确认仓（20%~30%）</strong>：经过充分研究、你有把握的中期持仓。按金字塔方式加仓，明确的止损位。<br><br>
<strong>试错仓（10%~20%）</strong>：短期波段或高赔率机会。严格止损，不影响核心资产。<br><br>
<strong>现金（至少 10%）</strong>：永远留一部分现金在账户里，以应对极端机会或风险。
</div>

<h3>心理层面的一个练习</h3>
<p>每次开仓之前，问自己一个问题：<em>"如果这笔交易明天就跌停，我的心情会怎样？"</em></p>
<p>如果答案是"很慌，要出大事了"——那你的仓位就太重了，立刻减仓。</p>
<p>如果答案是"有点难受，但能接受"——仓位合理。</p>
<p>如果答案是"无所谓，反正我做好了准备"——完美。</p>

<h3>最后一句提醒</h3>
<p>仓位管理的核心不是"赚更多"，而是"活得更久"。活着，你就有机会等到牛市、等到好机会、等到你的能力真正成长的那一天。没活着，你只是股市里一串被抹掉的数字。</p>
<p>股市是一个长期游戏。每一次"差点爆仓"的经历都不会让你成长——它只会让你离市场越来越远。</p>
`
},
{
id: 'risk-illegal-rec',
category: 'risk',
title: '识别非法荐股和社群带单：你以为进的是学习群，实际进的是收割池',
summary: '拆解典型话术、收费节奏和情绪操控方式，帮助大学生提高辨别力，避免在"老师带你赚"里交学费。',
date: '2026-03-27',
views: '7,021',
readTime: '8 分钟',
level: '必修',
content: `
<p>这篇文章是写给每一个曾经或将要被拉进"炒股学习群"的大学生。我想直接说一个结论：<strong>在中国大陆，任何非持牌机构以"荐股""带单""策略分享"名义收取费用的行为，都是违法的</strong>。不是"可能违法"，是"百分百违法"。</p>
<p>下面是这套骗局的完整套路，你看完之后应该能在 3 分钟内识别出它们。</p>

<h3>第一阶段：引流（免费进群）</h3>
<p>你是怎么进群的？大概率是下面几种之一：</p>
<ul style="list-style:none;display:grid;gap:10px;margin:12px 0">
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px">"老师直播免费讲解 K 线，扫码进群"——抖音、快手、B 站、小红书随处可见。</li>
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px">某个"投资学习"公众号，关注后自动推送"加老师微信"。</li>
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px">同学或朋友分享："有个老师挺厉害的，跟他学点东西"——这些朋友自己也是被拉进去的。</li>
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px">炒股软件里的"策略广场"推广位、某些财经 App 首页的推荐位。</li>
</ul>
<p>进群后你会看到：一个老师 + 十几个"助教" + 几十到几百个"学员"。群里每天发新闻、行情分析、"老师今日观点"。看起来很热闹，像一个真正的学习社群。</p>

<h3>第二阶段：建立信任（3~7 天）</h3>
<p>前几天老师不会做任何"收费"动作，只是：</p>
<p>1. <strong>每天免费推荐 1~2 只票</strong>。有的时候还真涨了几天。这不是因为老师厉害，而是"大数法则"——他同时在几十个群里推不同的票，总有几个会对。</p>
<p>2. <strong>组织"盈利晒单"</strong>。助教号开始陆续晒"跟老师买 XX 赚了 20%""感谢老师让我扭亏为盈"。这些截图 99% 是 PS 或虚假模拟盘截图。</p>
<p>3. <strong>讲一些似是而非的"技术分析"</strong>。用均线、MACD、KDJ 这些公开知识包装成"独家秘笈"，让你觉得"有点东西"。</p>
<p>这个阶段的目的是让你从"怀疑"变成"将信将疑"。如果你发现自己开始认真听老师讲话、开始在群里回复、开始期待明天的推荐——你已经上钩了一半。</p>

<h3>第三阶段：筛选付费用户</h3>
<p>免费阶段之后，老师会抛出"VIP 群"的概念：</p>
<div style="background:rgba(255,142,142,.08);border-left:3px solid #ff8e8e;padding:16px 18px;border-radius:10px;margin:18px 0;font-style:italic">
"免费群只能推两只票，我真正的核心策略都在 VIP 群"<br>
"VIP 群每天私推一只主力票，配合仓位计算和止盈止损"<br>
"进 VIP 要 6800 元，但你跟两单就能赚回来"<br>
"名额只剩 5 个，今晚 12 点截止"
</div>
<p>这种制造紧迫感的话术是典型的"饥饿营销 + 稀缺性操纵"。真正的投顾机构不会这样收费——他们有固定的、透明的服务合同。</p>
<p>有些人付了 VIP 费用，进去后前几天可能"跟单赚了一点小钱"。这是老师故意安排的，为的是让你相信"这钱花得值"。然后就进入下一阶段。</p>

<h3>第四阶段：真正的收割</h3>
<p>一旦你付了 VIP 费用并且开始跟单，骗局的核心就启动了。两种典型模式：</p>
<p><strong>模式 A：接盘侠模式</strong>。老师在低位提前建仓某只垃圾股，然后让 VIP 群的人"跟进"，推高股价到老师的出货位。老师卖出后，股价开始下跌，你成为高位接盘者。老师的利润 = 你的亏损。</p>
<p><strong>模式 B：加大付费模式</strong>。初期跟单亏了，老师会说"这只票还会涨，先止损出来，我明天推一只更好的"。几次下来你亏得差不多了，老师会说"你之前没跟住我的策略，是因为你进的是低级 VIP，高级 VIP 推的才是真正内部票"。让你再付一次钱——2 万、5 万、甚至 10 万都有人付过。</p>
<p>到这个阶段，其实你已经输了——不是输在市场，是输在"你相信自己能靠别人赚钱"这件事上。</p>

<h3>识别骗局的几个硬指标</h3>
<p>不需要记复杂的东西，只要符合下面任何一条，100% 是骗局：</p>
<ul style="list-style:none;display:grid;gap:10px;margin:12px 0">
<li style="padding:12px 14px;background:rgba(255,142,142,.06);border-radius:10px;font-size:14px;border-left:3px solid #ff8e8e"><strong>❌ 任何形式的私人微信/支付宝转账收费</strong>。合法投顾只走公司对公账户，不会用个人收款码。</li>
<li style="padding:12px 14px;background:rgba(255,142,142,.06);border-radius:10px;font-size:14px;border-left:3px solid #ff8e8e"><strong>❌ 老师头衔无法在"中国证券业协会从业人员查询"网站核验</strong>。</li>
<li style="padding:12px 14px;background:rgba(255,142,142,.06);border-radius:10px;font-size:14px;border-left:3px solid #ff8e8e"><strong>❌ 承诺任何形式的收益率（"月收益 20%""稳赚不赔"）</strong>。</li>
<li style="padding:12px 14px;background:rgba(255,142,142,.06);border-radius:10px;font-size:14px;border-left:3px solid #ff8e8e"><strong>❌ 有"老师操盘手帮你炒"的说法</strong>——证券账户不允许任何人代操作。</li>
<li style="padding:12px 14px;background:rgba(255,142,142,.06);border-radius:10px;font-size:14px;border-left:3px solid #ff8e8e"><strong>❌ 群里只看到盈利截图，从不看到亏损讨论</strong>。真实的投资社群一定有盈亏双向讨论。</li>
<li style="padding:12px 14px;background:rgba(255,142,142,.06);border-radius:10px;font-size:14px;border-left:3px solid #ff8e8e"><strong>❌ 要求你下载指定 App 或注册"内部交易平台"</strong>——这往往是假平台，钱进去就出不来。</li>
</ul>

<h3>如果已经被骗怎么办</h3>
<p>不要觉得丢脸而不敢声张，越拖越难追回。正确的做法是：</p>
<ul style="list-style:none;display:grid;gap:8px;margin:10px 0">
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">1.</span>立刻停止所有转账和跟单，退出相关群聊，但保留所有聊天记录和转账记录。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">2.</span>拨打反诈中心 96110 报案。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">3.</span>保存证据：聊天截图、转账凭证、对方账号信息、群号。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">4.</span>如果是通过平台（微信、QQ）付款的，向平台举报可以冻结对方账户。</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">5.</span>如果是大额损失，咨询律师考虑民事追偿。</li>
</ul>

<h3>一句话总结</h3>
<p>任何要你花钱买"荐股"的行为，都是把你当韭菜。真正的投资能力无法通过"加老师微信"获得，它只能通过你自己读书、研究、犯错、复盘一点点积累。这条路很慢，但它是唯一能带你到达的路。</p>
`
},

// ══════════════════ 案例进阶 ══════════════════
{
id: 'advanced-3-frameworks',
category: 'advanced',
title: '腾讯、茅台、苹果的研究框架有何不同：三种典型公司怎么比较',
summary: '同样是优质公司，平台、消费和科技硬件的核心矛盾完全不同。文章会给出可复用的比较模板。',
date: '2026-04-04',
views: '2,876',
readTime: '16 分钟',
level: '进阶',
content: `
<p>新手做研究有个常见误区：觉得"好公司都可以用同一套框架分析"。实际上，不同商业模式的公司，它们的关键指标、竞争要素、估值逻辑差别巨大。用白酒的思路去看科技股，会亏得莫名其妙；用科技股的思路去看消费股，会错过最好的复利机会。</p>
<p>这篇文章拿三家真正的"巨头"作例子：茅台（消费品）、腾讯（互联网平台）、苹果（消费电子）。看完你会明白为什么"具体公司具体分析"不是空话。</p>

<h3>茅台：消费品之王的分析框架</h3>
<p><strong>核心问题</strong>：茅台酒的"真实产能"和"真实需求"分别是多少？</p>
<p>茅台是一个极其特殊的生意。它的终端价（消费者购买价）和出厂价（茅台卖给经销商的价格）之间有巨大的差距——市场上一瓶飞天茅台零售价 2800~3000 元，而茅台的出厂价是 1169 元。这个"价差"不归茅台，而是进入了经销商和渠道体系。</p>
<p><strong>关键监控指标</strong>：</p>
<ul style="list-style:none;display:grid;gap:10px;margin:12px 0">
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong>批价（经销商之间的批发价）</strong>：批价上涨说明渠道缺货、需求旺盛；批价下跌说明渠道在抛货、需求疲软。这是茅台景气度的真正领先指标。</li>
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong>提价频率</strong>：茅台每次提价都是"印钞机"事件。历史上的提价节奏是 3~5 年一次，每次提价 15%~30%。</li>
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong>预收款</strong>：经销商打款才能拿货，预收款越高说明渠道越"嗷嗷待哺"。</li>
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong>基酒产量</strong>：茅台酒需要 5 年窖藏，所以今年的基酒产量决定了 5 年后的销售能力。</li>
</ul>
<p><strong>估值逻辑</strong>：茅台的 PE 长期在 25~45 倍区间。低于 25 倍往往是极度悲观情绪主导（2013 年反腐、2018 年贸易战、2022 年消费疲软），这种时候是历史性买点。高于 45 倍是泡沫区。</p>
<p><strong>核心风险</strong>：<em>不是经营风险，而是需求结构变化</em>。如果年轻一代不喝白酒，茅台的长期需求会崩塌。这也是茅台最大的不确定性——它的客户是 40 岁以上的中国商务人群，这个群体在未来 10~20 年会慢慢老去。</p>

<h3>腾讯：互联网平台的分析框架</h3>
<p><strong>核心问题</strong>：腾讯的"用户池"还能撑起多大的变现空间？</p>
<p>腾讯的商业本质是"流量 + 多场景变现"。它通过微信、QQ 等社交产品拥有中国几乎所有互联网用户，然后在这个流量池上做游戏、广告、金融科技、云服务。</p>
<p><strong>关键监控指标</strong>：</p>
<ul style="list-style:none;display:grid;gap:10px;margin:12px 0">
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong>微信 MAU（月活用户）</strong>：已经触及 13 亿+ 天花板，增长基本停滞。这意味着"拉新"的故事结束了，未来要靠"单用户变现效率"。</li>
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong>游戏流水和版号</strong>：游戏是腾讯最大的利润来源，新版号发放速度、头部游戏流水直接决定短期业绩。</li>
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong>广告收入增速</strong>：反映宏观消费强度（广告主的预算直接联动消费信心）。</li>
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong>视频号发展</strong>：这是腾讯未来 5 年最重要的变量。视频号能否做到字节系的广告效率，决定了腾讯有没有"第二成长曲线"。</li>
</ul>
<p><strong>估值逻辑</strong>：腾讯的估值比茅台复杂得多，因为它包含多个业务板块。专业做法是"分部估值"——游戏按 15~20 倍 PE、广告按 25~30 倍、云按市销率、投资资产按账面价值。把各个板块估值加总再打个折扣得到合理市值。</p>
<p><strong>核心风险</strong>：<em>政策风险 &gt; 经营风险</em>。2021 年游戏版号收紧、互联网平台反垄断，让腾讯股价腰斩。这种风险不是基本面能预测的，更多要看政策环境。买腾讯等互联网龙头，本质上是<em>"在政策周期中做波段"</em>。</p>

<h3>苹果：消费电子 + 服务混合体的分析框架</h3>
<p><strong>核心问题</strong>：iPhone 的替换周期有没有被拉长？服务业务的增长能不能抵消硬件的疲软？</p>
<p>苹果有一个独特的商业结构：硬件是"流量入口"（iPhone 销量决定了有多少活跃设备），服务是"变现出口"（App Store、iCloud、Apple Music、广告）。两者互相支撑。</p>
<p><strong>关键监控指标</strong>：</p>
<ul style="list-style:none;display:grid;gap:10px;margin:12px 0">
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong>iPhone 出货量 + 平均售价（ASP）</strong>：出货量反映用户活跃基础，ASP 反映定价权。两个指标都向上是理想状态。</li>
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong>服务收入占比</strong>：从 2017 年的 13% 涨到现在 25% 左右。服务毛利率 70%+，远高于硬件的 35%。服务占比越高，整体利润率越高。</li>
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong>活跃设备数</strong>：苹果披露的"10 亿 iPhone 活跃用户"是未来服务收入的基础。</li>
<li style="padding:12px 14px;background:rgba(255,255,255,.03);border-radius:10px;font-size:14px"><strong>回购和分红</strong>：苹果每年花数百亿美元回购股票，这是它股价长期走牛的最重要支撑之一。</li>
</ul>
<p><strong>估值逻辑</strong>：苹果的 PE 从 2016 年的 15 倍左右，被市场重新定价到 25~35 倍。为什么？因为市场开始把它当作"服务 + 消费品"而不是纯硬件公司。服务业务的高毛利和高粘性让它享受更高估值。</p>
<p><strong>核心风险</strong>：<em>中国市场、AI 创新节奏、替换周期</em>。苹果最大的单一市场风险是中国——大中华区贡献 20% 收入。另一个风险是 AI 时代是否被 Android/Google 弯道超车。</p>

<h3>三家公司的对比总结</h3>
<table style="width:100%;border-collapse:collapse;margin:14px 0;font-size:13px">
<thead><tr style="background:rgba(111,215,255,.08);color:#6fd7ff"><th style="padding:10px;text-align:left">维度</th><th style="padding:10px;text-align:left">茅台</th><th style="padding:10px;text-align:left">腾讯</th><th style="padding:10px;text-align:left">苹果</th></tr></thead>
<tbody>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">核心护城河</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">品牌 + 产能</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">网络效应</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">生态闭环</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">增长来源</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">提价 + 产能释放</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">用户变现效率</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">服务业务 + 新品类</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">关键监控</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">批价、预收款</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">游戏流水、视频号</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">iPhone 销量、服务占比</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">估值区间</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">PE 25~45 倍</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">分部估值</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">PE 25~35 倍</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">核心风险</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">需求结构变化</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">政策风险</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">中国市场 + 创新节奏</td></tr>
<tr><td style="padding:10px">研究重点</td><td style="padding:10px">跟踪渠道和提价</td><td style="padding:10px">跟踪监管和新业务</td><td style="padding:10px">跟踪产品周期和服务</td></tr>
</tbody>
</table>

<h3>可复用的研究模板</h3>
<p>当你研究任何一家公司时，先判断它属于哪一类：</p>
<div style="background:rgba(89,240,194,.08);border-left:3px solid #59f0c2;padding:18px 20px;border-radius:10px;margin:18px 0">
<strong>消费品类（茅台、海天、伊利、海底捞）</strong>：关注品牌、渠道、提价能力、单店模型。估值看 PE 历史分位。<br><br>
<strong>平台互联网类（腾讯、阿里、美团、字节）</strong>：关注用户、活跃度、单用户价值、变现效率、政策环境。估值用分部估值或 PS。<br><br>
<strong>消费电子类（苹果、小米、立讯精密）</strong>：关注产品周期、供应链地位、服务占比、创新能力。估值看 PE + 产品周期。<br><br>
<strong>周期类（煤炭、钢铁、有色、航运）</strong>：关注价格周期、库存、产能利用率。估值用 PB，不用 PE。<br><br>
<strong>金融类（银行、券商、保险）</strong>：关注净息差、不良率、ROE。估值看 PB + ROE。<br><br>
<strong>科技硬件类（半导体、面板、新能源）</strong>：关注产能、技术迭代、客户结构。估值看 PE + 增速，波动大。
</div>

<p>每一类都有自己的"看法"，用错了框架会得出完全相反的结论。研究是一门"先分类、再深挖"的功夫，不是机械地套用模板。</p>
`
},
{
id: 'advanced-asset-alloc',
category: 'advanced',
title: '从 ETF 到个股：什么时候该做资产配置，什么时候才该做主动判断',
summary: '很多同学在还没有资产配置框架时就直接下场选股。真正稳的顺序应该是先配置、再择时、后择股。',
date: '2026-03-29',
views: '2,558',
readTime: '13 分钟',
level: '进阶',
content: `
<p>很多大学生进入股市的顺序是反的：一上来就研究"今天买哪只股票"，完全跳过了"我的整体组合应该长什么样"这个问题。结果是——即使偶尔选对了股票，账户整体表现依然像过山车。</p>
<p>专业投资者的顺序永远是：<strong>先决定资产配置 → 再决定择时 → 最后才考虑个股选择</strong>。这三个层次的重要性是<em>80%、15%、5%</em>——而不是大多数人以为的反过来。</p>

<h3>为什么资产配置占 80%</h3>
<p>这不是我拍脑袋说的，是学术研究的结论。1986 年 Brinson、Hood、Beebower 的经典论文发现：一个投资组合的长期表现，93% 的差异来自资产配置决策，而不是择时或选股。</p>
<p>换句话说：<strong>你是股票 80% + 债券 20%，还是股票 40% + 债券 60%，这个决定对你 10 年后的账户表现的影响，远远大于你具体选了哪些股票</strong>。</p>
<p>这个结论对新手的意义是：不要本末倒置。先想清楚"我应该拿多少钱在股市里、多少钱在债市里、多少钱在现金里"，这比"今天买茅台还是五粮液"重要 10 倍。</p>

<h3>第一步：决定你的风险承受能力</h3>
<p>资产配置的起点是你能承受多大的波动。用一个简单的问题来测试：</p>
<div style="background:rgba(111,215,255,.08);border-left:3px solid #6fd7ff;padding:16px 18px;border-radius:10px;margin:18px 0">
<strong>假设你有 10 万元投资，明天早上打开账户发现变成了 7 万。你的反应是：</strong><br>
A. "完了完了，我要赶紧清仓止损"—— 风险承受能力低<br>
B. "有点慌，但我先观察几天再决定"—— 中等<br>
C. "市场波动正常，我看看要不要加仓"—— 高<br>
D. "无所谓，这钱 10 年内不动，爱跌就跌"—— 非常高
</div>
<p>对应的资产配置建议：</p>
<table style="width:100%;border-collapse:collapse;margin:14px 0;font-size:13px">
<thead><tr style="background:rgba(111,215,255,.08);color:#6fd7ff"><th style="padding:10px;text-align:left">类型</th><th style="padding:10px;text-align:left">股票</th><th style="padding:10px;text-align:left">债券</th><th style="padding:10px;text-align:left">现金</th></tr></thead>
<tbody>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">A 保守型</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">20%~30%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">50%~60%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">20%</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">B 稳健型</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">40%~50%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">35%~45%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">10%~15%</td></tr>
<tr><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">C 成长型</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">60%~70%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">20%~30%</td><td style="padding:10px;border-bottom:1px solid rgba(255,255,255,.08)">10%</td></tr>
<tr><td style="padding:10px">D 激进型</td><td style="padding:10px">80%~90%</td><td style="padding:10px">10%~15%</td><td style="padding:10px">5%</td></tr>
</tbody>
</table>
<p>大学生多数属于 C~D 类型：年轻、时间长、没有家庭负担、即使亏了也有时间弥补。所以股票仓位 60%+ 是合理的。但如果你学费都没着落，那就应该退到 A 类型。</p>

<h3>第二步：在"股票篮子"里做地域和风格分散</h3>
<p>确定股票总仓位后，进一步把股票分散到不同的"子篮子"里。这里的分散维度有三个：</p>
<p><strong>1. 地域分散</strong>：A 股 / 港股 / 美股。不同市场的相关性并不高，一个市场大跌时另一个市场可能稳定甚至上涨。</p>
<p><strong>2. 行业分散</strong>：科技 / 消费 / 金融 / 医药 / 能源 / 公用事业。同一行业内的股票相关性极高，跨行业才是真正的分散。</p>
<p><strong>3. 风格分散</strong>：大盘股 / 中小盘股、价值股 / 成长股。不同风格在不同阶段占优。</p>
<p>对大学生来说，简化版的股票配置可以是：</p>
<div style="background:rgba(89,240,194,.08);border-left:3px solid #59f0c2;padding:16px 18px;border-radius:10px;margin:18px 0">
<strong>股票部分（假设总仓位 60%，这 60% 内部的分配）：</strong><br>
- A 股宽基 ETF（沪深 300 或中证 500）：40%<br>
- A 股行业 ETF（消费、医药、红利）：20%<br>
- 港股宽基 ETF（恒生科技或恒生指数）：15%<br>
- 美股宽基 ETF（标普 500 或纳斯达克 100）：15%<br>
- 个股（研究比较熟悉的 2~3 只）：10%
</div>
<p>注意：个股只占股票仓位的 10%，而不是相反。这是大多数新手最容易颠倒的地方。</p>

<h3>第三步：择时——只在极端时刻才做</h3>
<p>择时是非常危险的事情。学术研究显示：大部分试图择时的主动管理基金反而跑输不择时的被动组合。但"完全不择时"也不对——在估值极端时做一些调整，长期看能显著提升收益。</p>
<p><strong>什么叫"极端"</strong>？用估值分位来判断：</p>
<ul style="list-style:none;display:grid;gap:10px;margin:12px 0">
<li style="padding:12px 14px;background:rgba(89,240,194,.06);border-radius:10px;font-size:14px;border-left:3px solid #59f0c2"><strong>极度低估区（PE/PB 历史 20% 分位以下）</strong>：逐步加仓，把股票仓位从 60% 推到 75%~80%。</li>
<li style="padding:12px 14px;background:rgba(255,211,124,.06);border-radius:10px;font-size:14px;border-left:3px solid #ffd37c"><strong>正常区间（20%~80% 分位）</strong>：维持基准配置，不做主动调整，做好定投和再平衡就够了。</li>
<li style="padding:12px 14px;background:rgba(255,142,142,.06);border-radius:10px;font-size:14px;border-left:3px solid #ff8e8e"><strong>极度高估区（PE/PB 80% 分位以上）</strong>：逐步减仓，把股票仓位从 60% 降到 40%~45%。</li>
</ul>
<p>这种操作不是"择时"意义上的短线买卖，而是"仓位调节"——基于估值的纪律性再平衡。它不需要你预测市场，只需要你机械地执行规则。</p>

<h3>第四步：个股——最后才考虑</h3>
<p>当你完成了前三步，账户里已经有稳定的资产配置、地域行业分散、估值驱动的仓位调节。这时候你才可以拿出<strong>10%~20% 的资金</strong>来做主动选股。</p>
<p>为什么只能这么少？因为个股选择的成功率是最低的。即使你研究得再深，你依然无法预测监管政策、黑天鹅事件、行业突变。把大部分资金交给"指数 + 纪律"，把一小部分交给"你的判断"，这是最稳的配比。</p>

<h3>再平衡：这是资产配置的发动机</h3>
<p>定期再平衡是资产配置策略真正"能赚钱"的秘密。规则很简单：</p>
<p>如果你的目标是股票 60% + 债券 40%，但半年后股票因为大涨变成了 70% + 30%，那你应该卖掉 10% 的股票，买入 10% 的债券，回到目标比例。</p>
<p>听起来很反直觉——"我正在赚钱，为什么要卖掉赚钱的那部分"？但这正是再平衡的价值：<strong>强制你高位卖出、低位买入</strong>。这比你自己"看心情操作"要理性得多。</p>
<p>再平衡的频率建议是：每半年一次，或者偏离目标超过 5 个百分点就做一次。不要每天都看，否则你会忍不住过度操作。</p>

<h3>对大学生的一个务实建议</h3>
<div style="background:rgba(111,215,255,.08);border-left:3px solid #6fd7ff;padding:18px 20px;border-radius:10px;margin:18px 0">
如果你的本金不到 1 万元，不要急着做复杂的资产配置。就做一件事：<strong>每月定投一只宽基 ETF</strong>。把你所有的精力用在学习上（读财报、研究公司、理解市场），而不是用在"调仓"上。<br><br>
等你本金到 1 万~3 万元，开始做简化版配置：70% 股票 ETF + 30% 债券基金。每半年再平衡一次。<br><br>
本金到 5 万元以上，可以开始做地域分散和行业分散，并且拿出 10% 左右做个股练手。<br><br>
这个节奏听起来慢，但它是你账户真正能长大的方式。
</div>

<h3>最后的心态提醒</h3>
<p>资产配置是一个"无聊但有效"的策略。它不会让你成为"某只股票涨了 5 倍"的故事主角，但它会让你 10 年后回头看账户时——数字大到你自己都意外。这种无聊的复利，才是真正让人自由的东西。</p>
`
},
{
id: 'advanced-review',
category: 'advanced',
title: '如何做一份属于自己的投资复盘：记录什么、复盘什么、淘汰什么',
summary: '把每一笔模拟交易都沉淀成可复用经验，最终形成自己的规则库，而不是永远在"下一次注意"里循环。',
date: '2026-03-26',
views: '2,201',
readTime: '11 分钟',
level: '进阶',
content: `
<p>99% 的新手不做复盘。剩下 1% 里，大部分做的复盘也是无效的——无非是看看哪几笔赚了哪几笔亏了，感叹几句"下次注意"，然后继续犯同样的错误。</p>
<p>有效的复盘是一个系统性过程。它不是"反思"，而是"把经验结构化"——把每一笔交易变成可积累、可检验、可淘汰的数据点。这篇文章告诉你具体怎么做。</p>

<h3>为什么不复盘的人永远在原地</h3>
<p>交易是一个"决策质量很难被即时反馈"的活动。你做了一笔好决策可能亏钱（运气差），做了一笔坏决策可能赚钱（运气好）。如果只看结果、不看过程，你会把运气当作能力，把愚蠢当作"意外"。</p>
<p>复盘的意义就是把"决策质量"和"结果"分开评价。一个有效的复盘系统，能让你在一年后清楚地回答：</p>
<ul style="list-style:none;display:grid;gap:8px;margin:10px 0">
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>我哪几类决策是真正能赚钱的？</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>我哪几类决策长期亏损，应该淘汰掉？</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>我有没有在重复同一个错误？</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#59f0c2">▸</span>我的"好运气"部分占多少？</li>
</ul>

<h3>复盘第一步：建立交易日志</h3>
<p>每一笔交易都要记录。不是盈利的才记，不是重要的才记——<strong>每一笔都要</strong>。用一个 Excel 或 Notion 表格，至少包含这些字段：</p>
<div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:16px 18px;margin:14px 0;font-size:13px">
<strong style="color:#6fd7ff">买入记录</strong>：日期 / 股票代码 / 股票名称 / 买入价 / 仓位（占总资金百分比）/ 买入理由（1~3 句话）/ 预期持有时间 / 止损位 / 目标价<br><br>
<strong style="color:#6fd7ff">卖出记录</strong>：日期 / 卖出价 / 持有天数 / 盈亏金额 / 盈亏比例 / 卖出原因（止损 / 止盈 / 逻辑变化 / 其他）<br><br>
<strong style="color:#6fd7ff">分类标签</strong>：策略类型（价值 / 趋势 / 事件 / 波段）/ 行业 / 市场（A/H/U）<br><br>
<strong style="color:#6fd7ff">复盘笔记</strong>：这笔交易我做对了什么 / 做错了什么 / 下次应该怎么调整
</div>
<p>"买入理由"和"预期"这两个字段是最关键的。它们让你的未来自己可以检验<strong>当初的想法到底对不对</strong>，而不是事后编造一个解释。</p>

<h3>复盘第二步：每周回顾本周交易</h3>
<p>每周末花 30 分钟，打开你的交易日志，做三件事：</p>
<p><strong>1. 数字统计</strong>：本周交易笔数、胜率（盈利笔数 / 总笔数）、盈亏比（平均盈利 / 平均亏损）、总盈亏。</p>
<p><strong>2. 按分类汇总</strong>：<em>价值策略这周表现如何？趋势策略这周表现如何？</em>不同策略要分开评价，不要混在一起。</p>
<p><strong>3. 挑出本周最"离谱"的那笔</strong>：可能是盈亏最大的，也可能是最让你后悔的。单独写一段复盘笔记。</p>
<p>这个动作听起来很简单，但大部分人做不到——因为他们只想看盈利的那笔（感觉良好），不想看亏损的那笔（情绪抵抗）。</p>

<h3>复盘第三步：每月对策略做评价</h3>
<p>每月末做一次更深入的分析。重点是<em>评价策略，而不是评价单笔交易</em>：</p>
<div style="background:rgba(89,240,194,.08);border-left:3px solid #59f0c2;padding:18px 20px;border-radius:10px;margin:18px 0">
<strong>每月复盘模板：</strong><br><br>
<strong>策略 A（价值投资）</strong>：本月共 X 笔，胜率 Y%，平均持有 Z 天，总盈亏 +/- N%。<br>
→ 本月这个策略表现比上月好还是差？<br>
→ 失败的那几笔有什么共同特征？<br>
→ 需要调整买入条件吗？<br><br>
<strong>策略 B（趋势跟随）</strong>：同上结构。<br><br>
<strong>整体账户</strong>：总回撤多少？最大单日亏损？现金比例是否合理？
</div>
<p>做这个动作的最大价值是：你会发现自己有些"自以为擅长"的策略其实长期亏钱，而一些"不起眼"的策略反而稳定盈利。真相会让你很难受，但这是进步的起点。</p>

<h3>复盘第四步：每季度淘汰失效的做法</h3>
<p>季度复盘是真正让你"变强"的动作。规则很简单：<em>任何连续 3 个月都亏损的策略或做法，直接淘汰</em>。</p>
<p>很多人在这一步卡住——他们会找各种理由为失败的策略辩护："这个策略只是暂时不好""下次我会执行得更严格""再给它一次机会"。但数据不会说谎：如果一个做法 3 个月都不赚钱，它多半是有根本性问题的。</p>
<p><strong>什么样的做法应该被淘汰</strong>：</p>
<ul style="list-style:none;display:grid;gap:8px;margin:10px 0">
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span>总胜率低于 30%（大部分策略至少要 40%+ 才算合格）</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span>盈亏比小于 1（亏的时候比赚的时候狠）</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span>某个特定行业/类型的股票你总是亏（可能不符合你的能力圈）</li>
<li style="padding-left:16px;position:relative;font-size:14px"><span style="position:absolute;left:0;color:#ff8e8e">▸</span>某个时段你总是冲动交易（可能需要回避这个时段）</li>
</ul>

<h3>复盘第五步：年度形成"个人交易宪法"</h3>
<p>一年的系统复盘之后，你会沉淀出一份"属于自己的交易规则"——这不是抄来的，是你用真金白银换来的。它可能是这样的：</p>
<div style="background:rgba(111,215,255,.08);border-left:3px solid #6fd7ff;padding:18px 20px;border-radius:10px;margin:18px 0">
<strong>我的交易宪法（样例）</strong><br><br>
1. 只在我熟悉的 3 个行业里选股（消费、科技、医药）。<br>
2. 每笔单只仓位不超过总资金 15%。<br>
3. 止损线 -8%，无条件执行。<br>
4. 严禁亏损加仓——只做金字塔加仓。<br>
5. 不参与任何"消息驱动"的短线炒作，我的胜率在这里长期为负。<br>
6. 重大财报发布前夕不加仓，有不确定性。<br>
7. 每月复盘一次，每季度淘汰一次。<br>
8. 账户最大回撤超过 20% 时无条件停手一周。
</div>
<p>这份"宪法"会随着你的经验不断迭代。它不是一成不变的教条，而是你对自己的了解越来越深之后的规则化表达。</p>

<h3>最容易失败的几个复盘坑</h3>
<p><strong>1. 只记账不复盘</strong>：记录了交易但从不回顾，等于没记。</p>
<p><strong>2. 复盘只看情绪不看数据</strong>：凭感觉说"我这周手感不错"，而不是看具体数字。</p>
<p><strong>3. 每次都说"下次注意"</strong>：没有具体改进动作的"注意"毫无意义。</p>
<p><strong>4. 把运气当能力</strong>：一两次盈利就觉得自己掌握了某个策略。需要至少 20~30 笔样本才能判断策略有效性。</p>
<p><strong>5. 把能力当运气</strong>：连续几次亏损就否定自己过去所有的判断。可能只是这个阶段不适合你的风格，不是策略错了。</p>

<h3>一个长期主义者的复盘</h3>
<p>真正有效的复盘是"长期的、被动的、机械的"，而不是"临时的、情绪的、偶发的"。它不让你立刻变强，但它让你每个月都比上个月清楚一点点。一年之后你会发现，你不再问"这只股票能涨吗"这种没意义的问题——你会问"这笔交易符合我的规则吗"。</p>
<p>这就是从"散户"到"有系统的个人投资者"的分水岭。</p>
`
}
];

// 便捷函数：根据 id 查找文章
window.getCampusQuantArticle = function(id){
return (window.CAMPUSQUANT_ARTICLES || []).find(a => a.id === id);
};

// 分类元数据
window.CAMPUSQUANT_CATEGORIES = {
basic: {label:'财商基础', className:'pill-basic', color:'#6fd7ff'},
analysis: {label:'分析方法', className:'pill-analysis', color:'#59f0c2'},
risk: {label:'风险控制', className:'pill-risk', color:'#ffd37c'},
advanced: {label:'案例进阶', className:'pill-advanced', color:'#d3bbff'}
};
