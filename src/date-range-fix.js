(function () {
  const LOOKBACK_DAYS = 92;
  const PATCH_INTERVAL_MS = 5000;

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
        notes: ["今日不使用历史日期冒充。选择无交易日时，涨停、炸板、跌停显示为空。"],
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
      setData(vm, emptyPayload(today, "waiting_today"), "今日等待更新", "");
      return;
    }
    try {
      const payload = await fetchJson(`./data/history/${dateText}.json`);
      setData(vm, payload, "历史数据", "");
    } catch (error) {
      setData(
        vm,
        emptyPayload(dateText, "missing_history"),
        "无交易数据",
        `${dateText} 没有可用的交易数据。若是周末或节假日，涨停、炸板、跌停会显示为空。`
      );
    }
  }

  function correctToday(vm) {
    const today = todayText();
    const input = document.querySelector('.date-select-wrap input[type="date"]');
    if (input && input.value !== vm.selectedDate) input.value = vm.selectedDate || today;
    if ((vm.selectedDate || today) === today && vm.data?.meta?.trade_date !== today) {
      setData(vm, emptyPayload(today, "waiting_today"), "今日等待更新", "");
      if (input) input.value = today;
    }
  }

  function run() {
    const vm = getVm();
    if (!vm) return;
    installDatePicker(vm);
    correctToday(vm);
  }

  run();
  window.addEventListener("load", run);
  setInterval(run, PATCH_INTERVAL_MS);
})();
