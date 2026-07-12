import { createApp, computed, ref, onMounted, onBeforeUnmount, nextTick } from "./vendor/vue.esm-browser.prod.js";

const emptyData = {
  meta: {},
  sentiment: {},
  rankings: {},
  limit_ups: [],
  broken_limits: [],
  limit_downs: [],
  strong_stocks: [],
  sub_new_stocks: [],
  stats: [],
};

const marketBoards = ["主板", "创业板", "科创板", "北交所"];
const refreshMs = 60000;
const feedbackRefreshMs = 30000;
const feedbackStorageKey = "fenggu-feedbacks";
const layoutKey = "fenggu-layout:";
const themeNotice = "题材来自东方财富概念数据，仅供参考";
const limitStatsHelp = "涨停统计格式为 N/M，表示近 M 个交易日内涨停 N 次，例如 6/6 表示近 6 个交易日涨停 6 次。";
const dateRangeMonths = 3;
let holidaysCache = null;
const themeSeparators = /[，,；;、|/\n\r]+/;
const ignoredThemes = new Set(["", "-", "--", "其他", "未知", "暂无", "暂无题材", "无", "null", "none", "nan"]);

function numberValue(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeText(value) {
  return String(value ?? "").trim().toLowerCase();
}

function inferMarketBoard(code) {
  const text = String(code || "");
  if (text.startsWith("300") || text.startsWith("301")) return "创业板";
  if (text.startsWith("688")) return "科创板";
  if (text.startsWith("8") || text.startsWith("4") || text.startsWith("920")) return "北交所";
  return "主板";
}

function marketBoardOf(stock) {
  return marketBoards.includes(stock?.market_board) ? stock.market_board : inferMarketBoard(stock?.code);
}

function normalizeThemes(values) {
  const source = Array.isArray(values) ? values : [values];
  const themes = [];
  const seen = new Set();
  for (const value of source.flat(Infinity)) {
    for (const part of String(value || "").split(themeSeparators)) {
      const theme = part.trim();
      if (!theme || theme.startsWith("<generator object") || ignoredThemes.has(theme.toLowerCase()) || seen.has(theme)) continue;
      seen.add(theme);
      themes.push(theme);
    }
  }
  return themes;
}

function stockThemes(stock) {
  const savedThemes = normalizeThemes(stock?.themes);
  return savedThemes.length ? savedThemes : normalizeThemes([stock?.concept, stock?.theme]);
}

function normalizeIndustry(value) {
  const text = String(value || "").trim();
  const patches = {
    计算机设: "计算机设备",
    旅游及景: "旅游及景区",
  };
  return patches[text] || text;
}

function normalizeStock(stock) {
  const themes = stockThemes(stock);
  return {
    ...stock,
    industry: normalizeIndustry(stock.industry),
    market_board: marketBoardOf(stock),
    themes,
    theme: themes.join("、"),
  };
}

function shanghaiDateText(date = new Date()) {
  return date.toLocaleDateString("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).replaceAll("/", "-");
}

function isWeekend(dateText) {
  const date = new Date(`${dateText}T00:00:00+08:00`);
  const day = date.getDay();
  return day === 0 || day === 6;
}

function addMonths(dateText, offset) {
  const date = new Date(`${dateText}T00:00:00+08:00`);
  date.setMonth(date.getMonth() + offset);
  return shanghaiDateText(date);
}

async function loadHolidays() {
  if (holidaysCache) return holidaysCache;
  try {
    const response = await fetch("./data/holidays.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    holidaysCache = await response.json();
  } catch (error) {
    console.warn("节假日数据加载失败", error);
    holidaysCache = {};
  }
  return holidaysCache;
}

async function isTradingDay(dateText) {
  if (isWeekend(dateText)) return false;
  const holidays = await loadHolidays();
  const year = dateText.slice(0, 4);
  return !(holidays[year] || []).includes(dateText);
}

function isDateWithinRange(dateText, minDateText, maxDateText) {
  return Boolean(dateText) && dateText >= minDateText && dateText <= maxDateText;
}

function todayEmptyPayload(dateText, status = "waiting") {
  return {
    ...emptyData,
    meta: {
      site_name: "峰股top",
      trade_date: dateText,
      updated_at: new Date().toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }),
      market_data_ready_time: "15:30",
      source: "today-empty",
      data_status: status,
      available_dates: [],
      notes: ["今日数据等待更新，交易时间内按实时接口逐步刷新，不使用前一交易日数据冒充。"],
    },
    sentiment: {
      limit_up_count: 0,
      limit_down_count: 0,
      broken_limit_count: 0,
      highest_board: 0,
      first_board_count: 0,
      multi_board_count: 0,
      broken_rate: 0,
      promoted_count: 0,
      promotion_rate: 0,
      promoted_stocks: [],
    },
  };
}

function missingDatePayload(dateText, message = "暂无历史数据") {
  return {
    ...emptyData,
    meta: {
      site_name: "峰股top",
      trade_date: dateText,
      updated_at: new Date().toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }),
      source: "history-missing",
      data_status: "missing",
      available_dates: [],
      notes: [message],
    },
    sentiment: {
      limit_up_count: 0,
      limit_down_count: 0,
      broken_limit_count: 0,
      highest_board: 0,
      first_board_count: 0,
      multi_board_count: 0,
      broken_rate: 0,
      promoted_count: 0,
      promotion_rate: 0,
      promoted_stocks: [],
    },
  };
}

