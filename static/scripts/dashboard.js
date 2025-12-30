document.addEventListener("DOMContentLoaded", () => {
  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = value;
    }
  };

  const formatDate = (value) => {
    if (!value) {
      return "-";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    const pad = (num) => String(num).padStart(2, "0");
    const day = pad(date.getDate());
    const month = pad(date.getMonth() + 1);
    const year = date.getFullYear();
    const hours = pad(date.getHours());
    const minutes = pad(date.getMinutes());
    return `${day}/${month}/${year} ${hours}:${minutes}`;
  };

  const renderLastImports = (items) => {
    const body = document.getElementById("dashboard-last-imports");
    if (!body) {
      return;
    }
    if (!items || !items.length) {
      body.innerHTML = '<tr><td colspan="3" class="text-muted">No imports yet</td></tr>';
      return;
    }
    body.innerHTML = items.map((item) => {
      const title = item.title || "-";
      const source = item.source || "-";
      const imported = formatDate(item.created_at);
      return `<tr><td>${title}</td><td>${source}</td><td>${imported}</td></tr>`;
    }).join("");
  };

  const renderWantedList = (id, items, emptyLabel) => {
    const list = document.getElementById(id);
    if (!list) {
      return;
    }
    if (!items || !items.length) {
      list.innerHTML = `<li class="list-group-item text-muted">${emptyLabel}</li>`;
      return;
    }
    list.innerHTML = items.map((item) => {
      const year = item.year ? ` (${item.year})` : "";
      const title = `${item.title || "-"}${year}`;
      return (
        '<li class="list-group-item d-flex justify-content-between align-items-center">' +
        `<span>${title}</span>` +
        '<span class="badge bg-warning text-dark">Missing</span>' +
        "</li>"
      );
    }).join("");
  };

  fetch("/api/dashboard/data")
    .then((response) => response.json())
    .then((data) => {
      const counts = data.counts || {};
      const radarr = data.radarr_info || {};
      const sonarr = data.sonarr_info || {};
      const wantedSources = data.wanted_sources || {};

      setText("dashboard-total", counts.total ?? "0");
      setText("dashboard-present", counts.present ?? "0");
      setText("dashboard-missing", counts.missing ?? "0");

      setText("dashboard-radarr-total", radarr.total ?? "0");
      setText("dashboard-radarr-monitored", radarr.monitored ?? "0");
      setText("dashboard-radarr-downloaded", radarr.downloaded ?? "0");

      setText("dashboard-sonarr-total", sonarr.total ?? "0");
      setText("dashboard-sonarr-monitored", sonarr.monitored ?? "0");
      setText("dashboard-sonarr-downloaded", sonarr.downloaded ?? "0");

      setText("dashboard-wanted-aw", wantedSources.animeworld ?? "0");
      setText("dashboard-wanted-ddu", wantedSources.ddunlimited ?? "0");
      setText("dashboard-wanted-plex", wantedSources.plex_db ?? "0");
      setText("dashboard-wanted-text", wantedSources.text ?? "0");

      renderLastImports(data.last_imports || []);
      renderWantedList("dashboard-wanted-movies", data.wanted_movies || [], "No missing movies");
      renderWantedList("dashboard-wanted-series", data.wanted_series || [], "No missing series");

      const loading = document.getElementById("dashboard-loading");
      if (loading) {
        loading.classList.add("d-none");
      }
    })
    .catch(() => {
      renderLastImports([]);
      renderWantedList("dashboard-wanted-movies", [], "No missing movies");
      renderWantedList("dashboard-wanted-series", [], "No missing series");
      setText("dashboard-total", "0");
      setText("dashboard-present", "0");
      setText("dashboard-missing", "0");
      setText("dashboard-radarr-total", "0");
      setText("dashboard-radarr-monitored", "0");
      setText("dashboard-radarr-downloaded", "0");
      setText("dashboard-sonarr-total", "0");
      setText("dashboard-sonarr-monitored", "0");
      setText("dashboard-sonarr-downloaded", "0");
      setText("dashboard-wanted-aw", "0");
      setText("dashboard-wanted-ddu", "0");
      setText("dashboard-wanted-plex", "0");
      setText("dashboard-wanted-text", "0");

      const loading = document.getElementById("dashboard-loading");
      if (loading) {
        loading.innerHTML = '<i class="bi bi-exclamation-triangle me-1"></i>Errore nel caricamento.';
      }
    });
});
