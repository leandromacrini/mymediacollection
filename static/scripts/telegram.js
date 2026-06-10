(function () {
  const dataEl = document.getElementById("telegram-preview-data");
  if (!dataEl) return;

  const MAX_RELEASE_ROWS = 400;
  const MAX_MESSAGE_ROWS = 500;
  const state = JSON.parse(dataEl.textContent);
  const releaseIndex = new Map();
  const messageIndex = new Map();
  const messageOrder = [];
  let selectedReleaseId = state.preview_releases[0]?.preview_id || null;
  let selectedMessages = new Set();

  const releaseListEl = document.getElementById("telegram-release-list");
  const selectedReleaseEditorEl = document.getElementById("telegram-selected-release-editor");
  const releaseSummaryEl = document.getElementById("telegram-release-summary");
  const releaseMessageBodyEl = document.getElementById("telegram-release-message-body");
  const releaseFilterEl = document.getElementById("telegram-release-filter");
  const releaseSearchEl = document.getElementById("telegram-release-search");
  const messageBodyEl = document.getElementById("telegram-message-body");
  const messageFilterEl = document.getElementById("telegram-message-filter");
  const messageSearchEl = document.getElementById("telegram-message-search");
  const contextWindowEl = document.getElementById("telegram-context-window");
  const selectionStatusEl = document.getElementById("telegram-selection-status");
  const payloadEl = document.getElementById("telegram-preview-payload");
  const confirmFormEl = document.getElementById("telegram-preview-confirm-form");
  const checkAllEl = document.getElementById("telegram-check-all");

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function rebuildIndexes() {
    releaseIndex.clear();
    for (const release of state.preview_releases || []) {
      releaseIndex.set(release.preview_id, release);
    }
    messageIndex.clear();
    messageOrder.length = 0;
    for (const message of state.messages || []) {
      const key = Number(message.message_id);
      messageIndex.set(key, message);
      messageOrder.push(key);
    }
  }

  function selectedRelease() {
    return releaseIndex.get(selectedReleaseId) || null;
  }

  function releaseLabel(releaseId) {
    const release = releaseIndex.get(releaseId);
    return release ? (release.title_display || release.title_normalized || release.preview_id) : "Nessuna";
  }

  function statusBadgeClass(status) {
    if (status === "new") return "text-bg-success";
    if (status === "updated") return "text-bg-warning";
    if (status === "removed") return "text-bg-danger";
    return "text-bg-secondary";
  }

  function messageStatusBadgeClass(status) {
    if (status === "newly_assigned") return "text-bg-success";
    if (status === "moved") return "text-bg-warning";
    if (status === "removed") return "text-bg-danger";
    if (status === "context") return "text-bg-info";
    if (status === "unassigned") return "text-bg-secondary";
    return "text-bg-light";
  }

  function refreshDerived() {
    const messageIdsByRelease = new Map();
    for (const release of state.preview_releases || []) {
      messageIdsByRelease.set(release.preview_id, []);
    }

    for (const message of state.messages || []) {
      if (!message.preview_release_id) continue;
      if (!messageIdsByRelease.has(message.preview_release_id)) {
        messageIdsByRelease.set(message.preview_release_id, []);
      }
      messageIdsByRelease.get(message.preview_release_id).push(Number(message.message_id));
    }

    for (const release of state.preview_releases || []) {
      const ids = (messageIdsByRelease.get(release.preview_id) || []).sort((a, b) => a - b);
      release.message_ids = ids;
      release.linked_messages = ids.length;
      release.first_message_id = ids[0] || null;
      release.last_message_id = ids[ids.length - 1] || null;

      let mediaCount = 0;
      let totalSizeBytes = 0;
      let firstDate = null;
      let lastDate = null;
      for (const messageId of ids) {
        const message = messageIndex.get(messageId);
        if (!message) continue;
        if (message.has_media) mediaCount += 1;
        totalSizeBytes += Number(message.file_size || 0);
        if (message.message_date) {
          if (!firstDate || message.message_date < firstDate) firstDate = message.message_date;
          if (!lastDate || message.message_date > lastDate) lastDate = message.message_date;
        }
      }
      release.media_count = mediaCount;
      release.total_size_bytes = totalSizeBytes;
      release.published_at = firstDate;
      release.updated_source_at = lastDate;
    }
  }

  function recomputeStatuses() {
    const removedIds = new Set((state.removed_releases || []).map((row) => Number(row.id)));
    let newCount = 0;
    let updatedCount = 0;
    let unchangedCount = 0;
    for (const release of state.preview_releases || []) {
      if (!release.matched_db_release_id) {
        release.status = "new";
        newCount += 1;
        continue;
      }
      if (removedIds.has(Number(release.matched_db_release_id))) {
        removedIds.delete(Number(release.matched_db_release_id));
      }
      const fromDb =
        release.title_display_source === "db" &&
        release.year_guess_source === "db" &&
        release.release_kind_source === "db";
      release.status = fromDb ? "unchanged" : "updated";
      if (release.status === "updated") updatedCount += 1;
      else unchangedCount += 1;
    }
    state.summary = Object.assign({}, state.summary || {}, {
      new: newCount,
      updated: updatedCount,
      unchanged: unchangedCount,
      removed: removedIds.size,
      preview_total: (state.preview_releases || []).length,
    });
  }

  function visibleReleases() {
    const filter = releaseFilterEl?.value || "changed";
    const search = (releaseSearchEl?.value || "").trim().toLowerCase();
    return (state.preview_releases || [])
      .filter((release) => {
        if (filter === "changed" && !["new", "updated"].includes(release.status)) return false;
        if (filter === "new" && release.status !== "new") return false;
        if (filter === "updated" && release.status !== "updated") return false;
        if (filter === "unchanged" && release.status !== "unchanged") return false;
        if (search) {
          const haystack = [
            release.title_display,
            release.title_normalized,
            release.forward_title_dominant,
            release.release_kind,
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
          if (!haystack.includes(search)) return false;
        }
        return true;
      })
      .slice(0, MAX_RELEASE_ROWS);
  }

  function getSelectedReleaseMessageIds() {
    const release = selectedRelease();
    return new Set((release?.message_ids || []).map(Number));
  }

  function visibleMessages() {
    const filter = messageFilterEl?.value || "selected_context";
    const search = (messageSearchEl?.value || "").trim().toLowerCase();
    const contextWindow = Number(contextWindowEl?.value || 10);
    const selectedIds = getSelectedReleaseMessageIds();
    const selectedRows = [];
    const contextIds = new Set();

    if (selectedIds.size) {
      const selectedIndexes = [];
      for (let i = 0; i < messageOrder.length; i += 1) {
        if (selectedIds.has(messageOrder[i])) selectedIndexes.push(i);
      }
      for (const index of selectedIndexes) {
        for (let offset = -contextWindow; offset <= contextWindow; offset += 1) {
          const neighbor = messageOrder[index + offset];
          if (neighbor != null) contextIds.add(neighbor);
        }
      }
    }

    for (const message of state.messages || []) {
      const messageId = Number(message.message_id);
      let include = false;
      let renderStatus = message.status;

      if (filter === "selected") include = selectedIds.has(messageId);
      else if (filter === "selected_context") include = contextIds.has(messageId);
      else if (filter === "changed") include = ["newly_assigned", "moved", "removed"].includes(message.status);
      else if (filter === "unassigned") include = !message.preview_release_id;
      else include = true;

      if (!include) continue;
      if (filter === "selected_context" && !selectedIds.has(messageId)) {
        renderStatus = "context";
      }

      if (search) {
        const haystack = [
          message.file_name,
          message.text_raw,
          message.title_guess,
          message.title_guess_normalized,
          releaseLabel(message.preview_release_id),
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(search)) continue;
      }

      selectedRows.push(Object.assign({}, message, { render_status: renderStatus }));
    }

    return selectedRows.slice(0, MAX_MESSAGE_ROWS);
  }

  function renderReleaseList() {
    const releases = visibleReleases();
    releaseListEl.innerHTML = "";
    if (!releases.length) {
      releaseListEl.innerHTML = '<div class="text-muted">Nessuna release con i filtri correnti.</div>';
      return;
    }

    for (const release of releases) {
      const item = document.createElement("div");
      item.className = `telegram-release-item ${selectedReleaseId === release.preview_id ? "is-selected" : ""}`;
      item.innerHTML = `
        <div class="d-flex align-items-start justify-content-between gap-2">
          <button type="button" class="telegram-release-select btn btn-link p-0 text-start text-decoration-none flex-grow-1">
            <div class="fw-semibold">${escapeHtml(release.title_display || release.title_normalized || "Release senza titolo")}</div>
            <div class="telegram-results-info">norm: ${escapeHtml(release.title_normalized || "-")}</div>
            <div class="telegram-results-info">msg: ${release.linked_messages || 0} | media: ${release.media_count || 0}</div>
          </button>
          <span class="badge ${statusBadgeClass(release.status)}">${escapeHtml(release.status)}</span>
        </div>
      `;
      item.querySelector(".telegram-release-select")?.addEventListener("click", () => {
        selectedReleaseId = release.preview_id;
        renderAll();
      });
      releaseListEl.appendChild(item);
    }
  }

  function renderSelectedReleaseEditor() {
    const release = selectedRelease();
    if (!release) {
      selectedReleaseEditorEl.innerHTML = '<div class="text-muted">Nessuna release selezionata.</div>';
      releaseSummaryEl.textContent = "";
      return;
    }

    releaseSummaryEl.textContent = `${release.status} | ${release.linked_messages || 0} messaggi | ${release.media_count || 0} media`;
    selectedReleaseEditorEl.innerHTML = `
      <div class="row g-2">
        <div class="col-12">
          <label class="form-label form-label-sm mb-1">Titolo</label>
          <input class="form-control form-control-sm" id="telegram-selected-release-title" value="${escapeHtml(release.title_display || "")}" placeholder="Titolo release">
        </div>
        <div class="col-4">
          <label class="form-label form-label-sm mb-1">Anno</label>
          <input class="form-control form-control-sm" id="telegram-selected-release-year" value="${escapeHtml(release.year_guess ?? "")}" placeholder="Anno">
        </div>
        <div class="col-4">
          <label class="form-label form-label-sm mb-1">Kind</label>
          <select class="form-select form-select-sm" id="telegram-selected-release-kind">
            ${["movie", "series", "anime", "special", "unknown"].map((kind) => `<option value="${kind}" ${release.release_kind === kind ? "selected" : ""}>${kind}</option>`).join("")}
          </select>
        </div>
        <div class="col-4">
          <label class="form-label form-label-sm mb-1">Season</label>
          <input class="form-control form-control-sm" id="telegram-selected-release-season" value="${escapeHtml(release.season_guess ?? "")}" placeholder="Season">
        </div>
        <div class="col-12">
          <label class="form-label form-label-sm mb-1">Note</label>
          <input class="form-control form-control-sm" id="telegram-selected-release-notes" value="${escapeHtml(release.notes || "")}" placeholder="Note release">
        </div>
      </div>
    `;

    document.getElementById("telegram-selected-release-title")?.addEventListener("input", (event) => {
      release.title_display = event.target.value.trim() || null;
      release.title_display_source = "user";
      renderReleaseList();
    });
    document.getElementById("telegram-selected-release-year")?.addEventListener("input", (event) => {
      const value = event.target.value.trim();
      release.year_guess = /^\d+$/.test(value) ? Number(value) : null;
      release.year_guess_source = "user";
    });
    document.getElementById("telegram-selected-release-kind")?.addEventListener("change", (event) => {
      release.release_kind = event.target.value || null;
      release.release_kind_source = "user";
      renderReleaseList();
    });
    document.getElementById("telegram-selected-release-season")?.addEventListener("input", (event) => {
      const value = event.target.value.trim();
      release.season_guess = /^\d+$/.test(value) ? Number(value) : null;
    });
    document.getElementById("telegram-selected-release-notes")?.addEventListener("input", (event) => {
      release.notes = event.target.value.trim() || null;
    });
  }

  function releaseOptionsHtml(selectedValue) {
    return [
      '<option value="">Nessuna</option>',
      ...(state.preview_releases || []).map((release) => `<option value="${release.preview_id}" ${release.preview_id === selectedValue ? "selected" : ""}>${escapeHtml(releaseLabel(release.preview_id))}</option>`),
    ].join("");
  }

  function renderMessageRow(message, includeCheckbox) {
    return `
      <tr class="telegram-message-row telegram-message-${escapeHtml(message.render_status || message.status || "")}">
        ${includeCheckbox ? `<td><input type="checkbox" class="telegram-message-check" data-message-id="${message.message_id}" ${selectedMessages.has(Number(message.message_id)) ? "checked" : ""}></td>` : ""}
        <td>
          <div>${message.message_id}</div>
          <div class="telegram-subline">${message.message_date ? String(message.message_date).slice(0, 16).replace("T", " ") : "-"}</div>
        </td>
        <td><span class="badge ${messageStatusBadgeClass(message.render_status || message.status)}">${escapeHtml(message.render_status || message.status || "")}</span></td>
        <td>
          <select class="form-select form-select-sm telegram-message-release" data-message-id="${message.message_id}">
            ${releaseOptionsHtml(message.preview_release_id || "")}
          </select>
        </td>
        <td>
          <div class="fw-semibold">${escapeHtml(message.file_name || message.title_guess || "Messaggio")}</div>
          <div class="telegram-results-info">${escapeHtml(message.text_raw || "")}</div>
          <div class="telegram-results-info">guess: ${escapeHtml(message.title_guess_normalized || "-")} | media=${message.has_media ? "yes" : "no"} | video=${message.is_video_like ? "yes" : "no"}</div>
        </td>
      </tr>
    `;
  }

  function attachMessageRowHandlers(scopeRoot) {
    scopeRoot.querySelectorAll(".telegram-message-check").forEach((checkbox) => {
      checkbox.addEventListener("change", (event) => {
        const messageId = Number(event.target.dataset.messageId);
        if (event.target.checked) selectedMessages.add(messageId);
        else selectedMessages.delete(messageId);
        updateSelectionStatus();
      });
    });
    scopeRoot.querySelectorAll(".telegram-message-release").forEach((select) => {
      select.addEventListener("change", (event) => {
        const messageId = Number(event.target.dataset.messageId);
        const message = messageIndex.get(messageId);
        if (!message) return;
        const previous = message.preview_release_id || null;
        const next = event.target.value || null;
        message.preview_release_id = next;
        if (!previous && next) message.status = "newly_assigned";
        else if (previous && !next) message.status = "unassigned";
        else if (previous !== next) message.status = "moved";
        else message.status = previous ? "existing" : "unassigned";
        renderAll();
      });
    });
  }

  function renderSelectedReleaseMessages() {
    const release = selectedRelease();
    const rows = (state.messages || [])
      .filter((message) => message.preview_release_id === release?.preview_id)
      .map((message) => Object.assign({}, message, { render_status: message.status }))
      .slice(0, MAX_MESSAGE_ROWS);
    releaseMessageBodyEl.innerHTML = rows.map((message) => renderMessageRow(message, false)).join("");
    attachMessageRowHandlers(releaseMessageBodyEl);
  }

  function renderMessagesTab() {
    const rows = visibleMessages();
    messageBodyEl.innerHTML = rows.map((message) => renderMessageRow(message, true)).join("");
    attachMessageRowHandlers(messageBodyEl);
    updateSelectionStatus(rows.length);
  }

  function updateSelectionStatus(visibleCount = null) {
    const parts = [`${selectedMessages.size} messaggi selezionati`];
    if (visibleCount != null) parts.push(`visibili: ${visibleCount}`);
    selectionStatusEl.textContent = parts.join(" | ");
  }

  function assignSelectedTo(releaseId) {
    if (!releaseId) return;
    for (const messageId of selectedMessages) {
      const message = messageIndex.get(Number(messageId));
      if (!message) continue;
      const previous = message.preview_release_id || null;
      message.preview_release_id = releaseId;
      if (!previous) message.status = "newly_assigned";
      else if (previous !== releaseId) message.status = "moved";
      else message.status = "existing";
    }
    renderAll();
  }

  function unassignSelected() {
    for (const messageId of selectedMessages) {
      const message = messageIndex.get(Number(messageId));
      if (!message) continue;
      message.preview_release_id = null;
      message.status = "unassigned";
    }
    renderAll();
  }

  function createReleaseFromSelected() {
    const selectedIds = Array.from(selectedMessages);
    if (!selectedIds.length) return;
    const seed = messageIndex.get(Number(selectedIds[0]));
    const previewId = `preview-${Date.now()}`;
    state.preview_releases.unshift({
      preview_id: previewId,
      status: "new",
      matched_db_release_id: null,
      title_display: seed?.title_guess || `Nuova release ${state.preview_releases.length + 1}`,
      title_display_source: "user",
      title_raw: seed?.title_guess || null,
      title_normalized: seed?.title_guess_normalized || null,
      release_kind: seed?.release_kind_guess || "unknown",
      release_kind_source: "preview",
      forward_title_dominant: seed?.forward_chat_title || null,
      year_guess: seed?.year_guess || null,
      year_guess_source: "preview",
      season_guess: seed?.season_guess || null,
      media_count: 0,
      linked_messages: 0,
      total_size_bytes: 0,
      release_key: null,
      source_ref: seed ? `telegram:${seed.channel_id || ""}:${seed.message_id}` : null,
      notes: null,
      message_ids: [],
    });
    selectedReleaseId = previewId;
    assignSelectedTo(previewId);
  }

  function deleteSelectedRelease() {
    const release = selectedRelease();
    if (!release) return;
    state.preview_releases.splice(state.preview_releases.findIndex((row) => row.preview_id === release.preview_id), 1);
    for (const message of state.messages || []) {
      if (message.preview_release_id === release.preview_id) {
        message.preview_release_id = null;
        message.status = "unassigned";
      }
    }
    selectedReleaseId = state.preview_releases[0]?.preview_id || null;
    renderAll();
  }

  function renderAll() {
    rebuildIndexes();
    refreshDerived();
    recomputeStatuses();
    renderReleaseList();
    renderSelectedReleaseEditor();
    renderSelectedReleaseMessages();
    renderMessagesTab();
  }

  releaseFilterEl?.addEventListener("change", renderReleaseList);
  releaseSearchEl?.addEventListener("input", renderReleaseList);
  messageFilterEl?.addEventListener("change", renderMessagesTab);
  messageSearchEl?.addEventListener("input", renderMessagesTab);
  contextWindowEl?.addEventListener("change", renderMessagesTab);

  document.getElementById("telegram-add-release")?.addEventListener("click", createReleaseFromSelected);
  document.getElementById("telegram-delete-release")?.addEventListener("click", deleteSelectedRelease);
  document.getElementById("telegram-select-visible")?.addEventListener("click", () => {
    for (const row of visibleMessages()) selectedMessages.add(Number(row.message_id));
    renderMessagesTab();
  });
  document.getElementById("telegram-clear-selection")?.addEventListener("click", () => {
    selectedMessages.clear();
    renderMessagesTab();
  });
  document.getElementById("telegram-assign-selected")?.addEventListener("click", () => assignSelectedTo(selectedReleaseId));
  document.getElementById("telegram-unassign-selected")?.addEventListener("click", unassignSelected);
  document.getElementById("telegram-create-from-selected")?.addEventListener("click", createReleaseFromSelected);
  checkAllEl?.addEventListener("change", (event) => {
    for (const row of visibleMessages()) {
      if (event.target.checked) selectedMessages.add(Number(row.message_id));
      else selectedMessages.delete(Number(row.message_id));
    }
    renderMessagesTab();
  });

  confirmFormEl?.addEventListener("submit", () => {
    refreshDerived();
    payloadEl.value = JSON.stringify({
      preview_releases: (state.preview_releases || []).map((release) => ({
        ...release,
        published_at: release.published_at || null,
        updated_source_at: release.updated_source_at || null,
      })),
    });
  });

  renderAll();

  if (dataEl.dataset.openPreview === "1" && window.bootstrap) {
    const modalEl = document.getElementById("telegramPreviewModal");
    if (modalEl) {
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      modal.show();
    }
  }
})();
