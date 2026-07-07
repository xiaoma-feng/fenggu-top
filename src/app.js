import { createApp, computed, ref, onMounted } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";

const emptyData = {
  meta: {},
  sentiment: {},
  limit_ups: [],
  broken_limits: [],
  limit_downs: [],
  strong_stocks: [],
  sub_new_stocks: [],
  stats: [],
};

function numberValue(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeText(value) {
  return String(value ?? "").trim().toLowerCase();
}

function percent(value) {
  const parsed = numberValue(value);
  return `${parsed.toFixed(2)}%`;
}

createApp({
  setup() {
    const data = ref(window.__FENGGU_FALLBACK_DATA__ || emptyData);
    const loadError = ref("");
    const query = ref("");
    const statQuery = ref("");
    const boardFilter = ref("all");
    const sortKey = ref("first_limit_time");
    const activeSection = ref("overview");
    const navItems = [
      { key: "overview", label: "首页概览", target: "overview-section" },
      { key: "limitups", label: "今日涨停", target: "limitups-section" },
      { key: "stats", label: "个股统计", target: "stats-section" },
      { key: "boards", label: "连板统计", target: "boards-section" },
      { key: "rankings", label: "排行榜", target: "rankings-section" },
      { key: "data", label: "数据中心", target: "data-section" },
    ];

    async function loadData() {
      if (window.location.protocol === "file:") {
        data.value = window.__FENGGU_FALLBACK_DATA__ || emptyData;
        return;
      }

      try {
        const response = await fetch("./data/latest.json", { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        data.value = await response.json();
      } catch (error) {
        loadError.value = "未能读取 data/latest.json，当前显示内置演示数据。";
        console.warn(error);
        data.value = window.__FENGGU_FALLBACK_DATA__ || emptyData;
      }
    }

    onMounted(loadData);

    const limitUps = computed(() => data.value.limit_ups || []);
    const brokenWatch = computed(() => data.value.broken_limits || []);
    const limitDowns = computed(() => data.value.limit_downs || []);
    const strongStocks = computed(() => data.value.strong_stocks || []);
    const subNewStocks = computed(() => data.value.sub_new_stocks || []);
    const allStats = computed(() => data.value.stats || []);
    const totalLimitUps = computed(() => numberValue(data.value.sentiment.limit_up_count, limitUps.value.length));
    const highestBoard = computed(() => Math.max(0, ...limitUps.value.map((item) => numberValue(item.consecutive_days, 1))));
    const brokenRate = computed(() => {
      const broken = numberValue(data.value.sentiment.broken_limit_count, brokenWatch.value.length);
      const total = totalLimitUps.value + broken;
      return total ? ((broken / total) * 100).toFixed(1) : "0.0";
    });

    const metricCards = computed(() => [
      { label: "今日涨停", value: totalLimitUps.value, unit: "只", caption: data.value.meta.trade_date || "收盘后自动更新" },
      {
        label: "连板股",
        value: numberValue(
          data.value.sentiment.multi_board_count,
          limitUps.value.filter((item) => numberValue(item.consecutive_days, 1) >= 2).length,
        ),
        unit: "只",
        caption: "2板及以上",
      },
      { label: "炸板股", value: numberValue(data.value.sentiment.broken_limit_count, brokenWatch.value.length), unit: "只", caption: "盘中打开涨停" },
      { label: "今日跌停", value: numberValue(data.value.sentiment.limit_down_count, limitDowns.value.length), unit: "只", caption: "跌停池同步统计" },
      { label: "炸板率", value: `${brokenRate.value}%`, unit: "", caption: "炸板 / 涨停炸板合计" },
      {
        label: "晋级率",
        value: `${numberValue(data.value.sentiment.promotion_rate).toFixed(1)}%`,
        unit: "",
        caption: data.value.sentiment.previous_trade_date ? `基于 ${data.value.sentiment.previous_trade_date}` : "昨日涨停今日连板",
      },
      { label: "市场最高板", value: highestBoard.value, unit: "板", caption: highestBoard.value >= 5 ? "高位活跃" : "情绪观察" },
    ]);

    const filteredLimitUps = computed(() => {
      const term = normalizeText(query.value);
      return limitUps.value.filter((stock) => {
        const board = numberValue(stock.consecutive_days, 1);
        const matchesBoard =
          boardFilter.value === "all" ||
          (boardFilter.value === "5" ? board >= 5 : board === Number(boardFilter.value));
        const matchesQuery =
          !term ||
          normalizeText(stock.code).includes(term) ||
          normalizeText(stock.name).includes(term);
        return matchesBoard && matchesQuery;
      });
    });

    const sortedLimitUps = computed(() => {
      const rows = [...filteredLimitUps.value];
      const sorters = {
        first_limit_time: (a, b) => String(a.first_limit_time || "99:99:99").localeCompare(String(b.first_limit_time || "99:99:99")),
        consecutive_days: (a, b) => numberValue(b.consecutive_days, 1) - numberValue(a.consecutive_days, 1),
        seal_amount: (a, b) => numberValue(b.seal_amount) - numberValue(a.seal_amount),
        turnover_amount: (a, b) => numberValue(b.turnover_amount) - numberValue(a.turnover_amount),
        turnover_rate: (a, b) => numberValue(b.turnover_rate) - numberValue(a.turnover_rate),
        open_times: (a, b) => numberValue(b.open_times) - numberValue(a.open_times),
      };
      return rows.sort(sorters[sortKey.value] || sorters.first_limit_time);
    });

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

    const statsByCode = computed(() => {
      const map = new Map();
      for (const row of data.value.stats || []) {
        map.set(row.code, row);
      }
      return map;
    });

    const enrichedStocks = computed(() =>
      limitUps.value.map((stock) => ({
        ...stock,
        stats: statsByCode.value.get(stock.code) || {
          limit_count_7d: 0,
          limit_count_30d: 0,
          limit_count_1y: 0,
          total_limit_count: 0,
          max_consecutive_days: numberValue(stock.consecutive_days, 1),
          last_limit_date: data.value.meta.trade_date,
        },
      })),
    );

    const selectedStock = computed(() => {
      const term = normalizeText(statQuery.value || query.value);
      const todayMatch = !term ? enrichedStocks.value[0] : enrichedStocks.value.find(
        (stock) => normalizeText(stock.code).includes(term) || normalizeText(stock.name).includes(term),
      );
      if (todayMatch) return todayMatch;
      const statMatch = allStats.value.find(
        (stock) => normalizeText(stock.code).includes(term) || normalizeText(stock.name).includes(term),
      );
      return statMatch ? { ...statMatch, stats: statMatch } : null;
    });

    const highestBoardRank = computed(() =>
      [...enrichedStocks.value]
        .sort((a, b) => numberValue(b.consecutive_days, 1) - numberValue(a.consecutive_days, 1))
        .slice(0, 6),
    );

    const thirtyDayRank = computed(() =>
      [...allStats.value]
        .sort((a, b) => numberValue(b.limit_count_30d) - numberValue(a.limit_count_30d))
        .slice(0, 6),
    );

    const promotedStocks = computed(() => data.value.sentiment.promoted_stocks || []);

    const dataCompleteness = computed(() => [
      { label: "涨停池", count: limitUps.value.length, ok: limitUps.value.length > 0 },
      { label: "炸板池", count: brokenWatch.value.length, ok: brokenWatch.value.length > 0 },
      { label: "跌停池", count: limitDowns.value.length, ok: limitDowns.value.length > 0 },
      { label: "强势股池", count: strongStocks.value.length, ok: strongStocks.value.length > 0 },
      { label: "次新股池", count: subNewStocks.value.length, ok: subNewStocks.value.length > 0 },
      { label: "历史统计", count: allStats.value.length, ok: allStats.value.length > 0 },
    ]);

    const heatMap = computed(() => {
      const counts = new Map();
      for (const stock of limitUps.value) {
        const key = stock.concept || stock.industry || "其他";
        counts.set(key, (counts.get(key) || 0) + 1);
      }
      return [...counts.entries()]
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count)
        .slice(0, 9);
    });

    function formatMoney(value) {
      const amount = numberValue(value);
      if (!amount) return "--";
      if (amount >= 100000000) return `${(amount / 100000000).toFixed(2)}亿`;
      if (amount >= 10000) return `${(amount / 10000).toFixed(0)}万`;
      return String(amount);
    }

    function formatPercent(value) {
      return percent(value);
    }

    function formatReason(stock) {
      return stock.reason || stock.concept || stock.industry || stock.limit_stats || "--";
    }

    function clearFilters() {
      query.value = "";
      boardFilter.value = "all";
      sortKey.value = "first_limit_time";
    }

    function csvCell(value) {
      const text = String(value ?? "").replaceAll('"', '""');
      return `"${text}"`;
    }

    function exportLimitUps() {
      const headers = ["代码", "名称", "涨幅", "最新价", "首次封板", "最后封板", "行业/原因", "成交额", "换手率", "封单金额", "连板", "炸板", "涨停统计"];
      const rows = sortedLimitUps.value.map((stock) => [
        stock.code,
        stock.name,
        formatPercent(stock.change_pct),
        stock.latest_price || "",
        stock.first_limit_time || "",
        stock.last_limit_time || "",
        formatReason(stock),
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
      link.download = `峰股top-涨停汇总-${data.value.meta.trade_date || "latest"}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    }

    function scrollToSection(item) {
      activeSection.value = item.key;
      const target = document.getElementById(item.target);
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    return {
      data,
      loadError,
      query,
      statQuery,
      boardFilter,
      sortKey,
      activeSection,
      navItems,
      metricCards,
      totalLimitUps,
      filteredLimitUps,
      sortedLimitUps,
      boardDistribution,
      selectedStock,
      brokenWatch,
      limitDowns,
      strongStocks,
      subNewStocks,
      highestBoardRank,
      thirtyDayRank,
      promotedStocks,
      dataCompleteness,
      heatMap,
      formatMoney,
      formatPercent,
      formatReason,
      clearFilters,
      exportLimitUps,
      scrollToSection,
    };
  },
}).mount("#app");
