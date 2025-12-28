function updateSelectionStats() {
    var totalEl = document.getElementById('selected-total');
    if (!totalEl) {
        return;
    }
    var selected = document.querySelectorAll('.plex-select:checked');
    var selectedMovies = document.querySelectorAll('.plex-movie:checked');
    var selectedSeries = document.querySelectorAll('.plex-series:checked');
    totalEl.textContent = selected.length;
    var moviesEl = document.getElementById('selected-movies');
    var seriesEl = document.getElementById('selected-series');
    var importBtn = document.getElementById('import-btn');
    if (moviesEl) {
        moviesEl.textContent = selectedMovies.length;
    }
    if (seriesEl) {
        seriesEl.textContent = selectedSeries.length;
    }
    if (importBtn) {
        importBtn.disabled = selected.length === 0;
    }
    updateTypeToggleButtons();
}

function applyFilters() {
    var searchEl = document.getElementById('plex-search');
    var selectedEl = document.getElementById('plex-only-selected');
    if (!searchEl || !selectedEl) {
        return;
    }
    var query = (searchEl.value || '').trim().toLowerCase();
    var onlySelected = selectedEl.checked;
    document.querySelectorAll('.plex-row').forEach(function(row) {
        var title = row.getAttribute('data-title') || '';
        var checkbox = row.querySelector('.plex-select');
        var matchesQuery = !query || title.indexOf(query) !== -1;
        var matchesSelected = !onlySelected || (checkbox && checkbox.checked);
        row.style.display = (matchesQuery && matchesSelected) ? '' : 'none';
    });
}

function updateTypeToggleButtons() {
    var movieBoxes = document.querySelectorAll('.plex-movie');
    var seriesBoxes = document.querySelectorAll('.plex-series');
    var allMoviesSelected = Array.from(movieBoxes).every(function(el) { return el.checked; });
    var allSeriesSelected = Array.from(seriesBoxes).every(function(el) { return el.checked; });
    document.querySelectorAll('.type-toggle').forEach(function(btn) {
        var type = btn.getAttribute('data-type');
        var isActive = type === 'movie' ? allMoviesSelected : allSeriesSelected;
        btn.classList.toggle('btn-primary', type === 'movie' && isActive);
        btn.classList.toggle('btn-outline-primary', type === 'movie' && !isActive);
        btn.classList.toggle('btn-secondary', type === 'series' && isActive);
        btn.classList.toggle('btn-outline-secondary', type === 'series' && !isActive);
    });
}

function sortTable(table, key, asc) {
    var tbody = table.querySelector('tbody');
    var rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort(function(a, b) {
        var aVal = a.getAttribute('data-' + key) || '';
        var bVal = b.getAttribute('data-' + key) || '';
        if (key === 'year') {
            aVal = parseInt(aVal || '0', 10);
            bVal = parseInt(bVal || '0', 10);
        } else {
            aVal = aVal.toLowerCase();
            bVal = bVal.toLowerCase();
        }
        if (aVal < bVal) return asc ? -1 : 1;
        if (aVal > bVal) return asc ? 1 : -1;
        return 0;
    });
    rows.forEach(function(row) { tbody.appendChild(row); });
}

