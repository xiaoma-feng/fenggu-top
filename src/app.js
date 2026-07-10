import { createApp, computed, ref, onMounted, onBeforeUnmount, nextTick } from "./vendor/vue.esm-browser.prod.js";

const emptyData = { meta: {}, sentiment: {}, rankings: {}, limit_ups: [], broken_limits: [], limit_downs: [], stats: [] };
const marketBoards = ["主板", "创业板", "科创板", "北交所"];
const themeNotice = "题材为系统识别，仅供参考";
const limitStatsHelp = "涨停统计格式为 N/M，表示近 M 个交易日内涨停 N 次，例如 6/6 表示近 6 个交易日涨停 6 次。";
const feedbackStorageKey = "fenggu-feedbacks";
const layoutKey = "fenggu-layout:";
const refreshMs = 60000;
const dateRangeMonths = 3;
let holidaysCache = null;

function numberValue(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function shanghaiDateText(date = new Date()) {
  return date.toLocaleDateString("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).replaceAll("/", "-");
}

function addMonths(dateText, offset) {
  const date = new Date(`${dateText}T00:00:00+08:00`);
  date.setMonth(date.getMonth() + offset);
  return shanghaiDateText(date);
}

function isWeekend(dateText) {
  const day = new Date(`${dateText}T00:00:00+08:00`).getDay();
  return day === 0 || day === 6;
}

async function loadHolidays() {
  if (holidaysCache) return holidaysCache;
  try {
    const res = await fetch("./data/holidays.json", { cache: "no-store" });
    holidaysCache = res.ok ? await res.json() : {};
  } catch (error) {
    console.warn("节假日数据加载失败", error);
    holidaysCache = {};
  }
  return holidaysCache;
}

async function isTradingDay(dateText) {
  if (isWeekend(dateText)) return false;
  const holidays = await loadHolidays();
  return !(holidays[dateText.slice(0, 4)] || []).includes(dateText);
}

function shanghaiMinutes() {
  const parts = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(new Date());
  return Number(parts.find((p) => p.type === "hour")?.value || 0) * 60 + Number(parts.find((p) => p.type === "minute")?.value || 0);
}

function marketPhase() {
  const minutes = shanghaiMinutes();
  if ((minutes >= 570 && minutes < 690) || (minutes >= 780 && minutes < 900)) return "intraday";
  if (minutes >= 900 && minutes < 930) return "settling";
  return "closed";
}

function inferMarketBoard(code) {
  const text = String(code || "");
  if (text.startsWith("300") || text.startsWith("301")) return "创业板";
  if (text.startsWith("688")) return "科创板";
  if (text.startsWith("8") || text.startsWith("4") || text.startsWith("920")) return "北交所";
  return "主板";
}

function normalizeIndustry(value) {
  const text = String(value || "").trim();
  return { "计算机设": "计算机设备", "旅游及景": "旅游及景区" }[text] || text;
}

function inferTheme(stock) {
  if (stock?.theme) return stock.theme;
  const text = [stock?.name, stock?.concept, stock?.industry, stock?.reason, stock?.selected_reason].join(" ");
  const rules = [
    ["机器人", ["机器人", "减速器", "智能制造"]], ["PCB", ["PCB", "线路板", "覆铜板"]], ["算力", ["算力", "服务器", "数据中心", "光模块"]],
    ["创新药", ["创新药", "医药", "生物"]], ["军工", ["军工", "航天", "航空", "卫星"]], ["半导体", ["半导体", "芯片", "集成电路"]],
    ["AI硬件", ["AI", "人工智能", "光学光电"]], ["消费电子", ["消费电子", "电子"]], ["有色金属", ["有色", "稀土", "金属"]],
    ["固态电池", ["固态电池", "电池", "锂电"]], ["商业航天", ["商业航天", "卫星", "航天"]],
  ];
  return rules.find(([, words]) => words.some((word) => text.includes(word)))?.[0] || "其他";
}

function normalizeStock(stock) {
  return { ...stock, industry: normalizeIndustry(stock.industry), market_board: stock.market_board || inferMarketBoard(stock.code), theme: inferTheme(stock) };
}

function emptyPayload(dateText, status, message) {
  return {
    ...emptyData,
    meta: { site_name: "峰股top", trade_date: dateText, updated_at: new Date().toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }), data_status: status, notes: [message] },
    sentiment: { limit_up_count: 0, broken_limit_count: 0, limit_down_count: 0, highest_board: 0, multi_board_count: 0, promotion_rate: 0, broken_rate: 0 },
    rankings: { industry_limit_rank: [], theme_limit_rank: [], market_board_limit_rank: [] },
  };
}

