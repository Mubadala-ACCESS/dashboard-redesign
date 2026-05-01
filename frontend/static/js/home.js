(() => {
  const page = document.querySelector('.home-page');
  if (!page) return;

  const DEFAULT_MAP_CENTER = [24.4539, 54.3773];
  const DEFAULT_MAP_ZOOM = 10;
  const SINGLE_STATION_ZOOM = 14;
  const MAX_FIT_ZOOM = 14;
  const FIT_PADDING = [14, 14];

  const map = L.map('map', { zoomControl: true, scrollWheelZoom: true }).setView(DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM);
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
    loadRequestId: 0,
    fitToken: 0,
  };

  const STATION_TYPE_STYLES = {
    IoTBox: { label: 'IoT Box', color: '#2563eb' },
    Meteorological: { label: 'Meteorological', color: '#f59e0b' },
    Fidas_Palas: { label: 'Fidas Palas', color: '#be123c' },
    Buoy: { label: 'Buoy', color: '#0891b2' },
    JWCruise: { label: 'Jaywun Cruise', color: '#16a34a' },
    SBNTransect: { label: 'SBN Transect', color: '#7c3aed' },
    coral_reef: { label: 'Coral Reef', color: '#db2777' },
    underwater_probe: { label: 'Underwater Probe', color: '#0e7490' },
    Unknown: { label: 'Unknown', color: '#64748b' },
  };

  const STATUS_COLORS = {
    Active: '#0f766e',
    Maintenance: '#d97706',
    Decommissioned: '#64748b',
    Unknown: '#94a3b8',
  };

  const PRIVACY_COLORS = {
    Public: '#ffffff',
    Private: '#dc2626',
  };

  const drawer = document.getElementById('station-drawer');
  const currentEl = document.getElementById('drawer-current');
  const detailsEl = document.getElementById('drawer-details');
  const drawerTitle = document.getElementById('drawer-title');
  const drawerSubtitle = document.getElementById('drawer-subtitle');
  const drawerMetadata = document.getElementById('drawer-open-metadata');
  const drawerOpenStation = document.getElementById('drawer-open-station');
  const legendEl = document.querySelector('.legend-inline');

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

  function stationTypeStyle(stationOrType) {
    const key = typeof stationOrType === 'string' ? stationOrType : stationOrType?.device_type;
    const fallbackLabel = typeof stationOrType === 'string' ? key : stationOrType?.device_label;
    const style = STATION_TYPE_STYLES[key] || STATION_TYPE_STYLES.Unknown;
    return {
      key: key || 'Unknown',
      label: fallbackLabel || style.label,
      color: style.color,
    };
  }

  function statusColor(status) {
    return STATUS_COLORS[status] || STATUS_COLORS.Unknown;
  }

  function privacyLabel(station) {
    if (station?.privacy) return station.privacy;
    return station?.is_public === false ? 'Private' : 'Public';
  }

  function privacyColor(privacy) {
    const label = privacy === 'private' ? 'Private' : privacy === 'public' ? 'Public' : privacy;
    return PRIVACY_COLORS[label] || PRIVACY_COLORS.Public;
  }

  function markerIcon(station) {
    const type = stationTypeStyle(station);
    const privacy = privacyLabel(station);
    return L.divIcon({
      className: 'station-marker-wrap',
      html: `
        <span class="station-marker" style="--station-type:${type.color}; --station-status:${statusColor(station.status)}; --station-privacy:${privacyColor(privacy)}">
          <span class="station-marker__status">
            <span class="station-marker__type"></span>
          </span>
        </span>
      `,
      iconSize: [18, 18],
      iconAnchor: [9, 9],
      popupAnchor: [0, -7],
    });
  }

  function renderLegend() {
    if (!legendEl || !state.filters) return;
    const typeItems = (state.filters.device_types || []).filter((item) => item.value !== 'all');
    const statusItems = (state.filters.statuses || []).filter((item) => item.value !== 'all');
    const privacyItems = (state.filters.privacy || []).filter((item) => item.value !== 'all');

    legendEl.classList.add('station-legend');
    legendEl.innerHTML = `
      <span class="legend-group">
        <strong>Center: station type</strong>
        <span class="legend-items">
          ${typeItems.map((item) => {
            const style = stationTypeStyle(item.value);
            return `<span class="legend-key"><em class="legend-dot" style="--legend-color:${style.color}"></em>${App.escapeHtml(item.label)}</span>`;
          }).join('')}
        </span>
      </span>
      <span class="legend-group">
        <strong>Middle ring: status</strong>
        <span class="legend-items">
          ${statusItems.map((item) => `<span class="legend-key"><em class="legend-ring" style="--legend-color:${statusColor(item.value)}"></em>${App.escapeHtml(item.label)}</span>`).join('')}
        </span>
      </span>
      <span class="legend-group">
        <strong>Outer ring: privacy</strong>
        <span class="legend-items">
          ${privacyItems.map((item) => `<span class="legend-key"><em class="legend-ring legend-ring--outer" style="--legend-color:${privacyColor(item.value)}"></em>${App.escapeHtml(item.label)}</span>`).join('')}
        </span>
      </span>
    `;
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

  function fitMapToStations(stations) {
    const fitToken = ++state.fitToken;
    const points = stations
      .filter((station) => station.display_lat != null && station.display_lon != null)
      .map((station) => [station.display_lat, station.display_lon]);

    requestAnimationFrame(() => {
      if (fitToken !== state.fitToken) return;
      map.stop();
      map.invalidateSize();
      if (!points.length) {
        map.setView(DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM);
        return;
      }

      if (points.length === 1) {
        map.setView(points[0], SINGLE_STATION_ZOOM, { animate: true });
        return;
      }

      map.fitBounds(points, {
        animate: true,
        maxZoom: MAX_FIT_ZOOM,
        padding: FIT_PADDING,
      });
    });
  }

  function renderMarkers(stations) {
    if (state.markers) state.markers.remove();
    state.markers = L.layerGroup();
    const plotted = jitterStations(stations);
    plotted.forEach((station) => {
      if (station.display_lat == null || station.display_lon == null) return;
      const marker = L.marker([station.display_lat, station.display_lon], {
        icon: markerIcon(station),
        keyboard: true,
        title: `${station.name} - ${station.device_label}`,
        riseOnHover: true,
      });
      marker.on('click', () => openDrawer(station.station_id));
      marker.addTo(state.markers);
    });
    state.markers.addTo(map);
    fitMapToStations(plotted);
  }

  function resetDrawerTabs() {
    document.querySelectorAll('#drawer-tabs button').forEach((item) => {
      item.classList.toggle('is-active', item.dataset.drawerTab === 'details');
    });
    document.querySelectorAll('[data-drawer-panel]').forEach((panel) => {
      panel.classList.toggle('is-active', panel.getAttribute('data-drawer-panel') === 'details');
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

    if (!latest.cards?.length) {
      currentEl.innerHTML = '<article class="drawer-card"><h3>Current Readings</h3><p>No live readings are available for this station view.</p></article>';
    } else {
      currentEl.innerHTML = `
        <article class="drawer-card">
          <h3>Current Readings</h3>
          <div class="drawer-metrics">
            ${latest.cards.slice(0, 6).map((card) => `
              <div class="drawer-metric">
                <span>${App.escapeHtml(card.label)}</span>
                <strong>${card.latest ?? '—'}${card.unit ? ` ${App.escapeHtml(card.unit)}` : ''}</strong>
              </div>
            `).join('')}
          </div>
        </article>
      `;
    }

    detailsEl.innerHTML = `
      <article class="drawer-card">
        <h3>Station details</h3>
        <div class="drawer-kv compact">
          <div><span>Device</span><strong>${App.escapeHtml(summary.device_label)}</strong></div>
          <div><span>Status</span><strong>${App.escapeHtml(summary.status)}</strong></div>
          <div><span>Privacy</span><strong>${App.escapeHtml(summary.privacy)}</strong></div>
          <div><span>Latitude</span><strong>${summary.lat?.toFixed?.(4) ?? '—'}</strong></div>
          <div><span>Longitude</span><strong>${summary.lon?.toFixed?.(4) ?? '—'}</strong></div>
          <div><span>Earliest data</span><strong>${App.escapeHtml(metadata.summary?.earliest_data || 'N/A')}</strong></div>
          <div><span>Latest data</span><strong>${App.escapeHtml(metadata.summary?.latest_data || 'N/A')}</strong></div>
          <div><span>Measurement frequency</span><strong>${App.escapeHtml(metadata.summary?.measurement_frequency || 'N/A')}</strong></div>
        </div>
      </article>
    `;
  }

  async function loadStations() {
    const requestId = ++state.loadRequestId;
    const url = new URL('/api/map/stations', window.location.origin);
    url.searchParams.set('privacy', state.privacy);
    url.searchParams.set('device_type', state.device_type);
    url.searchParams.set('status', state.status);
    url.searchParams.set('search', state.search);
    const payload = await App.fetchJSON(url.toString());
    if (requestId !== state.loadRequestId) return;
    state.stations = payload.stations || [];
    renderMarkers(state.stations);
    renderLegend();
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
