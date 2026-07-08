const EASTMONEY_UT = "7eea3edcaed734bea9cbfc24409ed989";
const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

const themeRules = [
  ["机器人", ["机器人", "减速器", "伺服", "工业母机", "智能制造"]],
  ["PCB", ["PCB", "印制电路", "线路板", "覆铜板", "电子元件", "元件"]],
  ["算力", ["算力", "服务器", "数据中心", "液冷", "光模块", "CPO"]],
  ["创新药", ["创新药", "医药", "生物制品", "化学制药", "医疗"]],
  ["军工", ["军工", "航天", "航空", "卫星", "国防"]],
  ["半导体", ["半导体", "芯片", "集成电路", "封测"]],
  ["AI硬件", ["AI", "人工智能", "消费电子", "计算机设", "光学光电"]],
  ["消费电子", ["消费电子", "电子", "光学光电"]],
  ["有色金属", ["有色", "稀土", "金属", "冶钢", "矿业"]],
  ["固态电池", ["固态电池", "电池", "锂电", "新能源"]],
  ["商业航天", ["商业航天", "卫星", "航天"]],
];

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      ...corsHeaders,
      "content-type": "application/json; charset=utf-8",
      "cache-control": "public, max-age=45",
    },
  });
}

function value(input, fallback = 0) {
  return Number.isFinite(Number(input)) ? Number(input) : fallback;
}

function text(input) {
  return input === null || input === undefined ? "" : String(input).trim();
}

