document.addEventListener("DOMContentLoaded", () => {
  const metaNode = document.getElementById("studio-meta");
  if (!metaNode) return;
  const meta = JSON.parse(metaNode.textContent || "{}");
  const columns = meta.columns || [];
  const state = { filters: [], groups: [], values: [], formulas: [] };
  let timer = 0;

  const fields = document.getElementById("studio-fields");
  columns.forEach((column) => {
    const item = document.createElement("li");
    const chip = document.createElement("div");
    chip.className = "cursor-grab rounded-md border border-stone-200 bg-stone-50 px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950";
    chip.draggable = true;
    chip.setAttribute("role", "button");
    chip.textContent = column.name;
    chip.title = column.type;
    chip.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("text/plain", JSON.stringify({ column: column.name, type: column.type }));
      event.dataTransfer.effectAllowed = "copy";
    });
    item.appendChild(chip);
    fields.appendChild(item);
  });

  document.querySelectorAll("[data-zone]").forEach((zone) => {
    zone.addEventListener("dragover", (event) => {
      event.preventDefault();
      zone.classList.add("ring-2", "ring-green-700");
    });
    zone.addEventListener("dragleave", (event) => {
      if (zone.contains(event.relatedTarget)) return;
      zone.classList.remove("ring-2", "ring-green-700");
    });
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.classList.remove("ring-2", "ring-green-700");
      let payload;
      try {
        payload = JSON.parse(event.dataTransfer.getData("text/plain") || "");
      } catch (error) {
        return;
      }
      if (!payload || !payload.column) return;
      addDrop(zone.dataset.zone, payload);
    });
  });

  document.getElementById("studio-formula").addEventListener("submit", (event) => {
    event.preventDefault();
    const expression = document.getElementById("studio-expr").value.trim();
    const alias = document.getElementById("studio-alias").value.trim();
    if (!expression) return;
    state.formulas.push({ expression, alias: alias || expression });
    document.getElementById("studio-expr").value = "";
    document.getElementById("studio-alias").value = "";
    render();
  });

  document.getElementById("studio-save").addEventListener("click", saveFile);
  render();
  schedule();

  function t(key) {
    return translate(localStorage.getItem("lang") || "vi", key);
  }

  function addDrop(zone, payload) {
    if (zone === "filter") {
      state.filters.push({ column: payload.column, op: "gte", value: "" });
    } else if (zone === "group") {
      if (!state.groups.includes(payload.column)) state.groups.push(payload.column);
    } else if (zone === "value") {
      const func = payload.type === "number" ? "SUM" : "COUNT";
      const alias = func === "SUM" ? `Tổng ${payload.column}` : `Đếm ${payload.column}`;
      state.values.push({ column: payload.column, func, alias });
    }
    render();
  }

  function render() {
    const filters = document.getElementById("studio-filters");
    filters.replaceChildren();
    state.filters.forEach((rule, index) => {
      const row = document.createElement("li");
      row.className = "flex flex-wrap items-center gap-1 text-xs";
      const name = document.createElement("span");
      name.className = "font-medium";
      name.textContent = rule.column;
      const op = document.createElement("select");
      op.className = "rounded border border-stone-300 bg-white px-1 py-1 dark:border-zinc-700 dark:bg-zinc-950";
      [["eq", "="], ["ne", "≠"], ["gt", ">"], ["gte", "≥"], ["lt", "<"], ["lte", "≤"], ["contains", t("op_contains")]].forEach((pair) => {
        const option = document.createElement("option");
        option.value = pair[0];
        option.textContent = pair[1];
        op.appendChild(option);
      });
      op.value = rule.op;
      op.addEventListener("change", () => { rule.op = op.value; schedule(); });
      const input = document.createElement("input");
      input.className = "w-28 rounded border border-stone-300 bg-white px-1 py-1 dark:border-zinc-700 dark:bg-zinc-950";
      input.value = rule.value;
      input.addEventListener("input", () => { rule.value = input.value; schedule(); });
      const remove = removeButton(() => { state.filters.splice(index, 1); render(); });
      row.append(name, op, input, remove);
      filters.appendChild(row);
    });

    const groups = document.getElementById("studio-groups");
    groups.replaceChildren();
    state.groups.forEach((name, index) => {
      const chip = document.createElement("li");
      chip.className = "flex items-center gap-1 rounded-full bg-green-50 px-2 py-1 text-xs dark:bg-green-950";
      chip.append(document.createTextNode(name), removeButton(() => { state.groups.splice(index, 1); render(); }));
      groups.appendChild(chip);
    });

    const values = document.getElementById("studio-values");
    values.replaceChildren();
    state.values.forEach((item, index) => {
      const row = document.createElement("li");
      row.className = "flex flex-wrap items-center gap-1 text-xs";
      const func = document.createElement("select");
      func.className = "rounded border border-stone-300 bg-white px-1 py-1 dark:border-zinc-700 dark:bg-zinc-950";
      ["SUM", "COUNT", "AVG", "MIN", "MAX"].forEach((name) => {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        func.appendChild(option);
      });
      func.value = item.func;
      func.addEventListener("change", () => { item.func = func.value; schedule(); });
      const label = document.createElement("span");
      label.textContent = item.column;
      const alias = document.createElement("input");
      alias.className = "w-28 rounded border border-stone-300 bg-white px-1 py-1 dark:border-zinc-700 dark:bg-zinc-950";
      alias.value = item.alias;
      alias.addEventListener("input", () => { item.alias = alias.value; schedule(); });
      row.append(func, label, alias, removeButton(() => { state.values.splice(index, 1); render(); }));
      values.appendChild(row);
    });

    const formulas = document.getElementById("studio-formulas");
    formulas.replaceChildren();
    state.formulas.forEach((item, index) => {
      const row = document.createElement("li");
      row.className = "flex items-center justify-between gap-2 text-xs";
      const label = document.createElement("span");
      label.className = "truncate";
      label.textContent = `${item.alias}: ${item.expression}`;
      row.append(label, removeButton(() => { state.formulas.splice(index, 1); render(); }));
      formulas.appendChild(row);
    });
    schedule();
  }

  function removeButton(onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "text-red-700";
    button.textContent = "×";
    button.addEventListener("click", onClick);
    return button;
  }

  function payload() {
    return {
      file_id: meta.file_id,
      filters: state.filters,
      group_by: state.groups,
      aggregations: state.values,
      formulas: state.formulas,
    };
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(runPreview, 500);
  }

  async function runPreview() {
    const status = document.getElementById("studio-status");
    const response = await fetch("/studio/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload()),
    });
    const data = await response.json();
    if (data.error) {
      status.textContent = t(data.error) || data.error;
      return;
    }
    status.textContent = "";
    drawTable(data);
  }

  function drawTable(data) {
    const host = document.getElementById("studio-preview");
    host.replaceChildren();
    const table = document.createElement("table");
    table.className = "min-w-full text-sm";
    const head = document.createElement("tr");
    (data.columns || []).forEach((name) => {
      const cell = document.createElement("th");
      cell.className = "px-2 py-1 text-left text-xs";
      cell.textContent = name;
      head.appendChild(cell);
    });
    const thead = document.createElement("thead");
    thead.appendChild(head);
    const body = document.createElement("tbody");
    (data.rows || []).forEach((row) => {
      const line = document.createElement("tr");
      row.forEach((value) => {
        const cell = document.createElement("td");
        cell.className = "whitespace-nowrap px-2 py-1";
        cell.textContent = value == null ? "" : String(value);
        line.appendChild(cell);
      });
      body.appendChild(line);
    });
    table.append(thead, body);
    host.appendChild(table);
  }

  async function saveFile() {
    const status = document.getElementById("studio-status");
    const response = await fetch("/studio/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload()),
    });
    const data = await response.json();
    if (!response.ok || data.error) {
      status.textContent = t(data.error) || data.error || t("bad_excel");
      return;
    }
    window.location.href = `/files/${data.file_id}`;
  }
});
