var pendingDownloadIds = new Set();
var pendingDownloadAttempts = 0;
var pendingDownloadTimer = null;
var MAX_PENDING_DOWNLOAD_ATTEMPTS = 4;
var PENDING_REFRESH_DELAY_MS = 3500;
var wantedCustomFilter = null;

function markRowDownloadPendingInRow($row) {
    var $cell = $row.find('td').eq(5);
    $cell.attr('data-order', '0');
    $cell.html('<span class="spinner-border spinner-border-sm text-secondary" role="status" aria-hidden="true"></span>');
}

function markRowDownloadPendingById(id) {
    if (!id) {
        return;
    }
    if (pendingDownloadIds.size === 0) {
        pendingDownloadAttempts = 0;
    }
    pendingDownloadIds.add(String(id));
    var $row = $('.wanted-select[value="' + id + '"]').closest('tr');
    if ($row.length) {
        markRowDownloadPendingInRow($row);
    }
}

function applyPendingDownloadState() {
    if (!pendingDownloadIds.size) {
        return;
    }
    var nextPending = new Set();
    pendingDownloadIds.forEach(function(id) {
        var $row = $('.wanted-select[value="' + id + '"]').closest('tr');
        if (!$row.length) {
            return;
        }
        var total = $row.attr('data-download-total');
        var hasTotal = total !== undefined && total !== null && total !== '';
        if (!hasTotal) {
            markRowDownloadPendingInRow($row);
            nextPending.add(id);
        }
    });
    pendingDownloadIds = nextPending;
    if (pendingDownloadIds.size) {
        if (pendingDownloadAttempts < MAX_PENDING_DOWNLOAD_ATTEMPTS) {
            schedulePendingRefresh(PENDING_REFRESH_DELAY_MS);
        } else {
            pendingDownloadIds.forEach(function(id) {
                var $row = $('.wanted-select[value="' + id + '"]').closest('tr');
                if (!$row.length) {
                    return;
                }
                var $cell = $row.find('td').eq(5);
                $cell.attr('data-order', '0');
                $cell.html('<span class="text-muted">-</span>');
            });
            pendingDownloadIds.clear();
        }
    }
}

function schedulePendingRefresh(delayMs) {
    if (!pendingDownloadIds.size) {
        return;
    }
    if (pendingDownloadTimer) {
        clearTimeout(pendingDownloadTimer);
    }
    pendingDownloadTimer = setTimeout(function() {
        if (typeof window.reloadWantedContent === 'function') {
            pendingDownloadAttempts += 1;
            window.reloadWantedContent();
        }
    }, delayMs || PENDING_REFRESH_DELAY_MS);
}

