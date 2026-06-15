(() => {
  const refreshBtn = document.getElementById("mircrew-refresh-cache");
  const statusEl = document.getElementById("mircrew-cache-status");
  const cacheModalEl = document.getElementById("mircrewCacheModal");
  const cacheModalTitleEl = document.getElementById("mircrew-cache-modal-title");
  const cacheProgressEl = document.getElementById("mircrew-cache-progress");
  const cacheCancelBtn = document.getElementById("mircrew-cache-cancel");
  const sourcesBody = document.getElementById("mircrew-sources-body");
  const sourceForm = document.getElementById("mircrew-source-form");
  const detailModalEl = document.getElementById("mircrewDetailModal");
  const detailTitleEl = document.getElementById("mircrew-detail-title");
  const detailMetaEl = document.getElementById("mircrew-detail-meta");
  const detailLoadingEl = detailModalEl?.querySelector(".mircrew-detail-loading");
  const detailContentEl = detailModalEl?.querySelector(".mircrew-detail-content");
  const detailErrorEl = document.getElementById("mircrew-detail-error");
  const detailMagnetsEl = document.getElementById("mircrew-detail-magnets");
  const detailTorrentsEl = document.getElementById("mircrew-detail-torrents");

  if (!refreshBtn || !statusEl || !sourcesBody || !sourceForm) {
    return;
  }

  const fields = {
    id: document.getElementById("mircrew-source-id"),
    name: document.getElementById("mircrew-name"),
    url: document.getElementById("mircrew-url"),
    categoryLabel: document.getElementById("mircrew-category-label"),
    categoryValue: document.getElementById("mircrew-category-value"),
    enabled: document.getElementById("mircrew-enabled"),
    formMode: document.getElementById("mircrew-form-mode"),
    resetBtn: document.getElementById("mircrew-reset-btn"),
  };

  let pollTimer = null;
  let refreshing = false;
  let editingId = null;
  let cacheModal = null;

  const formatTimestamp = (value) => {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    const pad = (v) => String(v).padStart(2, "0");
    return `${pad(date.getDate())}/${pad(date.getMonth() + 1)}/${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  };

  const setCacheStatus = (count, updated) => {
    const formatted = formatTimestamp(updated);
    statusEl.textContent = formatted ? `Cache: ${count} release (agg. ${formatted})` : `Cache: ${count} release`;
  };

  const setRefreshButtonState = (running) => {
    refreshing = Boolean(running);
    refreshBtn.disabled = false;
    refreshBtn.innerHTML = running
      ? '<i class="bi bi-hourglass-split me-1"></i>Refresh in corso'
      : '<i class="bi bi-arrow-clockwise me-1"></i>Ricarica cache';
    if (cacheCancelBtn) {
      cacheCancelBtn.classList.toggle("d-none", !running);
      cacheCancelBtn.disabled = false;
    }
  };

  const getJobTitle = (jobType) => {
    if (jobType === "single_source_refresh") {
      return "Test lista";
    }
    return "Ricarica cache";
  };

  const showProgressModal = ({ title, message, showCancel = false }) => {
    cacheModal = cacheModalEl ? bootstrap.Modal.getOrCreateInstance(cacheModalEl) : null;
    if (cacheModalTitleEl) {
      cacheModalTitleEl.textContent = title || "Ricarica cache";
    }
    if (cacheProgressEl) {
      cacheProgressEl.textContent = message || "";
    }
    if (cacheCancelBtn) {
      cacheCancelBtn.classList.toggle("d-none", !showCancel);
      cacheCancelBtn.disabled = false;
    }
    cacheModal?.show();
  };

  const renderProgressText = (data) => {
    const processed = data.processed_sources || 0;
    const total = data.total_sources || 0;
    const source = data.current_source || "Inizializzazione";
    const page = data.current_page || 0;
    const totalPages = data.current_source_total_pages || 0;
    const pagesScanned = data.pages_scanned || 0;
    const seen = data.items_count || 0;
    const sourceNew = data.current_source_new_items || 0;
    const pageLabel = totalPages > 0 ? `${page}/${totalPages}` : `${page}`;
    const title = getJobTitle(data.job_type);
    if (data.cancelled) return `${title} annullato.`;
    if (data.error) return `${title} fallito: ${data.error}`;
    if (!data.running) return `${title} completato: ${seen} release in cache`;
    if (data.job_type === "single_source_refresh") {
      return `${source} • pagina ${pageLabel} • ${pagesScanned} pagine lette • +${sourceNew} nuove nella source • ${seen} release in cache`;
    }
    return `Liste ${processed}/${total} • ${source} • pagina ${pageLabel} • ${pagesScanned} pagine lette • +${sourceNew} nuove nella source • ${seen} release totali`;
  };

  const stopPolling = () => {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  };

  const pollRefreshStatus = async ({ openModal = false, scheduleNext = true } = {}) => {
    const res = await fetch("/api/mircrew/cache/progress");
    const data = await res.json();
    if (openModal) {
      cacheModal?.show();
    }
    if (cacheModalTitleEl) {
      cacheModalTitleEl.textContent = getJobTitle(data.job_type);
    }
    if (cacheProgressEl) {
      cacheProgressEl.textContent = renderProgressText(data);
    }
    setRefreshButtonState(data.running);
    if (!data.running) {
      stopPolling();
      setCacheStatus(data.items_count || 0, data.updated_at || "");
      return data;
    }
    if (scheduleNext && !pollTimer) {
      pollTimer = setInterval(async () => {
        try {
          await pollRefreshStatus();
        } catch {
          stopPolling();
          setRefreshButtonState(false);
          if (cacheProgressEl) cacheProgressEl.textContent = "Errore durante il polling dello stato.";
        }
      }, 1000);
    }
    return data;
  };

  const waitForRefreshCompletion = async ({ openModal = false } = {}) => {
    while (true) {
      const data = await pollRefreshStatus({ openModal, scheduleNext: false });
      if (!data.running) {
        return data;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  };

  const resetForm = () => {
    editingId = null;
    fields.id.value = "";
    fields.name.value = "";
    fields.url.value = "";
    fields.categoryLabel.value = "";
    fields.categoryValue.value = "";
    fields.enabled.value = "true";
    fields.formMode.textContent = "Nuova lista";
  };

  const renderSources = (items) => {
    if (!items.length) {
      sourcesBody.innerHTML = '<tr><td colspan="7" class="text-muted">Nessuna lista configurata.</td></tr>';
      return;
    }
    sourcesBody.innerHTML = items.map((source) => `
      <tr>
        <td>${source.name || ""}</td>
        <td class="small text-break">
          <a href="${source.url || ""}" target="_blank" rel="noopener">${source.url || ""}</a>
        </td>
        <td>${source.category_label || ""}</td>
        <td>${source.category_value || ""}</td>
        <td>${source.last_count ?? 0}</td>
        <td>${source.enabled ? "On" : "Off"}</td>
        <td class="text-end">
          <button class="btn btn-sm btn-outline-secondary me-1" data-action="test" data-id="${source.id}">Test</button>
          <button class="btn btn-sm btn-outline-primary me-1" data-action="edit" data-id="${source.id}">Modifica</button>
          <button class="btn btn-sm btn-outline-danger" data-action="delete" data-id="${source.id}">Rimuovi</button>
        </td>
      </tr>
    `).join("");
  };

  const loadSources = async () => {
    const res = await fetch("/api/mircrew/sources");
    const data = await res.json();
    renderSources(data.items || []);
  };

  const fetchCacheStatus = async () => {
    const res = await fetch("/api/mircrew/cache/status");
    const data = await res.json();
    setCacheStatus(data.count || 0, data.updated_at || "");
  };

  refreshBtn.addEventListener("click", async () => {
    cacheModal = cacheModalEl ? bootstrap.Modal.getOrCreateInstance(cacheModalEl) : null;
    if (refreshing) {
      try {
        await pollRefreshStatus({ openModal: true });
      } catch {
        if (cacheProgressEl) cacheProgressEl.textContent = "Errore durante il recupero dello stato.";
      }
      return;
    }
    showProgressModal({
      title: "Ricarica cache",
      message: "Avvio ricarica...",
      showCancel: true,
    });
    setRefreshButtonState(true);
      try {
        const startRes = await fetch("/api/mircrew/cache/refresh", { method: "POST" });
        const data = await startRes.json();
        if (!startRes.ok || data.ok === false) throw new Error(data.error || "refresh_failed");
        await waitForRefreshCompletion({ openModal: true });
      } catch {
        setRefreshButtonState(false);
        if (cacheProgressEl) cacheProgressEl.textContent = "Errore durante la ricarica.";
        await fetchCacheStatus();
    }
  });

  cacheCancelBtn?.addEventListener("click", async () => {
    cacheCancelBtn.disabled = true;
    try {
      await fetch("/api/mircrew/cache/cancel", { method: "POST" });
      if (cacheProgressEl) {
        cacheProgressEl.textContent = "Richiesta di annullamento inviata...";
      }
      await pollRefreshStatus();
    } catch {
      cacheCancelBtn.disabled = false;
      if (cacheProgressEl) {
        cacheProgressEl.textContent = "Errore durante l'annullamento del refresh.";
      }
    }
  });

  sourcesBody.addEventListener("click", async (event) => {
    const btn = event.target.closest("button[data-action]");
    if (!btn) return;
    const id = btn.dataset.id;
    const action = btn.dataset.action;
    if (action === "delete") {
      await fetch(`/api/mircrew/sources/${id}`, { method: "DELETE" });
      await loadSources();
      if (editingId === id) resetForm();
      return;
    }
    if (action === "test") {
      btn.disabled = true;
      const sourceLabel = btn.closest("tr")?.children?.[0]?.textContent?.trim() || `lista #${id}`;
      showProgressModal({
        title: "Test lista",
        message: `Avvio test: ${sourceLabel}...`,
        showCancel: true,
      });
      try {
        const res = await fetch(`/api/mircrew/sources/${id}/test`, { method: "POST" });
        const data = await res.json();
        if (!res.ok || data.ok === false) {
          throw new Error(data.message || data.error || "Errore");
        }
        await waitForRefreshCompletion({ openModal: true });
      } finally {
        btn.disabled = false;
      }
      await loadSources();
      await fetchCacheStatus();
      return;
    }
    if (action === "edit") {
      const res = await fetch("/api/mircrew/sources");
      const data = await res.json();
      const source = (data.items || []).find((item) => String(item.id) === String(id));
      if (!source) return;
      editingId = String(source.id);
      fields.id.value = source.id;
      fields.name.value = source.name || "";
      fields.url.value = source.url || "";
      fields.categoryLabel.value = source.category_label || "";
      fields.categoryValue.value = source.category_value || "";
      fields.enabled.value = source.enabled ? "true" : "false";
      fields.formMode.textContent = `Modifica lista #${source.id}`;
    }
  });

  sourceForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      name: fields.name.value.trim(),
      url: fields.url.value.trim(),
      category_label: fields.categoryLabel.value.trim(),
      category_value: fields.categoryValue.value.trim(),
      enabled: fields.enabled.value === "true",
    };
    const isEdit = Boolean(editingId);
    const endpoint = isEdit ? `/api/mircrew/sources/${editingId}` : "/api/mircrew/sources";
    await fetch(endpoint, {
      method: isEdit ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    resetForm();
    await loadSources();
  });

  fields.resetBtn?.addEventListener("click", resetForm);

  document.addEventListener("click", async (event) => {
    const btn = event.target.closest(".mircrew-detail-btn");
    if (!btn || !detailModalEl) return;
    const modal = bootstrap.Modal.getOrCreateInstance(detailModalEl);
    const releaseId = btn.dataset.releaseId;
    const releaseTitle = btn.dataset.releaseTitle || "Dettaglio release";
    detailTitleEl.textContent = releaseTitle;
    detailMetaEl.textContent = "";
    detailErrorEl.classList.add("d-none");
    detailErrorEl.textContent = "";
    detailMagnetsEl.innerHTML = "";
    detailTorrentsEl.innerHTML = "";
    detailLoadingEl.classList.remove("d-none");
    detailContentEl.classList.add("d-none");
    modal.show();
    try {
      const res = await fetch(`/api/mircrew/release?release_id=${encodeURIComponent(releaseId)}`);
      const data = await res.json();
      if (!res.ok || data.ok === false) {
        throw new Error(data.message || data.error || "lookup_failed");
      }
      detailMetaEl.textContent = `cache_hit=${data.cache_hit ? "yes" : "no"} • thanks=${data.thanks_required ? (data.thanks_clicked ? "clicked" : "required") : "not_required"} • size=${data.size_text_raw || data.size_bytes || "-"}`;
      const renderLinks = (container, links) => {
        container.innerHTML = (links || []).length
          ? links.map((link, idx) => `<a class="list-group-item list-group-item-action small text-break" href="${link}" target="_blank" rel="noopener">${idx + 1}. ${link}</a>`).join("")
          : '<div class="text-muted small">Nessun link trovato.</div>';
      };
      renderLinks(detailMagnetsEl, data.magnet_links);
      renderLinks(detailTorrentsEl, data.torrent_links);
    } catch (err) {
      detailErrorEl.textContent = String(err.message || err);
      detailErrorEl.classList.remove("d-none");
    } finally {
      detailLoadingEl.classList.add("d-none");
      detailContentEl.classList.remove("d-none");
    }
  });

  resetForm();
  fetchCacheStatus();
  loadSources();
  cacheModal = cacheModalEl ? bootstrap.Modal.getOrCreateInstance(cacheModalEl) : null;
  pollRefreshStatus().catch(() => setRefreshButtonState(false));
})();