var selectAllBtn = document.getElementById('select-all-btn');
if (selectAllBtn) {
    selectAllBtn.addEventListener('click', function() {
        document.querySelectorAll('.plex-select').forEach(function(el) { el.checked = true; });
        updateSelectionStats();
        applyFilters();
    });
}
var clearAllBtn = document.getElementById('clear-all-btn');
if (clearAllBtn) {
    clearAllBtn.addEventListener('click', function() {
        document.querySelectorAll('.plex-select').forEach(function(el) { el.checked = false; });
        updateSelectionStats();
        applyFilters();
    });
}
function normalizeBasePath(value) {
    if (!value) {
        return '';
    }
    var cleaned = value.trim().toLowerCase().replace(/\//g, '\\');
    while (cleaned.endsWith('\\')) {
        cleaned = cleaned.slice(0, -1);
    }
    return cleaned;
}

function toggleBaseSelection(checked) {
    var basePath = normalizeBasePath(document.getElementById('plex-basepath').value);
    if (!basePath) {
        return;
    }
    document.querySelectorAll('.plex-row').forEach(function(row) {
        var rowPath = row.getAttribute('data-path') || '';
        if (rowPath.startsWith(basePath)) {
            var checkbox = row.querySelector('.plex-select');
            if (checkbox) {
                checkbox.checked = checked;
            }
        }
    });
    updateSelectionStats();
    applyFilters();
}

var selectBaseBtn = document.getElementById('select-base-btn');
if (selectBaseBtn) {
    selectBaseBtn.addEventListener('click', function() {
        toggleBaseSelection(true);
    });
}
var clearBaseBtn = document.getElementById('clear-base-btn');
if (clearBaseBtn) {
    clearBaseBtn.addEventListener('click', function() {
        toggleBaseSelection(false);
    });
}

document.querySelectorAll('.plex-select').forEach(function(el) {
    el.addEventListener('change', function(event) {
        updateSelectionStats();
        applyFilters();
    });
});
var plexSearchEl = document.getElementById('plex-search');
if (plexSearchEl) {
    plexSearchEl.addEventListener('input', applyFilters);
}
var plexOnlySelectedEl = document.getElementById('plex-only-selected');
if (plexOnlySelectedEl) {
    plexOnlySelectedEl.addEventListener('change', applyFilters);
}
document.querySelectorAll('.type-toggle').forEach(function(btn) {
    btn.addEventListener('click', function() {
        var type = btn.getAttribute('data-type');
        var boxes = document.querySelectorAll(type === 'movie' ? '.plex-movie' : '.plex-series');
        var shouldSelect = btn.classList.contains(type === 'movie' ? 'btn-outline-primary' : 'btn-outline-secondary');
        boxes.forEach(function(el) { el.checked = shouldSelect; });
        updateSelectionStats();
        applyFilters();
    });
});
document.querySelectorAll('.plex-table .sortable').forEach(function(th) {
    th.addEventListener('click', function() {
        var key = th.getAttribute('data-sort-key');
        var table = th.closest('table');
        var asc = !th.classList.contains('sorted-asc');
        table.querySelectorAll('.sortable').forEach(function(header) {
            header.classList.remove('sorted-asc', 'sorted-desc');
        });
        th.classList.add(asc ? 'sorted-asc' : 'sorted-desc');
        sortTable(table, key, asc);
    });
});
updateSelectionStats();

function showPlexLoading() {
    var el = document.getElementById('plex-loading');
    if (el) {
        el.classList.remove('d-none');
    }
}
function updatePlexLoading(stage, processed, total) {
    var stageEl = document.getElementById('plex-loading-stage');
    var detailEl = document.getElementById('plex-loading-detail');
    var barEl = document.getElementById('plex-loading-bar');
    if (stageEl && stage) {
        stageEl.textContent = stage;
    }
    if (detailEl) {
        if (total && total > 0) {
            detailEl.textContent = processed + ' / ' + total;
        } else {
            detailEl.textContent = 'Operazione in background, attendi qualche istante.';
        }
    }
    if (barEl && total && total > 0) {
        var pct = Math.min(100, Math.round((processed / total) * 100));
        barEl.style.width = pct + '%';
    }
}
document.querySelectorAll('form').forEach(function(form) {
    form.addEventListener('submit', function() {
        showPlexLoading();
    });
});

var previewForm = document.getElementById('plex-preview-form');
if (previewForm) {
    previewForm.addEventListener('submit', function(event) {
        event.preventDefault();
        showPlexLoading();
        var formData = new FormData(previewForm);
        fetch(previewForm.getAttribute('action') || window.location.pathname, {
            method: 'POST',
            headers: {'X-Requested-With': 'XMLHttpRequest'},
            body: formData
        }).then(function(resp) { return resp.json(); })
          .then(function(data) {
              if (!data.ok || !data.job_id) {
                  throw new Error('Errore avvio job');
              }
              var jobId = data.job_id;
              var poll = setInterval(function() {
                  fetch('/import/plex/status?job_id=' + jobId)
                    .then(function(resp) { return resp.json(); })
                    .then(function(status) {
                        if (!status.ok) {
                            throw new Error('Errore stato job');
                        }
                        updatePlexLoading(status.stage, status.processed, status.total);
                        if (status.status === 'done') {
                            clearInterval(poll);
                            window.location.href = '/import/plex?job_id=' + jobId;
                        } else if (status.status === 'error') {
                            clearInterval(poll);
                            updatePlexLoading('Errore', 0, 0);
                        }
                    }).catch(function() {
                        clearInterval(poll);
                        updatePlexLoading('Errore', 0, 0);
                    });
              }, 1000);
          })
          .catch(function() {
              updatePlexLoading('Errore', 0, 0);
          });
    });
}