async function fetchJson(path, options = {}) {
  const res = await fetch(path, { cache: "no-store", ...options });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

createApp({
  setup() {
    const data = ref(window.__FENGGU_FALLBACK_DATA__ || emptyData);
    const loadError = ref("");
    const isDateLoading = ref(false);
    const query = ref("");
    const selectedBoards = ref([]);
    const boardFilter = ref("all");
    const selectedDate = ref("");
    const activeSection = ref("overview");
    const refreshPaused = ref(false);
    const realtimeStatus = ref("今日等待更新");
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
    const isAdminMode = ref(false);\n    const adminToken = ref(localStorage.getItem("fenggu-admin-token") || "");
    const sortKeys = ref({ limitups: "first_limit_time", broken: "open_times", down: "change_pct" });
    let timer = null;
    let observer = null;

    const todayText = computed(() => shanghaiDateText());
    const minDateText = computed(() => addMonths(todayText.value, -dateRangeMonths));

    function setUrlDate(date) {
      if (location.protocol === "file:" || !date) return;
      const url = new URL(location.href);
      url.searchParams.set("date", date);
      history.replaceState({}, "", url);
    }

    function updateData(payload, status = "") {
      const next = { ...emptyData, ...payload, meta: { ...(payload.meta || {}) }, sentiment: { ...(payload.sentiment || {}) }, rankings: { ...(payload.rankings || {}) } };
      next.limit_ups = (payload.limit_ups || []).map(normalizeStock);
      next.broken_limits = (payload.broken_limits || []).map(normalizeStock);
      next.limit_downs = (payload.limit_downs || []).map(normalizeStock);
      next.stats = payload.stats || [];
      data.value = next;
      selectedDate.value = next.meta.trade_date || selectedDate.value;
      if (status) realtimeStatus.value = status;
      lastRefreshAt.value = new Date().toLocaleTimeString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
    }

    async function loadToday() {
      const today = todayText.value;
      selectedDate.value = today;
      setUrlDate(today);
      const phase = marketPhase();
      if (phase === "intraday" && !refreshPaused.value) {
        try {
          const payload = await fetchJson(`./api/realtime?date=${today.replaceAll("-", "")}`);
          updateData({ ...emptyPayload(today, "intraday", "盘中实时数据"), ...payload }, "盘中实时");
          loadError.value = "";
          return;
        } catch {
          updateData(emptyPayload(today, "waiting", "今日数据等待更新。"), "实时接口不可用");
          loadError.value = "今日数据等待更新。";
          return;
        }
      }
      if (phase === "settling") {
        updateData(emptyPayload(today, "settling", "今日数据等待更新。"), "等待收盘固化");
        loadError.value = "今日数据等待更新。";
        return;
      }
      try {
        const latest = await fetchJson("./data/latest.json");
        if (latest?.meta?.trade_date === today) {
          updateData(latest, "收盘锁定");
          loadError.value = "";
        } else {
          updateData(emptyPayload(today, "waiting", "今日数据等待更新。"), "今日等待更新");
          loadError.value = "今日数据等待更新。";
        }
      } catch {
        updateData(emptyPayload(today, "waiting", "今日数据等待更新。"), "今日等待更新");
        loadError.value = "今日数据等待更新。";
      }
    }

    async function loadDataByDate(date) {
      if (!date) return;
      selectedDate.value = date;
      setUrlDate(date);
      isDateLoading.value = true;
      loadError.value = "";
      try {
        if (date < minDateText.value || date > todayText.value) {
          updateData(emptyPayload(date, "missing", "暂无历史数据"), "暂无历史数据");
          loadError.value = "暂无历史数据";
          return;
        }
        if (!(await isTradingDay(date))) {
          updateData(emptyPayload(date, "non_trading", "当天非交易日，无数据"), "当天非交易日");
          loadError.value = "当天非交易日，无数据";
          return;
        }
        if (date === todayText.value) {
          await loadToday();
          return;
        }
        updateData(emptyPayload(date, "loading", "数据切换中"), "数据切换中");
        const payload = await fetchJson(`./data/history/${date}.json`);
        updateData(payload, "历史数据");
      } catch (error) {
        updateData(emptyPayload(date, "missing", "暂无历史数据"), "暂无历史数据");
        loadError.value = "暂无历史数据";
        console.warn(error);
      } finally {
        isDateLoading.value = false;
      }
    }

    async function loadInitial() {
      const urlDate = new URL(location.href).searchParams.get("date");
      await loadDataByDate(urlDate || todayText.value);
    }

    const limitUps = computed(() => (data.value.limit_ups || []).map(normalizeStock));
    const brokenWatch = computed(() => (data.value.broken_limits || []).map(normalizeStock));
    const limitDowns = computed(() => (data.value.limit_downs || []).map(normalizeStock));
    const allStats = computed(() => data.value.stats || []);
    const statsByCode = computed(() => new Map(allStats.value.map((row) => [row.code, row])));

    const navItems = computed(() => [
      { key: "overview", label: "首页概览", target: "overview-section" },
      { key: "limitups", label: `涨停汇总(${limitUps.value.length})`, target: "limitups-section" },
      { key: "broken", label: `炸板汇总(${brokenWatch.value.length})`, target: "broken-section" },
      { key: "down", label: `跌停汇总(${limitDowns.value.length})`, target: "down-section" },
    ]);

    function boardAllowed(stock) { return !selectedBoards.value.length || selectedBoards.value.includes(stock.market_board || inferMarketBoard(stock.code)); }
    function searchAllowed(stock) {
      const term = String(query.value || "").trim().toLowerCase();
      return !term || String(stock.code || "").toLowerCase().includes(term) || String(stock.name || "").toLowerCase().includes(term);
    }
    function filteredRows(rows, type) {
      return rows.filter((stock) => {
        const board = numberValue(stock.consecutive_days, 1);
        const okBoard = type !== "limitups" || boardFilter.value === "all" || (boardFilter.value === "5" ? board >= 5 : board === Number(boardFilter.value));
        return okBoard && boardAllowed(stock) && searchAllowed(stock);
      });
    }
    function sortedRows(rows, type) { return [...filteredRows(rows, type)].sort((a, b) => numberValue(b.consecutive_days, 1) - numberValue(a.consecutive_days, 1)); }

    const tableSections = computed(() => [
      { id: "limitups-section", key: "limitups", title: `收盘涨停股票(${limitUps.value.length})`, rows: sortedRows(limitUps.value, "limitups"), sortKey: sortKeys.value.limitups },
      { id: "broken-section", key: "broken", title: `收盘炸板股票(${brokenWatch.value.length})`, rows: sortedRows(brokenWatch.value, "broken"), sortKey: sortKeys.value.broken },
      { id: "down-section", key: "down", title: `收盘跌停股票(${limitDowns.value.length})`, rows: sortedRows(limitDowns.value, "down"), sortKey: sortKeys.value.down },
    ]);

    function rankByField(rows, field) {
      const map = new Map();
      for (const stock of rows) {
        const name = field === "industry" ? normalizeIndustry(stock[field]) || "其他" : stock[field] || "其他";
        map.set(name, (map.get(name) || 0) + 1);
      }
      return [...map.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
    }
    const industryRank = computed(() => rankByField(limitUps.value, "industry"));
    const themeRank = computed(() => rankByField(limitUps.value, "theme"));
    const marketBoardRank = computed(() => rankByField(limitUps.value, "market_board"));
    const highestBoardRank = computed(() => [...limitUps.value].sort((a, b) => numberValue(b.consecutive_days, 1) - numberValue(a.consecutive_days, 1)).slice(0, 6));
    const boardDistribution = computed(() => [1, 2, 3, 4, 5].map((n) => {
      const count = limitUps.value.filter((s) => n === 5 ? numberValue(s.consecutive_days, 1) >= 5 : numberValue(s.consecutive_days, 1) === n).length;
      return { label: n === 1 ? "首板" : n === 5 ? "5板+" : `${n}连板`, count, width: Math.max(6, count ? count * 8 : 6) };
    }));
    const totalLimitUps = computed(() => numberValue(data.value.sentiment.limit_up_count, limitUps.value.length));
    const brokenCount = computed(() => numberValue(data.value.sentiment.broken_limit_count, brokenWatch.value.length));
    const downCount = computed(() => numberValue(data.value.sentiment.limit_down_count, limitDowns.value.length));
    const highestBoard = computed(() => Math.max(0, ...limitUps.value.map((s) => numberValue(s.consecutive_days, 1))));
    const brokenRate = computed(() => totalLimitUps.value + brokenCount.value ? ((brokenCount.value / (totalLimitUps.value + brokenCount.value)) * 100).toFixed(1) : "0.0");
    const metricCards = computed(() => [
      { label: realtimeStatus.value === "盘中实时" ? "盘中涨停" : "收盘涨停", value: totalLimitUps.value, unit: "只", caption: data.value.meta.trade_date || "自动更新" },
      { label: "连板股", value: limitUps.value.filter((s) => numberValue(s.consecutive_days, 1) >= 2).length, unit: "只", caption: "2板及以上" },
      { label: "炸板股", value: brokenCount.value, unit: "只", caption: "盘中打开涨停" },
      { label: "跌停股", value: downCount.value, unit: "只", caption: "跌停池同步统计" },
      { label: "炸板率", value: `${brokenRate.value}%`, unit: "", caption: "炸板 / 涨停炸板合计" },
      { label: "市场最高板", value: highestBoard.value, unit: "板", caption: "情绪观察" },
    ]);
    const dataScopeText = computed(() => {
      if (realtimeStatus.value === "当天非交易日") return `当前选择 ${data.value.meta.trade_date}，当天非交易日，无数据。`;
      if (realtimeStatus.value === "暂无历史数据") return `当前选择 ${data.value.meta.trade_date}，暂无历史数据。`;
      if (realtimeStatus.value === "今日等待更新") return `当前显示 ${todayText.value} 今日空数据，不沿用前一个交易日数据。`;
      return `当前显示 ${data.value.meta.trade_date || todayText.value} 数据。`;
    });
    const dataCompleteness = computed(() => [{ label: "涨停池", count: limitUps.value.length, ok: limitUps.value.length > 0 }, { label: "炸板池", count: brokenWatch.value.length, ok: brokenWatch.value.length > 0 }, { label: "跌停池", count: limitDowns.value.length, ok: limitDowns.value.length > 0 }]);

    function formatMoney(value) { const n = numberValue(value); if (!n) return "--"; return n >= 100000000 ? `${(n / 100000000).toFixed(2)}亿` : n >= 10000 ? `${(n / 10000).toFixed(0)}万` : String(n); }
    function formatPercent(value) { return `${numberValue(value).toFixed(2)}%`; }
    function formatText(value) { return value ?? "--"; }
    function stockStats(stock) { return statsByCode.value.get(stock.code) || {}; }
    function detailValue(value) { return value === null || value === undefined || value === "" ? "数据积累中" : value; }
    function rowClass(stock, sectionKey) { return sectionKey === "down" || numberValue(stock.change_pct) < 0 ? "down-text" : "up-text"; }
    function clearFilters() { query.value = ""; boardFilter.value = "all"; selectedBoards.value = []; }
    function setSort(section, value) { sortKeys.value = { ...sortKeys.value, [section]: value }; }
    function exportRows() {}
    function scrollToSection(item) { activeSection.value = item.key; document.getElementById(item.target)?.scrollIntoView({ behavior: "smooth", block: "start" }); }
    function panelStyle(id) {
      const size = panelSizes.value[id] || {};
      return {
        width: size.width ? `${size.width}px` : undefined,
        height: size.height ? `${size.height}px` : undefined,
      };
    }
    function loadPanelSizes() {
      const next = {};
      const ids = ["feedback-panel", ...tableSections.value.map((item) => item.id)];
      for (const id of ids) {
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
    function showStockPopover(stock, event) { hoveredStock.value = normalizeStock(stock); popoverStyle.value = { left: `${Math.min(event.clientX + 14, innerWidth - 340)}px`, top: `${Math.min(event.clientY + 14, innerHeight - 240)}px` }; }
    function hideStockPopover() { hoveredStock.value = null; }
    function toggleRefresh() { refreshPaused.value = !refreshPaused.value; if (!refreshPaused.value) loadToday(); }

    function readFeedbacks() {
      try {
        const rows = JSON.parse(localStorage.getItem(feedbackStorageKey) || "[]");
        return Array.isArray(rows)
          ? rows.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""))).slice(0, 50)
          : [];
      } catch {
        return [];
      }
    }
    function writeFeedbacks(rows) {
      localStorage.setItem(feedbackStorageKey, JSON.stringify((rows || []).slice(0, 50)));
    }
    function loadFeedbacks() {
      feedbackItems.value = readFeedbacks();
      feedbackError.value = "";
    }
    function openFeedbackModal() {
      feedbackModalOpen.value = true;
      feedbackForm.value = { displayName: "", content: "" };
      feedbackError.value = "";
      feedbackNotice.value = "";
    }
    function closeFeedbackModal() {
      if (!feedbackSubmitting.value) feedbackModalOpen.value = false;
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
        const item = {
          id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          display_name: feedbackForm.value.displayName.trim() || "匿名用户",
          content,
          like_count: 0,
          created_at: new Date().toISOString(),
          local: true,
        };
        const next = [item, ...readFeedbacks()];
        writeFeedbacks(next);
        feedbackItems.value = next;
        feedbackModalOpen.value = false;
        feedbackForm.value = { displayName: "", content: "" };
        feedbackError.value = "";
        feedbackNotice.value = "提交成功。";
      } catch (error) {
        feedbackError.value = "反馈提交失败";
        feedbackNotice.value = "";
        console.warn(error);
      } finally {
        feedbackSubmitting.value = false;
      }
    }
    function likeFeedback(item) {
      const likedKey = `fenggu-liked:${item.id}`;
      if (localStorage.getItem(likedKey)) return;
      const next = readFeedbacks().map((row) =>
        row.id === item.id ? { ...row, like_count: numberValue(row.like_count) + 1 } : row,
      );
      writeFeedbacks(next);
      feedbackItems.value = next;
      localStorage.setItem(likedKey, "1");
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
    function deleteFeedback(item) {
      if (!adminToken.value || !window.confirm("确认删除这条反馈？")) return;
      const next = readFeedbacks().filter((row) => row.id !== item.id);
      writeFeedbacks(next);
      feedbackItems.value = next;
    }
    function formatFeedbackTime(value) { return value ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }) : "--"; }

    onMounted(async () => { loadPanelSizes(); await loadInitial(); loadFeedbacks(); await nextTick(); timer = setInterval(() => { if (selectedDate.value === todayText.value && !refreshPaused.value) loadToday(); }, refreshMs); });
    onBeforeUnmount(() => { if (timer) clearInterval(timer); if (observer) observer.disconnect(); });

    return { data, loadError, isDateLoading, query, selectedBoards, marketBoards, boardFilter, sortKeys, selectedDate, activeSection, navItems, todayText, minDateText, metricCards, dataScopeText, realtimeStatus, lastRefreshAt, refreshPaused, themeNotice, limitStatsHelp, tableSections, boardDistribution, highestBoardRank, dataCompleteness, industryRank, themeRank, marketBoardRank, hoveredStock, popoverStyle, feedbackItems, feedbackError, feedbackNotice, feedbackModalOpen, feedbackSubmitting, feedbackForm, isAdminMode, formatMoney, formatPercent, formatText, formatFeedbackTime, stockStats, detailValue, rowClass, clearFilters, setSort, exportRows, loadDataByDate, scrollToSection, panelStyle, startResize, showStockPopover, hideStockPopover, toggleRefresh, openFeedbackModal, closeFeedbackModal, submitFeedback, likeFeedback, toggleAdminMode, deleteFeedback };
  },
}).mount("#app");
