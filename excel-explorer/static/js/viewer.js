function sheetView() {
  return {
    id: 0,
    columns: [],
    rows: [],
    total: 0,
    offset: 0,
    logic: "and",
    rules: [],
    filterText: "",
    chartOpen: false,
    chartType: "bar",
    chartX: "",
    chartY: "",
    chartAgg: "sum",
    chartTop: 20,
    chartName: "",
    chartError: false,
    savedCharts: [],
    plot: null,
    showColors: false,
    bounds: {},
    colorLow: localStorage.getItem("excel-color-low") || "#bbf7d0",
    colorHigh: localStorage.getItem("excel-color-high") || "#fecaca",
    tab: "data",
    profile: [],
    profileLoading: false,
    pivotRows: [],
    pivotCols: [],
    pivotValues: [],
    pivotTable: { columns: [], rows: [] },
    pivotError: false,
    pivotName: "",
    savedPivots: [],
    reusablePivots: [],
    dragName: "",
    loading: false,
    inflight: "",
    rowHeight: 36,
    io: null,
    lastIoOffset: -1,
    get fromRow() {
      return this.rows.length ? this.offset + 1 : 0;
    },
    get toRow() {
      return this.offset + this.rows.length;
    },
    get padTop() {
      return this.offset * this.rowHeight;
    },
    get padBottom() {
      return Math.max(0, this.total - this.offset - this.rows.length) * this.rowHeight;
    },
    get numberColumns() {
      const measured = this.columns.filter((col) => this.bounds[col.name]);
      if (measured.length) return measured;
      return this.columns.filter((col) => col.type === "number");
    },
    get chartYColumns() {
      const preferred = this.numberColumns;
      const rest = this.columns.filter((col) => !preferred.some((item) => item.name === col.name));
      return preferred.concat(rest);
    },
    start() {
      const meta = JSON.parse(document.getElementById("sheet-meta").textContent);
      this.id = meta.id;
      this.columns = meta.columns || [];
      this.total = meta.total || 0;
      const numeric = this.columns.find((col) => col.type === "number");
      const label = this.columns.find((col) => col.type !== "number");
      this.chartY = numeric ? numeric.name : "";
      this.chartX = label ? label.name : (this.columns[0] ? this.columns[0].name : "");
      this.fetch(0, false);
      this.loadBounds();
      this.io = new IntersectionObserver((entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        if (this.lastIoOffset === this.offset) return;
        this.onScroll();
        this.lastIoOffset = this.offset;
      }, { root: this.$refs.scroller, rootMargin: "240px" });
    },
    typeLabel(type) {
      const key = type === "number" ? "type_number" : type === "date" ? "type_date" : "type_text";
      return translate(localStorage.getItem("lang") || "vi", key);
    },
    needsValue(rule) {
      return !["is_null", "is_not_null", "min", "max", "none"].includes(rule.op);
    },
    addRule() {
      const first = this.columns[0] ? this.columns[0].name : "";
      this.rules.push({ column: first, op: "contains", value: "", value2: "" });
      this.$nextTick(() => applyI18n(localStorage.getItem("lang") || "vi"));
    },
    apply() {
      const rules = this.rules.filter((rule) => {
        if (!rule.column || !rule.op || rule.op === "none") return false;
        if (!this.needsValue(rule)) return true;
        if (!String(rule.value || "").trim()) return false;
        return rule.op !== "between" || String(rule.value2 || "").trim();
      });
      this.filterText = rules.length ? JSON.stringify({ logic: this.logic, rules }) : "";
      this.offset = -1;
      this.fetch(0, true);
      if (this.chartOpen && this.tab === "data") this.drawChart();
      if (this.tab === "pivot" && this.pivotValues.length) this.runPivot();
    },
    clearFilter() {
      this.rules = [];
      this.filterText = "";
      this.offset = -1;
      this.fetch(0, true);
    },
    exportUrl(fmt) {
      const params = new URLSearchParams({ format: fmt });
      if (this.filterText) params.set("filter", this.filterText);
      return `/files/${this.id}/export?${params}`;
    },
    onScroll() {
      const scroller = this.$refs.scroller;
      if (!scroller) return;
      const start = Math.max(0, Math.floor(scroller.scrollTop / this.rowHeight) - 20);
      const aligned = Math.floor(start / 40) * 40;
      if (aligned !== this.offset) this.fetch(aligned, false);
    },
    async fetch(offset, recount) {
      let start = Math.max(0, offset);
      if (this.total > 0) start = Math.min(start, Math.max(0, this.total - 1));
      start = Math.floor(start / 40) * 40;
      const key = `${start}:${this.filterText}:${recount ? 1 : 0}`;
      if (this.inflight === key) return;
      if (!recount && start === this.offset && this.rows.length) return;
      this.inflight = key;
      this.loading = true;
      const params = new URLSearchParams({ offset: String(start), limit: "80", recount: recount ? "1" : "0" });
      if (!recount && this.total >= 0) params.set("total", String(this.total));
      if (this.filterText) params.set("filter", this.filterText);
      try {
        const response = await fetch(`/files/${this.id}/rows?${params}`);
        if (!response.ok) return;
        const data = await response.json();
        this.offset = data.offset || 0;
        this.rows = data.rows || [];
        if (recount || data.total >= 0) this.total = data.total;
      } finally {
        this.loading = false;
        if (this.inflight === key) this.inflight = "";
        this.$nextTick(() => this.observe());
      }
    },
    cellStyle(index, cell) {
      if (!this.showColors) return "";
      const column = this.columns[index];
      if (!column) return "";
      const bound = this.bounds[column.name];
      const number = parseLooseNumber(cell);
      if (!bound || !Number.isFinite(number)) return "";
      const low = Number(bound.min);
      const high = Number(bound.max);
      const span = high - low || 1;
      const ratio = Math.min(1, Math.max(0, (number - low) / span));
      const heat = mixColor(this.colorLow, this.colorHigh, ratio);
      const scale = Math.max(Math.abs(low), Math.abs(high)) || 1;
      const width = Math.min(100, (Math.abs(number) / scale) * 100);
      return `background-color:${heat};background-image:linear-gradient(90deg, rgba(22,101,52,.28) ${width}%, transparent ${width}%)`;
    },
    async loadBounds() {
      const response = await fetch(`/files/${this.id}/bounds`);
      if (!response.ok) return;
      const data = await response.json();
      this.bounds = data.columns || {};
      this.showColors = !!data.show_colors;
      const measures = Object.keys(this.bounds);
      if (measures.length && !measures.includes(this.chartY)) this.chartY = measures[0];
      if (measures.includes(this.chartX)) {
        const label = this.columns.find((col) => !this.bounds[col.name]);
        if (label) this.chartX = label.name;
      }
    },
    async toggleColors() {
      this.showColors = !this.showColors;
      await fetch(`/files/${this.id}/colors`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ show: this.showColors }),
      });
    },
    rememberColors() {
      localStorage.setItem("excel-color-low", this.colorLow);
      localStorage.setItem("excel-color-high", this.colorHigh);
    },
    async openChart() {
      this.chartOpen = true;
      const response = await fetch(`/charts?file_id=${this.id}`);
      if (response.ok) this.savedCharts = await response.json();
      this.$nextTick(() => {
        applyI18n(localStorage.getItem("lang") || "vi");
        this.drawChart();
      });
    },
    async drawChart() {
      this.chartError = false;
      if (this.chartAgg !== "count" && !this.chartY) {
        const first = this.chartYColumns[0];
        this.chartY = first ? first.name : "";
      }
      const response = await fetch(`/files/${this.id}/chart-data`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chart_type: this.chartType,
          x_col: this.chartX,
          y_col: this.chartY,
          aggregate: this.chartType === "scatter" ? "none" : this.chartAgg,
          top_n: Number(this.chartTop) || 20,
          filter: this.filterText,
        }),
      });
      if (!response.ok) {
        this.chartError = true;
        return;
      }
      this.paintChart(await response.json());
    },
    paintChart(data) {
      const box = document.getElementById("chart-box");
      if (!box || !window.echarts) {
        this.chartError = true;
        return;
      }
      const series = (data.series && data.series[0]) || { name: "", data: [] };
      const usable = (series.data || []).some((value) => value != null && Number.isFinite(Number(value)));
      if (this.chartAgg !== "count" && !usable) {
        this.chartError = true;
        return;
      }
      if (this.plot) this.plot.dispose();
      const dark = document.documentElement.classList.contains("dark");
      this.plot = echarts.init(box, dark ? "dark" : null);
      const labels = data.labels || [];
      if (this.chartType === "pie") {
        this.plot.setOption({
          backgroundColor: "transparent",
          tooltip: { trigger: "item" },
          series: [{
            type: "pie",
            radius: "70%",
            data: labels.map((label, index) => ({ name: String(label), value: series.data[index] })),
          }],
        });
        requestAnimationFrame(() => { if (this.plot) this.plot.resize(); });
        return;
      }
      const kind = this.chartType === "area" ? "line" : (this.chartType === "scatter" ? "scatter" : this.chartType);
      this.plot.setOption({
        backgroundColor: "transparent",
        tooltip: { trigger: "axis" },
        grid: { left: 48, right: 16, top: 24, bottom: 48 },
        xAxis: { type: "category", data: labels, axisLabel: { rotate: labels.length > 6 ? 30 : 0, hideOverlap: true } },
        yAxis: { type: "value" },
        series: [{ type: kind, name: series.name, data: series.data, areaStyle: this.chartType === "area" ? {} : undefined }],
      });
      requestAnimationFrame(() => { if (this.plot) this.plot.resize(); });
    },
    async saveChart() {
      const name = this.chartName || this.chartType;
      const response = await fetch("/charts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          file_id: this.id,
          name,
          config: {
            chart_type: this.chartType,
            x_col: this.chartX,
            y_col: this.chartY,
            aggregate: this.chartAgg,
            top_n: Number(this.chartTop) || 20,
          },
        }),
      });
      if (!response.ok) return;
      const created = await response.json();
      this.savedCharts.unshift({ id: created.id, name, config: { chart_type: this.chartType, x_col: this.chartX, y_col: this.chartY, aggregate: this.chartAgg, top_n: Number(this.chartTop) || 20 } });
    },
    loadChart(item) {
      const config = item.config || {};
      this.chartType = config.chart_type || this.chartType;
      this.chartX = config.x_col || this.chartX;
      this.chartY = config.y_col || this.chartY;
      this.chartAgg = config.aggregate || this.chartAgg;
      this.chartTop = config.top_n || this.chartTop;
      this.chartName = item.name || "";
      this.drawChart();
    },
    async removeChart(id) {
      const response = await fetch(`/charts/${id}`, { method: "DELETE" });
      if (response.ok) this.savedCharts = this.savedCharts.filter((item) => item.id !== id);
    },
    async openProfile() {
      this.tab = "profile";
      if (this.profile.length) return;
      this.profileLoading = true;
      try {
        const response = await fetch(`/files/${this.id}/profile`);
        if (!response.ok) return;
        const data = await response.json();
        this.profile = data.columns || [];
      } finally {
        this.profileLoading = false;
        this.$nextTick(() => applyI18n(localStorage.getItem("lang") || "vi"));
      }
    },
    async copyProfile() {
      const text = JSON.stringify(this.profile, null, 2);
      if (navigator.clipboard) await navigator.clipboard.writeText(text);
    },
    async openPivot() {
      this.tab = "pivot";
      const response = await fetch(`/pivots?file_id=${this.id}`);
      if (response.ok) {
        const data = await response.json();
        this.savedPivots = Array.isArray(data) ? data : (data.saved || []);
        this.reusablePivots = Array.isArray(data) ? [] : (data.reusable || []);
        const empty = !this.pivotRows.length && !this.pivotCols.length && !this.pivotValues.length;
        if (empty && data.last) this.loadPivot({ name: "", config: data.last });
      }
      this.$nextTick(() => applyI18n(localStorage.getItem("lang") || "vi"));
    },
    dropPivot(zone) {
      const name = this.dragName;
      if (!name) return;
      if (zone === "rows" && !this.pivotRows.includes(name) && this.pivotRows.length < 4) this.pivotRows.push(name);
      if (zone === "cols" && !this.pivotCols.includes(name)) this.pivotCols = [name];
      if (zone === "values" && !this.pivotValues.some((item) => item.column === name) && this.pivotValues.length < 3) {
        this.pivotValues.push({ column: name, aggregate: "sum" });
      }
      this.dragName = "";
    },
    pivotBody(format) {
      return {
        rows: this.pivotRows,
        columns: this.pivotCols,
        values: this.pivotValues,
        filter: this.filterText,
        format: format || "",
      };
    },
    async runPivot() {
      this.pivotError = false;
      const response = await fetch(`/files/${this.id}/pivot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(this.pivotBody()),
      });
      if (!response.ok) {
        this.pivotError = true;
        return;
      }
      this.pivotTable = await response.json();
    },
    async savePivot() {
      const name = this.pivotName || "Pivot";
      const config = { rows: this.pivotRows, columns: this.pivotCols, values: this.pivotValues };
      const response = await fetch("/pivots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_id: this.id, name, config }),
      });
      if (!response.ok) return;
      const created = await response.json();
      this.savedPivots.unshift({ id: created.id, name, config });
    },
    loadPivot(item) {
      const config = item.config || {};
      this.pivotRows = config.rows || [];
      this.pivotCols = config.columns || [];
      this.pivotValues = config.values || [];
      this.pivotName = item.name || "";
      this.runPivot();
    },
    async removePivot(id) {
      const response = await fetch(`/pivots/${id}`, { method: "DELETE" });
      if (response.ok) this.savedPivots = this.savedPivots.filter((item) => item.id !== id);
    },
    async exportPivot(format) {
      const response = await fetch(`/files/${this.id}/pivot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(this.pivotBody(format)),
      });
      if (!response.ok) {
        this.pivotError = true;
        return;
      }
      const blob = await response.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `pivot.${format}`;
      link.click();
    },
    async downloadPng() {
      const box = document.getElementById("chart-box");
      if (!box || !window.html2canvas) return;
      const canvas = await html2canvas(box, { backgroundColor: document.documentElement.classList.contains("dark") ? "#18181b" : "#ffffff" });
      const link = document.createElement("a");
      link.href = canvas.toDataURL("image/png");
      link.download = `${this.chartName || "chart"}.png`;
      link.click();
    },
    observe() {
      if (this.io && this.$refs.tail) {
        this.io.disconnect();
        this.io.observe(this.$refs.tail);
      }
    },
  };
}

function mixColor(low, high, ratio) {
  const from = hexColor(low);
  const to = hexColor(high);
  const mix = from.map((part, index) => Math.round(part + (to[index] - part) * ratio));
  return `rgb(${mix[0]}, ${mix[1]}, ${mix[2]})`;
}

function parseLooseNumber(value) {
  let text = String(value == null ? "" : value).trim().replace(/[\s₫đ]/g, "").replace(/VND/g, "");
  if (!text) return NaN;
  if (text.includes(",") && text.includes(".")) {
    text = text.lastIndexOf(",") > text.lastIndexOf(".") ? text.replace(/\./g, "").replace(",", ".") : text.replace(/,/g, "");
  } else if (text.includes(",")) {
    const parts = text.split(",");
    text = parts.length > 2 || (parts[parts.length - 1].length === 3 && parts[0].length <= 3) ? text.replace(/,/g, "") : text.replace(",", ".");
  } else if ((text.match(/\./g) || []).length > 1) {
    text = text.replace(/\./g, "");
  }
  return Number(text);
}

function hexColor(value) {
  const text = String(value || "").replace("#", "");
  if (text.length !== 6) return [187, 247, 208];
  return [0, 2, 4].map((index) => parseInt(text.slice(index, index + 2), 16));
}