function shanghaiMinutes(date = new Date()) {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const hour = Number(parts.find((part) => part.type === "hour")?.value || 0);
  const minute = Number(parts.find((part) => part.type === "minute")?.value || 0);
  return hour * 60 + minute;
}

function marketPhase() {
  const minutes = shanghaiMinutes();
  if ((minutes >= 570 && minutes < 690) || (minutes >= 780 && minutes < 900)) return "intraday";
  if (minutes >= 900 && minutes < 930) return "settling";
  return "closed";
}

function shouldUseLocalFeedback() {
  return window.location.protocol === "file:" || window.location.hostname.endsWith("github.io");
}

createApp({
  setup() {
    const data = ref(window.__FENGGU_FALLBACK_DATA__ || emptyData);
    const loadError = ref("");
    const isDateLoading = ref(false);
    const query = ref("");
    const selectedBoards = ref([]);
    const boardFilter = ref("all");
    const sortKeys = ref({
      limitups: "first_limit_time",
      broken: "open_times",
      down: "change_pct",
    });
    const selectedDate = ref("");
    const historicalDateLocked = ref(false);
    const activeSection = ref("overview");
    const refreshPaused = ref(false);
    const realtimeStatus = ref("收盘锁定");
    const lastRefreshAt = ref("");
    const hoveredStock = ref(null);
    const popoverStyle = ref({});
    const panelSizes = ref({});
    const feedbackItems = ref([]);
    const feedbackError = ref("");
    const feedbackNotice = ref("");
    const feedbackModalOpen = ref(false);
    const feedbackSubmitting = ref(false);
    const feedbackForm = ref({ displayName: "", content: "" });
    const isAdminMode = ref(false);
    const adminToken = ref(localStorage.getItem("fenggu-admin-token") || "");
    let refreshTimer = null;
    let feedbackTimer = null;
    let observer = null;

    function setUrlDate(date) {
      if (window.location.protocol === "file:" || !date) return;
      const url = new URL(window.location.href);
      url.searchParams.set("date", date);
      window.history.replaceState({}, "", url);
    }

    function readUrlDate() {
      if (window.location.protocol === "file:") return "";
      return new URL(window.location.href).searchParams.get("date") || "";
    }

    async function fetchJson(path, options = {}) {
      const response = await fetch(path, { cache: "no-store", ...options });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    }

    function readLocalFeedbacks() {
      try {
        const rows = JSON.parse(localStorage.getItem(feedbackStorageKey) || "[]");
        return Array.isArray(rows)
          ? rows.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""))).slice(0, 50)
          : [];
      } catch {
        return [];
      }
    }

    function writeLocalFeedbacks(rows) {
      localStorage.setItem(feedbackStorageKey, JSON.stringify(rows.slice(0, 50)));
    }

    function createLocalFeedback(content, displayName) {
      return {
        id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        display_name: displayName || "匿名用户",
        content,
        like_count: 0,
        created_at: new Date().toISOString(),
        local: true,
      };
    }

    function setFeedbackList(rows) {
      feedbackItems.value = (rows || []).filter(Boolean).slice(0, 50);
    }

    function normalizePayload(payload) {
      const normalized = {
        ...emptyData,
        ...payload,
        meta: { ...(payload.meta || {}) },
        sentiment: { ...(payload.sentiment || {}) },
        rankings: { ...(payload.rankings || {}) },
      };
      normalized.limit_ups = (payload.limit_ups || []).map(normalizeStock);
      normalized.broken_limits = (payload.broken_limits || []).map(normalizeStock);
      normalized.limit_downs = (payload.limit_downs || []).map(normalizeStock);
      normalized.strong_stocks = payload.strong_stocks || [];
      normalized.sub_new_stocks = payload.sub_new_stocks || [];
      normalized.stats = payload.stats || [];
      return normalized;
    }

    function updateData(payload) {
      data.value = normalizePayload(payload);
      selectedDate.value = data.value.meta.trade_date || selectedDate.value;
      lastRefreshAt.value = new Date().toLocaleTimeString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
    }

    async function loadClosedData() {
      if (window.location.protocol === "file:") {
        updateData(window.__FENGGU_FALLBACK_DATA__ || emptyData);
        realtimeStatus.value = "本地备用数据";
        return;
      }
      const payload = await fetchJson("./data/latest.json");
      const today = shanghaiDateText();
      if (payload?.meta?.trade_date === today) {
        updateData(payload);
        realtimeStatus.value = "收盘锁定";
        loadError.value = "";
        return;
      }
      updateData(todayEmptyPayload(today, "waiting_closed"));
      realtimeStatus.value = "今日等待更新";
      loadError.value = "今日数据等待更新，当前不沿用前一个交易日数据。你可以手动选择历史交易日查看。";
    }

    async function loadRealtimeData() {
      if (window.location.protocol === "file:" || refreshPaused.value) return;
      if (historicalDateLocked.value) return;
      try {
        const today = shanghaiDateText().replaceAll("-", "");
        const payload = await fetchJson(`./api/realtime?date=${today}`);
        updateData({
          ...todayEmptyPayload(shanghaiDateText(), "intraday"),
          ...payload,
          meta: {
            ...todayEmptyPayload(shanghaiDateText(), "intraday").meta,
            ...(payload.meta || {}),
            trade_date: shanghaiDateText(),
            data_status: payload.meta?.data_status || "intraday",
          },
          sentiment: {
            ...todayEmptyPayload(shanghaiDateText(), "intraday").sentiment,
            ...(payload.sentiment || {}),
            limit_up_count: (payload.limit_ups || []).length,
            broken_limit_count: (payload.broken_limits || []).length,
            limit_down_count: (payload.limit_downs || []).length,
          },
          limit_ups: payload.limit_ups || [],
          broken_limits: payload.broken_limits || [],
          limit_downs: payload.limit_downs || [],
        });
        realtimeStatus.value = marketPhase() === "settling" ? "等待收盘固化" : "盘中实时";
        loadError.value = "";
      } catch (error) {
        if (marketPhase() === "intraday") {
          const today = shanghaiDateText();
          updateData(todayEmptyPayload(today, "realtime_unavailable"));
          loadError.value = "实时接口暂时不可用，当前显示今日空数据，不使用前一交易日数据冒充。";
          realtimeStatus.value = "实时接口不可用";
        }
        console.warn(error);
      }
    }

    async function refreshForTime() {
      const phase = marketPhase();
      const today = shanghaiDateText();
      if (phase === "intraday" && !historicalDateLocked.value) {
        await loadRealtimeData();
        return;
      }
      if (phase === "settling" && !historicalDateLocked.value) {
        if (data.value.meta.trade_date !== today) updateData(todayEmptyPayload(today, "settling"));
        realtimeStatus.value = "等待收盘固化";
        return;
      }
      if (!historicalDateLocked.value && (!selectedDate.value || selectedDate.value === today || data.value.meta.trade_date !== today)) {
        await loadClosedData();
      }
    }

    async function loadData() {
      try {
        const urlDate = readUrlDate();
        if (urlDate && isDateWithinRange(urlDate, addMonths(shanghaiDateText(), -dateRangeMonths), shanghaiDateText())) {
          await loadDate(urlDate);
          return;
        }
        await loadClosedData();
        await refreshForTime();
      } catch (error) {
        loadError.value = "未能读取 data/latest.json，当前显示内置演示数据。";
        console.warn(error);
        updateData(window.__FENGGU_FALLBACK_DATA__ || emptyData);
      }
    }

    async function loadDate(date) {
      if (!date) return;
      const today = shanghaiDateText();
      const minDate = addMonths(today, -dateRangeMonths);
      selectedDate.value = date;
      setUrlDate(date);
      isDateLoading.value = true;
      loadError.value = "";
      let tradingDay = true;
      try {
        if (!isDateWithinRange(date, minDate, today)) {
          historicalDateLocked.value = true;
          updateData(missingDatePayload(date, "暂无历史数据"));
          realtimeStatus.value = "暂无历史数据";
          loadError.value = "暂无历史数据";
          return;
        }
        tradingDay = await isTradingDay(date);
        if (!tradingDay) {
          historicalDateLocked.value = true;
          updateData(missingDatePayload(date, "当天非交易日，无数据"));
          realtimeStatus.value = "当天非交易日";
          loadError.value = "当天非交易日，无数据";
          return;
        }
        if (date === today) {
          historicalDateLocked.value = false;
          selectedDate.value = date;
          await refreshForTime();
          clearFilters();
          return;
        }
        historicalDateLocked.value = true;
        updateData(todayEmptyPayload(date, "loading"));
        realtimeStatus.value = "数据切换中";
        const payload = await fetchJson(`./data/history/${date}.json`);
        updateData(payload);
        selectedDate.value = data.value.meta.trade_date || date;
        realtimeStatus.value = "历史数据";
        clearFilters();
      } catch (error) {
        historicalDateLocked.value = true;
        const message = tradingDay ? "暂无历史数据" : "当天非交易日，无数据";
        updateData(missingDatePayload(date, message));
        realtimeStatus.value = tradingDay ? "暂无历史数据" : "当天非交易日";
        loadError.value = message;
        console.warn(error);
      } finally {
        isDateLoading.value = false;
      }
    }

    async function loadDataByDate(date) {
      await loadDate(date);
    }

    const limitUps = computed(() => (data.value.limit_ups || []).map(normalizeStock));
    const brokenWatch = computed(() => (data.value.broken_limits || []).map(normalizeStock));
    const limitDowns = computed(() => (data.value.limit_downs || []).map(normalizeStock));
    const allStats = computed(() => data.value.stats || []);
    const statsByCode = computed(() => new Map(allStats.value.map((row) => [row.code, row])));
    const todayText = computed(() => shanghaiDateText());
    const minDateText = computed(() => addMonths(todayText.value, -dateRangeMonths));
    const totalLimitUps = computed(() => numberValue(data.value.sentiment.limit_up_count, limitUps.value.length));
    const brokenCount = computed(() => numberValue(data.value.sentiment.broken_limit_count, brokenWatch.value.length));
    const downCount = computed(() => numberValue(data.value.sentiment.limit_down_count, limitDowns.value.length));
    const isLatestClosedSession = computed(() => data.value.meta.trade_date && data.value.meta.trade_date !== todayText.value);
    const dataScopeText = computed(() => {
      if (realtimeStatus.value === "盘中实时") return `当前显示 ${todayText.value} 盘中实时数据，每 1 分钟自动刷新。`;
      if (realtimeStatus.value === "实时接口不可用") return `当前显示 ${todayText.value} 今日空数据，实时接口恢复后会继续按 1 分钟刷新。`;
      if (realtimeStatus.value === "等待收盘固化") return `当前显示 ${todayText.value} 最后一份盘中数据，15:30 后切换收盘锁定。`;
      if (realtimeStatus.value === "历史数据") return `当前显示历史交易日 ${data.value.meta.trade_date}，可在日期框切换任意历史日期。`;
      if (realtimeStatus.value === "当天非交易日") return `当前选择 ${data.value.meta.trade_date}，当天非交易日，无数据。`;
      if (realtimeStatus.value === "暂无历史数据") return `当前选择 ${data.value.meta.trade_date}，暂无历史数据。`;
      if (realtimeStatus.value === "今日等待更新") return `当前显示 ${todayText.value} 今日空数据，不沿用前一个交易日数据。`;
      if (isLatestClosedSession.value) return `当前显示最近已收盘交易日 ${data.value.meta.trade_date}，交易日 15:30 后更新。`;
      return `当前显示 ${data.value.meta.trade_date || "最新"} 收盘锁定数据。`;
    });

    const navItems = computed(() => [
      { key: "overview", label: "首页概览", target: "overview-section" },
      { key: "limitups", label: `涨停汇总(${limitUps.value.length})`, target: "limitups-section" },
      { key: "broken", label: `炸板汇总(${brokenWatch.value.length})`, target: "broken-section" },
      { key: "down", label: `跌停汇总(${limitDowns.value.length})`, target: "down-section" },
    ]);

    const highestBoard = computed(() => Math.max(0, ...limitUps.value.map((item) => numberValue(item.consecutive_days, 1))));
    const limitUpBoardCounts = computed(() => {
      const counts = Object.fromEntries(marketBoards.map((board) => [board, 0]));
      for (const stock of limitUps.value) {
        const board = marketBoardOf(stock);
        counts[board] += 1;
      }
      return counts;
    });
    const brokenRate = computed(() => {
      const total = totalLimitUps.value + brokenCount.value;
      return total ? ((brokenCount.value / total) * 100).toFixed(1) : "0.0";
    });
    const metricCards = computed(() => [
      { label: realtimeStatus.value === "盘中实时" ? "盘中涨停" : "收盘涨停", value: totalLimitUps.value, unit: "只", caption: data.value.meta.trade_date || "自动更新" },
      { label: "连板股", value: numberValue(data.value.sentiment.multi_board_count, limitUps.value.filter((item) => numberValue(item.consecutive_days, 1) >= 2).length), unit: "只", caption: "2板及以上" },
      { label: "炸板股", value: brokenCount.value, unit: "只", caption: "盘中打开涨停" },
      { label: "跌停股", value: downCount.value, unit: "只", caption: "跌停池同步统计" },
      { label: "炸板率", value: `${brokenRate.value}%`, unit: "", caption: "炸板 / 涨停炸板合计" },
      { label: "晋级率", value: `${numberValue(data.value.sentiment.promotion_rate).toFixed(1)}%`, unit: "", caption: data.value.sentiment.previous_trade_date ? `基于 ${data.value.sentiment.previous_trade_date}` : "昨日涨停今日连板" },
      { label: "市场最高板", value: highestBoard.value, unit: "板", caption: highestBoard.value >= 5 ? "高位活跃" : "情绪观察" },
    ]);

    function boardAllowed(stock) {
      return !selectedBoards.value.length || selectedBoards.value.includes(marketBoardOf(stock));
    }

    function searchAllowed(stock, localQuery = query.value) {
      const term = normalizeText(localQuery);
      return !term || normalizeText(stock.code).includes(term) || normalizeText(stock.name).includes(term);
    }

    function filteredRows(rows, type) {
      return rows.filter((stock) => {
        const board = numberValue(stock.consecutive_days, 1);
        const matchesBoardCount = type !== "limitups" || boardFilter.value === "all" || (boardFilter.value === "5" ? board >= 5 : board === Number(boardFilter.value));
        return matchesBoardCount && boardAllowed(stock) && searchAllowed(stock);
      });
    }

    function sortedRows(rows, type) {
      const sortKey = sortKeys.value[type];
      const rowList = [...filteredRows(rows, type)];
      const sorters = {
        first_limit_time: (a, b) => String(a.first_limit_time || "99:99:99").localeCompare(String(b.first_limit_time || "99:99:99")),
        consecutive_days: (a, b) => numberValue(b.consecutive_days, 1) - numberValue(a.consecutive_days, 1),
        seal_amount: (a, b) => numberValue(b.seal_amount) - numberValue(a.seal_amount),
        turnover_amount: (a, b) => numberValue(b.turnover_amount) - numberValue(a.turnover_amount),
        turnover_rate: (a, b) => numberValue(b.turnover_rate) - numberValue(a.turnover_rate),
        open_times: (a, b) => numberValue(b.open_times) - numberValue(a.open_times),
        change_pct: (a, b) => numberValue(a.change_pct) - numberValue(b.change_pct),
      };
      return rowList.sort(sorters[sortKey] || sorters.first_limit_time);
    }

    const sortedLimitUps = computed(() => sortedRows(limitUps.value, "limitups"));
    const sortedBroken = computed(() => sortedRows(brokenWatch.value, "broken"));
    const sortedDowns = computed(() => sortedRows(limitDowns.value, "down"));

    const tableSections = computed(() => [
      { id: "limitups-section", key: "limitups", title: `收盘涨停股票(${limitUps.value.length})`, rows: sortedLimitUps.value, sortKey: sortKeys.value.limitups },
      { id: "broken-section", key: "broken", title: `收盘炸板股票(${brokenWatch.value.length})`, rows: sortedBroken.value, sortKey: sortKeys.value.broken },
      { id: "down-section", key: "down", title: `收盘跌停股票(${limitDowns.value.length})`, rows: sortedDowns.value, sortKey: sortKeys.value.down },
    ]);

    const boardDistribution = computed(() => {
      const buckets = [
        { label: "首板", min: 1, max: 1 },
        { label: "2连板", min: 2, max: 2 },
        { label: "3连板", min: 3, max: 3 },
        { label: "4连板", min: 4, max: 4 },
        { label: "5板+", min: 5, max: Infinity },
      ];
      const rows = buckets.map((bucket) => {
        const count = limitUps.value.filter((stock) => {
          const board = numberValue(stock.consecutive_days, 1);
          return board >= bucket.min && board <= bucket.max;
        }).length;
        return { ...bucket, count };
      });
      const max = Math.max(1, ...rows.map((row) => row.count));
      return rows.map((row) => ({ ...row, width: Math.max(6, Math.round((row.count / max) * 100)) }));
    });

    function rankByField(rows, field) {
      const counts = new Map();
      for (const stock of rows) {
        if (field === "theme") {
          for (const theme of stockThemes(stock)) {
            counts.set(theme, (counts.get(theme) || 0) + 1);
          }
          continue;
        }
        const key = normalizeIndustry(stock[field]) || "其他";
        counts.set(key, (counts.get(key) || 0) + 1);
      }
      return [...counts.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count).slice(0, 12);
    }

    const industryRank = computed(() => {
      const rank = data.value.rankings.industry_limit_rank || rankByField(limitUps.value, "industry");
      const merged = new Map();
      for (const item of rank) {
        const name = normalizeIndustry(item.name) || "其他";
        merged.set(name, (merged.get(name) || 0) + numberValue(item.count));
      }
      return [...merged.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
    });
    const themeRank = computed(() => rankByField(limitUps.value, "theme"));
    const highestBoardRank = computed(() => [...limitUps.value].sort((a, b) => numberValue(b.consecutive_days, 1) - numberValue(a.consecutive_days, 1)).slice(0, 6));
    const promotedStocks = computed(() => data.value.sentiment.promoted_stocks || []);
    const dataCompleteness = computed(() => [
      { label: "涨停池", count: limitUps.value.length, ok: limitUps.value.length > 0 },
      { label: "炸板池", count: brokenWatch.value.length, ok: brokenWatch.value.length > 0 },
      { label: "跌停池", count: limitDowns.value.length, ok: limitDowns.value.length > 0 },
      { label: "历史统计", count: allStats.value.length, ok: allStats.value.length > 0 },
    ]);

    function formatMoney(value) {
      const amount = numberValue(value);
      if (!amount) return "--";
      if (amount >= 100000000) return `${(amount / 100000000).toFixed(2)}亿`;
      if (amount >= 10000) return `${(amount / 10000).toFixed(0)}万`;
      return String(amount);
    }

    function formatPercent(value) {
      return `${numberValue(value).toFixed(2)}%`;
    }

    function formatText(value) {
      return value === null || value === undefined || value === "" ? "--" : value;
    }

    function stockStats(stock) {
      return statsByCode.value.get(stock.code) || {};
    }

    function detailValue(value) {
      return value === null || value === undefined || value === "" ? "数据积累中" : value;
    }

    function rowClass(stock, sectionKey) {
      if (sectionKey === "down") return "down-text";
      return numberValue(stock.change_pct) >= 0 ? "up-text" : "down-text";
    }

    function clearFilters() {
      query.value = "";
      boardFilter.value = "all";
      selectedBoards.value = [];
      sortKeys.value = { limitups: "first_limit_time", broken: "open_times", down: "change_pct" };
    }

    function setSort(section, value) {
      sortKeys.value = { ...sortKeys.value, [section]: value };
    }

    function csvCell(value) {
      const text = String(value ?? "").replaceAll('"', '""');
      return `"${text}"`;
    }

    function exportRows(section) {
      const headers = ["代码", "名称", "涨幅", "最新价", "上市板块", "行业", "题材", "流通市值", "总市值", "首次封板", "最后封板", "成交额", "换手率", "封单金额", "连板", "炸板", "涨停统计"];
      const rows = section.rows.map((stock) => [
        stock.code,
        stock.name,
        formatPercent(stock.change_pct),
        stock.latest_price || "",
        stock.market_board || "",
        stock.industry || "",
        stock.theme || "",
        formatMoney(stock.float_market_cap),
        formatMoney(stock.total_market_cap),
        stock.first_limit_time || "",
        stock.last_limit_time || "",
        formatMoney(stock.turnover_amount),
        formatPercent(stock.turnover_rate),
        formatMoney(stock.seal_amount),
        stock.consecutive_days || 1,
        stock.open_times ?? 0,
        stock.limit_stats || "",
      ]);
      const csv = [headers, ...rows].map((row) => row.map(csvCell).join(",")).join("\n");
      const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `峰股top-${section.title}-${data.value.meta.trade_date || "latest"}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    }

    function scrollToSection(item) {
      activeSection.value = item.key;
      const target = document.getElementById(item.target);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function panelStyle(id) {
      const size = panelSizes.value[id] || {};
      return {
        width: size.width ? `${size.width}px` : undefined,
        height: size.height ? `${size.height}px` : undefined,
      };
    }

    function loadPanelSizes() {
      const next = {};
      const panelIds = ["feedback-panel", "data-section", ...tableSections.value.map((item) => item.id)];
      for (const item of navItems.value) {
        try {
          const saved = JSON.parse(localStorage.getItem(`${layoutKey}${item.target}`) || "null");
          if (saved) next[item.target] = saved;
        } catch {
          // Ignore invalid saved layout values.
        }
      }
      for (const id of panelIds) {
        try {
          const saved = JSON.parse(localStorage.getItem(`${layoutKey}${id}`) || "null");
          if (saved) next[id] = saved;
        } catch {
          // Ignore invalid saved layout values.
        }
      }
      panelSizes.value = next;
    }

    function startResize(event, id, axis) {
      if (window.matchMedia("(max-width: 900px)").matches && axis === "x") return;
      const panel = event.currentTarget.closest(".resizable-panel");
      if (!panel) return;
      event.preventDefault();
      const resizeClass = axis === "x" ? "is-resizing-x" : "is-resizing-y";
      document.body.classList.add(resizeClass);
      const startX = event.clientX;
      const startY = event.clientY;
      const startWidth = panel.offsetWidth;
      const startHeight = panel.offsetHeight;
      function onMove(moveEvent) {
        const current = panelSizes.value[id] || {};
        const next = { ...current };
        if (axis === "x") next.width = Math.max(320, startWidth + moveEvent.clientX - startX);
        if (axis === "y") next.height = Math.max(id === "feedback-panel" ? 140 : 260, startHeight + moveEvent.clientY - startY);
        panelSizes.value = { ...panelSizes.value, [id]: next };
      }
      function onUp() {
        localStorage.setItem(`${layoutKey}${id}`, JSON.stringify(panelSizes.value[id] || {}));
        document.body.classList.remove(resizeClass);
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        window.removeEventListener("blur", onUp);
      }
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
      window.addEventListener("blur", onUp);
    }

    function showStockPopover(stock, event) {
      hoveredStock.value = normalizeStock(stock);
      const x = Math.min(event.clientX + 14, window.innerWidth - 340);
      const y = Math.min(event.clientY + 14, window.innerHeight - 360);
      popoverStyle.value = { left: `${Math.max(12, x)}px`, top: `${Math.max(12, y)}px` };
    }

    function hideStockPopover() {
      hoveredStock.value = null;
    }

    async function loadFeedbacks() {
      feedbackNotice.value = "";
      if (shouldUseLocalFeedback()) {
        setFeedbackList(readLocalFeedbacks());
        feedbackError.value = "";
        return;
      }
      try {
        const payload = await fetchJson("./api/feedbacks");
        setFeedbackList(payload.feedbacks || []);
        feedbackError.value = "";
      } catch (error) {
        setFeedbackList(readLocalFeedbacks());
        feedbackError.value = "";
        console.warn(error);
      }
    }

    function openFeedbackModal() {
      feedbackModalOpen.value = true;
      feedbackForm.value = { displayName: "", content: "" };
      feedbackNotice.value = "";
      feedbackError.value = "";
    }

    function closeFeedbackModal() {
      if (feedbackSubmitting.value) return;
      feedbackModalOpen.value = false;
    }

    async function submitFeedback() {
      const content = feedbackForm.value.content.trim();
      if (!content) {
        feedbackError.value = "请先填写反馈内容";
        feedbackNotice.value = "";
        return;
      }
      feedbackSubmitting.value = true;
      try {
        const displayName = feedbackForm.value.displayName.trim();
        if (shouldUseLocalFeedback()) {
          const feedback = createLocalFeedback(content, displayName);
          const next = [feedback, ...readLocalFeedbacks()];
          writeLocalFeedbacks(next);
          setFeedbackList(next);
        } else {
          try {
            const payload = await fetchJson("./api/feedbacks", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                content,
                display_name: displayName,
              }),
            });
            setFeedbackList([payload.feedback, ...feedbackItems.value]);
          } catch {
            const feedback = createLocalFeedback(content, displayName);
            const next = [feedback, ...readLocalFeedbacks()];
            writeLocalFeedbacks(next);
            setFeedbackList(next);
          }
        }
        feedbackModalOpen.value = false;
        feedbackError.value = "";
        feedbackNotice.value = "提交成功。";
        feedbackForm.value = { displayName: "", content: "" };
      } catch (error) {
        feedbackError.value = "反馈提交失败";
        feedbackNotice.value = "";
        console.warn(error);
      } finally {
        feedbackSubmitting.value = false;
      }
    }

    async function likeFeedback(item) {
      try {
        const likedKey = `fenggu-liked:${item.id}`;
        if (localStorage.getItem(likedKey)) return;
        if (shouldUseLocalFeedback() || item.local || String(item.id).startsWith("local-")) {
          const next = readLocalFeedbacks().map((row) =>
            row.id === item.id ? { ...row, like_count: numberValue(row.like_count) + 1 } : row,
          );
          writeLocalFeedbacks(next);
          setFeedbackList(next);
          localStorage.setItem(likedKey, "1");
          feedbackError.value = "";
          return;
        }
        const payload = await fetchJson(`./api/feedbacks/${encodeURIComponent(item.id)}/like`, { method: "POST" });
        localStorage.setItem(likedKey, "1");
        const next = payload.feedback || { ...item, like_count: numberValue(item.like_count) + 1 };
        feedbackItems.value = feedbackItems.value.map((row) => (row.id === item.id ? next : row));
      } catch (error) {
        const next = feedbackItems.value.map((row) =>
          row.id === item.id ? { ...row, like_count: numberValue(row.like_count) + 1 } : row,
        );
        setFeedbackList(next);
        writeLocalFeedbacks(next.filter((row) => row.local || String(row.id).startsWith("local-")));
        feedbackError.value = "";
        console.warn(error);
      }
    }

    function toggleAdminMode() {
      if (isAdminMode.value) {
        isAdminMode.value = false;
        return;
      }
      const token = window.prompt("请输入管理员密钥");
      if (!token) return;
      adminToken.value = token.trim();
      localStorage.setItem("fenggu-admin-token", adminToken.value);
      isAdminMode.value = true;
    }

    async function deleteFeedback(item) {
      if (!adminToken.value) return;
      const confirmed = window.confirm("确认删除这条反馈？");
      if (!confirmed) return;
      try {
        if (shouldUseLocalFeedback() || item.local || String(item.id).startsWith("local-")) {
          const next = readLocalFeedbacks().filter((row) => row.id !== item.id);
          writeLocalFeedbacks(next);
          setFeedbackList(next);
          feedbackError.value = "";
          return;
        }
        await fetchJson(`./api/feedbacks/${encodeURIComponent(item.id)}`, {
          method: "DELETE",
          headers: { "X-Admin-Token": adminToken.value },
        });
        feedbackItems.value = feedbackItems.value.filter((row) => row.id !== item.id);
      } catch (error) {
        feedbackError.value = "删除失败，请检查管理员密钥";
        console.warn(error);
      }
    }

    function formatFeedbackTime(value) {
      if (!value) return "--";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
    }

    function setupObserver() {
      if (observer) observer.disconnect();
      observer = new IntersectionObserver(
        (entries) => {
          const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
          if (!visible) return;
          const match = navItems.value.find((item) => item.target === visible.target.id);
          if (match) activeSection.value = match.key;
        },
        { rootMargin: "-20% 0px -68% 0px", threshold: [0.1, 0.3, 0.6] },
      );
      navItems.value.forEach((item) => {
        const node = document.getElementById(item.target);
        if (node) observer.observe(node);
      });
    }

    function startRefreshTimer() {
      refreshTimer = window.setInterval(refreshForTime, refreshMs);
      feedbackTimer = window.setInterval(loadFeedbacks, feedbackRefreshMs);
      document.addEventListener("visibilitychange", () => {
        if (!document.hidden) {
          refreshForTime();
          loadFeedbacks();
        }
      });
    }

    function toggleRefresh() {
      refreshPaused.value = !refreshPaused.value;
      if (!refreshPaused.value) refreshForTime();
    }

    onMounted(async () => {
      loadPanelSizes();
      await loadData();
      await loadFeedbacks();
      await nextTick();
      setupObserver();
      startRefreshTimer();
    });

    onBeforeUnmount(() => {
      if (refreshTimer) window.clearInterval(refreshTimer);
      if (feedbackTimer) window.clearInterval(feedbackTimer);
      if (observer) observer.disconnect();
    });

    return {
      data,
      loadError,
      isDateLoading,
      query,
      selectedBoards,
      marketBoards,
      boardFilter,
      sortKeys,
      selectedDate,
      activeSection,
      navItems,
      todayText,
      minDateText,
      metricCards,
      dataScopeText,
      realtimeStatus,
      lastRefreshAt,
      refreshPaused,
      themeNotice,
      limitStatsHelp,
      tableSections,
      boardDistribution,
      limitUpBoardCounts,
      highestBoardRank,
      promotedStocks,
      dataCompleteness,
      industryRank,
      themeRank,
      hoveredStock,
      popoverStyle,
      feedbackItems,
      feedbackError,
      feedbackNotice,
      feedbackModalOpen,
      feedbackSubmitting,
      feedbackForm,
      isAdminMode,
      formatMoney,
      formatPercent,
      formatText,
      formatFeedbackTime,
      stockStats,
      detailValue,
      rowClass,
      clearFilters,
      setSort,
      exportRows,
      loadDate,
      loadDataByDate,
      scrollToSection,
      panelStyle,
      startResize,
      showStockPopover,
      hideStockPopover,
      toggleRefresh,
      openFeedbackModal,
      closeFeedbackModal,
      submitFeedback,
      likeFeedback,
      toggleAdminMode,
      deleteFeedback,
    };
  },
}).mount("#app");