function initWantedUI() {
    var wantedSearchTerm = '';
    var wantedTypeFilter = 'all';
    var wantedImportFilter = 'all';
    var isSyncingSelection = false;
    var selectedIds = new Set();
    var rowInfo = {};
    var rowById = {};
    var checkboxById = {};
    var configEl = document.getElementById('wanted-config');
    var radarrBase = configEl ? (configEl.dataset.radarrUrl || '') : '';
    var sonarrBase = configEl ? (configEl.dataset.sonarrUrl || '') : '';
    

    function isRadarrEligibleInfo(info) {
        if (!info) {
            return false;
        }
        return info.mediaType === 'movie' && info.hasTmdb && !info.inRadarr && !info.statusPending;
    }

    var table = $('#wanted_table').DataTable({
        paging: true,
        ordering: true,
        searching: true,
        order: [],
        autoWidth: false,
        deferRender: true,
        processing: true,
        orderClasses: false,
        searchDelay: 150,
        pageLength: 50,
        lengthMenu: [25, 50, 100, 200],
        select: {
            style: 'os',
            selector: 'td:not(.wanted-actions-cell)'
        },
        columnDefs: [
            { orderable: false, targets: [0, 7] },
            { searchable: false, targets: [0, 4, 7] }
        ],
        dom: 'rt<"d-flex justify-content-between align-items-center mt-3"lip>'
    });

    $.fn.dataTable.ext.search = $.fn.dataTable.ext.search.filter(function(fn) {
        return !fn.__wantedFilter;
    });
    wantedCustomFilter = function(settings, data, dataIndex) {
        if (settings.nTable.id !== 'wanted_table') {
            return true;
        }
        var node = table.row(dataIndex).node();
        if (!node) {
            return true;
        }
        if (wantedTypeFilter !== 'all') {
            var mediaType = $(node).data('media-type');
            if (mediaType !== wantedTypeFilter) {
                return false;
            }
        }
        if (wantedImportFilter !== 'all') {
            var importPath = $(node).data('import-path') || '';
            if (importPath !== wantedImportFilter) {
                return false;
            }
        }
        return true;
    };
    wantedCustomFilter.__wantedFilter = true;
    $.fn.dataTable.ext.search.push(wantedCustomFilter);

    function getRowInfo(id) {
        if (!id) {
            return null;
        }
        if (rowInfo[id]) {
            return rowInfo[id];
        }
        var $row = rowById[id] ? $(rowById[id]) : $('.wanted-select[value="' + id + '"]').closest('tr');
        if (!$row.length) {
            return null;
        }
        rowInfo[id] = {
            id: id,
            mediaType: $row.data('media-type'),
            category: $row.data('category') || '',
            hasTmdb: $row.data('has-tmdb') === 1 || $row.data('has-tmdb') === '1',
            hasTvdb: $row.data('has-tvdb') === 1 || $row.data('has-tvdb') === '1',
            tmdbId: $row.data('tmdb-id') || '',
            tvdbId: $row.data('tvdb-id') || '',
            inRadarr: $row.data('in-radarr') === 1 || $row.data('in-radarr') === '1',
            inSonarr: $row.data('in-sonarr') === 1 || $row.data('in-sonarr') === '1',
            downloaded: $row.data('downloaded') === 1 || $row.data('downloaded') === '1',
            statusPending: $row.data('status-pending') === 1 || $row.data('status-pending') === '1',
            missingExternal: $row.data('missing-external') === 1 || $row.data('missing-external') === '1',
            title: $row.find('.wanted-title').text().trim()
        };
        return rowInfo[id];
    }

    function buildRowIndex() {
        rowById = {};
        checkboxById = {};
        table.rows().nodes().to$().each(function() {
            var $row = $(this);
            var id = $row.find('.wanted-select').val();
            if (!id) {
                return;
            }
            rowById[id] = this;
            checkboxById[id] = $row.find('.wanted-select').get(0);
        });
    }

    function updateRowInRadarr(mediaId) {
        var $row = rowById[mediaId] ? $(rowById[mediaId]) : $('.wanted-select[value="' + mediaId + '"]').closest('tr');
        if (!$row.length) {
            return;
        }
        $row.attr('data-in-radarr', '1');
        $row.data('in-radarr', '1');
        var tmdbId = $row.data('tmdb-id');
        if (tmdbId && !$row.find('.badge-radarr').length) {
            var idCell = $row.find('td').eq(4);
            var badgeWrap = idCell.find('.d-flex').first();
            var target = badgeWrap.length ? badgeWrap : idCell;
            target.append(
                '<a class="badge badge-radarr text-decoration-none" href="' + radarrBase + '/movie/' + tmdbId + '" target="_blank" rel="noopener" data-bs-toggle="tooltip" data-bs-placement="top" title="Radarr ' + tmdbId + '">Radarr</a>'
            );
        }
        $row.find('.radarr-add-btn').prop('disabled', false);
        var info = getRowInfo(mediaId);
        if (info) {
            info.inRadarr = true;
        }
        table.draw(false);
        updateBulkState();
        updateStatsCounts();
    }

    function updateRowInSonarr(mediaId) {
        var $row = rowById[mediaId] ? $(rowById[mediaId]) : $('.wanted-select[value="' + mediaId + '"]').closest('tr');
        if (!$row.length) {
            return;
        }
        $row.attr('data-in-sonarr', '1');
        $row.data('in-sonarr', '1');
        var tvdbId = $row.data('tvdb-id');
        var idCell = $row.find('td').eq(4);
        var slug = $row.data('sonarr-slug') || '';
        var existingBadge = idCell.find('.badge-sonarr');
        if (tvdbId && sonarrBase && slug) {
            var link = sonarrBase + '/series/' + slug;
            var linkHtml = '<a class="badge badge-sonarr text-decoration-none" href="' + link + '" target="_blank" rel="noopener">Sonarr</a>';
            if (existingBadge.length) {
                if (!existingBadge.is('a')) {
                    existingBadge.replaceWith(linkHtml);
                }
            } else {
                var badgeWrap = idCell.find('.d-flex').first();
                var target = badgeWrap.length ? badgeWrap : idCell;
                target.append(linkHtml);
            }
        } else if (!existingBadge.length) {
            var badgeWrap = idCell.find('.d-flex').first();
            var target = badgeWrap.length ? badgeWrap : idCell;
            target.append('<span class="badge badge-sonarr">Sonarr</span>');
        }
        $row.find('.sonarr-add-btn').prop('disabled', false);
        var info = getRowInfo(mediaId);
        if (info) {
            info.inSonarr = true;
        }
        table.draw(false);
        updateBulkState();
        updateStatsCounts();
    }

    function updateRowDownloadStatus(mediaId, downloaded, total) {
        var $row = rowById[mediaId] ? $(rowById[mediaId]) : $('.wanted-select[value="' + mediaId + '"]').closest('tr');
        if (!$row.length) {
            return;
        }
        var totalCount = (total === undefined || total === null || total === '') ? null : Number(total);
        var downloadedCount = (downloaded === undefined || downloaded === null || downloaded === '') ? 0 : Number(downloaded);
        $row.attr('data-download-current', totalCount !== null ? downloadedCount : '');
        $row.data('download-current', totalCount !== null ? downloadedCount : '');
        $row.attr('data-download-total', totalCount !== null ? totalCount : '');
        $row.data('download-total', totalCount !== null ? totalCount : '');
        var $cell = $row.find('td').eq(5);
        if (totalCount && totalCount > 0) {
            var ratio = downloadedCount / totalCount;
            var orderVal = downloadedCount >= totalCount ? -2 : (-1 - ratio);
            $cell.attr('data-order', orderVal);
            var klass = downloadedCount >= totalCount ? 'bg-success' : 'bg-light text-dark';
            $cell.html('<span class="badge ' + klass + '">' + downloadedCount + '/' + totalCount + '</span>');
            $row.attr('data-downloaded', downloadedCount >= totalCount ? '1' : '0');
            $row.data('downloaded', downloadedCount >= totalCount ? '1' : '0');
        } else {
            $cell.attr('data-order', '0');
            $cell.html('<span class="text-muted">-</span>');
            $row.attr('data-downloaded', '0');
            $row.data('downloaded', '0');
        }
        var info = getRowInfo(mediaId);
        if (info) {
            info.downloaded = $row.data('downloaded') === 1 || $row.data('downloaded') === '1';
        }
    }

    function updateStatsCounts() {
        var total = 0;
        var movies = 0;
        var series = 0;
        var missing = 0;
        var inRadarr = 0;
        var inSonarr = 0;
        table.rows().nodes().to$().each(function() {
            var $row = $(this);
            total += 1;
            var mediaType = $row.data('media-type');
            if (mediaType === 'movie') {
                movies += 1;
            } else if (mediaType === 'series') {
                series += 1;
            }
            if ($row.data('missing-external') === 1 || $row.data('missing-external') === '1') {
                missing += 1;
            }
            if ($row.data('in-radarr') === 1 || $row.data('in-radarr') === '1') {
                inRadarr += 1;
            }
            if ($row.data('in-sonarr') === 1 || $row.data('in-sonarr') === '1') {
                inSonarr += 1;
            }
        });
        $('#wanted-count-total').text(total);
        $('#wanted-count-movies').text(movies);
        $('#wanted-count-series').text(series);
        $('#wanted-count-missing').text(missing);
        $('#wanted-count-in-radarr').text(inRadarr);
        $('#wanted-count-in-sonarr').text(inSonarr);
    }

    function updateRowRoot(mediaId, serviceKey, rootPath) {
        if (!mediaId || !serviceKey || !rootPath) {
            return;
        }
        var $row = rowById[mediaId] ? $(rowById[mediaId]) : $('.wanted-select[value="' + mediaId + '"]').closest('tr');
        if (!$row.length) {
            return;
        }
        var attr = 'data-' + serviceKey + '-root';
        $row.attr(attr, rootPath);
        $row.data(serviceKey + '-root', rootPath);
    }

    function removeRowsByIds(ids) {
        ids.forEach(function(id) {
            var $row = rowById[id] ? $(rowById[id]) : $('.wanted-select[value="' + id + '"]').closest('tr');
            if ($row.length) {
                table.row($row).remove();
            }
            selectedIds.delete(id);
            delete rowInfo[id];
            delete rowById[id];
            delete checkboxById[id];
        });
        table.draw(false);
        syncSelectionToTable();
        updateBulkState();
        updateStatsCounts();
    }

    function syncSelectionToTable() {
        isSyncingSelection = true;
        table.rows({ page: 'current' }).every(function() {
            var row = this.node();
            if (!row) {
                return;
            }
            var $row = $(row);
            var id = $row.find('.wanted-select').val();
            var shouldSelect = selectedIds.has(id);
            $row.find('.wanted-select').prop('checked', shouldSelect);
            if (shouldSelect && !this.selected()) {
                this.select();
            } else if (!shouldSelect && this.selected()) {
                this.deselect();
            }
        });
        isSyncingSelection = false;
    }


    function getRadarrEligibleIds() {
        return Array.from(selectedIds).filter(function(id) {
            return isRadarrEligibleInfo(getRowInfo(id));
        });
    }

    function getSonarrEligibleIds() {
        return Array.from(selectedIds).filter(function(id) {
            var info = getRowInfo(id);
            if (!info) {
                return false;
            }
            return info.mediaType === 'series' && info.hasTvdb && !info.inSonarr && !info.statusPending;
        });
    }

    function getRadarrUpdateIds() {
        return Array.from(selectedIds).filter(function(id) {
            var info = getRowInfo(id);
            if (!info) {
                return false;
            }
            return info.mediaType === 'movie' && info.hasTmdb && info.inRadarr && !info.statusPending;
        });
    }

    function getSonarrUpdateIds() {
        return Array.from(selectedIds).filter(function(id) {
            var info = getRowInfo(id);
            if (!info) {
                return false;
            }
            return info.mediaType === 'series' && info.hasTvdb && info.inSonarr && !info.statusPending;
        });
    }

    function getTvdbMatchIds() {
        return Array.from(selectedIds).filter(function(id) {
            var info = getRowInfo(id);
            if (!info) {
                return false;
            }
            return info.mediaType === 'series' && !info.hasTvdb;
        });
    }

    function getTmdbMatchIds() {
        return Array.from(selectedIds).filter(function(id) {
            var info = getRowInfo(id);
            if (!info) {
                return false;
            }
            return info.mediaType === 'movie' && !info.hasTmdb;
        });
    }

    function getRadarrBulkMode() {
        var addIds = getRadarrEligibleIds();
        var updateIds = getRadarrUpdateIds();
        if (addIds.length && updateIds.length) {
            return 'mixed';
        }
        if (addIds.length) {
            return 'add';
        }
        if (updateIds.length) {
            return 'update';
        }
        return 'none';
    }

    function getSonarrBulkMode() {
        var addIds = getSonarrEligibleIds();
        var updateIds = getSonarrUpdateIds();
        if (addIds.length && updateIds.length) {
            return 'mixed';
        }
        if (addIds.length) {
            return 'add';
        }
        if (updateIds.length) {
            return 'update';
        }
        return 'none';
    }

    function updateBulkState() {
        var count = selectedIds.size;
        var eligible = getRadarrEligibleIds();
        var eligibleSonarr = getSonarrEligibleIds();
        var eligibleRadarrUpdate = getRadarrUpdateIds();
        var eligibleSonarrUpdate = getSonarrUpdateIds();
        var tvdbMatchIds = getTvdbMatchIds();
        var tmdbMatchIds = getTmdbMatchIds();
        var radarrMode = getRadarrBulkMode();
        var sonarrMode = getSonarrBulkMode();
        var excluded = count - eligible.length;
        $('#wanted-count-selected').text(count);
        $('#bulk-delete-btn').prop('disabled', count === 0);
        $('#bulk-delete-confirm').prop('disabled', count === 0);
        $('#bulk-delete-count').text(count);
        if (radarrMode === 'update') {
            $('#bulk-radarr-count').text(eligibleRadarrUpdate.length);
        } else {
            $('#bulk-radarr-count').text(eligible.length);
        }
        if (sonarrMode === 'update') {
            $('#bulk-sonarr-count').text(eligibleSonarrUpdate.length);
        } else {
            $('#bulk-sonarr-count').text(eligibleSonarr.length);
        }
        $('#bulk-match-tvdb-btn').prop('disabled', tvdbMatchIds.length === 0);
        $('#bulk-match-tmdb-btn').prop('disabled', tmdbMatchIds.length === 0);
        $('#bulk-merge-btn').prop('disabled', count === 0);
        if (count === 0) {
            $('#bulk-radarr-btn').prop('disabled', true);
            $('#bulk-radarr-note').text('Solo movie con TMDB non presenti in Radarr.');
        } else if (radarrMode === 'mixed') {
            $('#bulk-radarr-btn').prop('disabled', true);
            $('#bulk-radarr-note').text('Record misti: separa in due selezioni.');
        } else if (radarrMode === 'add') {
            $('#bulk-radarr-btn').prop('disabled', eligible.length === 0);
            $('#bulk-radarr-note').text('Inviabili: ' + eligible.length + '. Esclusi: ' + (count - eligible.length) + '.');
        } else if (radarrMode === 'update') {
            $('#bulk-radarr-btn').prop('disabled', eligibleRadarrUpdate.length === 0);
            $('#bulk-radarr-note').text('Aggiornabili: ' + eligibleRadarrUpdate.length + '. Esclusi: ' + (count - eligibleRadarrUpdate.length) + '.');
        } else {
            $('#bulk-radarr-btn').prop('disabled', true);
            $('#bulk-radarr-note').text('Nessun record aggiornabile o inviabile.');
        }

        if (count === 0) {
            $('#bulk-sonarr-btn').prop('disabled', true);
            $('#bulk-sonarr-note').text('Solo serie con TVDB non presenti in Sonarr.');
        } else if (sonarrMode === 'mixed') {
            $('#bulk-sonarr-btn').prop('disabled', true);
            $('#bulk-sonarr-note').text('Record misti: separa in due selezioni.');
        } else if (sonarrMode === 'add') {
            $('#bulk-sonarr-btn').prop('disabled', eligibleSonarr.length === 0);
            $('#bulk-sonarr-note').text('Inviabili: ' + eligibleSonarr.length + '. Esclusi: ' + (count - eligibleSonarr.length) + '.');
        } else if (sonarrMode === 'update') {
            $('#bulk-sonarr-btn').prop('disabled', eligibleSonarrUpdate.length === 0);
            $('#bulk-sonarr-note').text('Aggiornabili: ' + eligibleSonarrUpdate.length + '. Esclusi: ' + (count - eligibleSonarrUpdate.length) + '.');
        } else {
            $('#bulk-sonarr-btn').prop('disabled', true);
            $('#bulk-sonarr-note').text('Nessun record aggiornabile o inviabile.');
        }
    }

    function applyFilters() {
        table.column(1).search(wantedSearchTerm || '');
        table.draw();
        updateBulkState();
        if (typeof window.updateWantedUrlState === 'function') {
            window.updateWantedUrlState(table);
        }
    }

    function applySearch() {
        var value = $('#wanted-title-search').val() || '';
        wantedSearchTerm = value.toLowerCase();
        applyFilters();
    }

    function getSelectedIds() {
        return Array.from(selectedIds);
    }

    $('#wanted-type-filter').off('change.wanted').on('change.wanted', function() {
        wantedTypeFilter = $(this).val() || 'all';
        applyFilters();
    });

    function populateImportFilter() {
        var values = new Set();
        table.rows().nodes().to$().each(function() {
            var val = $(this).data('import-path');
            if (val) {
                values.add(String(val));
            }
        });
        var $select = $('#wanted-import-filter');
        if (!$select.length) {
            return;
        }
        var opts = ['<option value="all">Tutti</option>'];
        Array.from(values).sort().forEach(function(val) {
            opts.push('<option value="' + val.replace(/"/g, '&quot;') + '">' + val + '</option>');
        });
        $select.html(opts.join(''));
        $select.prop('disabled', values.size === 0);
    }

    $('#wanted-import-filter').off('change.wanted').on('change.wanted', function() {
        wantedImportFilter = $(this).val() || 'all';
        applyFilters();
    });


    $('#wanted-title-search').off('input.wanted').on('input.wanted', function() {
        applySearch();
    });

    $(document).off('change.wanted', '.wanted-select').on('change.wanted', '.wanted-select', function() {
        if (isSyncingSelection) {
            return;
        }
        var $row = $(this).closest('tr');
        var rowApi = table.row($row);
        if (!rowApi) {
            return;
        }
        if ($(this).is(':checked')) {
            rowApi.select();
        } else {
            rowApi.deselect();
        }
    });

    $('#select-visible-btn').off('click.wanted').on('click.wanted', function() {
        var nodes = table.rows({ search: 'applied' }).nodes();
        $(nodes).find('.wanted-select').each(function() {
            selectedIds.add($(this).val());
        });
        syncSelectionToTable();
        updateBulkState();
    });

    function selectRowsByPredicate(predicate) {
        var nodes = table.rows({ search: 'applied' }).nodes();
        $(nodes).each(function() {
            var $row = $(this);
            if (!predicate($row)) {
                return;
            }
            var id = $row.find('.wanted-select').val();
            if (id) {
                table.row($row).select();
            }
        });
        syncSelectionToTable();
        updateBulkState();
    }

    $('#select-downloaded-btn').off('click.wanted').on('click.wanted', function() {
        selectRowsByPredicate(function($row) {
            return $row.data('downloaded') === 1 || $row.data('downloaded') === '1';
        });
    });

    $('#select-tmdb-btn').off('click.wanted').on('click.wanted', function() {
        selectRowsByPredicate(function($row) {
            return $row.data('has-tmdb') === 1 || $row.data('has-tmdb') === '1';
        });
    });

    $('#select-tvdb-btn').off('click.wanted').on('click.wanted', function() {
        selectRowsByPredicate(function($row) {
            return $row.data('has-tvdb') === 1 || $row.data('has-tvdb') === '1';
        });
    });

    $('#select-radarr-btn').off('click.wanted').on('click.wanted', function() {
        selectRowsByPredicate(function($row) {
            return $row.data('in-radarr') === 1 || $row.data('in-radarr') === '1';
        });
    });

    $('#select-sonarr-btn').off('click.wanted').on('click.wanted', function() {
        selectRowsByPredicate(function($row) {
            return $row.data('in-sonarr') === 1 || $row.data('in-sonarr') === '1';
        });
    });

    $('#clear-selection-btn').off('click.wanted').on('click.wanted', function() {
        selectedIds.clear();
        syncSelectionToTable();
        updateBulkState();
    });

    $('#bulk-delete-confirm').off('click.wanted').on('click.wanted', function() {
        var ids = Array.from(selectedIds);
        if (!ids.length) {
            return;
        }
        var button = $(this);
        button.prop('disabled', true).text('Elimino...');
        $.ajax({
            url: $('#bulk-delete-form').attr('action'),
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            dataType: 'json',
            data: { media_ids: ids }
        }).done(function() {
            removeRowsByIds(ids);
            button.text('Eliminati');
            var modalEl = document.getElementById('bulkDeleteModal');
            if (modalEl) {
                setTimeout(function() {
                    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
                    if (modal) {
                        modal.hide();
                    }
                }, 1000);
            }
        }).fail(function() {
            button.prop('disabled', false).text('Elimina');
        });
    });

    $('#bulkDeleteModal').off('show.bs.modal.wanted').on('show.bs.modal.wanted', updateBulkState);
    $('#bulkRadarrModal').off('show.bs.modal.wanted').on('show.bs.modal.wanted', updateBulkState);
    $('#bulkSonarrModal').off('show.bs.modal.wanted').on('show.bs.modal.wanted', updateBulkState);

    function renderLookupResults(provider, items, listEl) {
        if (!items || !items.length) {
            listEl.html('<li class="list-group-item text-muted">Nessun risultato trovato.</li>');
            return;
        }
        var html = items.map(function(item) {
            var title = item.title || 'Senza titolo';
            var year = item.year ? ' (' + item.year + ')' : '';
            var externalId = item.external_id || '';
            var imdb = item.imdb_id ? ' IMDB: ' + item.imdb_id : '';
            var link = item.link || '';
            if (!link && provider === 'tmdb' && externalId) {
                link = 'https://www.themoviedb.org/movie/' + externalId;
            }
            return (
                '<li class="list-group-item d-flex justify-content-between align-items-center gap-3">' +
                    '<div>' +
                        '<div class="fw-semibold">' + title + year + '</div>' +
                        '<div class="text-muted small">ID: ' + externalId + imdb + link + '</div>' +
                    '</div>' +
                    '<div class="d-flex align-items-center gap-2">' +
                        (link ? '<a class="btn btn-sm btn-outline-secondary" href="' + link + '" target="_blank" rel="noopener noreferrer">Apri</a>' : '') +
                        '<button class="btn btn-sm btn-primary select-external-btn" data-source="' + provider + '" data-external-id="' + externalId + '" data-media-id="' + item.media_item_id + '"' + (link ? ' data-link="' + link + '"' : '') + '>Seleziona</button>' +
                    '</div>' +
                '</li>'
            );
        }).join('');
        listEl.html(html);
    }

    function loadLookupResults(listEl, queryOverride) {
        var provider = listEl.data('provider');
        var mediaId = listEl.data('media-id');
        var query = queryOverride || listEl.closest('.modal-body').find('.lookup-query').val() || '';
        var modalBody = listEl.closest('.modal-body');
        modalBody.find('.lookup-loading').removeClass('d-none');
        listEl.html('<li class="list-group-item text-muted">Ricerca in corso...</li>');
        $.getJSON('/api/wanted/' + mediaId + '/lookup/' + provider, { q: query }, function(resp) {
            var items = resp && resp.items ? resp.items : [];
            items = items.map(function(item) {
                item.media_item_id = mediaId;
                return item;
            });
            renderLookupResults(provider, items, listEl);
            modalBody.find('.lookup-loading').addClass('d-none');
        }).fail(function() {
            listEl.html('<li class="list-group-item text-danger">Errore nella ricerca.</li>');
            modalBody.find('.lookup-loading').addClass('d-none');
        });
    }

    $(document).off('show.bs.modal.wanted', '.modal').on('show.bs.modal.wanted', '.modal', function() {
        var listEl = $(this).find('.lookup-results');
        if (!listEl.length) {
            return;
        }
        loadLookupResults(listEl);
    });

    $(document).off('click.wanted', '.lookup-run').on('click.wanted', '.lookup-run', function() {
        var modal = $(this).closest('.modal');
        var listEl = modal.find('.lookup-results');
        loadLookupResults(listEl);
    });

    $(document).off('keyup.wanted', '.lookup-query').on('keyup.wanted', '.lookup-query', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            $(this).closest('.modal').find('.lookup-run').click();
        }
    });

    function applyExternalUpdate(mediaId, source, externalId, link) {
        var $checkbox = checkboxById[mediaId] ? $(checkboxById[mediaId]) : $('.wanted-select[value="' + mediaId + '"]');
        var $row = rowById[mediaId] ? $(rowById[mediaId]) : $checkbox.closest('tr');
        if (!$row.length) {
            return;
        }
        var mediaType = $row.data('media-type');
        var category = $row.data('category');
        var title = $row.find('.wanted-title').text().trim();
        var idCell = $row.find('td').eq(4);
        var badgeWrap = idCell.find('.d-flex').first();
        var badgeTarget = badgeWrap.length ? badgeWrap : idCell;
        if (source === 'tmdb') {
            $row.attr('data-has-tmdb', '1');
            $row.data('has-tmdb', '1');
            $row.attr('data-tmdb-id', externalId);
            $row.data('tmdb-id', externalId);
            if (mediaType === 'movie') {
                $row.attr('data-missing-external', '0');
                $row.data('missing-external', '0');
            }
            if (!link) {
                link = (mediaType === 'series')
                    ? 'https://www.themoviedb.org/tv/' + externalId
                    : 'https://www.themoviedb.org/movie/' + externalId;
            }
            if (!idCell.find('.badge-tmdb').length) {
                badgeTarget.append(
                    '<a class="badge badge-tmdb text-decoration-none" href="' + link + '" target="_blank" rel="noopener" data-bs-toggle="tooltip" data-bs-placement="top" title="' + externalId + '">TMDB</a>'
                );
            }
            var $actions = $row.find('.wanted-actions');
            if (!$actions.find('.radarr-add-btn').length) {
                $actions.find('.btn-outline-secondary:disabled').first().replaceWith(
                    '<button class="btn btn-sm btn-radarr btn-icon d-inline-flex align-items-center justify-content-center radarr-add-btn" data-bs-toggle="modal" data-bs-target="#radarrAddModal" data-media-id="' + mediaId + '" data-title="' + title + '" title="Radarr">' +
                    '<i class="bi bi-cloud-download"></i></button>'
                );
            }
        } else if (source === 'tvdb') {
            $row.attr('data-has-tvdb', '1');
            $row.data('has-tvdb', '1');
            $row.attr('data-tvdb-id', externalId);
            $row.data('tvdb-id', externalId);
            if (mediaType === 'series') {
                $row.attr('data-missing-external', '0');
                $row.data('missing-external', '0');
            }
            if (!link) {
                link = 'https://thetvdb.com/series/' + externalId;
            }
            if (!idCell.find('.badge-imdb').length) {
                badgeTarget.append(
                    '<a class="badge badge-imdb text-decoration-none" href="' + link + '" target="_blank" rel="noopener" data-bs-toggle="tooltip" data-bs-placement="top" title="' + externalId + '">TVDB</a>'
                );
            }
            var $tvActions = $row.find('.wanted-actions');
            if (!$tvActions.find('.sonarr-add-btn').length) {
                $tvActions.find('.btn-outline-secondary:disabled').first().replaceWith(
                    '<button class="btn btn-sm btn-sonarr btn-icon d-inline-flex align-items-center justify-content-center sonarr-add-btn" data-bs-toggle="modal" data-bs-target="#sonarrAddModal" data-media-id="' + mediaId + '" data-title="' + title + '" title="Sonarr">' +
                    '<i class="bi bi-cloud-download"></i></button>'
                );
            }
        } else if (source === 'anilist') {
            if (category === 'anime') {
                $row.attr('data-missing-external', '0');
                $row.data('missing-external', '0');
            }
            if (!link) {
                link = 'https://anilist.co/anime/' + externalId;
            }
            if (!idCell.find('.badge-anilist').length) {
                badgeTarget.append(
                    '<a class="badge badge-anilist text-decoration-none" href="' + link + '" target="_blank" rel="noopener" data-bs-toggle="tooltip" data-bs-placement="top" title="' + externalId + '">AniList</a>'
                );
            }
        }
        var info = getRowInfo(mediaId);
        if (info) {
            info.hasTmdb = source === 'tmdb' ? true : info.hasTmdb;
            info.tmdbId = source === 'tmdb' ? externalId : info.tmdbId;
            info.hasTvdb = source === 'tvdb' ? true : info.hasTvdb;
            info.tvdbId = source === 'tvdb' ? externalId : info.tvdbId;
            info.missingExternal = false;
        }
        if (category === 'anime' && source === 'anilist') {
            idCell.attr('data-order', externalId || '');
        } else if (mediaType === 'movie') {
            idCell.attr('data-order', $row.data('tmdb-id') || '');
        } else {
            idCell.attr('data-order', $row.data('tvdb-id') || '');
        }
        table.draw(false);
        updateBulkState();
        updateStatsCounts();
    }

    function resetActionButton($row, target) {
        if (!$row || !$row.length) {
            return;
        }
        var $actions = $row.find('.wanted-actions');
        if (!$actions.length) {
            return;
        }
        if (target === 'radarr') {
            var $btn = $actions.find('.radarr-add-btn');
            if ($btn.length) {
                $btn.replaceWith(
                    '<span class="d-inline-flex" data-bs-toggle="tooltip" data-bs-placement="top" title="TMDB mancante">' +
                    '<button class="btn btn-sm btn-outline-secondary btn-icon d-inline-flex align-items-center justify-content-center" title="Radarr" disabled>' +
                    '<i class="bi bi-cloud-download"></i>' +
                    '</button></span>'
                );
            }
        } else if (target === 'sonarr') {
            var $sbtn = $actions.find('.sonarr-add-btn');
            if ($sbtn.length) {
                $sbtn.replaceWith(
                    '<span class="d-inline-flex" data-bs-toggle="tooltip" data-bs-placement="top" title="TVDB mancante">' +
                    '<button class="btn btn-sm btn-outline-secondary btn-icon d-inline-flex align-items-center justify-content-center" title="Sonarr" disabled>' +
                    '<i class="bi bi-cloud-download"></i>' +
                    '</button></span>'
                );
            }
        }
    }

    function removeExternalUpdate(mediaId, source, removed) {
        var $row = rowById[mediaId] ? $(rowById[mediaId]) : $('.wanted-select[value="' + mediaId + '"]').closest('tr');
        if (!$row.length) {
            return;
        }
        var mediaType = $row.data('media-type');
        var category = $row.data('category') || '';
        var idCell = $row.find('td').eq(4);
        function updateMissing() {
            var missing = false;
            var hasTmdb = $row.data('has-tmdb') === 1 || $row.data('has-tmdb') === '1';
            var hasTvdb = $row.data('has-tvdb') === 1 || $row.data('has-tvdb') === '1';
            if (mediaType === 'movie' && !hasTmdb) {
                missing = true;
            }
            if (mediaType === 'series' && !hasTvdb) {
                missing = true;
            }
            if (category === 'anime' && !$row.find('.badge-anilist').length) {
                missing = true;
            }
            $row.attr('data-missing-external', missing ? '1' : '0');
            $row.data('missing-external', missing ? '1' : '0');
        }

        function removeBadge(cls) {
            idCell.find(cls).remove();
        }

        if (source === 'tmdb') {
            $row.attr('data-has-tmdb', '0');
            $row.data('has-tmdb', '0');
            $row.attr('data-tmdb-id', '');
            $row.data('tmdb-id', '');
            removeBadge('.badge-tmdb');
            $row.attr('data-in-radarr', '0');
            $row.data('in-radarr', '0');
            removeBadge('.badge-radarr');
            resetActionButton($row, 'radarr');
        } else if (source === 'tvdb') {
            $row.attr('data-has-tvdb', '0');
            $row.data('has-tvdb', '0');
            $row.attr('data-tvdb-id', '');
            $row.data('tvdb-id', '');
            removeBadge('.badge-imdb');
            $row.attr('data-in-sonarr', '0');
            $row.data('in-sonarr', '0');
            removeBadge('.badge-sonarr');
            resetActionButton($row, 'sonarr');
        } else if (source === 'anilist') {
            removeBadge('.badge-anilist');
        } else if (source === 'radarr') {
            $row.attr('data-in-radarr', '0');
            $row.data('in-radarr', '0');
            removeBadge('.badge-radarr');
        } else if (source === 'sonarr') {
            $row.attr('data-in-sonarr', '0');
            $row.data('in-sonarr', '0');
            removeBadge('.badge-sonarr');
        }

        var info = getRowInfo(mediaId);
        if (info) {
            if (source === 'tmdb') {
                info.hasTmdb = false;
                info.tmdbId = '';
                info.inRadarr = false;
            } else if (source === 'tvdb') {
                info.hasTvdb = false;
                info.tvdbId = '';
                info.inSonarr = false;
            } else if (source === 'radarr') {
                info.inRadarr = false;
            } else if (source === 'sonarr') {
                info.inSonarr = false;
            }
        }

        if (removed && removed.indexOf('tvdb_link') !== -1) {
            $('#wantedInfoModal' + mediaId + ' .external-ref-row[data-source="tvdb_link"]').remove();
        }
        if (removed && removed.indexOf('anilist_link') !== -1) {
            $('#wantedInfoModal' + mediaId + ' .external-ref-row[data-source="anilist_link"]').remove();
        }
        if (removed && removed.indexOf('radarr') !== -1) {
            $('#wantedInfoModal' + mediaId + ' .external-ref-row[data-source="radarr"]').remove();
        }
        if (removed && removed.indexOf('sonarr') !== -1) {
            $('#wantedInfoModal' + mediaId + ' .external-ref-row[data-source="sonarr"]').remove();
        }

        if (mediaType === 'movie') {
            idCell.attr('data-order', $row.data('tmdb-id') || '');
        } else {
            idCell.attr('data-order', $row.data('tvdb-id') || '');
        }
        if (category === 'anime') {
            var anilistVal = $row.find('.badge-anilist').length ? $row.find('.badge-anilist').attr('title') : '';
            if (anilistVal) {
                idCell.attr('data-order', anilistVal);
            }
        }
        updateMissing();
        table.draw(false);
        updateBulkState();
        updateStatsCounts();
    }

    $(document).off('click.wanted', '.select-external-btn').on('click.wanted', '.select-external-btn', function() {
        var button = $(this);
        var mediaId = button.data('media-id');
        var source = button.data('source');
        var externalId = button.data('external-id');
        var link = button.data('link');

        button.prop('disabled', true).text('Salvo...');
        $.ajax({
            url: '/api/wanted/' + mediaId + '/external',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ source: source, external_id: externalId, link: link })
                }).done(function(resp) {
            applyExternalUpdate(mediaId, source, externalId, link);
            if (resp && resp.radarr_root) {
                updateRowRoot(mediaId, 'radarr', resp.radarr_root);
            }
            if (resp && resp.sonarr_root) {
                updateRowRoot(mediaId, 'sonarr', resp.sonarr_root);
            }
            if (resp && resp.sonarr_slug) {
                var $rowSlug = rowById[mediaId] ? $(rowById[mediaId]) : $('.wanted-select[value="' + mediaId + '"]').closest('tr');
                if ($rowSlug.length) {
                    $rowSlug.attr('data-sonarr-slug', resp.sonarr_slug);
                    $rowSlug.data('sonarr-slug', resp.sonarr_slug);
                }
            }
            if (resp && resp.downloaded_total !== undefined && resp.downloaded_total !== null) {
                updateRowDownloadStatus(mediaId, resp.downloaded_current, resp.downloaded_total);
            }
            if (source === 'tmdb' && resp && resp.in_radarr) {
                updateRowInRadarr(mediaId);
            }
            if (source === 'tvdb' && resp && resp.in_sonarr) {
                updateRowInSonarr(mediaId);
            }
            var modalEl = button.closest('.modal')[0];
            if (modalEl) {
                var modal = bootstrap.Modal.getInstance(modalEl);
                if (modal) {
                    modal.hide();
                }
            }
        }).fail(function() {
            button.prop('disabled', false).text('Seleziona');
        });
    });

    $(document).off('click.wanted', '.delete-single-btn').on('click.wanted', '.delete-single-btn', function(event) {
        event.preventDefault();
        var button = $(this);
        var mediaId = button.data('media-id');
        if (!mediaId) {
            return;
        }
        var url = '/wanted/' + mediaId + '/delete';
        button.prop('disabled', true).text('Elimino...');
        $.ajax({
            url: url,
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        }).done(function() {
            removeRowsByIds([String(mediaId)]);
            button.text('Eliminato');
            var modalEl = button.closest('.modal')[0];
            if (modalEl) {
                setTimeout(function() {
                    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
                    if (modal) {
                        modal.hide();
                    }
                }, 1000);
            }
        }).fail(function() {
            button.prop('disabled', false).text('Elimina');
        });
    });

    $(document).off('click.wanted', '.external-remove-btn').on('click.wanted', '.external-remove-btn', function() {
        var button = $(this);
        var mediaId = button.data('media-id');
        var source = button.data('source');
        if (!mediaId || !source) {
            return;
        }
        var ok = window.confirm('Vuoi rimuovere il riferimento "' + source + '"?');
        if (!ok) {
            return;
        }
        button.prop('disabled', true);
        $.ajax({
            url: '/api/wanted/' + mediaId + '/external/delete',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ source: source })
        }).done(function(resp) {
            var removed = (resp && resp.removed) ? resp.removed : [source];
            $('#wantedInfoModal' + mediaId + ' .external-ref-row[data-source="' + source + '"]').remove();
            removeExternalUpdate(String(mediaId), source, removed);
        }).fail(function() {
            button.prop('disabled', false);
        });
    });

    function updateBulkMatchConfirm() {
        var selected = 0;
        $('#bulk-match-table tbody tr').each(function() {
            var $row = $(this);
            var checked = $row.find('.bulk-match-check').is(':checked');
            var selectedId = $row.find('.bulk-match-select').val();
            if (checked && selectedId) {
                selected += 1;
            }
        });
        $('#bulk-match-confirm').prop('disabled', selected === 0);
        $('#bulk-match-summary').text(selected ? ('Da applicare: ' + selected) : '');
    }

    function updateBulkMatchLink($select) {
        var $row = $select.closest('tr');
        var $link = $row.find('.bulk-match-link');
        var $opt = $select.find('option:selected');
        var link = $opt.data('link') || '';
        if (link) {
            $link.attr('href', link).removeClass('d-none');
        } else {
            $link.attr('href', '#').addClass('d-none');
        }
    }

    function renderBulkMatchRows(source, items, state) {
        var $tbody = $('#bulk-match-table tbody');
        items.forEach(function(item) {
            var hasCandidates = item.candidates && item.candidates.length;
            if (hasCandidates) {
                state.found += 1;
            } else {
                state.missing += 1;
            }
            var options = ['<option value="">Nessun match</option>'];
            if (hasCandidates) {
                item.candidates.forEach(function(candidate) {
                    var label = candidate.title || '';
                    if (candidate.year) {
                        label += ' (' + candidate.year + ')';
                    }
                    var link = candidate.link || '';
                    options.push(
                        '<option value="' + candidate.external_id + '" data-link="' + link + '">' + label + '</option>'
                    );
                });
            }
            var checkedAttr = hasCandidates ? ' checked' : '';
            var queryText = item.query || '';
            var rowHtml = [
                '<tr data-media-id="', item.media_id, '" data-source="', source, '">',
                '<td class="text-center"><input class="form-check-input bulk-match-check" type="checkbox"', checkedAttr, '></td>',
                '<td>', item.title || '', '</td>',
                '<td>', item.year || '', '</td>',
                '<td>', item.media_type || '', '</td>',
                '<td>', queryText, '</td>',
                '<td>',
                '<div class="d-flex align-items-center gap-2">',
                '<select class="form-select form-select-sm bulk-match-select">', options.join(''), '</select>',
                '<a class="small text-decoration-none bulk-match-link d-none" target="_blank" rel="noopener">Apri</a>',
                '</div>',
                '</td>',
                '</tr>'
            ].join('');
            $tbody.append(rowHtml);
        });
        $('#bulk-match-selected').text(state.total);
        $('#bulk-match-found').text(state.found);
        $('#bulk-match-missing').text(state.missing);
        $tbody.find('.bulk-match-select').each(function() {
            var $select = $(this);
            if ($select.find('option').length > 1) {
                $select.prop('selectedIndex', 1);
            }
            updateBulkMatchLink($select);
        });
        updateBulkMatchConfirm();
    }

    function openBulkMatchModal(source) {
        var ids = source === 'tvdb' ? getTvdbMatchIds() : getTmdbMatchIds();
        var title = source === 'tvdb' ? 'Auto-match TVDB' : 'Auto-match TMDB';
        var state = {
            total: ids.length,
            processed: 0,
            found: 0,
            missing: 0
        };
        $('#bulk-match-title').text(title);
        $('#bulk-match-error').addClass('d-none');
        $('#bulk-match-status').removeClass('d-none').text('Ricerca in corso... 0/' + ids.length);
        $('#bulk-match-summary').text('');
        $('#bulk-match-progress').removeClass('d-none');
        $('#bulk-match-progress-bar')
            .css('width', '0%')
            .attr('aria-valuenow', 0)
            .text('0%');
        $('#bulk-match-selected').text('0');
        $('#bulk-match-found').text('0');
        $('#bulk-match-missing').text('0');
        $('#bulk-match-table tbody').empty();
        $('#bulk-match-confirm').prop('disabled', true);

        if (!ids.length) {
            $('#bulk-match-status').addClass('d-none');
            $('#bulk-match-error').removeClass('d-none').text('Nessun elemento selezionato.');
            return;
        }

        $('#bulkMatchModal').data('source', source);
        var chunkSize = 5;
        var batches = [];
        for (var i = 0; i < ids.length; i += chunkSize) {
            batches.push(ids.slice(i, i + chunkSize));
        }

        function processBatch(index) {
            if (index >= batches.length) {
                $('#bulk-match-status').addClass('d-none');
                return;
            }
            var batch = batches[index];
            $.ajax({
                url: '/api/wanted/bulk_lookup/' + source,
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ media_ids: batch })
            }).done(function(resp) {
                if (!resp || !resp.items) {
                    $('#bulk-match-error').removeClass('d-none').text('Risposta non valida.');
                    $('#bulk-match-status').addClass('d-none');
                    return;
                }
                state.processed += batch.length;
                renderBulkMatchRows(source, resp.items, state);
                var percent = state.total ? Math.min(100, Math.round((state.processed / state.total) * 100)) : 100;
                $('#bulk-match-status').removeClass('d-none').text(
                    'Ricerca in corso... ' + state.processed + '/' + state.total
                );
                $('#bulk-match-progress-bar')
                    .css('width', percent + '%')
                    .attr('aria-valuenow', percent)
                    .text(percent + '%');
                processBatch(index + 1);
            }).fail(function() {
                $('#bulk-match-error').removeClass('d-none').text('Errore durante la ricerca.');
                $('#bulk-match-status').addClass('d-none');
            });
        }

        processBatch(0);
    }

    $('#bulk-match-tvdb-btn').off('click.wanted').on('click.wanted', function() {
        openBulkMatchModal('tvdb');
    });

    $('#bulk-match-tmdb-btn').off('click.wanted').on('click.wanted', function() {
        openBulkMatchModal('tmdb');
    });

    $(document).off('change.wanted', '.bulk-match-select').on('change.wanted', '.bulk-match-select', function() {
        updateBulkMatchLink($(this));
        updateBulkMatchConfirm();
    });

    $(document).off('change.wanted', '.bulk-match-check').on('change.wanted', '.bulk-match-check', function() {
        updateBulkMatchConfirm();
    });

    $('#bulk-match-confirm').off('click.wanted').on('click.wanted', function() {
        var button = $(this);
        var source = $('#bulkMatchModal').data('source');
        var items = [];
        $('#bulk-match-table tbody tr').each(function() {
            var $row = $(this);
            var checked = $row.find('.bulk-match-check').is(':checked');
            var $select = $row.find('.bulk-match-select');
            var externalId = $select.val();
            if (!checked || !externalId) {
                return;
            }
            var link = $select.find('option:selected').data('link') || '';
            items.push({
                media_id: $row.data('media-id'),
                source: source,
                external_id: externalId,
                link: link
            });
        });
        if (!items.length) {
            return;
        }
        $('#bulk-match-error').addClass('d-none');
        $('#bulk-match-status').removeClass('d-none').text('Applico ' + items.length + ' match...');
        button.prop('disabled', true).text('Applico...');
        $.ajax({
            url: '/api/wanted/bulk_external',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ items: items })
        }).done(function(resp) {
            if (resp && resp.items) {
                resp.items.forEach(function(item) {
                    applyExternalUpdate(String(item.media_id), item.source, item.external_id, item.link);
                    if (item.in_radarr) {
                        updateRowInRadarr(String(item.media_id));
                    }
                    if (item.in_sonarr) {
                        updateRowInSonarr(String(item.media_id));
                    }
                });
            }
            var updated = resp && resp.updated ? resp.updated : 0;
            var skipped = resp && resp.skipped ? resp.skipped : 0;
            var errors = resp && resp.errors ? resp.errors : 0;
            $('#bulk-match-status').removeClass('d-none').text(
                'Completato: ' + updated + ' aggiornati, ' + skipped + ' saltati, ' + errors + ' errori.'
            );
            button.text('Completato');
            setTimeout(function() {
                var modalEl = document.getElementById('bulkMatchModal');
                if (modalEl) {
                    var modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) {
                        modal.hide();
                    }
                }
            }, 800);
        }).fail(function() {
            button.prop('disabled', false).text('Applica');
            $('#bulk-match-error').removeClass('d-none').text('Errore durante il salvataggio.');
            $('#bulk-match-status').addClass('d-none');
        });
    });

    $('#bulkMatchModal').off('hidden.bs.modal.wanted').on('hidden.bs.modal.wanted', function() {
        $('#bulk-match-status').addClass('d-none').text('Ricerca in corso...');
        $('#bulk-match-error').addClass('d-none').text('Errore durante la ricerca.');
        $('#bulk-match-summary').text('');
        $('#bulk-match-confirm').prop('disabled', true).text('Applica');
        $('#bulk-match-table tbody').empty();
        $('#bulk-match-progress').addClass('d-none');
        $('#bulk-match-progress-bar')
            .css('width', '0%')
            .attr('aria-valuenow', 0)
            .text('');
    });

    var radarrOptionsCache = null;
    var sonarrOptionsCache = null;

    function populateRadarrSelect($select, items, labelKey, valueKey) {
        if (!items || !items.length) {
            $select.html('<option value="">Nessuna opzione disponibile</option>');
            return;
        }
        var options = items.map(function(item) {
            var value = item[valueKey] || item.id;
            var label = item[labelKey] || item.path || item.name || item.id;
            return '<option value="' + value + '">' + label + '</option>';
        }).join('');
        $select.html(options);
    }

    function loadRadarrOptions($rootSelect, $profileSelect, $errorEl, preferredRoot, preferredProfile) {
        $errorEl.addClass('d-none');
        if (radarrOptionsCache) {
            populateRadarrSelect($rootSelect, radarrOptionsCache.root_folders, 'path', 'path');
            populateRadarrSelect($profileSelect, radarrOptionsCache.profiles, 'name', 'id');
            applyRadarrDefaults($rootSelect, $profileSelect);
            if (preferredRoot) {
                $rootSelect.val(preferredRoot);
            }
            if (preferredProfile) {
                $profileSelect.val(String(preferredProfile));
            }
            return $.Deferred().resolve().promise();
        }
        $rootSelect.html('<option value="">Caricamento...</option>');
        $profileSelect.html('<option value="">Caricamento...</option>');
        return $.getJSON('/api/radarr/options', function(resp) {
            radarrOptionsCache = resp || {};
            populateRadarrSelect($rootSelect, radarrOptionsCache.root_folders, 'path', 'path');
            populateRadarrSelect($profileSelect, radarrOptionsCache.profiles, 'name', 'id');
            applyRadarrDefaults($rootSelect, $profileSelect);
            if (preferredRoot) {
                $rootSelect.val(preferredRoot);
            }
            if (preferredProfile) {
                $profileSelect.val(String(preferredProfile));
            }
        }).fail(function() {
            $errorEl.removeClass('d-none').text('Errore nel caricamento delle opzioni Radarr.');
            $rootSelect.html('<option value="">Errore</option>');
            $profileSelect.html('<option value="">Errore</option>');
        });
    }

    function applyRadarrDefaults($rootSelect, $profileSelect) {
        var defaultRoot = $('#radarr-default-root').val();
        var defaultProfile = $('#radarr-default-profile').val();
        var defaultSearch = $('#radarr-default-search').val();
        if (defaultRoot) {
            $rootSelect.val(defaultRoot);
        }
        if (defaultProfile) {
            $profileSelect.val(defaultProfile);
        }
        if (defaultSearch !== undefined) {
            var enable = String(defaultSearch) === '1';
            $('#radarr-search-enable').prop('checked', enable);
            $('#bulk-radarr-search-enable').prop('checked', enable);
        }
    }

    function populateSonarrSelect($select, items, labelKey, valueKey) {
        if (!items || !items.length) {
            $select.html('<option value="">Nessuna opzione disponibile</option>');
            return;
        }
        var options = items.map(function(item) {
            var value = item[valueKey] || item.id;
            var label = item[labelKey] || item.path || item.name || item.id;
            return '<option value="' + value + '">' + label + '</option>';
        }).join('');
        $select.html(options);
    }

    function applySonarrDefaults($rootSelect, $profileSelect) {
        var defaultRoot = $('#sonarr-default-root').val();
        var defaultProfile = $('#sonarr-default-profile').val();
        var defaultSearch = $('#sonarr-default-search').val();
        if (defaultRoot) {
            $rootSelect.val(defaultRoot);
        }
        if (defaultProfile) {
            $profileSelect.val(defaultProfile);
        }
        if (defaultSearch !== undefined) {
            var enable = String(defaultSearch) === '1';
            $('#sonarr-search-enable').prop('checked', enable);
            $('#bulk-sonarr-search-enable').prop('checked', enable);
        }
    }

    function loadSonarrOptions($rootSelect, $profileSelect, $errorEl, preferredRoot, preferredProfile) {
        $errorEl.addClass('d-none');
        if (sonarrOptionsCache) {
            populateSonarrSelect($rootSelect, sonarrOptionsCache.root_folders, 'path', 'path');
            populateSonarrSelect($profileSelect, sonarrOptionsCache.profiles, 'name', 'id');
            applySonarrDefaults($rootSelect, $profileSelect);
            if (preferredRoot) {
                $rootSelect.val(preferredRoot);
            }
            if (preferredProfile) {
                $profileSelect.val(String(preferredProfile));
            }
            return $.Deferred().resolve().promise();
        }
        $rootSelect.html('<option value="">Caricamento...</option>');
        $profileSelect.html('<option value="">Caricamento...</option>');
        return $.getJSON('/api/sonarr/options', function(resp) {
            sonarrOptionsCache = resp || {};
            populateSonarrSelect($rootSelect, sonarrOptionsCache.root_folders, 'path', 'path');
            populateSonarrSelect($profileSelect, sonarrOptionsCache.profiles, 'name', 'id');
            applySonarrDefaults($rootSelect, $profileSelect);
            if (preferredRoot) {
                $rootSelect.val(preferredRoot);
            }
            if (preferredProfile) {
                $profileSelect.val(String(preferredProfile));
            }
        }).fail(function() {
            $errorEl.removeClass('d-none').text('Errore nel caricamento delle opzioni Sonarr.');
            $rootSelect.html('<option value="">Errore</option>');
            $profileSelect.html('<option value="">Errore</option>');
        });
    }

    $(document).off('click.wanted', '.radarr-add-btn').on('click.wanted', '.radarr-add-btn', function() {
        var mediaId = $(this).data('media-id');
        var title = $(this).data('title');
        var $row = $(this).closest('tr');
        var inRadarr = $row.data('in-radarr') === 1 || $row.data('in-radarr') === '1';
        var mode = inRadarr ? 'update' : 'add';
        var modal = $('#radarrAddModal');
        var preferredRoot = $row.data('radarr-root') || '';
        var preferredProfile = $row.data('radarr-profile') || '';
        modal.data('mode', mode);
        modal.data('preferredRoot', preferredRoot);
        modal.data('preferredProfile', preferredProfile);
        $('#radarr-add-media-id').val(mediaId);
        $('#radarr-add-title').text('Seleziona root e profilo per: ' + title);
        $('#radarr-add-confirm').text(mode === 'update' ? 'Aggiorna' : 'Invia');
        $('#radarr-add-modal-title').text(mode === 'update' ? 'Aggiorna su Radarr' : 'Invia a Radarr');
    });

    $(document).off('click.wanted', '.sonarr-add-btn').on('click.wanted', '.sonarr-add-btn', function() {
        var mediaId = $(this).data('media-id');
        var title = $(this).data('title');
        var $row = $(this).closest('tr');
        var inSonarr = $row.data('in-sonarr') === 1 || $row.data('in-sonarr') === '1';
        var mode = inSonarr ? 'update' : 'add';
        var modal = $('#sonarrAddModal');
        var preferredRoot = $row.data('sonarr-root') || '';
        var preferredProfile = $row.data('sonarr-profile') || '';
        modal.data('mode', mode);
        modal.data('preferredRoot', preferredRoot);
        modal.data('preferredProfile', preferredProfile);
        $('#sonarr-add-media-id').val(mediaId);
        $('#sonarr-add-title').text('Seleziona root e profilo per: ' + title);
        $('#sonarr-add-confirm').text(mode === 'update' ? 'Aggiorna' : 'Invia');
        $('#sonarr-add-modal-title').text(mode === 'update' ? 'Aggiorna su Sonarr' : 'Invia a Sonarr');
    });

    function setRadarrModalLoading(isLoading, text) {
        var $status = $('#radarr-add-status');
        var $confirm = $('#radarr-add-confirm');
        $('#radarr-root-select, #radarr-profile-select, #radarr-search-enable').prop('disabled', !!isLoading);
        $confirm.prop('disabled', !!isLoading);
        if (isLoading) {
            $status.removeClass('d-none').text(text || 'Caricamento...');
        } else {
            $status.addClass('d-none').text('Invio a Radarr in corso...');
            var mode = $('#radarrAddModal').data('mode') || 'add';
            $confirm.text(mode === 'update' ? 'Aggiorna' : 'Invia');
        }
    }

    function setSonarrModalLoading(isLoading, text) {
        var $status = $('#sonarr-add-status');
        var $confirm = $('#sonarr-add-confirm');
        $('#sonarr-root-select, #sonarr-profile-select, #sonarr-search-enable, #sonarr-monitor-specials').prop('disabled', !!isLoading);
        $confirm.prop('disabled', !!isLoading);
        if (isLoading) {
            $status.removeClass('d-none').text(text || 'Caricamento...');
        } else {
            $status.addClass('d-none').text('Invio a Sonarr in corso...');
            var mode = $('#sonarrAddModal').data('mode') || 'add';
            $confirm.text(mode === 'update' ? 'Aggiorna' : 'Invia');
        }
    }

    $('#radarrAddModal').off('show.bs.modal.wanted').on('show.bs.modal.wanted', function() {
        setRadarrModalLoading(true, 'Caricamento dati live da Radarr...');
        var modal = $(this);
        var fallbackRoot = modal.data('preferredRoot') || '';
        var fallbackProfile = modal.data('preferredProfile') || '';
        var mediaId = $('#radarr-add-media-id').val();
        var $root = $('#radarr-root-select');
        var $profile = $('#radarr-profile-select');
        var reqSeq = (Number(modal.data('statusReqSeq')) || 0) + 1;
        modal.data('statusReqSeq', reqSeq);
        var prevReq = modal.data('statusReqXhr');
        if (prevReq && prevReq.readyState !== 4) prevReq.abort();

        function isCurrentRequest() {
            return Number(modal.data('statusReqSeq')) === reqSeq;
        }

        function applyOptions(rootValue, profileValue) {
            return loadRadarrOptions($root, $profile, $('#radarr-add-error'), rootValue || fallbackRoot, profileValue || fallbackProfile);
        }

        function applyLive(rootValue, profileValue) {
            return $.when(applyOptions(rootValue, profileValue)).always(function() {
                var $row = rowById[mediaId] ? $(rowById[mediaId]) : $('.wanted-select[value="' + mediaId + '"]').closest('tr');
                if ($row.length) {
                    if (rootValue) {
                        $row.attr('data-radarr-root', rootValue);
                        $row.data('radarr-root', rootValue);
                    }
                    if (profileValue) {
                        $row.attr('data-radarr-profile', String(profileValue));
                        $row.data('radarr-profile', String(profileValue));
                    }
                }
            });
        }

        if (!mediaId) {
            $.when(applyOptions(fallbackRoot, fallbackProfile)).always(function() {
                if (isCurrentRequest()) setRadarrModalLoading(false);
            });
            return;
        }

        var xhr = $.getJSON('/api/wanted/' + mediaId + '/status', function(resp) {
            if (!isCurrentRequest()) return;
            var job;
            if (resp && resp.ok && resp.in_radarr) {
                job = applyLive(resp.radarr_root || '', resp.radarr_profile_id ? String(resp.radarr_profile_id) : '');
            } else {
                job = applyOptions(fallbackRoot, fallbackProfile);
            }
            $.when(job).always(function() {
                if (isCurrentRequest()) setRadarrModalLoading(false);
            });
        }).fail(function(_, textStatus) {
            if (!isCurrentRequest() || textStatus === 'abort') return;
            $.when(applyOptions(fallbackRoot, fallbackProfile)).always(function() {
                if (isCurrentRequest()) setRadarrModalLoading(false);
            });
        }).always(function() {
            if (isCurrentRequest()) modal.removeData('statusReqXhr');
        });
        modal.data('statusReqXhr', xhr);
    });

    $('#sonarrAddModal').off('show.bs.modal.wanted').on('show.bs.modal.wanted', function() {
        setSonarrModalLoading(true, 'Caricamento dati live da Sonarr...');
        var modal = $(this);
        var fallbackRoot = modal.data('preferredRoot') || '';
        var fallbackProfile = modal.data('preferredProfile') || '';
        var mediaId = $('#sonarr-add-media-id').val();
        var $root = $('#sonarr-root-select');
        var $profile = $('#sonarr-profile-select');
        var reqSeq = (Number(modal.data('statusReqSeq')) || 0) + 1;
        modal.data('statusReqSeq', reqSeq);
        var prevReq = modal.data('statusReqXhr');
        if (prevReq && prevReq.readyState !== 4) prevReq.abort();

        function isCurrentRequest() {
            return Number(modal.data('statusReqSeq')) === reqSeq;
        }

        function applyOptions(rootValue, profileValue) {
            return loadSonarrOptions($root, $profile, $('#sonarr-add-error'), rootValue || fallbackRoot, profileValue || fallbackProfile);
        }

        function applyLive(rootValue, profileValue, slugValue) {
            return $.when(applyOptions(rootValue, profileValue)).always(function() {
                var $row = rowById[mediaId] ? $(rowById[mediaId]) : $('.wanted-select[value="' + mediaId + '"]').closest('tr');
                if ($row.length) {
                    if (rootValue) {
                        $row.attr('data-sonarr-root', rootValue);
                        $row.data('sonarr-root', rootValue);
                    }
                    if (profileValue) {
                        $row.attr('data-sonarr-profile', String(profileValue));
                        $row.data('sonarr-profile', String(profileValue));
                    }
                    if (slugValue) {
                        $row.attr('data-sonarr-slug', slugValue);
                        $row.data('sonarr-slug', slugValue);
                    }
                }
            });
        }

        if (!mediaId) {
            $.when(applyOptions(fallbackRoot, fallbackProfile)).always(function() {
                if (isCurrentRequest()) setSonarrModalLoading(false);
            });
            return;
        }

        var xhr = $.getJSON('/api/wanted/' + mediaId + '/status', function(resp) {
            if (!isCurrentRequest()) return;
            var job;
            if (resp && resp.ok && resp.in_sonarr) {
                job = applyLive(
                    resp.sonarr_root || '',
                    resp.sonarr_profile_id ? String(resp.sonarr_profile_id) : '',
                    resp.sonarr_slug || ''
                );
            } else {
                job = applyOptions(fallbackRoot, fallbackProfile);
            }
            $.when(job).always(function() {
                if (isCurrentRequest()) setSonarrModalLoading(false);
            });
        }).fail(function(_, textStatus) {
            if (!isCurrentRequest() || textStatus === 'abort') return;
            $.when(applyOptions(fallbackRoot, fallbackProfile)).always(function() {
                if (isCurrentRequest()) setSonarrModalLoading(false);
            });
        }).always(function() {
            if (isCurrentRequest()) modal.removeData('statusReqXhr');
        });
        modal.data('statusReqXhr', xhr);
    });

    $('#radarrAddModal').off('hidden.bs.modal.wanted').on('hidden.bs.modal.wanted', function() {
        setRadarrModalLoading(false);
        var req = $(this).data('statusReqXhr');
        if (req && req.readyState !== 4) req.abort();
        $('#radarr-add-error').addClass('d-none').text('Errore durante il caricamento.');
        $('#radarr-add-status').addClass('d-none').text('Invio a Radarr in corso...');
        $('#radarr-add-confirm').prop('disabled', false).text('Invia');
        applyRadarrDefaults($('#radarr-root-select'), $('#radarr-profile-select'));
        $(this).data('mode', 'add');
        $(this).data('preferredRoot', '');
        $(this).data('preferredProfile', '');
        $(this).removeData('statusReqXhr');
        $('#radarr-add-modal-title').text('Invia a Radarr');
    });

    $('#sonarrAddModal').off('hidden.bs.modal.wanted').on('hidden.bs.modal.wanted', function() {
        setSonarrModalLoading(false);
        var req = $(this).data('statusReqXhr');
        if (req && req.readyState !== 4) req.abort();
        $('#sonarr-add-error').addClass('d-none').text('Errore durante il caricamento.');
        $('#sonarr-add-status').addClass('d-none').text('Invio a Sonarr in corso...');
        $('#sonarr-add-confirm').prop('disabled', false).text('Invia');
        applySonarrDefaults($('#sonarr-root-select'), $('#sonarr-profile-select'));
        $('#sonarr-monitor-specials').prop('checked', false);
        $(this).data('mode', 'add');
        $(this).data('preferredRoot', '');
        $(this).data('preferredProfile', '');
        $(this).removeData('statusReqXhr');
        $('#sonarr-add-modal-title').text('Invia a Sonarr');
    });
    function configureBulkRadarrModal() {
        var mode = getRadarrBulkMode();
        var $modal = $('#bulkRadarrModal');
        var $title = $modal.find('.modal-title');
        var $confirm = $('#bulk-radarr-confirm');
        if (mode === 'update') {
            $title.text('Aggiorna selezionati su Radarr');
            $confirm.text('Aggiorna');
        } else {
            $title.text('Invia selezionati a Radarr');
            $confirm.text('Invia');
        }
    }

    $('#bulkRadarrModal').off('show.bs.modal.wanted').on('show.bs.modal.wanted', function() {
        loadRadarrOptions(
            $('#bulk-radarr-root'),
            $('#bulk-radarr-profile'),
            $('#bulk-radarr-error'),
            ''
        );
        configureBulkRadarrModal();
    });
    $('#bulkRadarrModal').off('hidden.bs.modal.wanted').on('hidden.bs.modal.wanted', function() {
        $('#bulk-radarr-error').addClass('d-none').text('Errore durante il caricamento.');
        $('#bulk-radarr-status').addClass('d-none').text('Invio a Radarr in corso...');
        $('#bulk-radarr-confirm').prop('disabled', false).text('Invia');
        applyRadarrDefaults($('#bulk-radarr-root'), $('#bulk-radarr-profile'));
    });


    function configureBulkSonarrModal() {
        var mode = getSonarrBulkMode();
        var $modal = $('#bulkSonarrModal');
        var $title = $modal.find('.modal-title');
        var $confirm = $('#bulk-sonarr-confirm');
        if (mode === 'update') {
            $title.text('Aggiorna selezionati su Sonarr');
            $confirm.text('Aggiorna');
        } else {
            $title.text('Invia selezionati a Sonarr');
            $confirm.text('Invia');
        }
    }

    $('#bulkSonarrModal').off('show.bs.modal.wanted').on('show.bs.modal.wanted', function() {
        loadSonarrOptions(
            $('#bulk-sonarr-root'),
            $('#bulk-sonarr-profile'),
            $('#bulk-sonarr-error'),
            ''
        );
        configureBulkSonarrModal();
    });
    $('#bulkSonarrModal').off('hidden.bs.modal.wanted').on('hidden.bs.modal.wanted', function() {
        $('#bulk-sonarr-error').addClass('d-none').text('Errore durante il caricamento.');
        $('#bulk-sonarr-status').addClass('d-none').text('Invio a Sonarr in corso...');
        $('#bulk-sonarr-confirm').prop('disabled', false).text('Invia');
        applySonarrDefaults($('#bulk-sonarr-root'), $('#bulk-sonarr-profile'));
        $('#bulk-sonarr-monitor-specials').prop('checked', false);
    });


    $('#radarr-add-confirm').off('click.wanted').on('click.wanted', function() {
        var button = $(this);
        var mediaId = $('#radarr-add-media-id').val();
        var root = $('#radarr-root-select').val();
        var profile = $('#radarr-profile-select').val();
        var enableSearch = $('#radarr-search-enable').is(':checked');
        var mode = $('#radarrAddModal').data('mode') || 'add';
        if (!mediaId || !root || !profile) {
            $('#radarr-add-error').removeClass('d-none').text('Seleziona root e profilo.');
            return;
        }
        $('#radarr-add-error').addClass('d-none');
        $('#radarr-add-status').removeClass('d-none').text(mode === 'update' ? 'Aggiornamento in corso...' : 'Invio a Radarr in corso...');
        button.prop('disabled', true).text(mode === 'update' ? 'Aggiorno...' : 'Invio...');
        $.ajax({
            url: '/api/wanted/' + mediaId + '/radarr/' + (mode === 'update' ? 'update' : 'add'),
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ root_folder: root, profile_id: profile, enable_search: enableSearch })
        }).done(function() {
            $('#radarr-add-status').removeClass('d-none').text(mode === 'update' ? 'Aggiornato su Radarr.' : 'Inviato a Radarr. Aggiorno la lista...');
            setTimeout(function() {
                var modalEl = document.getElementById('radarrAddModal');
                if (modalEl) {
                    var modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) {
                        modal.hide();
                    }
                }
                if (mode === 'add') {
                    markRowDownloadPendingById(mediaId);
                    updateRowRoot(mediaId, 'radarr', root);
                    schedulePendingRefresh(2000);
                } else {
                    updateRowInRadarr(mediaId);
                    updateRowRoot(mediaId, 'radarr', root);
                }
            }, 900);
        }).fail(function() {
            button.prop('disabled', false).text(mode === 'update' ? 'Aggiorna' : 'Invia');
            $('#radarr-add-status').addClass('d-none');
            $('#radarr-add-error').removeClass('d-none').text(mode === 'update' ? 'Errore durante l\'aggiornamento.' : 'Errore durante il push a Radarr.');
        });
    });

    $('#sonarr-add-confirm').off('click.wanted').on('click.wanted', function() {
        var button = $(this);
        var mediaId = $('#sonarr-add-media-id').val();
        var root = $('#sonarr-root-select').val();
        var profile = $('#sonarr-profile-select').val();
        var enableSearch = $('#sonarr-search-enable').is(':checked');
        var monitorSpecials = $('#sonarr-monitor-specials').is(':checked');
        var mode = $('#sonarrAddModal').data('mode') || 'add';
        if (!mediaId || !root || !profile) {
            $('#sonarr-add-error').removeClass('d-none').text('Seleziona root e profilo.');
            return;
        }
        $('#sonarr-add-error').addClass('d-none');
        $('#sonarr-add-status').removeClass('d-none').text(mode === 'update' ? 'Aggiornamento in corso...' : 'Invio a Sonarr in corso...');
        button.prop('disabled', true).text(mode === 'update' ? 'Aggiorno...' : 'Invio...');
        $.ajax({
            url: '/api/wanted/' + mediaId + '/sonarr/' + (mode === 'update' ? 'update' : 'add'),
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                root_folder: root,
                profile_id: profile,
                enable_search: enableSearch,
                monitor_specials: monitorSpecials ? 1 : 0
            })
        }).done(function() {
            $('#sonarr-add-status').removeClass('d-none').text(mode === 'update' ? 'Aggiornato su Sonarr.' : 'Inviato a Sonarr. Aggiorno la lista...');
            setTimeout(function() {
                var modalEl = document.getElementById('sonarrAddModal');
                if (modalEl) {
                    var modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) {
                        modal.hide();
                    }
                }
                if (mode === 'add') {
                    markRowDownloadPendingById(mediaId);
                    updateRowRoot(mediaId, 'sonarr', root);
                    schedulePendingRefresh(PENDING_REFRESH_DELAY_MS);
                } else {
                    updateRowInSonarr(mediaId);
                    updateRowRoot(mediaId, 'sonarr', root);
                }
            }, 1200);
        }).fail(function() {
            button.prop('disabled', false).text(mode === 'update' ? 'Aggiorna' : 'Invia');
            $('#sonarr-add-status').addClass('d-none');
            $('#sonarr-add-error').removeClass('d-none').text(mode === 'update' ? 'Errore durante l\'aggiornamento.' : 'Errore durante il push a Sonarr.');
        });
    });

    $('#bulk-radarr-confirm').off('click.wanted').on('click.wanted', function() {
        var button = $(this);
        var root = $('#bulk-radarr-root').val();
        var profile = $('#bulk-radarr-profile').val();
        var mode = getRadarrBulkMode();
        var mediaIds = mode === 'update' ? getRadarrUpdateIds() : getRadarrEligibleIds();
        var enableSearch = $('#bulk-radarr-search-enable').is(':checked');
        if (!mediaIds.length || !root || !profile) {
            $('#bulk-radarr-error').removeClass('d-none').text('Seleziona elementi, root e profilo.');
            return;
        }
        if (mode === 'mixed' || mode === 'none') {
            $('#bulk-radarr-error').removeClass('d-none').text('Record misti: separa in due selezioni.');
            return;
        }
        $('#bulk-radarr-error').addClass('d-none');
        $('#bulk-radarr-status').removeClass('d-none').text(mode === 'update' ? 'Aggiornamento in corso...' : 'Invio a Radarr in corso...');
        button.prop('disabled', true).text(mode === 'update' ? 'Aggiorno...' : 'Invio...');
        $.ajax({
            url: '/api/wanted/radarr/' + (mode === 'update' ? 'bulk_update' : 'bulk_add'),
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ media_ids: mediaIds, root_folder: root, profile_id: profile, enable_search: enableSearch })
        }).done(function(resp) {
            $('#bulk-radarr-status').removeClass('d-none').text(mode === 'update' ? 'Aggiornati su Radarr.' : 'Inviati a Radarr. Aggiorno la lista...');
            setTimeout(function() {
                var modalEl = document.getElementById('bulkRadarrModal');
                if (modalEl) {
                    var modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) {
                        modal.hide();
                    }
                }
                if (mode === 'add') {
                    mediaIds.forEach(function(id) {
                        markRowDownloadPendingById(id);
                        updateRowRoot(id, 'radarr', root);
                    });
                    schedulePendingRefresh(2000);
                } else {
                    mediaIds.forEach(function(id) {
                        updateRowInRadarr(id);
                        updateRowRoot(id, 'radarr', root);
                    });
                }
            }, 900);
        }).fail(function() {
            button.prop('disabled', false).text(mode === 'update' ? 'Aggiorna' : 'Invia');
            $('#bulk-radarr-status').addClass('d-none');
            $('#bulk-radarr-error').removeClass('d-none').text(mode === 'update' ? 'Errore durante l\'aggiornamento.' : 'Errore durante il push bulk.');
        });
    });


    $('#bulk-sonarr-confirm').off('click.wanted').on('click.wanted', function() {
        var button = $(this);
        var root = $('#bulk-sonarr-root').val();
        var profile = $('#bulk-sonarr-profile').val();
        var mode = getSonarrBulkMode();
        var mediaIds = mode === 'update' ? getSonarrUpdateIds() : getSonarrEligibleIds();
        var enableSearch = $('#bulk-sonarr-search-enable').is(':checked');
        var monitorSpecials = $('#bulk-sonarr-monitor-specials').is(':checked');
        if (!mediaIds.length || !root || !profile) {
            $('#bulk-sonarr-error').removeClass('d-none').text('Seleziona elementi, root e profilo.');
            return;
        }
        if (mode === 'mixed' || mode === 'none') {
            $('#bulk-sonarr-error').removeClass('d-none').text('Record misti: separa in due selezioni.');
            return;
        }
        $('#bulk-sonarr-error').addClass('d-none');
        $('#bulk-sonarr-status').removeClass('d-none').text(mode === 'update' ? 'Aggiornamento in corso...' : 'Invio a Sonarr in corso...');
        button.prop('disabled', true).text(mode === 'update' ? 'Aggiorno...' : 'Invio...');
        $.ajax({
            url: '/api/wanted/sonarr/' + (mode === 'update' ? 'bulk_update' : 'bulk_add'),
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                media_ids: mediaIds,
                root_folder: root,
                profile_id: profile,
                enable_search: enableSearch,
                monitor_specials: monitorSpecials ? 1 : 0
            })
        }).done(function(resp) {
            $('#bulk-sonarr-status').removeClass('d-none').text(mode === 'update' ? 'Aggiornati su Sonarr.' : 'Inviati a Sonarr. Aggiorno la lista...');
            setTimeout(function() {
                var modalEl = document.getElementById('bulkSonarrModal');
                if (modalEl) {
                    var modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) {
                        modal.hide();
                    }
                }
                if (mode === 'add') {
                    mediaIds.forEach(function(id) {
                        markRowDownloadPendingById(id);
                        updateRowRoot(id, 'sonarr', root);
                    });
                    schedulePendingRefresh(PENDING_REFRESH_DELAY_MS);
                } else {
                    mediaIds.forEach(function(id) {
                        updateRowInSonarr(id);
                        updateRowRoot(id, 'sonarr', root);
                    });
                }
            }, 1200);
        }).fail(function() {
            button.prop('disabled', false).text(mode === 'update' ? 'Aggiorna' : 'Invia');
            $('#bulk-sonarr-status').addClass('d-none');
            $('#bulk-sonarr-error').removeClass('d-none').text(mode === 'update' ? 'Errore durante l\'aggiornamento.' : 'Errore durante il push bulk.');
        });
    });


    var mergePreviewData = null;

    function renderMergeItems(items) {
        return items.map(function(item) {
            var meta = [];
            if (item.year) {
                meta.push(item.year);
            }
            if (item.media_type) {
                meta.push(item.media_type);
            }
            if (item.category) {
                meta.push(item.category);
            }
            var metaText = meta.length ? ' (' + meta.join(', ') + ')' : '';
            return '<div class="mb-1">#' + item.id + ' - ' + item.title + metaText + '</div>';
        }).join('');
    }

    function renderExcluded(items) {
        var labels = {
            invalid_id: 'ID non valido',
            not_found: 'Elemento non trovato',
            missing_anilist: 'Manca AniList ID',
            missing_tvdb: 'Manca TVDB ID',
            missing_tmdb: 'Manca TMDB ID'
        };
        return items.map(function(item) {
            var reason = labels[item.reason] || item.reason || 'Escluso';
            var title = item.title ? ' - ' + item.title : '';
            return '<div class="mb-1">#' + item.id + title + ' Â· ' + reason + '</div>';
        }).join('');
    }

    function renderMergePreview(preview) {
        mergePreviewData = preview;
        var groups = preview.merge_groups || [];
        var singletons = preview.singletons || [];
        var excluded = preview.excluded || [];

        if (groups.length) {
            var html = groups.map(function(group) {
                var header = '<div class="fw-semibold mt-2">[' + group.source.toUpperCase() + ' ' + group.external_id + '] keep #' + group.keep_id + '</div>';
                return header + renderMergeItems(group.items);
            }).join('');
            $('#merge-preview-groups').html(html);
        } else {
            $('#merge-preview-groups').html('<div class="text-muted">Nessun gruppo mergiabile.</div>');
        }

        if (singletons.length) {
            $('#merge-preview-singletons').html(renderMergeItems(singletons));
        } else {
            $('#merge-preview-singletons').html('<div class="text-muted">Nessun elemento.</div>');
        }

        if (excluded.length) {
            $('#merge-preview-excluded').html(renderExcluded(excluded));
        } else {
            $('#merge-preview-excluded').html('<div class="text-muted">Nessun elemento.</div>');
        }

        var summary = 'Gruppi: ' + groups.length + ' Â· Non matchano: ' + singletons.length + ' Â· Esclusi: ' + excluded.length;
        $('#merge-preview-summary').text(summary);
        $('#merge-confirm-btn').prop('disabled', groups.length === 0);
    }

    $('#mergeWantedModal').off('show.bs.modal.wanted').on('show.bs.modal.wanted', function() {
        var ids = getSelectedIds();
        mergePreviewData = null;
        $('#merge-preview-status').removeClass('d-none').text('Caricamento anteprima merge...');
        $('#merge-preview-groups').html('<div class="text-muted">Nessun gruppo.</div>');
        $('#merge-preview-singletons').html('<div class="text-muted">Nessun elemento.</div>');
        $('#merge-preview-excluded').html('<div class="text-muted">Nessun elemento.</div>');
        $('#merge-preview-summary').text('');
        $('#merge-confirm-btn').prop('disabled', true);

        if (!ids.length) {
            $('#merge-preview-status').removeClass('d-none').text('Nessun elemento selezionato.');
            return;
        }

        $.ajax({
            url: '/api/wanted/merge/preview',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ media_ids: ids })
        }).done(function(resp) {
            $('#merge-preview-status').addClass('d-none');
            renderMergePreview(resp);
        }).fail(function() {
            $('#merge-preview-status').removeClass('d-none').text('Errore durante il caricamento della preview.');
        });
    });

    $('#merge-confirm-btn').off('click.wanted').on('click.wanted', function() {
        var button = $(this);
        if (!mergePreviewData || !mergePreviewData.merge_groups || !mergePreviewData.merge_groups.length) {
            return;
        }
        var groupsPayload = mergePreviewData.merge_groups.map(function(group) {
            var mergeIds = group.items.map(function(item) { return item.id; })
                .filter(function(id) { return id !== group.keep_id; });
            return {
                keep_id: group.keep_id,
                merge_ids: mergeIds
            };
        });
        button.prop('disabled', true).text('Merge in corso...');
        $.ajax({
            url: '/api/wanted/merge/commit',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ groups: groupsPayload })
        }).done(function() {
            button.text('Completato');
            setTimeout(function() {
                var mergeIds = [];
                mergePreviewData.merge_groups.forEach(function(group) {
                    group.items.forEach(function(item) {
                        if (item.id !== group.keep_id) {
                            mergeIds.push(String(item.id));
                        }
                    });
                });
                if (mergeIds.length) {
                    removeRowsByIds(mergeIds);
                }
                var modalEl = document.getElementById('mergeWantedModal');
                if (modalEl) {
                    var modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) {
                        modal.hide();
                    }
                }
            }, 900);
        }).fail(function() {
            button.prop('disabled', false).text('Esegui merge');
        });
    });

    function refreshWantedStatus() {
        var ids = [];
        table.rows().nodes().to$().each(function() {
            var $row = $(this);
            var mediaId = $row.find('.wanted-select').val();
            if (!mediaId) {
                return;
            }
            var hasTmdb = $row.data('has-tmdb') === 1 || $row.data('has-tmdb') === '1';
            var hasTvdb = $row.data('has-tvdb') === 1 || $row.data('has-tvdb') === '1';
            if (!hasTmdb && !hasTvdb) {
                return;
            }
            ids.push(String(mediaId));
        });
        if (!ids.length) {
            return;
        }
        var idx = 0;
        function next() {
            if (idx >= ids.length) {
                return;
            }
            var mediaId = ids[idx++];
            $.getJSON('/api/wanted/' + mediaId + '/status', function(resp) {
                if (!resp || !resp.ok) {
                    return;
                }
                if (resp.sonarr_slug) {
                    var $row = rowById[mediaId] ? $(rowById[mediaId]) : $('.wanted-select[value="' + mediaId + '"]').closest('tr');
                    if ($row.length) {
                        $row.attr('data-sonarr-slug', resp.sonarr_slug);
                        $row.data('sonarr-slug', resp.sonarr_slug);
                    }
                }
                var $targetRow = rowById[mediaId] ? $(rowById[mediaId]) : $('.wanted-select[value="' + mediaId + '"]').closest('tr');
                if ($targetRow.length) {
                    $targetRow.attr('data-status-pending', '0');
                    $targetRow.data('status-pending', '0');
                }
                var info = getRowInfo(mediaId);
                if (info) {
                    info.statusPending = false;
                }
                if (resp.in_radarr) {
                    updateRowInRadarr(mediaId);
                } else if ($targetRow.length) {
                    $targetRow.attr('data-in-radarr', '0');
                    $targetRow.data('in-radarr', '0');
                    $targetRow.find('.radarr-add-btn').prop('disabled', false);
                }
                if (resp.in_sonarr) {
                    updateRowInSonarr(mediaId);
                } else if ($targetRow.length) {
                    $targetRow.attr('data-in-sonarr', '0');
                    $targetRow.data('in-sonarr', '0');
                    $targetRow.find('.sonarr-add-btn').prop('disabled', false);
                }
                if (resp.radarr_root) {
                    updateRowRoot(mediaId, 'radarr', resp.radarr_root);
                }
                if (resp.sonarr_root) {
                    updateRowRoot(mediaId, 'sonarr', resp.sonarr_root);
                }
                updateRowDownloadStatus(mediaId, resp.downloaded_current, resp.downloaded_total);
                var infoFinal = getRowInfo(mediaId);
                if (infoFinal) {
                    infoFinal.inRadarr = !!resp.in_radarr;
                    infoFinal.inSonarr = !!resp.in_sonarr;
                }
                updateStatsCounts();
                updateBulkState();
            }).always(function() {
                setTimeout(next, 150);
            });
        }
        next();
    }

    buildRowIndex();
    applyFilters();
    syncSelectionToTable();
    refreshWantedStatus();

    table.off('draw.wanted').on('draw.wanted', function() {
        syncSelectionToTable();
    });

    table.off('select.wanted').on('select.wanted', function(e, dt, type, indexes) {
        if (isSyncingSelection || type !== 'row') {
            return;
        }
        table.rows(indexes).every(function() {
            var row = this.node();
            if (!row) {
                return;
            }
            var id = $(row).find('.wanted-select').val();
            if (id) {
                selectedIds.add(id);
                $(row).find('.wanted-select').prop('checked', true);
            }
        });
        updateBulkState();
    });

    table.off('deselect.wanted').on('deselect.wanted', function(e, dt, type, indexes) {
        if (isSyncingSelection || type !== 'row') {
            return;
        }
        table.rows(indexes).every(function() {
            var row = this.node();
            if (!row) {
                return;
            }
            var id = $(row).find('.wanted-select').val();
            if (id) {
                selectedIds.delete(id);
                $(row).find('.wanted-select').prop('checked', false);
            }
        });
        updateBulkState();
    });

    populateImportFilter();
}

