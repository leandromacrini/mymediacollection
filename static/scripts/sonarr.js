$(document).ready(function() {
    var configEl = document.getElementById('sonarr-config');
    var sonarrBase = configEl ? (configEl.dataset.sonarrUrl || '') : '';
    var sonarrTable = $('#sonarr_table').DataTable({
        paging: true,
        ordering: true,
        order: [[1, "desc"]],
        pageLength: 25,
        autoWidth: false,
        deferRender: true,
        ajax: {
            url: '/api/sonarr/list',
            dataSrc: function(json) {
                if (json && json.counts) {
                    $('#sonarr-count-total').text(json.counts.total || 0);
                    $('#sonarr-count-monitored').text(json.counts.monitored || 0);
                    $('#sonarr-count-unmonitored').text(json.counts.unmonitored || 0);
                }
                return json.items || [];
            }
        },
        columns: [
            {
                data: 'title',
                render: function(data, type, row) {
                    if (type === 'display') {
                        var slug = row.slug ? row.slug : '';
                        return '<a href="' + sonarrBase + '/series/' + slug + '" target="_blank">' + (data || '') + '</a>';
                    }
                    return data || '';
                }
            },
            { data: 'year' },
            { data: 'tvdb_id' },
            {
                data: 'monitored',
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

    sonarrTable.on('xhr', function() {
        var skeleton = document.getElementById('sonarr-skeleton');
        if (skeleton) {
            skeleton.style.display = 'none';
        }
        document.getElementById('sonarr_table').classList.remove('d-none');
    });

    var sonarrSyncCache = null;

    function updateSonarrSyncButton() {
        var count = $('#sonarr-sync-rows').find('input[type="checkbox"]:checked').length;
        $('#sonarr-sync-import').prop('disabled', count === 0);
    }

    function renderSonarrSyncRows(items) {
        var rows = items.map(function(item, idx) {
            var tvdb = item.tvdb_id ? String(item.tvdb_id) : '';
            var match = item.match_type === 'tvdb' ? 'TVDB' : (item.match_type === 'title_year' ? 'Titolo/Anno' : '-');
            var label = item.title || '';
            return '<tr>' +
                '<td><input class="form-check-input sonarr-sync-select" type="checkbox" data-index="' + idx + '" checked></td>' +
                '<td>' + label + '</td>' +
                '<td>' + (item.year || '') + '</td>' +
                '<td>' + tvdb + '</td>' +
                '<td>' + match + '</td>' +
            '</tr>';
        }).join('');
        $('#sonarr-sync-rows').html(rows);
        updateSonarrSyncButton();
    }

    $('#sonarrSyncModal').on('show.bs.modal', function() {
        $('#sonarr-sync-error').addClass('d-none');
        $('#sonarr-sync-summary').addClass('d-none');
        $('#sonarr-sync-list').addClass('d-none');
        $('#sonarr-sync-rows').empty();
        $('#sonarr-sync-import').prop('disabled', true).text('Importa selezionati');
        if (sonarrSyncCache) {
            $('#sonarr-sync-total').text(sonarrSyncCache.counts.total);
            $('#sonarr-sync-present').text(sonarrSyncCache.counts.present);
            $('#sonarr-sync-missing').text(sonarrSyncCache.counts.missing);
            $('#sonarr-sync-summary').removeClass('d-none');
            if (sonarrSyncCache.missing.length) {
                renderSonarrSyncRows(sonarrSyncCache.missing);
                $('#sonarr-sync-list').removeClass('d-none');
            }
            return;
        }
        $('#sonarr-sync-loading').removeClass('d-none');
        fetch('/api/sonarr/sync/preview')
            .then(function(resp) { return resp.json(); })
            .then(function(data) {
                $('#sonarr-sync-loading').addClass('d-none');
                if (!data || !data.ok) {
                    throw new Error('sync failed');
                }
                sonarrSyncCache = data;
                $('#sonarr-sync-total').text(data.counts.total);
                $('#sonarr-sync-present').text(data.counts.present);
                $('#sonarr-sync-missing').text(data.counts.missing);
                $('#sonarr-sync-summary').removeClass('d-none');
                if (data.missing.length) {
                    renderSonarrSyncRows(data.missing);
                    $('#sonarr-sync-list').removeClass('d-none');
                }
            })
            .catch(function() {
                $('#sonarr-sync-loading').addClass('d-none');
                $('#sonarr-sync-error').removeClass('d-none');
            });
    });

    $('#sonarrSyncModal').on('hidden.bs.modal', function() {
        $('#sonarr-sync-loading').addClass('d-none');
        $('#sonarr-sync-error').addClass('d-none');
    });

    $(document).on('change', '.sonarr-sync-select', function() {
        updateSonarrSyncButton();
    });

    $('#sonarr-sync-select-all').on('click', function() {
        $('#sonarr-sync-rows').find('input[type="checkbox"]').prop('checked', true);
        updateSonarrSyncButton();
    });

    $('#sonarr-sync-clear').on('click', function() {
        $('#sonarr-sync-rows').find('input[type="checkbox"]').prop('checked', false);
        updateSonarrSyncButton();
    });

    $('#sonarr-sync-import').on('click', function() {
        if (!sonarrSyncCache || !sonarrSyncCache.missing.length) {
            return;
        }
        var button = $(this);
        var selected = [];
        $('#sonarr-sync-rows').find('input[type="checkbox"]:checked').each(function() {
            var idx = parseInt($(this).data('index'), 10);
            if (!Number.isNaN(idx) && sonarrSyncCache.missing[idx]) {
                selected.push(sonarrSyncCache.missing[idx]);
            }
        });
        if (!selected.length) {
            return;
        }
        button.prop('disabled', true).text('Importo...');
        fetch('/api/sonarr/sync/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items: selected })
        })
            .then(function(resp) { return resp.json(); })
            .then(function(data) {
                if (!data || !data.ok) {
                    throw new Error('import failed');
                }
                sonarrSyncCache = null;
                button.text('Importati');
                setTimeout(function() {
                    var modalEl = document.getElementById('sonarrSyncModal');
                    if (modalEl) {
                        var modal = bootstrap.Modal.getInstance(modalEl);
                        if (modal) {
                            modal.hide();
                        }
                    }
                }, 1000);
            })
            .catch(function() {
                $('#sonarr-sync-error').removeClass('d-none').text('Errore durante l\'import.');
                button.prop('disabled', false).text('Importa selezionati');
            });
    });
});
