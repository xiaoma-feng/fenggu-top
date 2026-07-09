(function () {
  const LOOKBACK_DAYS = 92;
  const PATCH_INTERVAL_MS = 5000;
  const REFRESH_MS = 60000;
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

  function addDays(dateText, days) {
    const date = new Date(`${dateText}T00:00:00+08:00`);
    date.setDate(date.getDate() + days);
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
    if (minutes >= 570 && minutes < 900) return "intraday";
    if (minutes >= 900 && minutes < 930) return "settling";
    return "closed";
  }

  function emptyPayload(dateText, status) {
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
        source: "akshare",
        notes: ["今日数据等待更新，交易时间内按实时接口逐步刷新，不使用前一交易日数据冒充。"],
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
    const wrap = document.querySelector(".date-select-wrap");
    if (!wrap || wrap.querySelector('input[type="date"]')) return;
    wrap.innerHTML = "";
    const input = document.createElement("input");
    input.type = "date";
    input.setAttribute("aria-label", "选择历史日期");
    input.min = addDays(todayText(), -LOOKBACK_DAYS);
    input.max = todayText();
    input.value = vm.selectedDate || todayText();
    input.addEventListener("change", () => loadSelectedDate(vm, input.value));
    wrap.appendChild(input);

    const oldEm = document.querySelector(".date-picker em");
    if (oldEm) {
      oldEm.className = "date-range-note";
      oldEm.textContent = "近3个月";
    }
  }

  async function loadSelectedDate(vm, dateText) {
    const today = todayText();
    if (!dateText) return;
    if (dateText === today) {
      manualHistoryLocked = false;
      setData(vm, emptyPayload(today, "waiting_today"), "今日等待更新", "");
      refreshToday(vm);
      return;
    }
    try {
      manualHistoryLocked = true;
      const payload = await fetchJson(`./data/history/${dateText}.json`);
      setData(vm, payload, "历史数据", "");
    } catch (error) {
      const message = isWeekend(dateText) ? "当天非交易日，无数据" : "暂无历史数据";
      setData(
        vm,
        emptyPayload(dateText, "missing_history"),
        isWeekend(dateText) ? "当天非交易日" : "暂无历史数据",
        message
      );
    }
  }

  function correctToday(vm) {
    const today = todayText();
    const input = document.querySelector('.date-select-wrap input[type="date"]');
    if (input && input.value !== vm.selectedDate) input.value = vm.selectedDate || today;
    if ((vm.selectedDate || today) === today && vm.data?.meta?.trade_date !== today) {
      manualHistoryLocked = false;
      setData(vm, emptyPayload(today, "waiting_today"), "今日等待更新", "");
      if (input) input.value = today;
    }
  }

  async function refreshToday(vm) {
    const now = Date.now();
    if (now - lastRealtimeRefreshAt < REFRESH_MS) return;
    lastRealtimeRefreshAt = now;
    const today = todayText();
    if ((vm.selectedDate || today) !== today || manualHistoryLocked) return;
    const phase = marketPhase();
    if (phase === "intraday") {
      try {
        const payload = await fetchJson(`./api/realtime?date=${today.replaceAll("-", "")}`);
        setData(
          vm,
          {
            ...emptyPayload(today, "intraday"),
            ...payload,
            meta: {
              ...emptyPayload(today, "intraday").meta,
              ...(payload.meta || {}),
              trade_date: today,
              data_status: payload.meta?.data_status || "intraday",
            },
            sentiment: {
              ...emptyPayload(today, "intraday").sentiment,
              ...(payload.sentiment || {}),
              limit_up_count: (payload.limit_ups || []).length,
              broken_limit_count: (payload.broken_limits || []).length,
              limit_down_count: (payload.limit_downs || []).length,
            },
            limit_ups: payload.limit_ups || [],
            broken_limits: payload.broken_limits || [],
            limit_downs: payload.limit_downs || [],
          },
          "盘中实时",
          ""
        );
      } catch (error) {
        setData(vm, emptyPayload(today, "realtime_unavailable"), "实时接口不可用", "实时接口暂时不可用，当前显示今日空数据，不使用前一交易日数据冒充。");
      }
      return;
    }

    if (phase === "settling") {
      setData(vm, emptyPayload(today, "settling"), "等待收盘固化", "");
      return;
    }

    try {
      const payload = await fetchJson("./data/latest.json");
      if (payload?.meta?.trade_date === today) {
        setData(vm, payload, "收盘锁定", "");
      } else {
        setData(vm, emptyPayload(today, "waiting_today"), "今日等待更新", "");
      }
    } catch (error) {
      setData(vm, emptyPayload(today, "waiting_today"), "今日等待更新", "");
    }
  }

  function run() {
    const vm = getVm();
    if (!vm) return;
    installDatePicker(vm);
    correctToday(vm);
    refreshToday(vm);
  }

  run();
  window.addEventListener("load", run);
  setInterval(run, PATCH_INTERVAL_MS);
  setInterval(() => {
    const vm = getVm();
    if (vm) refreshToday(vm);
  }, REFRESH_MS);
})();