function normalizeDate(date) {
  const raw = text(date).replace(/\D/g, "");
  if (raw.length === 8) return raw;
  return new Date().toLocaleDateString("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).replaceAll("/", "");
}

function formatDate(raw) {
  return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
}

function normalizeTime(input) {
  const raw = text(input).replace(/\D/g, "").padStart(6, "0");
  if (!raw || raw === "000000") return "";
  return `${raw.slice(0, 2)}:${raw.slice(2, 4)}:${raw.slice(4, 6)}`;
}

function inferMarketBoard(code) {
  const raw = text(code);
  if (raw.startsWith("300") || raw.startsWith("301")) return "创业板";
  if (raw.startsWith("688")) return "科创板";
  if (raw.startsWith("8") || raw.startsWith("4") || raw.startsWith("920")) return "北交所";
  return "主板";
}

function inferTheme(row) {
  const haystack = [row.name, row.industry, row.concept, row.reason].join(" ").toLowerCase();
  const match = themeRules.find(([, words]) => words.some((word) => haystack.includes(word.toLowerCase())));
  return match ? match[0] : "其他";
}

function limitStats(input) {
  if (!input || typeof input !== "object") return { limit_days_in_window: 0, limit_days_window: 0, limit_stats: "" };
  const days = value(input.days, 0);
  const count = value(input.ct, 0);
  return {
    limit_days_in_window: days,
    limit_days_window: count,
    limit_stats: days && count ? `${days}/${count}` : "",
  };
}

async function fetchPool(endpoint, date, sort, pageSize = 10000) {
  const url = new URL(`https://push2ex.eastmoney.com/${endpoint}`);
  url.searchParams.set("ut", EASTMONEY_UT);
  url.searchParams.set("dpt", "wz.ztzt");
  url.searchParams.set("Pageindex", "0");
  url.searchParams.set("pagesize", String(pageSize));
  url.searchParams.set("sort", sort);
  url.searchParams.set("date", date);
  const response = await fetch(url.toString(), {
    headers: {
      "user-agent": "Mozilla/5.0",
      "referer": "https://quote.eastmoney.com/ztb/detail",
    },
    cf: { cacheTtl: 45, cacheEverything: true },
  });
  if (!response.ok) throw new Error(`Eastmoney ${endpoint} ${response.status}`);
  const payload = await response.json();
  return payload?.data?.pool || [];
}

function normalizeLimitUp(item) {
  const stats = limitStats(item.days);
  const row = {
    code: text(item.c).padStart(6, "0"),
    name: text(item.n),
    change_pct: value(item.zdp),
    latest_price: value(item.p) / 1000,
    turnover_amount: value(item.amount),
    float_market_cap: value(item.ltsz),
    total_market_cap: value(item.tshare),
    turnover_rate: value(item.hs),
    first_limit_time: normalizeTime(item.fbt),
    last_limit_time: normalizeTime(item.lbt),
    industry: text(item.hybk),
    seal_amount: value(item.fund),
    consecutive_days: Math.max(1, value(item.lbc, 1)),
    open_times: value(item.zbc),
    reason: "",
    concept: "",
    ...stats,
  };
  row.market_board = inferMarketBoard(row.code);
  row.theme = inferTheme(row);
  return row;
}

function normalizeBroken(item) {
  const stats = limitStats(item.days);
  const row = {
    code: text(item.c).padStart(6, "0"),
    name: text(item.n),
    change_pct: value(item.zdp),
    latest_price: value(item.p) / 1000,
    limit_price: value(item.ztp) / 1000,
    turnover_amount: value(item.amount),
    float_market_cap: value(item.ltsz),
    total_market_cap: value(item.tshare),
    turnover_rate: value(item.hs),
    first_limit_time: normalizeTime(item.fbt),
    last_limit_time: "",
    open_times: value(item.zbc),
    amplitude: value(item.zf),
    speed: value(item.zs),
    industry: text(item.hybk),
    seal_amount: 0,
    consecutive_days: 1,
    reason: "",
    concept: "",
    ...stats,
  };
  row.market_board = inferMarketBoard(row.code);
  row.theme = inferTheme(row);
  return row;
}

function normalizeDown(item) {
  const row = {
    code: text(item.c).padStart(6, "0"),
    name: text(item.n),
    change_pct: value(item.zdp),
    latest_price: value(item.p) / 1000,
    turnover_amount: value(item.amount),
    float_market_cap: value(item.ltsz),
    total_market_cap: value(item.tshare),
    turnover_rate: value(item.hs),
    first_limit_time: "",
    last_limit_time: normalizeTime(item.lbt),
    seal_amount: value(item.fund),
    open_times: value(item.oc),
    consecutive_days: Math.max(1, value(item.days, 1)),
    industry: text(item.hybk),
    concept: "",
    reason: "",
    limit_stats: "",
  };
  row.market_board = inferMarketBoard(row.code);
  row.theme = inferTheme(row);
  return row;
}

function rankByField(rows, field) {
  const counts = new Map();
  rows.forEach((row) => {
    const key = row[field] || "其他";
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 12);
}

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") return new Response(null, { headers: corsHeaders });
    const url = new URL(request.url);
    if (url.pathname !== "/api/realtime") return jsonResponse({ error: "not found" }, 404);

    try {
      const date = normalizeDate(url.searchParams.get("date"));
      const [limitUpsRaw, brokenRaw, downsRaw] = await Promise.all([
        fetchPool("getTopicZTPool", date, "fbt:asc", 10000),
        fetchPool("getTopicZBPool", date, "fbt:asc", 5000),
        fetchPool("getTopicDTPool", date, "fund:asc", 10000),
      ]);
      const limitUps = limitUpsRaw.map(normalizeLimitUp).filter((row) => row.code && row.name);
      const broken = brokenRaw.map(normalizeBroken).filter((row) => row.code && row.name);
      const downs = downsRaw.map(normalizeDown).filter((row) => row.code && row.name);
      const highestBoard = Math.max(0, ...limitUps.map((row) => value(row.consecutive_days, 1)));
      const totalForBrokenRate = limitUps.length + broken.length;
      return jsonResponse({
        meta: {
          site_name: "峰股top",
          trade_date: formatDate(date),
          updated_at: new Date().toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }),
          market_data_ready_time: "15:30",
          source: "eastmoney-worker",
          mode: "intraday",
          data_status: limitUps.length ? "ok" : "empty_or_failed",
          notes: ["盘中实时数据来自东方财富专题接口，经 Cloudflare Worker 缓存约 45 秒。"],
          available_dates: [formatDate(date)],
        },
        sentiment: {
          limit_up_count: limitUps.length,
          limit_down_count: downs.length,
          broken_limit_count: broken.length,
          highest_board: highestBoard,
          first_board_count: limitUps.filter((row) => value(row.consecutive_days, 1) === 1).length,
          multi_board_count: limitUps.filter((row) => value(row.consecutive_days, 1) >= 2).length,
          limit_up_turnover_amount: limitUps.reduce((sum, row) => sum + value(row.turnover_amount), 0),
          limit_up_seal_amount: limitUps.reduce((sum, row) => sum + value(row.seal_amount), 0),
          broken_rate: totalForBrokenRate ? Math.round((broken.length / totalForBrokenRate) * 10000) / 100 : 0,
          promoted_count: 0,
          promotion_rate: 0,
          promoted_stocks: [],
        },
        rankings: {
          industry_limit_rank: rankByField(limitUps, "industry"),
          theme_limit_rank: rankByField(limitUps, "theme"),
          market_board_limit_rank: rankByField(limitUps, "market_board"),
        },
        limit_ups: limitUps,
        broken_limits: broken,
        limit_downs: downs,
        strong_stocks: [],
        sub_new_stocks: [],
        stats: [],
      });
    } catch (error) {
      return jsonResponse({ error: "realtime unavailable", message: String(error?.message || error) }, 503);
    }
  },
};