document.addEventListener('DOMContentLoaded', function() {
    function parseOrderParam(value) {
        if (!value) {
            return [];
        }
        return value.split(';').map(function(part) {
            var bits = part.split(',');
            if (bits.length !== 2) {
                return null;
            }
            var col = parseInt(bits[0], 10);
            var dir = bits[1];
            if (Number.isNaN(col) || (dir !== 'asc' && dir !== 'desc')) {
                return null;
            }
            return [col, dir];
        }).filter(function(item) { return item; });
    }

    function readStateFromUrl() {
        var params = new URLSearchParams(window.location.search || '');
        if ([...params.keys()].length === 0) {
            return null;
        }
        var page = parseInt(params.get('page') || '0', 10);
        var len = parseInt(params.get('len') || '', 10);
        var order = parseOrderParam(params.get('order') || '');
        return {
            search: params.get('q') || '',
            type: params.get('type') || 'all',
            importPath: params.get('import') || 'all',
            page: Number.isNaN(page) ? 0 : page,
            order: order,
            length: Number.isNaN(len) ? null : len
        };
    }

    function writeStateToUrl(state) {
        if (!state) {
            return;
        }
        var params = new URLSearchParams();
        if (state.search) {
            params.set('q', state.search);
        }
        if (state.type && state.type !== 'all') {
            params.set('type', state.type);
        }
        if (state.importPath && state.importPath !== 'all') {
            params.set('import', state.importPath);
        }
        if (typeof state.page === 'number' && state.page > 0) {
            params.set('page', String(state.page));
        }
        if (state.length) {
            params.set('len', String(state.length));
        }
        if (state.order && state.order.length) {
            var orderVal = state.order.map(function(item) {
                return item[0] + ',' + item[1];
            }).join(';');
            params.set('order', orderVal);
        }
        var newUrl = window.location.pathname;
        var query = params.toString();
        if (query) {
            newUrl += '?' + query;
        }
        window.history.replaceState({}, '', newUrl);
    }

    function updateUrlFromTable(table) {
        var state = {
            search: $('#wanted-title-search').val() || '',
            type: $('#wanted-type-filter').val() || 'all',
            importPath: $('#wanted-import-filter').val() || 'all',
            page: table ? table.page() : 0,
            order: table ? table.order() : [],
            length: table ? table.page.len() : null
        };
        writeStateToUrl(state);
    }
    window.updateWantedUrlState = updateUrlFromTable;

    function captureWantedState() {
        var state = {
            search: $('#wanted-title-search').val() || '',
            type: $('#wanted-type-filter').val() || 'all',
            importPath: $('#wanted-import-filter').val() || 'all',
            page: 0,
            order: [],
            length: null
        };
        if ($.fn.DataTable.isDataTable('#wanted_table')) {
            var table = $('#wanted_table').DataTable();
            state.page = table.page();
            state.order = table.order();
            state.length = table.page.len();
        }
        return state;
    }

    function restoreWantedState(state) {
        if (!state) {
            return;
        }
        var $search = $('#wanted-title-search');
        var $type = $('#wanted-type-filter');
        var $import = $('#wanted-import-filter');
        if ($search.length) {
            $search.val(state.search);
            $search.trigger('input');
        }
        if ($type.length) {
            $type.val(state.type);
            $type.trigger('change');
        }
        if ($import.length) {
            if ($import.find('option[value="' + state.importPath + '"]').length) {
                $import.val(state.importPath);
            } else {
                $import.val('all');
            }
            $import.trigger('change');
        }
        if ($.fn.DataTable.isDataTable('#wanted_table')) {
            var table = $('#wanted_table').DataTable();
            if (state.length) {
                table.page.len(state.length);
            }
            if (state.order && state.order.length) {
                table.order(state.order);
            }
            if (typeof state.page === 'number') {
                table.page(state.page);
            }
            table.draw(false);
            updateUrlFromTable(table);
        }
    }

    function refreshWantedContent() {
        var container = document.getElementById('wanted-content');
        var skeleton = document.getElementById('wanted-skeleton');
        if (!container) {
            return Promise.resolve();
        }
        var urlState = readStateFromUrl();
        var savedState = urlState || captureWantedState();
        return fetch('/api/wanted/content')
            .then(function(resp) { return resp.text(); })
            .then(function(html) {
                if ($.fn.DataTable.isDataTable('#wanted_table')) {
                    $('#wanted_table').DataTable().destroy();
                }
                container.innerHTML = html;
                container.classList.remove('d-none');
                if (skeleton) {
                    skeleton.style.display = 'none';
                }
                var stats = document.getElementById('wanted-stats-data');
                if (stats) {
                    $('#wanted-count-total').text(stats.dataset.total || '0');
                    $('#wanted-count-movies').text(stats.dataset.movies || '0');
                    $('#wanted-count-series').text(stats.dataset.series || '0');
                    $('#wanted-count-missing').text(stats.dataset.missing || '0');
                    $('#wanted-count-in-radarr').text(stats.dataset.inRadarr || '0');
                    $('#wanted-count-in-sonarr').text(stats.dataset.inSonarr || '0');
                }
                $('#wanted-title-search').prop('disabled', false);
                $('#wanted-type-filter').prop('disabled', false);
                $('#wanted-import-filter').prop('disabled', false);
                $('#select-visible-btn').prop('disabled', false);
                $('#select-downloaded-btn').prop('disabled', false);
                $('#select-tmdb-btn').prop('disabled', false);
                $('#select-tvdb-btn').prop('disabled', false);
                $('#select-radarr-btn').prop('disabled', false);
                $('#select-sonarr-btn').prop('disabled', false);
                $('#clear-selection-btn').prop('disabled', false);
                initWantedUI();
                restoreWantedState(savedState);
                applyPendingDownloadState();
                if ($.fn.DataTable.isDataTable('#wanted_table')) {
                    var table = $('#wanted_table').DataTable();
                    table.off('order.wanted-url page.wanted-url length.wanted-url');
                    table.on('order.wanted-url page.wanted-url length.wanted-url', function() {
                        updateUrlFromTable(table);
                    });
                }
            })
            .catch(function() {
                if (skeleton) {
                    skeleton.style.display = 'none';
                }
            });
    }

    window.reloadWantedContent = refreshWantedContent;
    refreshWantedContent();
});





