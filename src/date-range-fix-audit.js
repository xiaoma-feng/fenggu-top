(function () {
  const PATCH_INTERVAL_MS = 5000;
  const REFRESH_MS = 60000;
  const RANGE_MONTHS = 3;
  let holidaysCache = null;
  let manualHistoryLocked = false;
  let lastRealtimeRefreshAt = 0;

  function todayText() {
    return new Date().toLocaleDateString("zh-CN", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).replaceAll("/", "-");
  }

  function addMonths(dateText, offset) {
    const date = new Date(`${dateText}T00:00:00+08:00`);
    date.setMonth(date.getMonth() + offset);
    return date.toLocaleDateString("zh-CN", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).replaceAll("/", "-");
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
    const date = new Date(`${dateText}T00:00:00+08:00`);
    const day = date.getDay();
    if (day === 0 || day === 6) return false;
    const holidays = await loadHolidays();
    const year = dateText.slice(0, 4);
    return !(holidays[year] || []).includes(dateText);
  }

  function shanghaiMinutes() {
    const parts = new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(new Date());
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

  function emptyPayload(dateText, status, message) {
    return {
      meta: {
        site_name: "峰股top",
        trade_date: dateText,
        updated_at: new Date().toLocaleString("zh-CN", {
          timeZone: "Asia/Shanghai",
          hour12: false,
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        }).replaceAll("/", "-"),
        data_status: status,
        source: "frontend-date-picker",
        notes: [message || "今日数据等待更新，交易时间内按实时接口逐步刷新，不使用前一交易日数据冒充。"],
      },
      sentiment: {
        limit_up_count: 0,
        broken_limit_count: 0,
        limit_down_count: 0,
        highest_board: 0,
        first_board_count: 0,
        multi_board_count: 0,
        broken_rate: 0,
      },
      rankings: {
        industry_limit_rank: [],
        theme_limit_rank: [],
        market_board_limit_rank: [],
      },
      limit_ups: [],
      broken_limits: [],
      limit_downs: [],
      strong_stocks: [],
      sub_new_stocks: [],
      stats: [],
    };
  }

  async function fetchJson(path) {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  function getVm() {
    return document.querySelector("#app")?.__vue_app__?._instance?.proxy;
  }

  function setUrlDate(dateText) {
    const url = new URL(window.location.href);
    url.searchParams.set("date", dateText);
    window.history.replaceState({}, "", url);
  }

  function setData(vm, payload, status, errorText) {
    vm.data = payload;
    vm.selectedDate = payload.meta.trade_date;
    vm.realtimeStatus = status;
    vm.loadError = errorText || "";
    vm.lastRefreshAt = new Date().toLocaleTimeString("zh-CN", {
      timeZone: "Asia/Shanghai",
      hour12: false,
    });
  }

  function installDatePicker(vm) {
    const picker = document.querySelector(".date-picker");
    if (!picker) return;
    picker.querySelectorAll("select, option, .date-select-wrap").forEach((node) => node.remove());
    let input = picker.querySelector("#datePicker");
    if (!input) {
      input = document.createElement("input");
      input.id = "datePicker";
      input.type = "date";
      picker.appendChild(input);
    }
    const today = todayText();
    input.type = "date";
    input.min = addMonths(today, -RANGE_MONTHS);
    input.max = today;
    input.value = new URL(window.location.href).searchParams.get("date") || vm.selectedDate || today;
    input.style.color = "#edf4ff";
    input.style.background = "#0c1425";
    input.onchange = () => loadSelectedDate(vm, input.value);

    const note = document.querySelector(".date-range-note") || document.querySelector(".date-picker em");
    if (note) note.textContent = "近3个月";
  }

  function hideTopTabs() {
    document.querySelectorAll(".topbar .tabs, .tabs").forEach((tabs) => tabs.remove());
  }

  async function loadSelectedDate(vm, dateText) {
    const today = todayText();
    const minDate = addMonths(today, -RANGE_MONTHS);
    if (!dateText) return;
    setUrlDate(dateText);
    vm.selectedDate = dateText;
    vm.loadError = "";
    if (dateText < minDate || dateText > today) {
      setData(vm, emptyPayload(dateText, "missing", "暂无历史数据"), "暂无历史数据", "暂无历史数据");
      return;
    }
    const tradingDay = await isTradingDay(dateText);
    if (!tradingDay) {
      setData(vm, emptyPayload(dateText, "non_trading", "当天非交易日，无数据"), "当天非交易日", "当天非交易日，无数据");
      return;
    }
    if (dateText === today) {
      manualHistoryLocked = false;
      await refreshToday(vm, true);
      return;
    }
    manualHistoryLocked = true;
    setData(vm, emptyPayload(dateText, "loading", "数据切换中"), "数据切换中", "");
    try {
      const payload = await fetchJson(`./data/history/${dateText}.json`);
      setData(vm, payload, "历史数据", "");
    } catch (error) {
      setData(vm, emptyPayload(dateText, "missing", "暂无历史数据"), "暂无历史数据", "暂无历史数据");
      console.warn(error);
    }
  }

  async function correctInitialDate(vm) {
    const today = todayText();
    const input = document.querySelector("#datePicker");
    const urlDate = new URL(window.location.href).searchParams.get("date");
    if (urlDate && input && input.value !== urlDate) input.value = urlDate;
    if (urlDate && !vm.__fengguInitialDateLoaded) {
      vm.__fengguInitialDateLoaded = true;
      await loadSelectedDate(vm, urlDate);
      return;
    }
    if (!urlDate && input && !input.value) input.value = today;
  }

  async function refreshToday(vm, force) {
    const now = Date.now();
    if (!force && now - lastRealtimeRefreshAt < REFRESH_MS) return;
    lastRealtimeRefreshAt = now;
    const today = todayText();
    if ((vm.selectedDate || today) !== today || manualHistoryLocked) return;
    const phase = marketPhase();
    if (phase === "intraday") {
      try {
        const payload = await fetchJson(`./api/realtime?date=${today.replaceAll("-", "")}`);
        setData(vm, payload, "盘中实时", "");
      } catch (error) {
        setData(vm, emptyPayload(today, "realtime_unavailable"), "实时接口不可用", "实时接口暂时不可用，当前显示今日空数据，不使用前一交易日数据冒充。");
      }
      return;
    }
    if (phase === "settling") {
      setData(vm, emptyPayload(today, "settling"), "等待收盘固化", "今日数据等待更新");
      return;
    }
    try {
      const payload = await fetchJson("./data/latest.json");
      if (payload?.meta?.trade_date === today) {
        setData(vm, payload, "收盘锁定", "");
      } else {
        setData(vm, emptyPayload(today, "waiting_today"), "今日等待更新", "今日数据等待更新");
      }
    } catch (error) {
      setData(vm, emptyPayload(today, "waiting_today"), "今日等待更新", "今日数据等待更新");
    }
  }

  async function run() {
    const vm = getVm();
    if (!vm) return;
    hideTopTabs();
    installDatePicker(vm);
    await correctInitialDate(vm);
    await refreshToday(vm);
  }

  run();
  window.addEventListener("load", run);
  setInterval(run, PATCH_INTERVAL_MS);
  setInterval(() => {
    const vm = getVm();
    if (vm) refreshToday(vm);
  }, REFRESH_MS);
})();
