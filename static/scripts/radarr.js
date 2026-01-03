$(document).ready(function() {
    var configEl = document.getElementById('radarr-config');
    var radarrBase = configEl ? (configEl.dataset.radarrUrl || '') : '';

    function formatRootPath(path) {
        if (!path) {
            return '';
        }
        var value = String(path);
        var lastSlash = value.lastIndexOf('/');
        var lastBack = value.lastIndexOf('\\');
        var sepIndex = Math.max(lastSlash, lastBack);
        if (sepIndex <= 0) {
            return value;
        }
        return value.slice(0, sepIndex + 1);
    }

    var radarrTable = $('#radarr_table').DataTable({
        paging: true,
        ordering: true,
        order: [[1, "desc"]],
        pageLength: 25,
        autoWidth: false,
        deferRender: true,
        ajax: {
            url: '/api/radarr/list',
            dataSrc: function(json) {
                if (json && json.counts) {
                    $('#radarr-count-total').text(json.counts.total || 0);
                    $('#radarr-count-monitored').text(json.counts.monitored || 0);
                    $('#radarr-count-downloaded').text(json.counts.downloaded || 0);
                }
                return json.items || [];
            }
        },
        columns: [
            {
                data: 'title',
                render: function(data, type, row) {
                    if (type === 'display') {
                        var tmdb = row.tmdb_id ? row.tmdb_id : '';
                        return '<a href="' + radarrBase + '/movie/' + tmdb + '" target="_blank">' + (data || '') + '</a>';
                    }
                    return data || '';
                }
            },
            {
                data: 'path',
                render: function(data, type) {
                    if (type === 'display') {
                        return formatRootPath(data);
                    }
                    return data || '';
                }
            },
            { data: 'year' },
            { data: 'tmdb_id' },
            { data: 'imdb_id' },
            {
                data: 'monitored',
                render: function(val, type) {
                    if (type === 'display') {
                        return val ? 'Yes' : 'No';
                    }
                    return val ? 1 : 0;
                }
            },
            {
                data: 'has_file',
                render: function(val, type) {
                    if (type === 'display') {
                        return val ? 'Yes' : 'No';
                    }
                    return val ? 1 : 0;
                }
            }
        ],
        initComplete: function() {}
    });

    radarrTable.on('xhr', function() {
        var skeleton = document.getElementById('radarr-skeleton');
        if (skeleton) {
            skeleton.style.display = 'none';
        }
        document.getElementById('radarr_table').classList.remove('d-none');
    });

    var syncCache = null;

    function updateSyncButtonState() {
        var count = $('#radarr-sync-rows').find('input[type="checkbox"]:checked').length;
        $('#radarr-sync-import').prop('disabled', count === 0);
    }

    function renderSyncRows(items) {
        var rows = items.map(function(item, idx) {
            var tmdb = item.tmdb_id ? String(item.tmdb_id) : '';
            var match = item.match_type === 'tmdb' ? 'TMDB' : (item.match_type === 'title_year' ? 'Titolo/Anno' : '-');
            var label = item.title || '';
            return '<tr>' +
                '<td><input class="form-check-input radarr-sync-select" type="checkbox" data-index="' + idx + '" checked></td>' +
                '<td>' + label + '</td>' +
                '<td>' + (item.year || '') + '</td>' +
                '<td>' + tmdb + '</td>' +
                '<td>' + match + '</td>' +
            '</tr>';
        }).join('');
        $('#radarr-sync-rows').html(rows);
        updateSyncButtonState();
    }

    $('#radarrSyncModal').on('show.bs.modal', function() {
        $('#radarr-sync-error').addClass('d-none');
        $('#radarr-sync-summary').addClass('d-none');
        $('#radarr-sync-list').addClass('d-none');
        $('#radarr-sync-rows').empty();
        $('#radarr-sync-import').prop('disabled', true).text('Importa selezionati');
        if (syncCache) {
            $('#radarr-sync-total').text(syncCache.counts.total);
            $('#radarr-sync-present').text(syncCache.counts.present);
            $('#radarr-sync-missing').text(syncCache.counts.missing);
            $('#radarr-sync-summary').removeClass('d-none');
            if (syncCache.missing.length) {
                renderSyncRows(syncCache.missing);
                $('#radarr-sync-list').removeClass('d-none');
            }
            return;
        }
        $('#radarr-sync-loading').removeClass('d-none');
        fetch('/api/radarr/sync/preview')
            .then(function(resp) { return resp.json(); })
            .then(function(data) {
                $('#radarr-sync-loading').addClass('d-none');
                if (!data || !data.ok) {
                    throw new Error('sync failed');
                }
                syncCache = data;
                $('#radarr-sync-total').text(data.counts.total);
                $('#radarr-sync-present').text(data.counts.present);
                $('#radarr-sync-missing').text(data.counts.missing);
                $('#radarr-sync-summary').removeClass('d-none');
                if (data.missing.length) {
                    renderSyncRows(data.missing);
                    $('#radarr-sync-list').removeClass('d-none');
                }
            })
            .catch(function() {
                $('#radarr-sync-loading').addClass('d-none');
                $('#radarr-sync-error').removeClass('d-none');
            });
    });

    $('#radarrSyncModal').on('hidden.bs.modal', function() {
        $('#radarr-sync-loading').addClass('d-none');
        $('#radarr-sync-error').addClass('d-none');
    });

    $(document).on('change', '.radarr-sync-select', function() {
        updateSyncButtonState();
    });

    $('#radarr-sync-select-all').on('click', function() {
        $('#radarr-sync-rows').find('input[type="checkbox"]').prop('checked', true);
        updateSyncButtonState();
    });

    $('#radarr-sync-clear').on('click', function() {
        $('#radarr-sync-rows').find('input[type="checkbox"]').prop('checked', false);
        updateSyncButtonState();
    });

    $('#radarr-sync-import').on('click', function() {
        if (!syncCache || !syncCache.missing.length) {
            return;
        }
        var button = $(this);
        var selected = [];
        $('#radarr-sync-rows').find('input[type="checkbox"]:checked').each(function() {
            var idx = parseInt($(this).data('index'), 10);
            if (!Number.isNaN(idx) && syncCache.missing[idx]) {
                selected.push(syncCache.missing[idx]);
            }
        });
        if (!selected.length) {
            return;
        }
        button.prop('disabled', true).text('Importo...');
        fetch('/api/radarr/sync/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items: selected })
        })
            .then(function(resp) { return resp.json(); })
            .then(function(data) {
                if (!data || !data.ok) {
                    throw new Error('import failed');
                }
                syncCache = null;
                button.text('Importati');
                setTimeout(function() {
                    var modalEl = document.getElementById('radarrSyncModal');
                    if (modalEl) {
                        var modal = bootstrap.Modal.getInstance(modalEl);
                        if (modal) {
                            modal.hide();
                        }
                    }
                }, 1000);
            })
            .catch(function() {
                $('#radarr-sync-error').removeClass('d-none').text('Errore durante l\'import.');
                button.prop('disabled', false).text('Importa selezionati');
            });
    });
});
