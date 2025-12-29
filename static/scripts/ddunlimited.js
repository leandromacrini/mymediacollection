(() => {
  const modal = document.getElementById("ddunlimitedSourcesModal");
  if (!modal) {
    return;
  }

  const body = document.getElementById("ddu-sources-body");
  const form = document.getElementById("ddu-source-form");
  const resetBtn = document.getElementById("ddu-reset");
  const newBtn = document.getElementById("ddu-new");
  const filterInput = document.getElementById("ddu-filter");
  const testAllBtn = document.getElementById("ddu-test-all");
  const idInput = document.getElementById("ddu-source-id");
  const nameInput = document.getElementById("ddu-name");
  const mediaTypeInput = document.getElementById("ddu-media-type");
  const categoryInput = document.getElementById("ddu-category");
  const enabledInput = document.getElementById("ddu-enabled");
  const urlInput = document.getElementById("ddu-url");
  const qualityInput = document.getElementById("ddu-quality");
  const languageInput = document.getElementById("ddu-language");
  const formMode = document.getElementById("ddu-form-mode");
  const saveBtn = document.getElementById("ddu-save-btn");
  const saveContinueBtn = document.getElementById("ddu-save-continue-btn");
  const updateBtn = document.getElementById("ddu-update-btn");

  let sources = [];
  const testingIds = new Set();
  let filterTerm = "";

  const setEditMode = (enabled) => {
    if (enabled) {
      formMode.textContent = "Modifica lista";
      saveBtn.classList.add("d-none");
      saveContinueBtn.classList.add("d-none");
      updateBtn.classList.remove("d-none");
    } else {
      formMode.textContent = "Nuova lista";
      saveBtn.classList.remove("d-none");
      saveContinueBtn.classList.remove("d-none");
      updateBtn.classList.add("d-none");
    }
  };

  const resetForm = () => {
    idInput.value = "";
    form.reset();
    setEditMode(false);
  };

  const renderRows = () => {
    const term = filterTerm.trim().toLowerCase();
    const filtered = term
      ? sources.filter(source => {
          const haystack = `${source.name || ""} ${source.url || ""} ${source.media_type || ""}`.toLowerCase();
          return haystack.includes(term);
        })
      : sources;
    if (!filtered.length) {
      body.innerHTML = '<tr><td colspan="6" class="text-muted">Nessuna lista configurata.</td></tr>';
      return;
    }
    body.innerHTML = filtered.map(source => {
      const safeUrl = source.url || "";
      const enabledText = source.enabled ? "Si" : "No";
      const countText = Number.isFinite(source.last_count) ? source.last_count : "-";
      const isTesting = testingIds.has(source.id);
      const testContent = isTesting
        ? '<span class="spinner-border spinner-border-sm me-1"></span>Test'
        : '<i class="bi bi-activity me-1"></i>Test';
      return `
        <tr>
          <td>${source.name || ""}</td>
          <td>${source.media_type || ""}</td>
          <td class="text-truncate" style="max-width: 320px;">
            <a href="${safeUrl}" target="_blank" rel="noopener">${safeUrl}</a>
          </td>
          <td>${countText}</td>
          <td>${enabledText}</td>
          <td class="text-end">
            <button class="btn btn-sm btn-outline-secondary me-1 ddu-action-btn" data-action="test" data-id="${source.id}" ${isTesting ? "disabled" : ""}>${testContent}</button>
            <button class="btn btn-sm btn-outline-primary me-1 ddu-action-btn" data-action="edit" data-id="${source.id}" ${isTesting ? "disabled" : ""}><i class="bi bi-pencil-square me-1"></i>Modifica</button>
            <button class="btn btn-sm btn-outline-danger ddu-action-btn" data-action="delete" data-id="${source.id}" ${isTesting ? "disabled" : ""}><i class="bi bi-trash me-1"></i>Rimuovi</button>
          </td>
        </tr>
      `;
    }).join("");
  };

  const loadSources = async () => {
    body.innerHTML = '<tr><td colspan="5" class="text-muted">Caricamento...</td></tr>';
    try {
      const res = await fetch("/api/ddunlimited/sources");
      const data = await res.json();
      sources = data.items || [];
      renderRows();
    } catch (err) {
      body.innerHTML = '<tr><td colspan="5" class="text-danger">Errore caricamento liste.</td></tr>';
    }
  };

  const handleEdit = (id) => {
    const source = sources.find(item => item.id === id);
    if (!source) {
      return;
    }
    idInput.value = source.id;
    nameInput.value = source.name || "";
    mediaTypeInput.value = source.media_type || "movie";
    categoryInput.value = source.category || "";
    enabledInput.value = source.enabled ? "true" : "false";
    urlInput.value = source.url || "";
    qualityInput.value = source.quality || "";
    languageInput.value = source.language || "";
    setEditMode(true);
  };

  const handleDelete = async (id) => {
    if (!confirm("Rimuovere questa lista?")) {
      return;
    }
    try {
      await fetch(`/api/ddunlimited/sources/${id}`, { method: "DELETE" });
      await loadSources();
    } catch (err) {
      alert("Errore durante la rimozione.");
    }
  };

  const handleTest = async (id) => {
    if (testingIds.has(id)) {
      return;
    }
    testingIds.add(id);
    renderRows();
    try {
      const res = await fetch(`/api/ddunlimited/sources/${id}/test`, { method: "POST" });
      const data = await res.json();
      if (data.ok) {
        const idx = sources.findIndex(item => item.id === id);
        if (idx >= 0) {
          sources[idx].last_count = data.count;
        }
      }
    } catch (err) {
      alert("Errore durante il test.");
    } finally {
      testingIds.delete(id);
      renderRows();
    }
  };

  body.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const action = target.dataset.action;
    const id = Number(target.dataset.id);
    if (!action || !id) {
      return;
    }
    if (action === "edit") {
      handleEdit(id);
    } else if (action === "test") {
      handleTest(id);
    } else if (action === "delete") {
      handleDelete(id);
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submitter = event.submitter;
    const action = submitter?.dataset?.action || "add";
    const payload = {
      name: nameInput.value.trim(),
      url: urlInput.value.trim(),
      media_type: mediaTypeInput.value,
      category: categoryInput.value.trim(),
      quality: qualityInput.value.trim(),
      language: languageInput.value.trim(),
      enabled: enabledInput.value === "true"
    };
    const id = idInput.value;
    const isEdit = Boolean(id) || action === "update";
    const method = isEdit ? "PUT" : "POST";
    const endpoint = isEdit ? `/api/ddunlimited/sources/${id}` : "/api/ddunlimited/sources";
    try {
      const res = await fetch(endpoint, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        if (res.status === 409) {
          alert("Esiste gia una lista con questo URL.");
          return;
        }
        throw new Error("Request failed");
      }
      if (isEdit || action === "add") {
        resetForm();
      } else {
        idInput.value = "";
        setEditMode(false);
        urlInput.focus();
        urlInput.select();
      }
      await loadSources();
    } catch (err) {
      alert("Errore durante il salvataggio.");
    }
  });

  resetBtn.addEventListener("click", () => resetForm());
  newBtn.addEventListener("click", () => resetForm());
  filterInput.addEventListener("input", (event) => {
    filterTerm = event.target.value || "";
    renderRows();
  });
  testAllBtn.addEventListener("click", async () => {
    const term = filterTerm.trim().toLowerCase();
    const list = (term
      ? sources.filter(source => {
          const haystack = `${source.name || ""} ${source.url || ""} ${source.media_type || ""}`.toLowerCase();
          return haystack.includes(term);
        })
      : sources
    ).filter(source => source.enabled);
    if (!list.length) {
      return;
    }
    testAllBtn.disabled = true;
    const originalLabel = testAllBtn.innerHTML;
    for (let i = 0; i < list.length; i += 1) {
      testAllBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>Test ${i + 1}/${list.length}`;
      await handleTest(list[i].id);
    }
    testAllBtn.innerHTML = originalLabel;
    testAllBtn.disabled = false;
  });
  modal.addEventListener("shown.bs.modal", () => loadSources());
  setEditMode(false);
})();
