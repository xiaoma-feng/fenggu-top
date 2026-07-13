const POOL_BASE_URL = "https://push2ex.eastmoney.com";
const TENCENT_TREND_BASE_URLS = [
  "https://web.ifzq.gtimg.cn/appstock/app/minute/query",
  "https://ifzq.gtimg.cn/appstock/app/minute/query",
];
const EASTMONEY_TREND_BASE_URLS = [
  "https://push2.eastmoney.com/api/qt/stock/trends2/get",
  "https://push2his.eastmoney.com/api/qt/stock/trends2/get",
];
const EASTMONEY_TOKEN = "7eea3edcaed734bea9cbfc24409ed989";
const EASTMONEY_TREND_TOKEN = "fa5fd1943c7b386f172d6893dbfba10b";

function numberValue(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formatPoolTime(value) {
  const digits = String(value ?? "").replace(/\D/g, "").padStart(6, "0");
  if (!digits || digits === "000000") return "";
  return `${digits.slice(0, 2)}:${digits.slice(2, 4)}:${digits.slice(4, 6)}`;
}

function inferMarketBoard(code) {
  const value = String(code || "");
  if (value.startsWith("300") || value.startsWith("301")) return "创业板";
  if (value.startsWith("688")) return "科创板";
  if (value.startsWith("8") || value.startsWith("4") || value.startsWith("920")) return "北交所";
  return "主板";
}

function limitStats(row) {
  const days = Math.max(0, numberValue(row?.zttj?.days));
  const count = Math.max(0, numberValue(row?.zttj?.ct));
  return {
    limit_days_in_window: days,
    limit_days_window: count,
    limit_stats: `${days}/${count}`,
  };
}

function commonStock(row) {
  const code = String(row.c || "").padStart(6, "0");
  return {
    code,
    name: String(row.n || ""),
    change_pct: numberValue(row.zdp),
    latest_price: numberValue(row.p) / 1000,
    turnover_amount: numberValue(row.amount),
    float_market_cap: numberValue(row.ltsz),
    total_market_cap: numberValue(row.tshare),
    turnover_rate: numberValue(row.hs),
    industry: String(row.hybk || ""),
    market_board: inferMarketBoard(code),
    themes: [],
    theme: "",
    concept: "",
  };
}

function normalizeLimitUp(row) {
  return {
    ...commonStock(row),
    first_limit_time: formatPoolTime(row.fbt),
    last_limit_time: formatPoolTime(row.lbt),
    seal_amount: numberValue(row.fund),
    consecutive_days: Math.max(1, numberValue(row.lbc, 1)),
    open_times: Math.max(0, numberValue(row.zbc)),
    ...limitStats(row),
  };
}

function normalizeBroken(row) {
  return {
    ...commonStock(row),
    limit_price: numberValue(row.ztp) / 1000,
    first_limit_time: formatPoolTime(row.fbt),
    last_limit_time: "",
    seal_amount: 0,
    consecutive_days: 1,
    open_times: Math.max(0, numberValue(row.zbc)),
    speed: numberValue(row.zs),
    amplitude: numberValue(row.zf),
    ...limitStats(row),
  };
}

function normalizeLimitDown(row) {
  return {
    ...commonStock(row),
    first_limit_time: "",
    last_limit_time: formatPoolTime(row.lbt),
    seal_amount: numberValue(row.fund),
    board_turnover_amount: numberValue(row.fba),
    consecutive_days: Math.max(1, numberValue(row.days, 1)),
    open_times: Math.max(0, numberValue(row.oc)),
    pe_dynamic: numberValue(row.pe),
    limit_days_in_window: 0,
    limit_days_window: 0,
    limit_stats: "0/0",
  };
}

async function fetchJsonWithRetry(url, attempts = 2) {
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(url, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      lastError = error;
      if (attempt + 1 < attempts) await new Promise((resolve) => window.setTimeout(resolve, 450));
    } finally {
      window.clearTimeout(timeout);
    }
  }
  throw lastError || new Error("行情接口请求失败");
}

