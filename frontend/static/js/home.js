(() => {
  const page = document.querySelector('.home-page');
  if (!page) return;

  const map = L.map('map', { zoomControl: true, scrollWheelZoom: true }).setView([24.4539, 54.3773], 9);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors' }).addTo(map);

  const state = {
    privacy: 'all',
    device_type: 'all',
    status: 'all',
    search: '',
    filters: null,
    markers: null,
    stations: [],
    selectedStationId: null,
  };

  const drawer = document.getElementById('station-drawer');
  const summaryEl = document.getElementById('drawer-summary');
  const currentEl = document.getElementById('drawer-current');
  const detailsEl = document.getElementById('drawer-details');
  const drawerTitle = document.getElementById('drawer-title');
  const drawerSubtitle = document.getElementById('drawer-subtitle');
  const drawerMetadata = document.getElementById('drawer-open-metadata');
  const drawerOpenStation = document.getElementById('drawer-open-station');

  function populateSelect(select, items, selectedValue) {
    if (!select) return;
    select.innerHTML = items
      .map((item) => `<option value="${App.escapeHtml(item.value)}" ${item.value === selectedValue ? 'selected' : ''}>${App.escapeHtml(item.label)}</option>`)
      .join('');
  }

  function renderFilterSelects() {
    if (!state.filters) return;
    populateSelect(document.getElementById('privacy-select'), state.filters.privacy, state.privacy);
    populateSelect(document.getElementById('device-type-select'), state.filters.device_types, state.device_type);
    populateSelect(document.getElementById('status-select'), state.filters.statuses, state.status);
    populateSelect(document.getElementById('privacy-select-mobile'), state.filters.privacy, state.privacy);
    populateSelect(document.getElementById('device-type-select-mobile'), state.filters.device_types, state.device_type);
    populateSelect(document.getElementById('status-select-mobile'), state.filters.statuses, state.status);
  }

  function circleStyle(station) {
    const fillColor = station.status === 'Maintenance' ? '#d97706' : '#0f766e';
    const strokeColor = station.is_public ? '#ffffff' : '#dc2626';
    return {
      radius: 5.5,
      fillColor,
      color: strokeColor,
      weight: station.is_public ? 2 : 3,
      opacity: 1,
      fillOpacity: 1,
      pane: 'markerPane',
    };
  }

  function jitterStations(stations) {
    const grouped = new Map();
    stations.forEach((station) => {
      if (station.lat == null || station.lon == null) return;
      const key = `${station.lat.toFixed(5)}:${station.lon.toFixed(5)}`;
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(station);
    });
    const output = [];
    grouped.forEach((items) => {
      if (items.length === 1) {
        output.push({ ...items[0], display_lat: items[0].lat, display_lon: items[0].lon });
        return;
      }
      items.forEach((item, index) => {
        const angle = (Math.PI * 2 * index) / items.length;
        const r = 0.00022;
        output.push({
          ...item,
          display_lat: item.lat + r * Math.sin(angle),
          display_lon: item.lon + r * Math.cos(angle),
        });
      });
    });
    return output;
  }

  function renderMarkers(stations) {
    if (state.markers) state.markers.remove();
    state.markers = L.layerGroup();
    const plotted = jitterStations(stations);
    const bounds = [];
    plotted.forEach((station) => {
      if (station.display_lat == null || station.display_lon == null) return;
      bounds.push([station.display_lat, station.display_lon]);
      const marker = L.circleMarker([station.display_lat, station.display_lon], circleStyle(station));
      marker.on('click', () => openDrawer(station.station_id));
      marker.addTo(state.markers);
    });
    state.markers.addTo(map);
    if (bounds.length) {
      map.fitBounds(bounds, { padding: [28, 28] });
    }
  }

  function resetDrawerTabs() {
    document.querySelectorAll('#drawer-tabs button').forEach((item) => {
      item.classList.toggle('is-active', item.dataset.drawerTab === 'summary');
    });
    document.querySelectorAll('[data-drawer-panel]').forEach((panel) => {
      panel.classList.toggle('is-active', panel.getAttribute('data-drawer-panel') === 'summary');
    });
  }

  function wireTabButtons() {
    document.querySelectorAll('#drawer-tabs button').forEach((button) => {
      button.addEventListener('click', () => {
        document.querySelectorAll('#drawer-tabs button').forEach((item) => item.classList.toggle('is-active', item === button));
        document.querySelectorAll('[data-drawer-panel]').forEach((panel) => {
          panel.classList.toggle('is-active', panel.getAttribute('data-drawer-panel') === button.dataset.drawerTab);
        });
      });
    });
  }

  function closeDrawer() {
    drawer.classList.remove('is-open');
    drawer.setAttribute('aria-hidden', 'true');
  }

  async function openDrawer(stationId) {
    state.selectedStationId = stationId;
    resetDrawerTabs();
    drawer.classList.add('is-open');
    drawer.setAttribute('aria-hidden', 'false');
    summaryEl.innerHTML = '<article class="drawer-card"><p>Loading station summary…</p></article>';
    currentEl.innerHTML = '<article class="drawer-card"><p>Loading current readings…</p></article>';
    detailsEl.innerHTML = '<article class="drawer-card"><p>Loading station details…</p></article>';
    drawerMetadata.disabled = false;
    drawerOpenStation.href = `/station/${encodeURIComponent(stationId)}`;
    drawerOpenStation.classList.remove('disabled-link');

    const [summary, latest, metadata] = await Promise.all([
      App.fetchJSON(`/api/stations/${encodeURIComponent(stationId)}`),
      App.fetchJSON(`/api/stations/${encodeURIComponent(stationId)}/latest`),
      App.fetchJSON(`/api/stations/${encodeURIComponent(stationId)}/metadata`),
    ]);

    drawerTitle.textContent = summary.name;
    drawerSubtitle.textContent = `${summary.device_label} · ${summary.status} · ${summary.location_text}`;

    summaryEl.innerHTML = `
      <article class="drawer-card">
        <div class="pill-row">
          <span class="status-pill ${summary.status === 'Maintenance' ? 'maintenance' : ''}">${App.escapeHtml(summary.status)}</span>
          <span class="status-pill subtle">${App.escapeHtml(summary.privacy)}</span>
        </div>
      </article>
      <article class="drawer-card">
        <h3>Station summary</h3>
        <div class="drawer-kv">
          <div><span>Station</span><strong>${App.escapeHtml(summary.station_num ?? summary.station_id)}</strong></div>
          <div><span>Device</span><strong>${App.escapeHtml(summary.device_label)}</strong></div>
          <div><span>Latitude</span><strong>${summary.lat?.toFixed?.(4) ?? '—'}</strong></div>
          <div><span>Longitude</span><strong>${summary.lon?.toFixed?.(4) ?? '—'}</strong></div>
        </div>
      </article>
      <article class="drawer-card">
        <h3>Data availability</h3>
        <div class="drawer-kv">
          <div><span>Freshness</span><strong>${App.escapeHtml(summary.freshness?.freshness_label || 'Unknown')}</strong></div>
          <div><span>Last update</span><strong>${App.escapeHtml(summary.freshness?.last_update || 'N/A')}</strong></div>
        </div>
      </article>
    `;

    if (!latest.cards?.length) {
      currentEl.innerHTML = '<article class="drawer-card"><h3>Current readings</h3><p>No live readings are available for this station view.</p></article>';
    } else {
      currentEl.innerHTML = `
        <article class="drawer-card">
          <h3>Current readings</h3>
          <div class="drawer-metrics">
            ${latest.cards.slice(0, 6).map((card) => `
              <div class="drawer-metric">
                <span>${App.escapeHtml(card.label)}</span>
                <strong>${card.latest ?? '—'}${card.unit ? ` ${App.escapeHtml(card.unit)}` : ''}</strong>
              </div>
            `).join('')}
          </div>
        </article>
        <article class="drawer-card">
          <h3>Interpretation</h3>
          <p>${latest.primary_aqi ? `${App.escapeHtml(latest.primary_aqi.category)}. ${App.escapeHtml(latest.primary_aqi.health_message)}` : 'AQI-style interpretation is not available for the current primary live metric.'}</p>
        </article>
      `;
    }

    detailsEl.innerHTML = `
      <article class="drawer-card">
        <h3>Station details</h3>
        <div class="drawer-kv">
          <div><span>Earliest data</span><strong>${App.escapeHtml(metadata.summary?.earliest_data || 'N/A')}</strong></div>
          <div><span>Latest data</span><strong>${App.escapeHtml(metadata.summary?.latest_data || 'N/A')}</strong></div>
          <div><span>Measurement frequency</span><strong>${App.escapeHtml(metadata.summary?.measurement_frequency || 'N/A')}</strong></div>
          <div><span>Metadata tabs</span><strong>${metadata.tabs?.length ?? 0}</strong></div>
        </div>
      </article>
      <article class="drawer-card">
        <h3>Available instruments</h3>
        <ul class="drawer-list">
          ${(metadata.tabs || []).map((tab) => `<li>${App.escapeHtml(tab.label)}</li>`).join('') || '<li>No metadata tabs available.</li>'}
        </ul>
      </article>
    `;
  }

  async function loadStations() {
    const url = new URL('/api/map/stations', window.location.origin);
    url.searchParams.set('privacy', state.privacy);
    url.searchParams.set('device_type', state.device_type);
    url.searchParams.set('status', state.status);
    url.searchParams.set('search', state.search);
    const payload = await App.fetchJSON(url.toString());
    state.stations = payload.stations || [];
    renderMarkers(state.stations);
  }

  function debounce(fn, delay = 250) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), delay);
    };
  }

  function syncStateFromSelects(prefix = '') {
    state.privacy = document.getElementById(`privacy-select${prefix}`)?.value || state.privacy;
    state.device_type = document.getElementById(`device-type-select${prefix}`)?.value || state.device_type;
    state.status = document.getElementById(`status-select${prefix}`)?.value || state.status;
  }

  async function init() {
    state.filters = await App.fetchJSON('/api/map/filters');
    renderFilterSelects();
    wireTabButtons();
    await loadStations();

    const debouncedSearch = debounce(async (event) => {
      state.search = event.target.value.trim();
      const other = event.target.id === 'station-search' ? document.getElementById('station-search-mobile') : document.getElementById('station-search');
      if (other && other.value !== event.target.value) other.value = event.target.value;
      await loadStations();
    }, 240);

    document.getElementById('station-search')?.addEventListener('input', debouncedSearch);
    document.getElementById('station-search-mobile')?.addEventListener('input', debouncedSearch);

    ['privacy-select', 'device-type-select', 'status-select'].forEach((id) => {
      document.getElementById(id)?.addEventListener('change', async () => {
        syncStateFromSelects('');
        renderFilterSelects();
        await loadStations();
      });
    });

    document.getElementById('reset-filters')?.addEventListener('click', async () => {
      state.privacy = 'all';
      state.device_type = 'all';
      state.status = 'all';
      state.search = '';
      const desktop = document.getElementById('station-search');
      if (desktop) desktop.value = '';
      const mobile = document.getElementById('station-search-mobile');
      if (mobile) mobile.value = '';
      renderFilterSelects();
      await loadStations();
      closeDrawer();
    });

    document.getElementById('open-mobile-filters')?.addEventListener('click', () => {
      renderFilterSelects();
      document.getElementById('mobile-filter-modal')?.showModal();
    });
    document.getElementById('close-mobile-filters')?.addEventListener('click', () => document.getElementById('mobile-filter-modal')?.close());
    document.getElementById('apply-mobile-filters')?.addEventListener('click', async () => {
      syncStateFromSelects('-mobile');
      renderFilterSelects();
      document.getElementById('mobile-filter-modal')?.close();
      await loadStations();
    });
    document.getElementById('reset-filters-mobile')?.addEventListener('click', () => {
      state.privacy = 'all';
      state.device_type = 'all';
      state.status = 'all';
      renderFilterSelects();
    });

    document.getElementById('close-drawer')?.addEventListener('click', closeDrawer);
    drawerMetadata?.addEventListener('click', () => {
      if (state.selectedStationId) App.showMetadata(state.selectedStationId);
    });
  }

  init().catch((error) => console.error(error));
})();
