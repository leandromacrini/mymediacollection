$(document).ready(function() {
    var configEl = document.getElementById('plex-config');
    var plexBase = configEl ? (configEl.dataset.plexUrl || '') : '';
    var plexMachine = configEl ? (configEl.dataset.plexMachine || '') : '';

    function buildPlexLink(ratingKey, machineId) {
        var serverId = machineId || plexMachine;
        if (!plexBase || !ratingKey) {
            return '';
        }
        if (serverId) {
            return plexBase + '/web/index.html#!/server/' + serverId + '/details?key=' + encodeURIComponent('/library/metadata/' + ratingKey);
        }
        return plexBase + '/web/index.html#!/details?key=' + encodeURIComponent('/library/metadata/' + ratingKey);
    }

    var plexTable = $('#plex_table').DataTable({
        paging: true,
        ordering: true,
        order: [[2, "desc"]],
        pageLength: 25,
        autoWidth: false,
        deferRender: true,
        ajax: {
            url: '/api/plex/media',
            dataSrc: function(json) {
                if (json && json.counts) {
                    $('#plex-count-total').text(json.counts.total || 0);
                    $('#plex-count-movies').text(json.counts.movies || 0);
                    $('#plex-count-series').text(json.counts.series || 0);
                }
                if (json && json.machine_identifier) {
                    plexMachine = json.machine_identifier;
                }
                return json.items || [];
            }
        },
        columns: [
            {
                data: 'rating_key',
                orderable: false,
                render: function(data, type, row) {
                    if (type === 'display') {
                        return '<input class="form-check-input plex-select" type="checkbox" value="' + (data || '') + '" aria-label="Seleziona">';
                    }
                    return data || '';
                }
            },
            {
                data: 'title',
                render: function(data, type, row) {
                    if (type === 'display') {
                        var link = buildPlexLink(row.rating_key, row.machine_identifier);
                        if (link) {
                            return '<a href="' + link + '" target="_blank" rel="noopener">' + (data || '') + '</a>';
                        }
                    }
                    return data || '';
                }
            },
            { data: 'year' },
            { data: 'media_type' },
            { data: 'library' },
            {
                data: 'in_radarr',
                orderable: true,
                render: function(data, type) {
                    if (type === 'sort' || type === 'type') {
                        return data ? 1 : 0;
                    }
                    return data
                        ? '<i class="bi bi-check-circle-fill text-success"></i>'
                        : '<i class="bi bi-dash-circle text-muted"></i>';
                }
            },
            {
                data: 'in_sonarr',
                orderable: true,
                render: function(data, type) {
                    if (type === 'sort' || type === 'type') {
                        return data ? 1 : 0;
                    }
                    return data
                        ? '<i class="bi bi-check-circle-fill text-success"></i>'
                        : '<i class="bi bi-dash-circle text-muted"></i>';
                }
            },
            {
                data: 'in_wanted',
                orderable: true,
                render: function(data, type) {
                    if (type === 'sort' || type === 'type') {
                        return data ? 1 : 0;
                    }
                    return data
                        ? '<i class="bi bi-check-circle-fill text-success"></i>'
                        : '<i class="bi bi-dash-circle text-muted"></i>';
                }
            },
            {
                data: 'rating_key',
                orderable: false,
                render: function(data, type, row) {
                    var disabled = row.in_wanted ? ' disabled' : '';
                    var wantedLabel = row.in_wanted ? 'In wanted' : 'Aggiungi';
                    return (
                        '<div class="d-flex flex-column gap-1">' +
                        '<button class="btn btn-sm btn-outline-primary plex-detail-btn" type="button" data-rating-key="' + data + '">Dettagli</button>' +
                        '<button class="btn btn-sm btn-outline-success plex-wanted-btn" type="button" data-title="' + (row.title || '') + '" data-year="' + (row.year || '') + '" data-media-type="' + (row.media_type || '') + '" data-library="' + (row.library || '') + '" data-rating-key="' + data + '" data-tmdb-id="' + (row.tmdb_id || '') + '" data-tvdb-id="' + (row.tvdb_id || '') + '"' + disabled + '>' +
                        '<i class="bi bi-bookmark-plus me-1"></i>' + wantedLabel + '</button>' +
                        '</div>'
                    );
                }
            }
        ],
        initComplete: function() {}
    });

    plexTable.on('xhr', function() {
        var skeleton = document.getElementById('plex-skeleton');
        if (skeleton) {
            skeleton.style.display = 'none';
        }
        document.getElementById('plex_table').classList.remove('d-none');
    });

    function populateSelect($select, values) {
        var options = values.map(function(value) {
            return '<option value="' + value + '">' + value + '</option>';
        }).join('');
        $select.append(options);
    }

    function getUniqueValuesFromItems(items, key) {
        var map = {};
        (items || []).forEach(function(item) {
            var cleaned = String(item[key] || '').trim();
            if (!cleaned) {
                return;
            }
            map[cleaned] = true;
        });
        return Object.keys(map).sort();
    }

    plexTable.on('xhr', function(event, settings, json) {
        var items = (json && json.items) ? json.items : [];
        $('#plex-type-filter').find('option:not(:first)').remove();
        $('#plex-library-filter').find('option:not(:first)').remove();
        populateSelect($('#plex-type-filter'), getUniqueValuesFromItems(items, 'media_type'));
        populateSelect($('#plex-library-filter'), getUniqueValuesFromItems(items, 'library'));
    });

    $('#plex-title-search').on('input', function() {
        plexTable.column(1).search(this.value || '').draw();
    });
    $('#plex-type-filter').on('change', function() {
        plexTable.column(3).search(this.value || '', true, false).draw();
    });
    $('#plex-library-filter').on('change', function() {
        plexTable.column(4).search(this.value || '', true, false).draw();
    });

    function fmtDuration(ms) {
        if (!ms) {
            return '';
        }
        var minutes = Math.round(ms / 60000);
        return minutes + ' min';
    }

    function fmtDate(ts) {
        if (!ts) {
            return '';
        }
        var d = new Date(ts * 1000);
        return d.toLocaleString();
    }

    function fillDetails(details) {
        $('#plex-detail-title').text(details.title || 'Dettagli Plex');
        $('#plex-detail-summary').text(details.summary || '');
        if (details.poster_url) {
            $('#plex-detail-poster').attr('src', details.poster_url).removeClass('d-none');
        } else {
            $('#plex-detail-poster').addClass('d-none').attr('src', '');
        }
        if (details.backdrop_url) {
            $('#plex-detail-backdrop-bg').css('background-image', 'url(' + details.backdrop_url + ')').removeClass('d-none');
        } else {
            $('#plex-detail-backdrop-bg').addClass('d-none').css('background-image', '');
        }
        $('#plex-detail-year').text(details.year || '');
        $('#plex-detail-type').text(details.type || '');
        $('#plex-detail-studio').text(details.studio || '');
        $('#plex-detail-rating').text(details.rating || '');
        $('#plex-detail-audience').text(details.audience_rating || '');
        $('#plex-detail-content-rating').text(details.content_rating || '');
        $('#plex-detail-duration').text(fmtDuration(details.duration));
        $('#plex-detail-view-count').text(details.view_count || '');
        $('#plex-detail-last-viewed').text(fmtDate(details.last_viewed_at));
        $('#plex-detail-original-title').text(details.original_title || '');
        $('#plex-detail-genres').text((details.genres || []).join(', '));
    }

    $(document).on('click', '.plex-detail-btn', function() {
        var ratingKey = $(this).data('rating-key');
        if (!ratingKey) {
            return;
        }
        $('#plex-detail-body').addClass('d-none');
        $('#plex-detail-error').addClass('d-none');
        $('#plex-detail-loading').removeClass('d-none');
        var modalEl = document.getElementById('plexDetailModal');
        var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        modal.show();
        fetch('/api/plex/media/' + ratingKey)
            .then(function(resp) { return resp.json(); })
            .then(function(data) {
                $('#plex-detail-loading').addClass('d-none');
                if (!data || !data.ok) {
                    throw new Error('not found');
                }
                fillDetails(data.details || {});
                $('#plex-detail-body').removeClass('d-none');
            })
            .catch(function() {
                $('#plex-detail-loading').addClass('d-none');
                $('#plex-detail-error').removeClass('d-none');
            });
    });

    function getSelectedRows() {
        var rows = [];
        $('#plex_table tbody .plex-select:checked').each(function() {
            var row = $(this).closest('tr');
            var data = plexTable.row(row).data();
            if (data) {
                rows.push(data);
            }
        });
        return rows;
    }

    function updateBulkState() {
        var count = $('#plex_table tbody .plex-select:checked').length;
        $('#plex-wanted-bulk').prop('disabled', count === 0);
    }

    $(document).on('change', '#plex-select-all', function() {
        var checked = $(this).is(':checked');
        $('#plex_table tbody .plex-select').prop('checked', checked);
        updateBulkState();
    });

    $(document).on('change', '.plex-select', function() {
        updateBulkState();
        var total = $('#plex_table tbody .plex-select').length;
        var checked = $('#plex_table tbody .plex-select:checked').length;
        $('#plex-select-all').prop('checked', total > 0 && total === checked);
    });

    $(document).on('click', '.plex-wanted-btn', function() {
        var btn = $(this);
        if (btn.prop('disabled')) {
            return;
        }
        var payload = {
            title: btn.data('title'),
            year: btn.data('year'),
            media_type: btn.data('media-type'),
            library: btn.data('library'),
            rating_key: btn.data('rating-key'),
            tmdb_id: btn.data('tmdb-id'),
            tvdb_id: btn.data('tvdb-id')
        };
        btn.prop('disabled', true).text('Invio...');
        fetch('/api/plex/wanted/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function(resp) { return resp.json(); })
            .then(function(data) {
                if (!data || !data.ok) {
                    throw new Error('error');
                }
                var row = btn.closest('tr');
                var rowData = plexTable.row(row).data();
                if (rowData) {
                    rowData.in_wanted = true;
                    plexTable.row(row).data(rowData).invalidate();
                }
            })
            .catch(function() {
                btn.prop('disabled', false).text('Aggiungi');
            });
    });

    $('#plex-wanted-bulk').on('click', function() {
        var rows = getSelectedRows();
        if (!rows.length) {
            return;
        }
        var items = rows.map(function(row) {
            return {
                title: row.title,
                year: row.year,
                media_type: row.media_type,
                library: row.library,
                rating_key: row.rating_key,
                tmdb_id: row.tmdb_id,
                tvdb_id: row.tvdb_id
            };
        });
        var btn = $(this);
        btn.prop('disabled', true).text('Invio...');
        fetch('/api/plex/wanted/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items: items })
        })
            .then(function(resp) { return resp.json(); })
            .then(function(data) {
                if (!data || !data.ok) {
                    throw new Error('error');
                }
                $('#plex_table tbody .plex-select:checked').each(function() {
                    var row = $(this).closest('tr');
                    var rowData = plexTable.row(row).data();
                    if (rowData) {
                        rowData.in_wanted = true;
                        plexTable.row(row).data(rowData).invalidate();
                    }
                    $(this).prop('checked', false);
                });
                $('#plex-select-all').prop('checked', false);
                updateBulkState();
            })
            .catch(function() {
                updateBulkState();
            })
            .finally(function() {
                btn.html('<i class="bi bi-bookmark-plus me-1"></i>Importa selezionati');
            });
    });
});
