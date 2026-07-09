(function () {
  const PATCH_INTERVAL_MS = 5000;
  const REFRESH_MS = 60000;
  const FEEDBACK_KEY = "fenggu-feedbacks";
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
    if ((minutes >= 570 && minutes < 690) || (minutes >= 780 && minutes < 900)) return "intraday";
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

  function readFeedbacks() {
    try {
      const rows = JSON.parse(localStorage.getItem(FEEDBACK_KEY) || "[]");
      return Array.isArray(rows)
        ? rows.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""))).slice(0, 50)
        : [];
    } catch {
      return [];
    }
  }

  function writeFeedbacks(rows) {
    localStorage.setItem(FEEDBACK_KEY, JSON.stringify((rows || []).slice(0, 50)));
  }

  function createFeedback(content, displayName) {
    return {
      id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      display_name: displayName || "匿名用户",
      content,
      like_count: 0,
      created_at: new Date().toISOString(),
      local: true,
    };
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
    if (!wrap) return;
    let input = wrap.querySelector('input[type="date"]');
    if (!input) {
      wrap.innerHTML = "";
      input = document.createElement("input");
      input.type = "date";
      input.setAttribute("aria-label", "选择历史日期");
      input.addEventListener("change", () => loadSelectedDate(vm, input.value));
      wrap.appendChild(input);
    }
    input.max = todayText();
    if (!manualHistoryLocked) input.value = todayText();

    const oldEm = document.querySelector(".date-picker em");
    if (oldEm) {
      oldEm.className = "date-range-note";
      oldEm.textContent = "历史日期";
    }
    const note = document.querySelector(".date-range-note");
    if (note) note.textContent = "历史日期";
  }

  function hideTopTabs() {
    document.querySelectorAll(".topbar .tabs, .tabs").forEach((tabs) => tabs.remove());
  }

  function fixFeedbackCopy() {
    const button = document.querySelector(".feedback-open");
    if (button) button.textContent = "提交反馈";
    const empty = document.querySelector(".feedback-empty");
    if (empty) empty.textContent = "暂无反馈。";
  }

  function fixScopeCopy() {
    const scope = document.querySelector(".scope-notice span");
    if (scope && scope.textContent.includes("近 3 个月任意日期")) {
      scope.textContent = scope.textContent.replace("近 3 个月任意日期", "任意历史日期");
    }
  }

  function installFeedbackFallback(vm) {
    if (vm.__fengguFeedbackFallbackInstalled) return;
    vm.__fengguFeedbackFallbackInstalled = true;
    vm.feedbackItems = readFeedbacks();
    vm.feedbackError = "";
    vm.feedbackNotice = "";

    vm.loadFeedbacks = async () => {
      vm.feedbackItems = readFeedbacks();
      vm.feedbackError = "";
    };

    vm.openFeedbackModal = () => {
      vm.feedbackModalOpen = true;
      vm.feedbackForm = { displayName: "", content: "" };
      vm.feedbackError = "";
      vm.feedbackNotice = "";
    };

    vm.submitFeedback = async () => {
      const content = String(vm.feedbackForm?.content || "").trim();
      if (!content) {
        vm.feedbackError = "请先填写反馈内容";
        vm.feedbackNotice = "";
        return;
      }
      const feedback = createFeedback(content, String(vm.feedbackForm?.displayName || "").trim());
      const next = [feedback, ...readFeedbacks()];
      writeFeedbacks(next);
      vm.feedbackItems = next;
      vm.feedbackForm = { displayName: "", content: "" };
      vm.feedbackModalOpen = false;
      vm.feedbackError = "";
      vm.feedbackNotice = "提交成功。";
    };

    vm.likeFeedback = async (item) => {
      const likedKey = `fenggu-liked:${item.id}`;
      if (localStorage.getItem(likedKey)) return;
      const next = readFeedbacks().map((row) =>
        row.id === item.id ? { ...row, like_count: Number(row.like_count || 0) + 1 } : row,
      );
      writeFeedbacks(next);
      localStorage.setItem(likedKey, "1");
      vm.feedbackItems = next;
      vm.feedbackError = "";
    };

    vm.deleteFeedback = async (item) => {
      const next = readFeedbacks().filter((row) => row.id !== item.id);
      writeFeedbacks(next);
      vm.feedbackItems = next;
      vm.feedbackError = "";
    };
  }

  async function loadSelectedDate(vm, dateText) {
    const today = todayText();
    if (!dateText) return;
    if (dateText === today) {
      manualHistoryLocked = false;
      setData(vm, emptyPayload(today, "waiting_today"), "今日等待更新", "今日数据等待更新。");
      refreshToday(vm, true);
      return;
    }
    try {
      manualHistoryLocked = true;
      const payload = await fetchJson(`./data/history/${dateText}.json`);
      setData(vm, payload, "历史数据", "");
    } catch {
      const message = isWeekend(dateText) ? "当天非交易日，无数据。" : "暂无历史数据。";
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
    if (manualHistoryLocked) return;
    if (vm.data?.meta?.trade_date !== today || vm.selectedDate !== today) {
      setData(vm, emptyPayload(today, "waiting_today"), "今日等待更新", "今日数据等待更新。");
    }
    if (input) input.value = today;
  }

  async function refreshToday(vm, force) {
    const now = Date.now();
    if (!force && now - lastRealtimeRefreshAt < REFRESH_MS) return;
    lastRealtimeRefreshAt = now;
    const today = todayText();
    if (manualHistoryLocked) return;
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
      } catch {
        setData(vm, emptyPayload(today, "realtime_unavailable"), "实时接口不可用", "实时接口暂时不可用，当前显示今日空数据，不使用前一交易日数据冒充。");
      }
      return;
    }

    if (phase === "settling") {
      setData(vm, emptyPayload(today, "settling"), "等待收盘固化", "今日数据等待更新。");
      return;
    }

    try {
      const payload = await fetchJson("./data/latest.json");
      if (payload?.meta?.trade_date === today) {
        setData(vm, payload, "收盘锁定", "");
      } else {
        setData(vm, emptyPayload(today, "waiting_today"), "今日等待更新", "今日数据等待更新。");
      }
    } catch {
      setData(vm, emptyPayload(today, "waiting_today"), "今日等待更新", "今日数据等待更新。");
    }
  }

  function run() {
    const vm = getVm();
    if (!vm) return;
    hideTopTabs();
    fixFeedbackCopy();
    fixScopeCopy();
    installFeedbackFallback(vm);
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
