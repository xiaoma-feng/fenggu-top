(() => {
  const api = "/api/feedbacks";
  let items = [];
  let adminMode = false;
  let adminToken = localStorage.getItem("fenggu-admin-token") || "";
  let panel;
  let list;
  let errorNode;

  function hideOldItems() {
    document.querySelectorAll(".side-nav button, .tabs button").forEach((button) => {
      const text = button.textContent.trim();
      if (["个股统计", "题材统计", "行业统计", "数据中心"].some((word) => text.includes(word))) {
        button.dataset.feedbackHidden = "true";
      }
    });
    ["stats-section", "themes-section", "industries-section"].forEach((id) => {
      const node = document.getElementById(id);
      if (node) node.style.display = "none";
    });
    const tools = document.querySelector(".top-tools");
    const picker = document.querySelector(".date-picker");
    if (tools && picker && !document.querySelector(".date-range-note")) {
      const note = document.createElement("span");
      note.className = "date-range-note";
      note.textContent = "近3个月";
      picker.insertAdjacentElement("afterend", note);
    }
  }

  function esc(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "'": "&#39;",
      '"': "&quot;",
    }[char]));
  }

  function formatTime(value) {
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

  function render() {
    if (!list) return;
    list.innerHTML = items.length
      ? items.map((item) => `
          <article class="feedback-item" data-id="${esc(item.id)}">
            <div class="feedback-meta">
              <strong>${esc(item.display_name || "匿名用户")}</strong>
              <span>${esc(formatTime(item.created_at))}</span>
            </div>
            <p>${esc(item.content)}</p>
            <div class="feedback-actions">
              <button type="button" data-like="${esc(item.id)}">赞 ${Number(item.like_count || 0)}</button>
              ${adminMode ? `<button type="button" class="danger" data-delete="${esc(item.id)}">删除</button>` : ""}
            </div>
          </article>
        `).join("")
      : '<div class="feedback-empty">暂无反馈</div>';
  }

  async function loadFeedbacks() {
    try {
      const response = await fetch(api, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      items = payload.feedbacks || [];
      if (errorNode) errorNode.textContent = "";
      render();
    } catch (error) {
      if (errorNode) errorNode.textContent = "反馈暂时不可用";
    }
  }

  async function submitFeedback(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const content = form.querySelector("textarea").value.trim();
    const displayName = form.querySelector("input").value.trim();
    if (!content) {
      if (errorNode) errorNode.textContent = "请先填写反馈内容";
      return;
    }
    const button = form.querySelector(".fg-submit");
    button.disabled = true;
    button.textContent = "提交中";
    try {
      const response = await fetch(api, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, display_name: displayName }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      items = [payload.feedback, ...items].filter(Boolean).slice(0, 30);
      closeModal();
      render();
      if (errorNode) errorNode.textContent = "";
    } catch (error) {
      if (errorNode) errorNode.textContent = "反馈提交失败，请稍后再试";
    } finally {
      button.disabled = false;
      button.textContent = "提交反馈";
    }
  }

  async function likeFeedback(id) {
    const key = `fenggu-liked:${id}`;
    if (localStorage.getItem(key)) return;
    try {
      const response = await fetch(`${api}/${encodeURIComponent(id)}/like`, { method: "POST" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      localStorage.setItem(key, "1");
      items = items.map((item) => item.id === id ? payload.feedback : item);
      render();
    } catch (error) {
      if (errorNode) errorNode.textContent = "点赞失败";
    }
  }

  async function deleteFeedback(id) {
    if (!adminToken) return;
    if (!confirm("确认删除这条反馈？")) return;
    try {
      const response = await fetch(`${api}/${encodeURIComponent(id)}`, {
        method: "DELETE",
        headers: { "X-Admin-Token": adminToken },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      items = items.filter((item) => item.id !== id);
      render();
    } catch (error) {
      if (errorNode) errorNode.textContent = "删除失败，请检查管理员密钥";
    }
  }

  function openModal() {
    const backdrop = document.querySelector(".fg-modal-backdrop");
    if (backdrop) {
      backdrop.classList.add("open");
      const textarea = backdrop.querySelector("textarea");
      if (textarea) textarea.focus();
    }
  }

  function closeModal() {
    const backdrop = document.querySelector(".fg-modal-backdrop");
    if (!backdrop) return;
    backdrop.classList.remove("open");
    const form = backdrop.querySelector("form");
    if (form) form.reset();
    const count = backdrop.querySelector(".fg-count");
    if (count) count.textContent = "0/300";
  }

  function setupResize() {
    const handle = panel.querySelector(".feedback-resize");
    const saved = Number(localStorage.getItem("fenggu-feedback-height") || 0);
    if (saved) panel.style.height = `${saved}px`;
    handle.addEventListener("mousedown", (event) => {
      event.preventDefault();
      const startY = event.clientY;
      const startHeight = panel.offsetHeight;
      const onMove = (moveEvent) => {
        panel.style.height = `${Math.max(140, startHeight + moveEvent.clientY - startY)}px`;
      };
      const onUp = () => {
        localStorage.setItem("fenggu-feedback-height", String(panel.offsetHeight));
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    });
  }

  function mount() {
    if (document.querySelector(".sidebar-feedback")) return;
    hideOldItems();
    const source = document.querySelector(".source-note");
    if (!source) return;
    panel = document.createElement("section");
    panel.className = "sidebar-feedback";
    panel.innerHTML = `
      <div class="sidebar-feedback-head">
        <h2>用户反馈</h2>
        <button type="button" class="feedback-admin">管理</button>
      </div>
      <div class="feedback-error"></div>
      <div class="feedback-list"><div class="feedback-empty">加载中</div></div>
      <span class="feedback-resize"></span>
    `;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "feedback-open";
    button.textContent = "意见反馈";
    source.parentNode.insertBefore(panel, source);
    source.parentNode.insertBefore(button, source);

    const modal = document.createElement("div");
    modal.className = "fg-modal-backdrop";
    modal.innerHTML = `
      <form class="fg-feedback-modal">
        <div class="fg-modal-head">
          <h2>意见反馈</h2>
          <button type="button" class="fg-modal-close" aria-label="关闭">×</button>
        </div>
        <label><span>昵称（可不填）</span><input maxlength="20" placeholder="匿名用户" /></label>
        <label><span>反馈内容</span><textarea maxlength="300" placeholder="请输入建议、问题或数据反馈"></textarea></label>
        <div class="fg-modal-foot"><span class="fg-count">0/300</span><button type="submit" class="fg-submit">提交反馈</button></div>
      </form>
    `;
    document.body.appendChild(modal);

    list = panel.querySelector(".feedback-list");
    errorNode = panel.querySelector(".feedback-error");
    button.addEventListener("click", openModal);
    modal.addEventListener("click", (event) => { if (event.target === modal) closeModal(); });
    modal.querySelector(".fg-modal-close").addEventListener("click", closeModal);
    modal.querySelector("form").addEventListener("submit", submitFeedback);
    modal.querySelector("textarea").addEventListener("input", (event) => {
      modal.querySelector(".fg-count").textContent = `${event.target.value.length}/300`;
    });
    panel.querySelector(".feedback-admin").addEventListener("click", () => {
      if (adminMode) {
        adminMode = false;
      } else {
        const token = prompt("请输入管理员密钥");
        if (!token) return;
        adminToken = token.trim();
        localStorage.setItem("fenggu-admin-token", adminToken);
        adminMode = true;
      }
      panel.querySelector(".feedback-admin").textContent = adminMode ? "退出管理" : "管理";
      render();
    });
    list.addEventListener("click", (event) => {
      const like = event.target.closest("[data-like]");
      const del = event.target.closest("[data-delete]");
      if (like) likeFeedback(like.dataset.like);
      if (del) deleteFeedback(del.dataset.delete);
    });
    setupResize();
    loadFeedbacks();
    setInterval(loadFeedbacks, 30000);
    setInterval(hideOldItems, 1000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();
