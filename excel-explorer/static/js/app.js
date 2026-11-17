function shell() {
  const savedTheme = localStorage.getItem("theme");
  const dark = savedTheme ? savedTheme === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  return {
    dark,
    lang: localStorage.getItem("lang") || "vi",
    init() {
      applyI18n(this.lang);
    },
    t(key) {
      return translate(this.lang, key);
    },
    setLang(lang) {
      this.lang = lang;
      localStorage.setItem("lang", lang);
      applyI18n(lang);
    },
    toggleTheme() {
      this.dark = !this.dark;
      localStorage.setItem("theme", this.dark ? "dark" : "light");
    },
  };
}

function dropZone() {
  return {
    state: "idle",
    enter() {
      this.state = "hover";
    },
    leave(event) {
      const next = event.relatedTarget;
      if (next && event.currentTarget.contains(next)) return;
      if (this.state !== "dropping") this.state = "idle";
    },
    drop(event) {
      const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
      if (!file) {
        this.state = "idle";
        return;
      }
      this.state = "dropping";
      const input = document.getElementById("excel-file");
      if (!input) return;
      const bag = new DataTransfer();
      bag.items.add(file);
      input.files = bag.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    },
    browse() {
      const input = document.getElementById("excel-file");
      if (input) input.click();
    },
  };
}

function homeBoard() {
  return {
    openName: "",
    files: [],
    openColumn(name) {
      const node = document.getElementById("home-columns");
      const all = node ? JSON.parse(node.textContent || "[]") : [];
      const hit = all.find((item) => item.name === name);
      this.openName = name;
      this.files = hit ? hit.files : [];
    },
    closeColumn() {
      this.openName = "";
      this.files = [];
    },
  };
}

function fileItem(id) {
  return {
    open: false,
    loading: false,
    loaded: false,
    columns: [],
    rows: [],
    hide() {
      this.open = false;
    },
    async show() {
      this.open = true;
      if (this.loaded || this.loading) return;
      this.loading = true;
      try {
        const response = await fetch(`/files/${id}/preview`);
        if (!response.ok) return;
        const data = await response.json();
        this.columns = data.columns || [];
        this.rows = data.rows || [];
        this.loaded = true;
      } finally {
        this.loading = false;
      }
    },
  };
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function showReading(name, key) {
  const stage = document.querySelector("#stage");
  if (!stage) return;
  const lang = localStorage.getItem("lang") || "vi";
  stage.innerHTML = `<p class="text-lg font-semibold">${escapeHtml(name || "")}</p><p class="mt-2 text-sm text-stone-500 dark:text-zinc-400">${escapeHtml(translate(lang, key))}</p>`;
}

document.addEventListener("dragover", (event) => {
  if (event.dataTransfer && Array.from(event.dataTransfer.types || []).includes("Files")) event.preventDefault();
});

document.addEventListener("drop", (event) => {
  const node = event.target && event.target.nodeType === 1 ? event.target : event.target && event.target.parentElement;
  if (node && node.closest && node.closest("[data-drop]")) return;
  if (event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files.length) event.preventDefault();
});

document.addEventListener("change", (event) => {
  const input = event.target;
  if (!input || input.id !== "excel-file") return;
  const file = input.files && input.files[0];
  if (file) showReading(file.name, "loading");
});

document.addEventListener("htmx:beforeRequest", (event) => {
  const elt = event.detail && event.detail.elt;
  const stage = document.querySelector("#stage");
  if (!elt || !stage || stage.contains(elt)) return;
  const path = (event.detail.requestConfig && event.detail.requestConfig.path) || "";
  if (!String(path).includes("/upload")) return;
  const input = document.querySelector("#excel-file");
  const file = input && input.files && input.files[0];
  showReading(file ? file.name : "", String(path).includes("/preview") ? "loading" : "uploading");
});

document.addEventListener("htmx:responseError", () => {
  const stage = document.querySelector("#stage");
  if (!stage) return;
  const lang = localStorage.getItem("lang") || "vi";
  stage.innerHTML = `<p class="text-sm text-red-700 dark:text-red-300">${escapeHtml(translate(lang, "bad_excel"))}</p>`;
});

function watchJobs(root) {
  (root || document).querySelectorAll("[data-job]").forEach((node) => {
    if (node.dataset.watched) return;
    node.dataset.watched = "1";
    const source = new EventSource(`/jobs/${node.dataset.job}/stream`);
    const apply = (data) => {
      const bar = node.querySelector("[data-bar]");
      const message = node.querySelector("[data-msg]");
      const detail = node.querySelector("[data-detail]");
      if (bar) bar.style.width = `${data.progress || 0}%`;
      const lang = localStorage.getItem("lang") || "vi";
      if (message) message.textContent = translate(lang, data.error || data.message_key || "uploading");
      if (detail) detail.textContent = data.detail || "";
      if (data.status === "done" && data.file_id) {
        source.close();
        if (node.dataset.studio === "1") {
          window.location.href = `/studio/${data.file_id}`;
          return;
        }
        if (node.dataset.stay === "1") {
          const link = document.createElement("a");
          link.href = `/files/${data.file_id}`;
          link.className = "ml-2 underline";
          link.textContent = translate(lang, "map_open_result");
          if (detail) detail.appendChild(link);
          return;
        }
        window.location.href = `/files/${data.file_id}`;
      }
      if (data.status === "error") source.close();
    };
    source.onmessage = (event) => apply(JSON.parse(event.data));
    source.onerror = () => {
      source.close();
      fetch(`/jobs/${node.dataset.job}`).then((response) => response.json()).then(apply).catch(() => {});
    };
  });
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-delete-file]");
  if (!button) return;
  event.preventDefault();
  event.stopPropagation();
  const lang = localStorage.getItem("lang") || "vi";
  if (!window.confirm(translate(lang, "delete_confirm"))) return;
  button.disabled = true;
  const response = await fetch(`/files/${button.dataset.deleteFile}`, { method: "DELETE" });
  if (response.ok || response.status === 204) {
    window.location.href = "/";
    return;
  }
  button.disabled = false;
});

document.addEventListener("htmx:afterSwap", (event) => {
  applyI18n(localStorage.getItem("lang") || "vi");
  const root = event.detail && event.detail.target;
  if (window.Alpine && root) window.Alpine.initTree(root);
  watchJobs(root || document);
});
