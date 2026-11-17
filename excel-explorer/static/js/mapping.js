document.addEventListener("DOMContentLoaded", () => {
  const mapper = document.getElementById("mapper");
  if (!mapper) return;
  const projectId = mapper.dataset.project;
  const stateNode = document.getElementById("map-state");
  let links = [];
  try {
    links = (JSON.parse(stateNode ? stateNode.textContent || "{}" : "{}").links) || [];
  } catch (error) {
    links = [];
  }

  const pick = document.getElementById("raw-pick");
  const sheet = document.getElementById("sheet-pick");
  const fillSheets = () => {
    if (!pick || !sheet) return;
    const option = pick.selectedOptions[0];
    const names = ((option && option.dataset.sheets) || "").split("||").filter(Boolean);
    sheet.replaceChildren();
    names.forEach((name) => {
      const item = document.createElement("option");
      item.value = name;
      item.textContent = name;
      sheet.appendChild(item);
    });
  };
  if (pick) pick.addEventListener("change", fillSheets);
  fillSheets();

  const panel = document.getElementById("transform-panel");
  const form = document.getElementById("tf-form");
  const empty = document.getElementById("tf-empty");
  const typeSelect = document.getElementById("tf-type");
  const lower = document.getElementById("tf-lower");
  const upper = document.getElementById("tf-upper");
  if (lower && upper) {
    lower.addEventListener("change", () => { if (lower.checked) upper.checked = false; });
    upper.addEventListener("change", () => { if (upper.checked) lower.checked = false; });
  }
  if (typeSelect) typeSelect.addEventListener("change", syncFields);
  if (form) form.addEventListener("submit", (event) => { event.preventDefault(); applyTransform(); });

  let dragPayload = "";
  document.querySelectorAll("[data-source]").forEach((chip) => {
    chip.addEventListener("dragstart", (event) => {
      dragPayload = JSON.stringify({ file: Number(chip.dataset.file), source: chip.dataset.source || "" });
      event.dataTransfer.setData("text/plain", dragPayload);
      event.dataTransfer.effectAllowed = "copy";
      chip.classList.add("opacity-50");
    });
    chip.addEventListener("dragend", () => {
      chip.classList.remove("opacity-50");
      setTimeout(() => { dragPayload = ""; }, 50);
    });
  });

  const sourcePanel = document.getElementById("source-panel");
  const targetPanel = document.getElementById("target-panel");
  document.querySelectorAll("[data-column]").forEach(bindCard);
  const newColumnDrop = document.getElementById("new-column-drop");
  if (targetPanel) {
    targetPanel.addEventListener("dragover", (event) => {
      if (event.target.closest && event.target.closest("[data-column]")) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      if (newColumnDrop) newColumnDrop.classList.add("bg-green-50", "dark:bg-green-950");
    });
    targetPanel.addEventListener("dragleave", (event) => {
      if (targetPanel.contains(event.relatedTarget)) return;
      if (newColumnDrop) newColumnDrop.classList.remove("bg-green-50", "dark:bg-green-950");
    });
    targetPanel.addEventListener("drop", (event) => {
      if (event.target.closest && event.target.closest("[data-column]")) return;
      event.preventDefault();
      if (newColumnDrop) newColumnDrop.classList.remove("bg-green-50", "dark:bg-green-950");
      createFromDrop(event.dataTransfer.getData("text/plain") || dragPayload);
    });
  }
  if (newColumnDrop) {
    newColumnDrop.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = "copy";
      newColumnDrop.classList.add("bg-green-50", "dark:bg-green-950");
    });
    newColumnDrop.addEventListener("drop", (event) => {
      event.preventDefault();
      event.stopPropagation();
      newColumnDrop.classList.remove("bg-green-50", "dark:bg-green-950");
      createFromDrop(event.dataTransfer.getData("text/plain") || dragPayload);
    });
  }

  [sourcePanel, targetPanel, window].forEach((node) => {
    if (node) node.addEventListener("scroll", scheduleDraw, true);
  });
  window.addEventListener("resize", scheduleDraw);
  if (window.ResizeObserver) new ResizeObserver(scheduleDraw).observe(mapper);
  const cont = document.getElementById("map-continue");
  if (cont) cont.addEventListener("click", continueStudio);

  document.body.addEventListener("htmx:afterSwap", (event) => {
    const target = event.detail && event.detail.target;
    if (target && (target.id === "map-preview" || target.id === "map-job" || target.id === "map-sum")) {
      const box = document.getElementById("map-results");
      if (box) box.scrollIntoView({ block: "nearest" });
    }
    scheduleDraw();
  });

  paint();

  function t(key) {
    return translate(localStorage.getItem("lang") || "vi", key);
  }

  function shortFile(name) {
    const base = String(name || "").split(/[/\\]/).pop();
    const stem = base.replace(/\.[^.]+$/, "");
    const matches = [...stem.matchAll(/(?:thang|month|t)[_\s-]?(\d{1,2})/gi)];
    if (matches.length) return "T" + Number(matches[matches.length - 1][1]);
    return stem.length > 14 ? stem.slice(0, 14) + "…" : stem;
  }

  async function continueStudio() {
    const response = await fetch(`/mappings/${projectId}/continue`, { method: "POST" });
    const type = response.headers.get("content-type") || "";
    if (type.includes("application/json")) {
      const data = await response.json();
      if (data.file_id) window.location.href = `/studio/${data.file_id}`;
      else note(t(data.detail || "bad_excel"));
      return;
    }
    const host = document.getElementById("map-job");
    if (!host) return;
    host.innerHTML = await response.text();
    if (window.htmx) window.htmx.process(host);
    watchJobs(host);
    host.scrollIntoView({ block: "nearest" });
  }

  function sourceFiles() {
    return [...document.querySelectorAll("[data-file-block]")].map((node) => ({
      id: Number(node.dataset.fileBlock),
      name: node.dataset.fileName || "",
    }));
  }

  function sourceNode(link) {
    const file = CSS.escape(String(link.mapping_file_id));
    const name = CSS.escape(link.source_column_name || "");
    return document.querySelector(`[data-file="${file}"][data-source="${name}"]`);
  }

  function lineBad(link) {
    return link.data_type === "date" && !(link.transform && link.transform.date_format);
  }

  function defaultTransform(type) {
    const base = { trim: true, case: "", default: "" };
    if (type === "date") return Object.assign({}, base, { date_format: "dd/mm/yyyy" });
    if (type === "number") {
      return Object.assign({}, base, {
        number_format: "eu",
        strip_dot: true,
        strip_comma: true,
        strip_currency: true,
      });
    }
    return base;
  }

  function bindCard(card) {
    card.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      card.classList.add("ring-2", "ring-green-700");
    });
    card.addEventListener("dragleave", (event) => {
      if (card.contains(event.relatedTarget)) return;
      card.classList.remove("ring-2", "ring-green-700");
    });
    card.addEventListener("drop", (event) => {
      event.preventDefault();
      event.stopPropagation();
      card.classList.remove("ring-2", "ring-green-700");
      dropOn(card, event.dataTransfer.getData("text/plain") || dragPayload);
    });
  }

  function guessType(name) {
    const folded = name.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    if (/(ngay|date|time)/.test(folded)) return "date";
    if (/(tien|amount|qty|so luong|thanh tien)/.test(folded)) return "number";
    return "text";
  }

  function appendCard(column) {
    const article = document.createElement("article");
    article.id = `tgt-${column.id}`;
    article.dataset.column = String(column.id);
    article.dataset.type = column.data_type;
    article.dataset.name = column.column_name;
    article.className = "rounded-xl border border-stone-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900";
    const head = document.createElement("div");
    head.className = "flex items-start justify-between gap-2";
    const titles = document.createElement("div");
    const heading = document.createElement("h2");
    heading.className = "text-sm font-semibold";
    heading.textContent = column.column_name;
    const type = document.createElement("p");
    type.className = "text-xs text-stone-500";
    type.dataset.typeLabel = "";
    type.textContent = column.data_type;
    titles.append(heading, type);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "text-xs text-red-700";
    remove.textContent = "×";
    remove.setAttribute("hx-delete", `/mappings/${projectId}/columns/${column.id}`);
    head.append(titles, remove);
    const hint = document.createElement("p");
    hint.dataset.dropHint = "";
    hint.className = "mt-2 rounded-md border border-dashed border-stone-300 px-2 py-3 text-center text-xs text-stone-500 dark:border-zinc-600";
    hint.dataset.i18n = "map_drop";
    hint.textContent = t("map_drop");
    const list = document.createElement("ul");
    list.dataset.mappedFor = String(column.id);
    list.className = "mt-2 space-y-1";
    const missing = document.createElement("p");
    missing.dataset.missingFor = String(column.id);
    missing.className = "mt-1 text-xs text-yellow-700 dark:text-yellow-300";
    article.append(head, hint, list, missing);
    const zone = document.getElementById("new-column-drop");
    if (zone) targetPanel.insertBefore(article, zone);
    else targetPanel.appendChild(article);
    bindCard(article);
    if (window.htmx) window.htmx.process(article);
    const placeholder = targetPanel.querySelector("[data-empty-cols]");
    if (placeholder) placeholder.remove();
    return article;
  }

  async function createFromDrop(raw) {
    let payload;
    try {
      payload = JSON.parse(raw || "");
    } catch (error) {
      return;
    }
    if (!payload || !payload.source) return;
    const response = await fetch(`/mappings/${projectId}/columns`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ column_name: payload.source, data_type: guessType(payload.source) }),
    });
    if (!response.ok) {
      note(t("bad_excel"));
      return;
    }
    const column = await response.json();
    let card = document.getElementById(`tgt-${column.id}`);
    if (!card) card = appendCard(column);
    await dropOn(card, raw);
  }

  async function dropOn(card, raw) {
    let payload;
    try {
      payload = JSON.parse(raw || "");
    } catch (error) {
      return;
    }
    if (!payload || !payload.source) return;
    const response = await fetch(`/mappings/${projectId}/files/${payload.file}/map`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_col: payload.source,
        target_col_id: Number(card.dataset.column),
        transform_json: defaultTransform(card.dataset.type || "text"),
      }),
    });
    if (!response.ok) {
      note(t("bad_excel"));
      return;
    }
    const saved = await response.json();
    const index = links.findIndex((item) => item.id === saved.id);
    if (index >= 0) links[index] = saved;
    else links.push(saved);
    paint();
  }

  async function removeLink(link) {
    const response = await fetch(`/mappings/${projectId}/files/${link.mapping_file_id}/map/${link.id}`, { method: "DELETE" });
    if (!response.ok) return;
    links = links.filter((item) => item.id !== link.id);
    if (form && form.dataset.mapId === String(link.id)) closePanel();
    paint();
  }

  function closePanel() {
    if (form) {
      form.classList.add("hidden");
      form.dataset.mapId = "";
    }
    if (empty) empty.classList.remove("hidden");
  }

  function openPanel(mapId) {
    const link = links.find((item) => item.id === mapId);
    if (!link || !form) return;
    form.dataset.mapId = String(link.id);
    form.classList.remove("hidden");
    if (empty) empty.classList.add("hidden");
    const title = document.getElementById("tf-title");
    const file = document.getElementById("tf-file");
    if (title) title.textContent = `${link.source_column_name} → ${link.target_name}`;
    if (file) {
      file.textContent = `${shortFile(link.raw_name)} / ${link.sheet_name}`;
      file.title = `${link.raw_name} / ${link.sheet_name}`;
    }
    typeSelect.value = link.data_type || "text";
    const transform = link.transform || {};
    document.getElementById("tf-date").value = transform.date_format || "";
    document.getElementById("tf-trim").checked = transform.trim !== false;
    lower.checked = transform.case === "lower";
    upper.checked = transform.case === "upper";
    document.getElementById("tf-default").value = transform.default || "";
    const mode = transform.number_format || "";
    const dot = document.getElementById("tf-dot");
    const comma = document.getElementById("tf-comma");
    const cur = document.getElementById("tf-cur");
    if (mode === "eu") {
      dot.checked = true;
      comma.checked = true;
    } else if (mode === "us" || (!mode && transform.strip_dot === undefined)) {
      dot.checked = false;
      comma.checked = true;
    } else if (mode === "dot") {
      dot.checked = true;
      comma.checked = false;
    } else if (mode === "plain") {
      dot.checked = false;
      comma.checked = false;
    } else {
      dot.checked = !!transform.strip_dot;
      comma.checked = !!transform.strip_comma;
    }
    cur.checked = transform.strip_currency !== false;
    const status = document.getElementById("tf-status");
    if (status) status.textContent = "";
    syncFields();
  }

  function syncFields() {
    const type = typeSelect ? typeSelect.value : "text";
    const dateWrap = document.getElementById("tf-date-wrap");
    const numWrap = document.getElementById("tf-num-wrap");
    if (dateWrap) dateWrap.hidden = type !== "date";
    if (numWrap) numWrap.hidden = type !== "number";
  }

  function readTransform() {
    const dot = document.getElementById("tf-dot").checked;
    const comma = document.getElementById("tf-comma").checked;
    let numberFormat = "plain";
    if (dot && comma) numberFormat = "eu";
    else if (comma) numberFormat = "us";
    else if (dot) numberFormat = "dot";
    const transform = {
      trim: document.getElementById("tf-trim").checked,
      case: lower.checked ? "lower" : (upper.checked ? "upper" : ""),
      default: document.getElementById("tf-default").value || "",
      date_format: document.getElementById("tf-date").value || "",
      number_format: numberFormat,
      strip_dot: dot,
      strip_comma: comma,
      strip_currency: document.getElementById("tf-cur").checked,
    };
    return transform;
  }

  async function applyTransform() {
    const mapId = Number(form.dataset.mapId || 0);
    const link = links.find((item) => item.id === mapId);
    const status = document.getElementById("tf-status");
    if (!link) return;
    const type = typeSelect.value;
    const columnBody = new URLSearchParams();
    columnBody.set("column_name", link.target_name);
    columnBody.set("data_type", type);
    const columnResponse = await fetch(`/mappings/${projectId}/columns/${link.target_column_id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: columnBody,
    });
    if (!columnResponse.ok && columnResponse.status !== 204) {
      if (status) status.textContent = t("bad_excel");
      return;
    }
    const response = await fetch(`/mappings/${projectId}/map/${link.id}/transform`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transform_json: readTransform() }),
    });
    if (!response.ok) {
      if (status) status.textContent = t("bad_excel");
      return;
    }
    const saved = await response.json();
    links = links.map((item) => {
      if (item.target_column_id === saved.target_column_id) item.data_type = saved.data_type;
      return item.id === saved.id ? saved : item;
    });
    const card = document.getElementById(`tgt-${saved.target_column_id}`);
    if (card) {
      card.dataset.type = saved.data_type;
      const label = card.querySelector("[data-type-label]");
      if (label) label.textContent = saved.data_type;
    }
    if (status) status.textContent = t("map_applied");
    paint();
    openPanel(saved.id);
    if (status) status.textContent = t("map_applied");
  }

  function paint() {
    document.querySelectorAll("[data-mapped-for]").forEach((list) => {
      const columnId = Number(list.dataset.mappedFor);
      list.replaceChildren();
      links.filter((link) => link.target_column_id === columnId).forEach((link) => {
        const row = document.createElement("li");
        row.className = "flex items-center justify-between gap-2 rounded bg-green-50 px-2 py-1 text-xs dark:bg-green-950";
        const label = document.createElement("span");
        label.className = "truncate";
        label.textContent = `${link.source_column_name} (${shortFile(link.raw_name)})`;
        label.title = link.raw_name;
        const gear = document.createElement("button");
        gear.type = "button";
        gear.className = "shrink-0";
        gear.textContent = "⚙";
        gear.title = t("map_config");
        gear.addEventListener("click", () => openPanel(link.id));
        row.append(label, gear);
        row.addEventListener("click", (event) => {
          if (event.target === gear) return;
          openPanel(link.id);
        });
        list.appendChild(row);
      });
      const hint = list.parentElement && list.parentElement.querySelector("[data-drop-hint]");
      if (hint) hint.classList.toggle("hidden", list.children.length > 0);
      const missingNode = document.querySelector(`[data-missing-for="${columnId}"]`);
      if (missingNode) {
        const missing = sourceFiles().filter((file) => !links.some((link) => link.mapping_file_id === file.id && link.target_column_id === columnId));
        missingNode.textContent = missing.length ? `${t("map_missing")}: ${missing.map((file) => shortFile(file.name)).join(", ")}` : "";
        missingNode.title = missing.map((file) => file.name).join(", ");
      }
    });
    document.querySelectorAll("[data-source]").forEach((chip) => {
      const used = links.some((link) => link.mapping_file_id === Number(chip.dataset.file) && link.source_column_name === chip.dataset.source);
      chip.classList.toggle("opacity-60", used);
      const mark = chip.querySelector("[data-check]");
      if (mark) mark.classList.toggle("hidden", !used);
    });
    drawLines();
  }

  let frame = 0;
  function scheduleDraw() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(drawLines);
  }

  function drawLines() {
    const svg = document.getElementById("mapping-lines");
    const buttons = document.getElementById("line-buttons");
    if (!svg || !buttons || !mapper) return;
    svg.replaceChildren();
    buttons.replaceChildren();
    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    defs.append(marker("arrow-green", "#166534"), marker("arrow-red", "#b91c1c"));
    svg.appendChild(defs);
    const origin = mapper.getBoundingClientRect();
    const sourceBox = sourcePanel ? sourcePanel.getBoundingClientRect() : origin;
    const targetBox = targetPanel ? targetPanel.getBoundingClientRect() : origin;
    links.forEach((link) => {
      const from = sourceNode(link);
      const to = document.getElementById(`tgt-${link.target_column_id}`);
      if (!from || !to) return;
      const start = from.getBoundingClientRect();
      const end = to.getBoundingClientRect();
      const y1raw = Math.min(Math.max(start.top + start.height / 2, sourceBox.top + 8), sourceBox.bottom - 8);
      const y2raw = Math.min(Math.max(end.top + end.height / 2, targetBox.top + 8), targetBox.bottom - 8);
      const x1 = Math.min(start.right, sourceBox.right) - origin.left;
      const y1 = y1raw - origin.top;
      const x2 = Math.max(end.left, targetBox.left) - origin.left;
      const y2 = y2raw - origin.top;
      const bend = Math.max(36, Math.abs(x2 - x1) / 2);
      const bad = lineBad(link);
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`);
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", bad ? "#b91c1c" : "#166534");
      path.setAttribute("stroke-width", "2");
      path.setAttribute("marker-end", bad ? "url(#arrow-red)" : "url(#arrow-green)");
      path.style.pointerEvents = "stroke";
      path.addEventListener("click", () => openPanel(link.id));
      svg.appendChild(path);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pointer-events-auto absolute flex h-4 w-4 items-center justify-center rounded-full bg-white text-xs leading-none text-red-700 shadow dark:bg-zinc-900";
      button.style.left = `${(x1 + x2) / 2 - 8}px`;
      button.style.top = `${(y1 + y2) / 2 - 8}px`;
      button.textContent = "×";
      button.title = t("map_remove_link");
      button.addEventListener("click", () => removeLink(link));
      buttons.appendChild(button);
    });
  }

  function marker(id, color) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", "marker");
    node.setAttribute("id", id);
    node.setAttribute("markerWidth", "8");
    node.setAttribute("markerHeight", "8");
    node.setAttribute("refX", "6");
    node.setAttribute("refY", "3");
    node.setAttribute("orient", "auto");
    const head = document.createElementNS("http://www.w3.org/2000/svg", "path");
    head.setAttribute("d", "M0,0 L6,3 L0,6 Z");
    head.setAttribute("fill", color);
    node.appendChild(head);
    return node;
  }

  function note(text) {
    const node = document.getElementById("map-job");
    if (node) node.textContent = text;
  }
});
