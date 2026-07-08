import { createApp, computed, ref, onMounted, onBeforeUnmount, nextTick } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";

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
const layoutKey = "fenggu-layout:";
const themeNotice = "题材为系统识别，仅供参考";
const limitStatsHelp = "涨停统计格式为 N/M，表示近 M 个交易日内涨停 N 次，例如 6/6 表示近 6 个交易日涨停 6 次。";

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

function inferTheme(stock) {
  if (stock?.theme) return stock.theme;
  const text = [stock?.name, stock?.concept, stock?.industry, stock?.reason, stock?.selected_reason]
    .map((value) => String(value || "").toLowerCase())
    .join(" ");
  const match = themeRules.find(([, keywords]) => keywords.some((keyword) => text.includes(keyword.toLowerCase())));
  return match ? match[0] : "其他";
}

function normalizeStock(stock) {
  return {
    ...stock,
    market_board: stock.market_board || inferMarketBoard(stock.code),
    theme: inferTheme(stock),
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
  if (minutes >= 570 && minutes < 900) return "intraday";
  if (minutes >= 900 && minutes < 930) return "settling";
  return "closed";
}

createApp({
  setup() {
    const data = ref(window.__FENGGU_FALLBACK_DATA__ || emptyData);
    const loadError = ref("");
    const query = ref("");
    const statQuery = ref("");
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
    let refreshTimer = null;
    let observer = null;

    async function fetchJson(path) {
      const response = await fetch(path, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
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
      updateData(payload);
      realtimeStatus.value = "收盘锁定";
    }

    async function loadRealtimeData() {
      if (window.location.protocol === "file:" || refreshPaused.value) return;
      if (historicalDateLocked.value) return;
      try {
        const today = shanghaiDateText().replaceAll("-", "");
        const payload = await fetchJson(`./api/realtime?date=${today}`);
        if ((payload.meta?.data_status && payload.meta.data_status !== "ok") || !(payload.limit_ups || []).length) {
          throw new Error("Realtime payload is empty");
        }
        updateData(payload);
        realtimeStatus.value = marketPhase() === "settling" ? "等待收盘固化" : "盘中实时";
        loadError.value = "";
      } catch (error) {
        if (marketPhase() === "intraday") {
          loadError.value = "实时接口暂时不可用，当前保留上一份可用数据。";
          realtimeStatus.value = "实时接口不可用";
          selectedDate.value = data.value.meta.trade_date || selectedDate.value;
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
      if (phase === "settling" && !historicalDateLocked.value && data.value.meta.trade_date === today) {
        realtimeStatus.value = "等待收盘固化";
        return;
      }
      if (!selectedDate.value || selectedDate.value === today || data.value.meta.trade_date !== selectedDate.value) {
        await loadClosedData();
      }
    }

    async function loadData() {
      try {
        await loadClosedData();
        await refreshForTime();
      } catch (error) {
        loadError.value = "未能读取 data/latest.json，当前显示内置演示数据。";
        console.warn(error);
        updateData(window.__FENGGU_FALLBACK_DATA__ || emptyData);
      }
    }

    async function loadDate(date) {
      if (!date || date === data.value.meta.trade_date) return;
      if (window.location.protocol === "file:") {
        selectedDate.value = data.value.meta.trade_date || "";
        return;
      }
      try {
        loadError.value = "";
        if (date === shanghaiDateText()) {
          historicalDateLocked.value = false;
          selectedDate.value = date;
          await refreshForTime();
          clearFilters();
          return;
        }
        historicalDateLocked.value = true;
        const payload = await fetchJson(`./data/history/${date}.json`);
        updateData(payload);
        selectedDate.value = data.value.meta.trade_date || date;
        realtimeStatus.value = "历史数据";
        clearFilters();
      } catch (error) {
        loadError.value = `未能读取 ${date} 的历史数据。`;
        console.warn(error);
        selectedDate.value = data.value.meta.trade_date || "";
      }
    }

    const limitUps = computed(() => (data.value.limit_ups || []).map(normalizeStock));
    const brokenWatch = computed(() => (data.value.broken_limits || []).map(normalizeStock));
    const limitDowns = computed(() => (data.value.limit_downs || []).map(normalizeStock));
    const allStats = computed(() => data.value.stats || []);
    const statsByCode = computed(() => new Map(allStats.value.map((row) => [row.code, row])));
    const todayText = computed(() => shanghaiDateText());
    const availableDates = computed(() => {
      const dates = data.value.meta.available_dates || [];
      const withCurrent = marketPhase() !== "closed" && !dates.includes(todayText.value) ? [todayText.value, ...dates] : dates;
      return selectedDate.value && !withCurrent.includes(selectedDate.value) ? [selectedDate.value, ...withCurrent] : withCurrent;
    });
    const totalLimitUps = computed(() => numberValue(data.value.sentiment.limit_up_count, limitUps.value.length));
    const brokenCount = computed(() => numberValue(data.value.sentiment.broken_limit_count, brokenWatch.value.length));
    const downCount = computed(() => numberValue(data.value.sentiment.limit_down_count, limitDowns.value.length));
    const isLatestClosedSession = computed(() => data.value.meta.trade_date && data.value.meta.trade_date !== todayText.value);
    const dataScopeText = computed(() => {
      if (realtimeStatus.value === "盘中实时") return `当前显示 ${todayText.value} 盘中实时数据，每 1 分钟自动刷新。`;
      if (realtimeStatus.value === "等待收盘固化") return `当前显示 ${todayText.value} 最后一份盘中数据，15:30 后切换收盘锁定。`;
      if (isLatestClosedSession.value) return `当前显示最近已收盘交易日 ${data.value.meta.trade_date}，交易日 15:30 后更新。`;
      return `当前显示 ${data.value.meta.trade_date || "最新"} 收盘锁定数据。`;
    });

    const navItems = computed(() => [
      { key: "overview", label: "首页概览", target: "overview-section" },
      { key: "limitups", label: `涨停汇总(${limitUps.value.length})`, target: "limitups-section" },
      { key: "broken", label: `炸板汇总(${brokenWatch.value.length})`, target: "broken-section" },
      { key: "down", label: `跌停汇总(${limitDowns.value.length})`, target: "down-section" },
      { key: "stats", label: "个股统计", target: "stats-section" },
      { key: "themes", label: "题材统计", target: "themes-section" },
      { key: "industries", label: "行业统计", target: "industries-section" },
      { key: "data", label: "数据中心", target: "data-section" },
    ]);

    const highestBoard = computed(() => Math.max(0, ...limitUps.value.map((item) => numberValue(item.consecutive_days, 1))));
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
      return !selectedBoards.value.length || selectedBoards.value.includes(stock.market_board || inferMarketBoard(stock.code));
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
        const key = stock[field] || "其他";
        counts.set(key, (counts.get(key) || 0) + 1);
      }
      return [...counts.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count).slice(0, 12);
    }

    const industryRank = computed(() => data.value.rankings.industry_limit_rank || rankByField(limitUps.value, "industry"));
    const themeRank = computed(() => data.value.rankings.theme_limit_rank || rankByField(limitUps.value, "theme"));
    const marketBoardRank = computed(() => data.value.rankings.market_board_limit_rank || rankByField(limitUps.value, "market_board"));
    const highestBoardRank = computed(() => [...limitUps.value].sort((a, b) => numberValue(b.consecutive_days, 1) - numberValue(a.consecutive_days, 1)).slice(0, 6));
    const thirtyDayRank = computed(() => [...allStats.value].sort((a, b) => numberValue(b.limit_count_30d) - numberValue(a.limit_count_30d)).slice(0, 6));
    const promotedStocks = computed(() => data.value.sentiment.promoted_stocks || []);
    const selectedStock = computed(() => {
      const term = normalizeText(statQuery.value || query.value);
      const rows = [...limitUps.value, ...brokenWatch.value, ...limitDowns.value];
      return (!term ? rows[0] : rows.find((stock) => normalizeText(stock.code).includes(term) || normalizeText(stock.name).includes(term))) || null;
    });
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
      for (const item of navItems.value) {
        try {
          const saved = JSON.parse(localStorage.getItem(`${layoutKey}${item.target}`) || "null");
          if (saved) next[item.target] = saved;
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
      const startX = event.clientX;
      const startY = event.clientY;
      const startWidth = panel.offsetWidth;
      const startHeight = panel.offsetHeight;
      function onMove(moveEvent) {
        const current = panelSizes.value[id] || {};
        const next = { ...current };
        if (axis === "x") next.width = Math.max(320, startWidth + moveEvent.clientX - startX);
        if (axis === "y") next.height = Math.max(260, startHeight + moveEvent.clientY - startY);
        panelSizes.value = { ...panelSizes.value, [id]: next };
      }
      function onUp() {
        localStorage.setItem(`${layoutKey}${id}`, JSON.stringify(panelSizes.value[id] || {}));
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      }
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
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
      document.addEventListener("visibilitychange", () => {
        if (!document.hidden) refreshForTime();
      });
    }

    function toggleRefresh() {
      refreshPaused.value = !refreshPaused.value;
      if (!refreshPaused.value) refreshForTime();
    }

    onMounted(async () => {
      loadPanelSizes();
      await loadData();
      await nextTick();
      setupObserver();
      startRefreshTimer();
    });

    onBeforeUnmount(() => {
      if (refreshTimer) window.clearInterval(refreshTimer);
      if (observer) observer.disconnect();
    });

    return {
      data,
      loadError,
      query,
      statQuery,
      selectedBoards,
      marketBoards,
      boardFilter,
      sortKeys,
      selectedDate,
      activeSection,
      navItems,
      availableDates,
      metricCards,
      dataScopeText,
      realtimeStatus,
      lastRefreshAt,
      refreshPaused,
      themeNotice,
      limitStatsHelp,
      tableSections,
      boardDistribution,
      selectedStock,
      highestBoardRank,
      thirtyDayRank,
      promotedStocks,
      dataCompleteness,
      industryRank,
      themeRank,
      marketBoardRank,
      hoveredStock,
      popoverStyle,
      formatMoney,
      formatPercent,
      formatText,
      stockStats,
      detailValue,
      rowClass,
      clearFilters,
      setSort,
      exportRows,
      loadDate,
      scrollToSection,
      panelStyle,
      startResize,
      showStockPopover,
      hideStockPopover,
      toggleRefresh,
    };
  },
}).mount("#app");
