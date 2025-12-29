(() => {
  const refreshBtn = document.getElementById("ddu-refresh-cache");
  const statusEl = document.getElementById("ddu-cache-status");
  const cacheModalEl = document.getElementById("dduCacheModal");
  const cacheProgressEl = document.getElementById("ddu-cache-progress");
  if (!refreshBtn || !statusEl) {
    return;
  }
  let pollTimer = null;
  let refreshing = false;

  const formatTimestamp = (value) => {
    if (!value) {
      return "";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    const pad = (v) => String(v).padStart(2, "0");
    return `${pad(date.getDate())}/${pad(date.getMonth() + 1)}/${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  };

  const formatStatus = (count, updated) => {
    const formatted = formatTimestamp(updated);
    const text = formatted ? `Cache: ${count} elementi (agg. ${formatted})` : `Cache: ${count} elementi`;
    statusEl.textContent = text;
  };

  const fetchStatus = async () => {
    try {
      const res = await fetch("/api/ddunlimited/cache/status");
      const data = await res.json();
      formatStatus(data.count || 0, data.updated_at || "");
    } catch (err) {
      formatStatus(0, "");
    }
  };

  refreshBtn.addEventListener("click", async () => {
    if (refreshing) {
      return;
    }
    const modal = cacheModalEl ? bootstrap.Modal.getOrCreateInstance(cacheModalEl) : null;
    if (cacheProgressEl) {
      cacheProgressEl.textContent = "Ricarica in corso...";
    }
    modal?.show();
    refreshBtn.disabled = true;
    const original = refreshBtn.innerHTML;
    refreshBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Ricarica cache';
    try {
      refreshing = true;
      const startRes = await fetch("/api/ddunlimited/cache/refresh", { method: "POST" });
      if (!startRes.ok) {
        throw new Error("refresh_failed");
      }
      const poll = async () => {
        const res = await fetch("/api/ddunlimited/cache/progress");
        const data = await res.json();
        const processed = data.processed_sources || 0;
        const total = data.total_sources || 0;
        const current = data.current_source ? ` - ${data.current_source}` : "";
          if (cacheProgressEl) {
            if (data.cancelled) {
              cacheProgressEl.textContent = "Ricarica annullata.";
            } else if (data.running) {
              cacheProgressEl.textContent = `Liste ${processed}/${total}${current} • ${data.items_count || 0} release`;
            } else {
              cacheProgressEl.textContent = `Completata: ${data.items_count || 0} release`;
            }
          }
          if (!data.running) {
            refreshing = false;
            formatStatus(data.items_count || 0, data.updated_at || "");
            if (pollTimer) {
              clearInterval(pollTimer);
              pollTimer = null;
            }
            if (!data.cancelled) {
              setTimeout(() => modal?.hide(), 500);
            }
          }
        };
      await poll();
      pollTimer = setInterval(poll, 1000);
    } catch (err) {
      await fetchStatus();
      if (cacheProgressEl) {
        cacheProgressEl.textContent = "Errore durante la ricarica.";
      }
    } finally {
      refreshBtn.innerHTML = original;
      refreshBtn.disabled = false;
    }
  });

  if (cacheModalEl) {
    cacheModalEl.addEventListener("hidden.bs.modal", async () => {
      if (refreshing) {
        try {
          await fetch("/api/ddunlimited/cache/cancel", { method: "POST" });
        } catch (err) {
          // ignore
        }
      }
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
      refreshing = false;
      refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise me-1"></i>Ricarica cache';
      refreshBtn.disabled = false;
    });
  }

  fetchStatus();
})();
