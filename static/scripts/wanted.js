function initWantedUI() {
    var wantedSearchTerm = '';
    var wantedTypeFilter = 'all';
    var selectedIds = new Set();
    var rowInfo = {};
    var rowById = {};
    var checkboxById = {};
    var configEl = document.getElementById('wanted-config');
    var radarrBase = configEl ? (configEl.dataset.radarrUrl || '') : '';
    

    function isRadarrEligibleInfo(info) {
        if (!info) {
            return false;
        }
        return info.mediaType === 'movie' && info.hasTmdb && !info.inRadarr;
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
        columnDefs: [
            { orderable: false, targets: [0, 5, 6] },
            { searchable: false, targets: [0, 4, 5, 6] }
        ],
        dom: 'rt<"d-flex justify-content-between align-items-center mt-3"lip>'
    });

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
            $row.find('td').eq(4).append(
                '<a class="badge badge-radarr text-decoration-none" href="' + radarrBase + '/movie/' + tmdbId + '" target="_blank" rel="noopener" data-bs-toggle="tooltip" data-bs-placement="top" title="Radarr ' + tmdbId + '">Radarr</a>'
            );
        }
        $row.find('.radarr-add-btn').prop('disabled', true);
        var info = getRowInfo(mediaId);
        if (info) {
            info.inRadarr = true;
        }
        table.draw(false);
        updateBulkState();
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
        if (tvdbId && !idCell.find('.badge-sonarr').length) {
            idCell.append('<span class="badge badge-sonarr">Sonarr</span>');
        }
        $row.find('.sonarr-add-btn').prop('disabled', true);
        var info = getRowInfo(mediaId);
        if (info) {
            info.inSonarr = true;
        }
        table.draw(false);
        updateBulkState();
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
    }

    function syncSelectionToTable() {
        var nodes = table.rows({ page: 'current' }).nodes();
        $(nodes).find('.wanted-select').each(function() {
            var id = $(this).val();
            $(this).prop('checked', selectedIds.has(id));
        });
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
            return info.mediaType === 'series' && info.hasTvdb && !info.inSonarr;
        });
    }

    function updateBulkState() {
        var count = selectedIds.size;
        var eligible = getRadarrEligibleIds();
        var eligibleSonarr = getSonarrEligibleIds();
        var excluded = count - eligible.length;
        $('#bulk-delete-btn').prop('disabled', count === 0);
        $('#bulk-delete-confirm').prop('disabled', count === 0);
        $('#bulk-delete-count').text(count);
        $('#bulk-radarr-btn').prop('disabled', eligible.length === 0);
        $('#bulk-radarr-count').text(eligible.length);
        $('#bulk-sonarr-btn').prop('disabled', eligibleSonarr.length === 0);
        $('#bulk-sonarr-count').text(eligibleSonarr.length);
        $('#bulk-merge-btn').prop('disabled', count === 0);
        if (count === 0) {
            $('#bulk-radarr-note').text('Solo movie con TMDB non presenti in Radarr.');
        } else {
            $('#bulk-radarr-note').text('Inviabili: ' + eligible.length + '. Esclusi: ' + excluded + '.');
        }
        if (count === 0) {
            $('#bulk-sonarr-note').text('Solo serie con TVDB non presenti in Sonarr.');
        } else {
            $('#bulk-sonarr-note').text('Inviabili: ' + eligibleSonarr.length + '. Esclusi: ' + (count - eligibleSonarr.length) + '.');
        }
    }

    function applyFilters() {
        var typeFilter = wantedTypeFilter === 'all' ? '' : wantedTypeFilter;
        table.column(1).search(wantedSearchTerm || '');
        table.column(3).search(typeFilter, true, false);
        table.draw();
        updateBulkState();
    }

    function applySearch() {
        var value = $('#wanted-title-search').val() || '';
        wantedSearchTerm = value.toLowerCase();
        applyFilters();
    }

    function getSelectedIds() {
        return Array.from(selectedIds);
    }

    $('#wanted-type-filter').on('change', function() {
        wantedTypeFilter = $(this).val() || 'all';
        applyFilters();
    });


    $('#wanted-title-search').on('input', function() {
        applySearch();
    });

    $(document).on('change', '.wanted-select', function() {
        var id = $(this).val();
        if ($(this).is(':checked')) {
            selectedIds.add(id);
        } else {
            selectedIds.delete(id);
        }
        updateBulkState();
    });

    $('#select-visible-btn').on('click', function() {
        var nodes = table.rows({ search: 'applied' }).nodes();
        $(nodes).find('.wanted-select').each(function() {
            selectedIds.add($(this).val());
        });
        syncSelectionToTable();
        updateBulkState();
    });

    $('#clear-selection-btn').on('click', function() {
        selectedIds.clear();
        syncSelectionToTable();
        updateBulkState();
    });

    $('#bulk-delete-confirm').on('click', function() {
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

    $('#bulkDeleteModal').on('show.bs.modal', updateBulkState);
    $('#bulkRadarrModal').on('show.bs.modal', updateBulkState);
    $('#bulkSonarrModal').on('show.bs.modal', updateBulkState);

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

    $(document).on('show.bs.modal', '.modal', function() {
        var listEl = $(this).find('.lookup-results');
        if (!listEl.length) {
            return;
        }
        loadLookupResults(listEl);
    });

    $(document).on('click', '.lookup-run', function() {
        var modal = $(this).closest('.modal');
        var listEl = modal.find('.lookup-results');
        loadLookupResults(listEl);
    });

    $(document).on('keyup', '.lookup-query', function(e) {
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
                idCell.append(
                    '<a class="badge badge-tmdb text-decoration-none" href="' + link + '" target="_blank" rel="noopener" data-bs-toggle="tooltip" data-bs-placement="top" title="' + externalId + '">TMDB</a>'
                );
            }
            var $actions = $row.find('.wanted-actions');
            if (!$actions.find('.radarr-add-btn').length) {
                $actions.find('.btn-outline-secondary:disabled').first().replaceWith(
                    '<button class="btn btn-sm btn-radarr d-inline-flex align-items-center gap-1 radarr-add-btn" data-bs-toggle="modal" data-bs-target="#radarrAddModal" data-media-id="' + mediaId + '" data-title="' + title + '">' +
                    '<i class="bi bi-cloud-download"></i>Radarr</button>'
                );
            }
        } else if (source === 'tvdb') {
            if (mediaType === 'series') {
                $row.attr('data-missing-external', '0');
                $row.data('missing-external', '0');
            }
            if (!link) {
                link = 'https://thetvdb.com/series/' + externalId;
            }
            if (!idCell.find('.badge-imdb').length) {
                idCell.append(
                    '<a class="badge badge-imdb text-decoration-none" href="' + link + '" target="_blank" rel="noopener" data-bs-toggle="tooltip" data-bs-placement="top" title="' + externalId + '">TVDB</a>'
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
                idCell.append(
                    '<a class="badge badge-anilist text-decoration-none" href="' + link + '" target="_blank" rel="noopener" data-bs-toggle="tooltip" data-bs-placement="top" title="' + externalId + '">AniList</a>'
                );
            }
        }
        var info = getRowInfo(mediaId);
        if (info) {
            info.hasTmdb = source === 'tmdb' ? true : info.hasTmdb;
            info.tmdbId = source === 'tmdb' ? externalId : info.tmdbId;
            info.missingExternal = false;
        }
        table.draw(false);
        updateBulkState();
    }

    $(document).on('click', '.select-external-btn', function() {
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
        }).done(function() {
            applyExternalUpdate(mediaId, source, externalId, link);
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

    $(document).on('click', '.delete-single-btn', function(event) {
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

    function loadRadarrOptions($rootSelect, $profileSelect, $errorEl) {
        $errorEl.addClass('d-none');
        if (radarrOptionsCache) {
            populateRadarrSelect($rootSelect, radarrOptionsCache.root_folders, 'path', 'path');
            populateRadarrSelect($profileSelect, radarrOptionsCache.profiles, 'name', 'id');
            applyRadarrDefaults($rootSelect, $profileSelect);
            return;
        }
        $rootSelect.html('<option value="">Caricamento...</option>');
        $profileSelect.html('<option value="">Caricamento...</option>');
        $.getJSON('/api/radarr/options', function(resp) {
            radarrOptionsCache = resp || {};
            populateRadarrSelect($rootSelect, radarrOptionsCache.root_folders, 'path', 'path');
            populateRadarrSelect($profileSelect, radarrOptionsCache.profiles, 'name', 'id');
            applyRadarrDefaults($rootSelect, $profileSelect);
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

    function loadSonarrOptions($rootSelect, $profileSelect, $errorEl) {
        $errorEl.addClass('d-none');
        if (sonarrOptionsCache) {
            populateSonarrSelect($rootSelect, sonarrOptionsCache.root_folders, 'path', 'path');
            populateSonarrSelect($profileSelect, sonarrOptionsCache.profiles, 'name', 'id');
            applySonarrDefaults($rootSelect, $profileSelect);
            return;
        }
        $rootSelect.html('<option value="">Caricamento...</option>');
        $profileSelect.html('<option value="">Caricamento...</option>');
        $.getJSON('/api/sonarr/options', function(resp) {
            sonarrOptionsCache = resp || {};
            populateSonarrSelect($rootSelect, sonarrOptionsCache.root_folders, 'path', 'path');
            populateSonarrSelect($profileSelect, sonarrOptionsCache.profiles, 'name', 'id');
            applySonarrDefaults($rootSelect, $profileSelect);
        }).fail(function() {
            $errorEl.removeClass('d-none').text('Errore nel caricamento delle opzioni Sonarr.');
            $rootSelect.html('<option value="">Errore</option>');
            $profileSelect.html('<option value="">Errore</option>');
        });
    }

    $(document).on('click', '.radarr-add-btn', function() {
        var mediaId = $(this).data('media-id');
        var title = $(this).data('title');
        $('#radarr-add-media-id').val(mediaId);
        $('#radarr-add-title').text('Seleziona root e profilo per: ' + title);
    });

    $(document).on('click', '.sonarr-add-btn', function() {
        var mediaId = $(this).data('media-id');
        var title = $(this).data('title');
        $('#sonarr-add-media-id').val(mediaId);
        $('#sonarr-add-title').text('Seleziona root e profilo per: ' + title);
    });

    $('#radarrAddModal').on('show.bs.modal', function() {
        loadRadarrOptions(
            $('#radarr-root-select'),
            $('#radarr-profile-select'),
            $('#radarr-add-error')
        );
    });
    $('#radarrAddModal').on('hidden.bs.modal', function() {
        $('#radarr-add-error').addClass('d-none').text('Errore durante il caricamento.');
        $('#radarr-add-status').addClass('d-none').text('Invio a Radarr in corso...');
        $('#radarr-add-confirm').prop('disabled', false).text('Invia');
        applyRadarrDefaults($('#radarr-root-select'), $('#radarr-profile-select'));
    });

    $('#sonarrAddModal').on('show.bs.modal', function() {
        loadSonarrOptions(
            $('#sonarr-root-select'),
            $('#sonarr-profile-select'),
            $('#sonarr-add-error')
        );
    });
    $('#sonarrAddModal').on('hidden.bs.modal', function() {
        $('#sonarr-add-error').addClass('d-none').text('Errore durante il caricamento.');
        $('#sonarr-add-status').addClass('d-none').text('Invio a Sonarr in corso...');
        $('#sonarr-add-confirm').prop('disabled', false).text('Invia');
        applySonarrDefaults($('#sonarr-root-select'), $('#sonarr-profile-select'));
    });

    $('#bulkRadarrModal').on('show.bs.modal', function() {
        loadRadarrOptions(
            $('#bulk-radarr-root'),
            $('#bulk-radarr-profile'),
            $('#bulk-radarr-error')
        );
    });
    $('#bulkRadarrModal').on('hidden.bs.modal', function() {
        $('#bulk-radarr-error').addClass('d-none').text('Errore durante il caricamento.');
        $('#bulk-radarr-status').addClass('d-none').text('Invio a Radarr in corso...');
        $('#bulk-radarr-confirm').prop('disabled', false).text('Invia');
        applyRadarrDefaults($('#bulk-radarr-root'), $('#bulk-radarr-profile'));
    });

    $('#bulkSonarrModal').on('show.bs.modal', function() {
        loadSonarrOptions(
            $('#bulk-sonarr-root'),
            $('#bulk-sonarr-profile'),
            $('#bulk-sonarr-error')
        );
    });
    $('#bulkSonarrModal').on('hidden.bs.modal', function() {
        $('#bulk-sonarr-error').addClass('d-none').text('Errore durante il caricamento.');
        $('#bulk-sonarr-status').addClass('d-none').text('Invio a Sonarr in corso...');
        $('#bulk-sonarr-confirm').prop('disabled', false).text('Invia');
        applySonarrDefaults($('#bulk-sonarr-root'), $('#bulk-sonarr-profile'));
    });

    $('#radarr-add-confirm').on('click', function() {
        var button = $(this);
        var mediaId = $('#radarr-add-media-id').val();
        var root = $('#radarr-root-select').val();
        var profile = $('#radarr-profile-select').val();
        var enableSearch = $('#radarr-search-enable').is(':checked');
        if (!mediaId || !root || !profile) {
            $('#radarr-add-error').removeClass('d-none').text('Seleziona root e profilo.');
            return;
        }
        $('#radarr-add-error').addClass('d-none');
        $('#radarr-add-status').removeClass('d-none').text('Invio a Radarr in corso...');
        button.prop('disabled', true).text('Invio...');
        $.ajax({
            url: '/api/wanted/' + mediaId + '/radarr/add',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ root_folder: root, profile_id: profile, enable_search: enableSearch })
        }).done(function() {
            $('#radarr-add-status').removeClass('d-none').text('Inviato a Radarr. Aggiorno la lista...');
            setTimeout(function() {
                updateRowInRadarr(mediaId);
                var modalEl = document.getElementById('radarrAddModal');
                if (modalEl) {
                    var modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) {
                        modal.hide();
                    }
                }
            }, 900);
        }).fail(function() {
            button.prop('disabled', false).text('Invia');
            $('#radarr-add-status').addClass('d-none');
            $('#radarr-add-error').removeClass('d-none').text('Errore durante il push a Radarr.');
        });
    });

    $('#sonarr-add-confirm').on('click', function() {
        var button = $(this);
        var mediaId = $('#sonarr-add-media-id').val();
        var root = $('#sonarr-root-select').val();
        var profile = $('#sonarr-profile-select').val();
        var enableSearch = $('#sonarr-search-enable').is(':checked');
        if (!mediaId || !root || !profile) {
            $('#sonarr-add-error').removeClass('d-none').text('Seleziona root e profilo.');
            return;
        }
        $('#sonarr-add-error').addClass('d-none');
        $('#sonarr-add-status').removeClass('d-none').text('Invio a Sonarr in corso...');
        button.prop('disabled', true).text('Invio...');
        $.ajax({
            url: '/api/wanted/' + mediaId + '/sonarr/add',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ root_folder: root, profile_id: profile, enable_search: enableSearch })
        }).done(function() {
            $('#sonarr-add-status').removeClass('d-none').text('Inviato a Sonarr. Aggiorno la lista...');
            setTimeout(function() {
                updateRowInSonarr(mediaId);
                var modalEl = document.getElementById('sonarrAddModal');
                if (modalEl) {
                    var modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) {
                        modal.hide();
                    }
                }
            }, 900);
        }).fail(function() {
            button.prop('disabled', false).text('Invia');
            $('#sonarr-add-status').addClass('d-none');
            $('#sonarr-add-error').removeClass('d-none').text('Errore durante il push a Sonarr.');
        });
    });

    $('#bulk-radarr-confirm').on('click', function() {
        var button = $(this);
        var root = $('#bulk-radarr-root').val();
        var profile = $('#bulk-radarr-profile').val();
        var mediaIds = getRadarrEligibleIds();
        var enableSearch = $('#bulk-radarr-search-enable').is(':checked');
        if (!mediaIds.length || !root || !profile) {
            $('#bulk-radarr-error').removeClass('d-none').text('Seleziona elementi, root e profilo.');
            return;
        }
        $('#bulk-radarr-error').addClass('d-none');
        $('#bulk-radarr-status').removeClass('d-none').text('Invio a Radarr in corso...');
        button.prop('disabled', true).text('Invio...');
        $.ajax({
            url: '/api/wanted/radarr/bulk_add',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ media_ids: mediaIds, root_folder: root, profile_id: profile, enable_search: enableSearch })
        }).done(function(resp) {
            $('#bulk-radarr-status').removeClass('d-none').text('Inviati a Radarr. Aggiorno la lista...');
            setTimeout(function() {
                var updatedIds = [];
                if (resp && resp.added_ids) {
                    updatedIds = updatedIds.concat(resp.added_ids);
                }
                if (resp && resp.skipped_ids) {
                    updatedIds = updatedIds.concat(resp.skipped_ids);
                }
                updatedIds.forEach(function(id) {
                    updateRowInRadarr(id);
                });
                var modalEl = document.getElementById('bulkRadarrModal');
                if (modalEl) {
                    var modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) {
                        modal.hide();
                    }
                }
            }, 900);
        }).fail(function() {
            button.prop('disabled', false).text('Invia');
            $('#bulk-radarr-status').addClass('d-none');
            $('#bulk-radarr-error').removeClass('d-none').text('Errore durante il push bulk.');
        });
    });

    $('#bulk-sonarr-confirm').on('click', function() {
        var button = $(this);
        var root = $('#bulk-sonarr-root').val();
        var profile = $('#bulk-sonarr-profile').val();
        var mediaIds = getSonarrEligibleIds();
        var enableSearch = $('#bulk-sonarr-search-enable').is(':checked');
        if (!mediaIds.length || !root || !profile) {
            $('#bulk-sonarr-error').removeClass('d-none').text('Seleziona elementi, root e profilo.');
            return;
        }
        $('#bulk-sonarr-error').addClass('d-none');
        $('#bulk-sonarr-status').removeClass('d-none').text('Invio a Sonarr in corso...');
        button.prop('disabled', true).text('Invio...');
        $.ajax({
            url: '/api/wanted/sonarr/bulk_add',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ media_ids: mediaIds, root_folder: root, profile_id: profile, enable_search: enableSearch })
        }).done(function(resp) {
            $('#bulk-sonarr-status').removeClass('d-none').text('Inviati a Sonarr. Aggiorno la lista...');
            setTimeout(function() {
                var updatedIds = [];
                if (resp && resp.added_ids) {
                    updatedIds = updatedIds.concat(resp.added_ids);
                }
                if (resp && resp.skipped_ids) {
                    updatedIds = updatedIds.concat(resp.skipped_ids);
                }
                updatedIds.forEach(function(id) {
                    updateRowInSonarr(id);
                });
                var modalEl = document.getElementById('bulkSonarrModal');
                if (modalEl) {
                    var modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) {
                        modal.hide();
                    }
                }
            }, 900);
        }).fail(function() {
            button.prop('disabled', false).text('Invia');
            $('#bulk-sonarr-status').addClass('d-none');
            $('#bulk-sonarr-error').removeClass('d-none').text('Errore durante il push bulk.');
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
            return '<div class="mb-1">#' + item.id + title + ' · ' + reason + '</div>';
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

        var summary = 'Gruppi: ' + groups.length + ' · Non matchano: ' + singletons.length + ' · Esclusi: ' + excluded.length;
        $('#merge-preview-summary').text(summary);
        $('#merge-confirm-btn').prop('disabled', groups.length === 0);
    }

    $('#mergeWantedModal').on('show.bs.modal', function() {
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

    $('#merge-confirm-btn').on('click', function() {
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

    buildRowIndex();
    applyFilters();
    syncSelectionToTable();

    table.on('draw', function() {
        syncSelectionToTable();
    });
}

document.addEventListener('DOMContentLoaded', function() {
    var container = document.getElementById('wanted-content');
    var skeleton = document.getElementById('wanted-skeleton');
    fetch('/api/wanted/content')
        .then(function(resp) { return resp.text(); })
        .then(function(html) {
            if (container) {
                container.innerHTML = html;
                container.classList.remove('d-none');
            }
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
            $('#select-visible-btn').prop('disabled', false);
            $('#clear-selection-btn').prop('disabled', false);
            initWantedUI();
        })
        .catch(function() {
            if (skeleton) {
                skeleton.style.display = 'none';
            }
        });
});
