function showPlexCompareLoading() {
    var el = document.getElementById('plex-compare-loading');
    if (el) {
        el.classList.remove('d-none');
    }
}

function updatePlexCompareLoading(stage, processed, total) {
    var stageEl = document.getElementById('plex-compare-loading-stage');
    var detailEl = document.getElementById('plex-compare-loading-detail');
    var barEl = document.getElementById('plex-compare-loading-bar');
    if (stageEl && stage) {
        stageEl.textContent = stage;
    }
    if (detailEl) {
        if (total && total > 0) {
            detailEl.textContent = processed + ' / ' + total;
        } else {
            detailEl.textContent = 'Attendi il completamento dell\'analisi.';
        }
    }
    if (barEl && total && total > 0) {
        var pct = Math.min(100, Math.round((processed / total) * 100));
        barEl.style.width = pct + '%';
    }
}

function applyPlexCompareFilters() {
    var searchEl = document.getElementById('plex-compare-search');
    var statusEl = document.getElementById('plex-compare-status');
    if (!searchEl || !statusEl) {
        return;
    }
    var query = (searchEl.value || '').trim().toLowerCase();
    var status = statusEl.value || '';
    var selectedLegacyLibraries = Array.from(document.querySelectorAll('.plex-compare-library-filter[data-scope="legacy"]:checked')).map(function(el) {
        return (el.value || '').trim().toLowerCase();
    });
    var selectedCurrentLibraries = Array.from(document.querySelectorAll('.plex-compare-library-filter[data-scope="current"]:checked')).map(function(el) {
        return (el.value || '').trim().toLowerCase();
    });
    var visibleMovies = 0;
    var visibleSeries = 0;
    document.querySelectorAll('.plex-compare-row').forEach(function(row) {
        var title = row.getAttribute('data-title') || '';
        var rowStatus = row.getAttribute('data-status') || '';
        var rowType = row.getAttribute('data-kind') || '';
        var legacyLibrary = row.getAttribute('data-legacy-library') || '';
        var currentLibrary = row.getAttribute('data-current-library') || '';
        var matchesQuery = !query || title.indexOf(query) !== -1;
        var matchesStatus = !status || rowStatus === status;
        var matchesLegacyLibrary = selectedLegacyLibraries.length === 0 || !legacyLibrary || selectedLegacyLibraries.indexOf(legacyLibrary) !== -1;
        var matchesCurrentLibrary = selectedCurrentLibraries.length === 0 || !currentLibrary || selectedCurrentLibraries.indexOf(currentLibrary) !== -1;
        var isVisible = matchesQuery && matchesStatus && matchesLegacyLibrary && matchesCurrentLibrary;
        row.style.display = isVisible ? '' : 'none';
        if (isVisible) {
            if (rowType === 'movie') {
                visibleMovies += 1;
            } else if (rowType === 'series') {
                visibleSeries += 1;
            }
        }
    });
    var moviesEl = document.getElementById('plex-compare-visible-movies');
    var seriesEl = document.getElementById('plex-compare-visible-series');
    var totalEl = document.getElementById('plex-compare-visible-total');
    if (moviesEl) {
        moviesEl.textContent = visibleMovies;
    }
    if (seriesEl) {
        seriesEl.textContent = visibleSeries;
    }
    if (totalEl) {
        totalEl.textContent = visibleMovies + visibleSeries;
    }
}

var compareForm = document.getElementById('plex-compare-form');
if (compareForm) {
    compareForm.addEventListener('submit', function(event) {
        event.preventDefault();
        showPlexCompareLoading();
        var formData = new FormData(compareForm);
        fetch(compareForm.getAttribute('action') || window.location.pathname, {
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
                  fetch('/compare/plex/status?job_id=' + jobId)
                    .then(function(resp) { return resp.json(); })
                    .then(function(status) {
                        if (!status.ok) {
                            throw new Error('Errore stato job');
                        }
                        updatePlexCompareLoading(status.stage, status.processed, status.total);
                        if (status.status === 'done') {
                            clearInterval(poll);
                            window.location.href = '/compare/plex?job_id=' + jobId;
                        } else if (status.status === 'error') {
                            clearInterval(poll);
                            updatePlexCompareLoading(status.error || 'Errore', 0, 0);
                        }
                    }).catch(function() {
                        clearInterval(poll);
                        updatePlexCompareLoading('Errore', 0, 0);
                    });
              }, 1000);
          })
          .catch(function() {
              updatePlexCompareLoading('Errore', 0, 0);
          });
    });
}

var compareSearchEl = document.getElementById('plex-compare-search');
if (compareSearchEl) {
    compareSearchEl.addEventListener('input', applyPlexCompareFilters);
}
var compareStatusEl = document.getElementById('plex-compare-status');
if (compareStatusEl) {
    compareStatusEl.addEventListener('change', applyPlexCompareFilters);
}
document.querySelectorAll('.plex-compare-library-filter').forEach(function(el) {
    el.addEventListener('change', applyPlexCompareFilters);
});
applyPlexCompareFilters();
