(() => {
  const modalEl = document.getElementById("dduEd2kModal");
  if (!modalEl) {
    return;
  }
  const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  const titleEl = document.getElementById("ddu-ed2k-title");
  const loadingEl = modalEl.querySelector(".ddu-ed2k-loading");
  const contentEl = modalEl.querySelector(".ddu-ed2k-content");
  const linksEl = document.getElementById("ddu-ed2k-links");
  const listingWrap = modalEl.querySelector(".ddu-listing-info");
  const listingEl = document.getElementById("ddu-ed2k-listing");
  const countEl = document.getElementById("ddu-ed2k-count");
  const copyBtn = document.getElementById("ddu-ed2k-copy");
  const manualWrap = document.getElementById("ddu-ed2k-manual");
  const manualTextarea = document.getElementById("ddu-ed2k-textarea");
  let lastLinks = [];

  const escapeHtml = (value) => (
    String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;")
  );

  const formatSize = (raw) => {
    const bytes = Number(raw);
    if (!Number.isFinite(bytes) || bytes <= 0) {
      return "";
    }
    const units = ["B", "KB", "MB", "GB", "TB"];
    let idx = 0;
    let value = bytes;
    while (value >= 1024 && idx < units.length - 1) {
      value /= 1024;
      idx += 1;
    }
    return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[idx]}`;
  };

  const formatEd2kLabel = (item) => {
    const name = item?.name || "file";
    let label = `ed2k: ${name}`;
    const maxLen = 92;
    if (label.length > maxLen) {
      return `${label.slice(0, maxLen - 3)}...`;
    }
    return label;
  };

  const renderLinks = (items) => {
    lastLinks = items || [];
    if (countEl) {
      const count = lastLinks.length;
      countEl.textContent = count ? `${count} link` : "0 link";
    }
    if (!items || !items.length) {
      linksEl.innerHTML = '<div class="text-muted small">Nessun link ed2k trovato.</div>';
      return;
    }
    linksEl.innerHTML = items.map((item, index) => {
      const label = escapeHtml(formatEd2kLabel(item));
      const link = escapeHtml(item.link);
      const size = formatSize(item.size);
      const idx = index + 1;
      return `
        <div class="list-group-item ddu-link-row">
          <span class="ddu-link-index">${idx}.</span>
          <a class="small ddu-link-text" href="${link}" title="${link}">${label}</a>
          ${size ? `<span class="ddu-link-size">${size}</span>` : ""}
        </div>
      `;
    }).join("");
  };

  const loadEd2k = async (url, title, listingInfo) => {
    titleEl.textContent = title || "Link eMule";
    loadingEl.classList.remove("d-none");
    contentEl.classList.add("d-none");
    linksEl.innerHTML = "";
    if (manualWrap) {
      manualWrap.classList.add("d-none");
    }
    if (listingWrap && listingEl) {
      if (listingInfo) {
        listingEl.textContent = listingInfo;
        listingWrap.classList.remove("d-none");
      } else {
        listingWrap.classList.add("d-none");
      }
    }
    modal.show();
    try {
      const res = await fetch(`/api/ddunlimited/ed2k?url=${encodeURIComponent(url)}`);
      const data = await res.json();
      if (countEl && data.ed2k_stats) {
        const total = formatSize(data.ed2k_stats.total_bytes || 0);
        const count = data.ed2k_stats.count || 0;
        countEl.textContent = total ? `${count} file • ${total}` : `${count} file`;
      }
      renderLinks(data.ed2k_items);
    } catch (err) {
      renderLinks([]);
    } finally {
      loadingEl.classList.add("d-none");
      contentEl.classList.remove("d-none");
    }
  };

  document.addEventListener("click", (event) => {
    const target = event.target.closest(".ddu-ed2k-btn");
    if (!target) {
      return;
    }
    const url = target.dataset.detailUrl;
    const title = target.dataset.detailTitle;
    const listingInfo = target.dataset.detailInfo;
    if (!url) {
      return;
    }
    loadEd2k(url, title, listingInfo);
  });

  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      const text = lastLinks
        .map(item => item?.link || "")
        .filter(link => link.startsWith("ed2k://|file|"))
        .join("\n");
      if (!text) {
        copyBtn.innerHTML = '<i class="bi bi-exclamation-circle me-1"></i>Nessun link';
        setTimeout(() => {
          copyBtn.innerHTML = '<i class="bi bi-clipboard me-1"></i>Copia tutti';
        }, 1200);
        return;
      }
      try {
        if (!navigator.clipboard || !window.isSecureContext) {
          throw new Error("clipboard_unavailable");
        }
        await navigator.clipboard.writeText(text);
        copyBtn.innerHTML = '<i class="bi bi-check2 me-1"></i>Copiato';
        setTimeout(() => {
          copyBtn.innerHTML = '<i class="bi bi-clipboard me-1"></i>Copia tutti';
        }, 1200);
      } catch (err) {
        if (manualWrap && manualTextarea) {
          manualTextarea.value = text;
          manualWrap.classList.remove("d-none");
          manualTextarea.focus();
          manualTextarea.select();
          copyBtn.innerHTML = '<i class="bi bi-clipboard me-1"></i>Copia manuale';
        }
      }
    });
  }
})();