function fetchJsonp(url, params, timeoutMs = 12000) {
  return new Promise((resolve, reject) => {
    const callbackName = `__fengguTrend_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    const script = document.createElement("script");
    let settled = false;
    let timeout;

    function cleanup() {
      window.clearTimeout(timeout);
      script.remove();
      try {
        delete window[callbackName];
      } catch {
        window[callbackName] = undefined;
      }
    }

    function finish(error, payload) {
      if (settled) return;
      settled = true;
      cleanup();
      if (error) reject(error);
      else resolve(payload);
    }

    window[callbackName] = (payload) => finish(null, payload);
    script.async = true;
    script.onerror = () => finish(new Error("分时行情脚本加载失败"));
    script.src = `${url}?${new URLSearchParams({ ...params, cb: callbackName })}`;
    timeout = window.setTimeout(() => finish(new Error("分时行情请求超时")), timeoutMs);
    document.head.appendChild(script);
  });
}

async function fetchPool(path, date, sort, pageSize, normalizer) {
  const params = new URLSearchParams({
    ut: EASTMONEY_TOKEN,
    dpt: "wz.ztzt",
    Pageindex: "0",
    pagesize: String(pageSize),
    sort,
    date,
  });
  const payload = await fetchJsonWithRetry(`${POOL_BASE_URL}/${path}?${params}`);
  const rows = payload?.data?.pool;
  return Array.isArray(rows) ? rows.map(normalizer).filter((stock) => stock.code && stock.name) : [];
}

export async function fetchRealtimePools(dateText) {
  const date = String(dateText || "").replaceAll("-", "");
  const [limitUps, brokenRows, limitDowns] = await Promise.all([
    fetchPool("getTopicZTPool", date, "fbt:asc", 10000, normalizeLimitUp),
    fetchPool("getTopicZBPool", date, "fbt:asc", 5000, normalizeBroken),
    fetchPool("getTopicDTPool", date, "fund:asc", 10000, normalizeLimitDown),
  ]);
  const limitUpCodes = new Set(limitUps.map((stock) => stock.code));
  const brokenLimits = brokenRows.filter((stock) => !limitUpCodes.has(stock.code));
  const highestBoard = Math.max(0, ...limitUps.map((stock) => stock.consecutive_days));
  const totalForRate = limitUps.length + brokenLimits.length;
  return {
    meta: {
      trade_date: String(dateText),
      updated_at: new Date().toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }),
      source: "东方财富涨停板行情",
      data_status: "intraday",
      notes: ["盘中数据由东方财富涨停池、炸板池、跌停池实时同步，每 60 秒刷新。"],
    },
    sentiment: {
      limit_up_count: limitUps.length,
      broken_limit_count: brokenLimits.length,
      limit_down_count: limitDowns.length,
      highest_board: highestBoard,
      first_board_count: limitUps.filter((stock) => stock.consecutive_days === 1).length,
      multi_board_count: limitUps.filter((stock) => stock.consecutive_days >= 2).length,
      broken_rate: totalForRate ? Number(((brokenLimits.length / totalForRate) * 100).toFixed(2)) : 0,
    },
    limit_ups: limitUps,
    broken_limits: brokenLimits,
    limit_downs: limitDowns,
  };
}

function marketId(code) {
  return String(code || "").startsWith("6") ? 1 : 0;
}

function tencentSymbol(code) {
  const value = String(code || "").padStart(6, "0");
  if (value.startsWith("6")) return `sh${value}`;
  if (value.startsWith("8") || value.startsWith("4") || value.startsWith("920")) return `bj${value}`;
  return `sz${value}`;
}

function parseTencentPoints(rows) {
  let previousVolume = 0;
  let calculatedAmount = 0;
  return (rows || []).map((row) => {
    const fields = String(row || "").trim().split(/\s+/);
    const rawTime = fields[0] || "";
    const price = numberValue(fields[1]);
    const volume = Math.max(0, numberValue(fields[2]));
    const amount = Math.max(0, numberValue(fields[3]));
    const incrementalVolume = Math.max(0, volume - previousVolume);
    previousVolume = volume;
    calculatedAmount += incrementalVolume * price;
    const average = amount > 0 && volume > 0
      ? amount / volume / 100
      : (volume > 0 ? calculatedAmount / volume : price);
    return {
      time: rawTime.length === 4 ? `${rawTime.slice(0, 2)}:${rawTime.slice(2)}` : rawTime,
      price,
      average: average > 0 ? average : price,
      volume,
    };
  }).filter((point) => point.time && point.price > 0);
}

function parseTencentTrend(payload, symbol, normalizedCode) {
  const source = payload?.data?.[symbol];
  const points = parseTencentPoints(source?.data?.data);
  const quote = source?.qt?.[symbol] || [];
  if (!source || !points.length) throw new Error("腾讯分时数据为空");
  return {
    code: normalizedCode,
    name: quote[1] || "",
    preClose: numberValue(quote[4], points[0]?.price),
    points,
  };
}

async function fetchTencentTrend(normalizedCode) {
  const symbol = tencentSymbol(normalizedCode);
  let lastError;
  for (const baseUrl of TENCENT_TREND_BASE_URLS) {
    try {
      const payload = await fetchJsonWithRetry(`${baseUrl}?code=${encodeURIComponent(symbol)}`, 1);
      return parseTencentTrend(payload, symbol, normalizedCode);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("腾讯分时行情请求失败");
}

function parseEastmoneyTrend(payload, normalizedCode) {
  const source = payload?.data;
  const points = (source?.trends || []).map((row) => {
    const fields = String(row).split(",");
    return {
      time: fields[0] || "",
      price: numberValue(fields[1]),
      average: numberValue(fields[2]),
      volume: numberValue(fields[5]),
    };
  }).filter((point) => point.price > 0);
  if (!source || !points.length) throw new Error("东方财富分时数据为空");
  return {
    code: normalizedCode,
    name: source.name || "",
    preClose: numberValue(source.preClose),
    points,
  };
}

async function fetchEastmoneyTrend(normalizedCode) {
  const params = {
    secid: `${marketId(normalizedCode)}.${normalizedCode}`,
    fields1: "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
    fields2: "f51,f52,f53,f54,f55,f56,f57,f58",
    ndays: "1",
    iscr: "0",
    ut: EASTMONEY_TREND_TOKEN,
  };
  let lastError;
  for (const baseUrl of EASTMONEY_TREND_BASE_URLS) {
    try {
      return parseEastmoneyTrend(await fetchJsonp(baseUrl, params), normalizedCode);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("东方财富分时行情请求失败");
}

export async function fetchIntradayTrend(code) {
  const normalizedCode = String(code || "").padStart(6, "0");
  try {
    return await fetchTencentTrend(normalizedCode);
  } catch (tencentError) {
    try {
      return await fetchEastmoneyTrend(normalizedCode);
    } catch (eastmoneyError) {
      throw new AggregateError([tencentError, eastmoneyError], "暂无今日分时数据");
    }
  }
}
