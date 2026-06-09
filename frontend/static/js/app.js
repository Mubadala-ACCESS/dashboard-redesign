const App = (() => {
  const metadataCache = new Map();

  async function fetchJSON(url, options = {}) {
    const redirectOnAuth = options.redirectOnAuth !== false;
    const response = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!response.ok) {
      const detail = await response.text();
      if (response.status === 401 && redirectOnAuth) {
        try {
          const payload = JSON.parse(detail);
          if (payload.login_url) {
            window.location.href = payload.login_url;
            return new Promise(() => {});
          }
        } catch (error) {
          // Fall through to the regular error path.
        }
      }
      throw new Error(detail || `Request failed: ${response.status}`);
    }
    return response.json();
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  function openModal(html) {
    const dialog = document.getElementById('global-modal');
    dialog.innerHTML = html;
    if (!dialog.open) dialog.showModal();
    dialog.addEventListener(
      'click',
      (event) => {
        const rect = dialog.getBoundingClientRect();
        const clickedOutside = event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom;
        if (clickedOutside) dialog.close();
      },
      { once: true }
    );
    dialog.querySelectorAll('[data-close-modal]').forEach((button) => {
      button.addEventListener('click', () => dialog.close());
    });
  }

  function buildMetadataModal(payload) {
    const tabs = payload.tabs || [];
    const tabButtons = tabs.map((tab, index) => `
      <button class="${index === 0 ? 'is-active' : ''}" data-metadata-tab="${escapeHtml(tab.file)}">${escapeHtml(tab.label)}</button>
    `).join('');
    const tables = tabs.map((tab, index) => `
      <section class="metadata-section" data-metadata-panel="${escapeHtml(tab.file)}" ${index === 0 ? '' : 'hidden'}>
        <div class="metadata-table">
          <table>
            <thead><tr><th>Column</th><th>Descriptor</th><th>Units</th><th>Definition</th></tr></thead>
            <tbody>
              ${tab.items.map((row) => `
                <tr>
                  <td>${escapeHtml(row.column_name)}</td>
                  <td>${escapeHtml(row.full_descriptor)}</td>
                  <td>${escapeHtml(row.units)}</td>
                  <td>${escapeHtml(row.definition)}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </section>`).join('');

    return `
      <article class="modal-panel">
        <header class="modal-head">
          <div>
            <span class="eyebrow">Station metadata</span>
            <h2>${escapeHtml(payload.station.name)}</h2>
            <p>${escapeHtml(payload.summary.measurement_frequency)}</p>
          </div>
          <button class="ghost-button" data-close-modal>Close</button>
        </header>
        <div class="drawer-kv">
          <div><span>Earliest data</span><strong>${escapeHtml(payload.summary.earliest_data)}</strong></div>
          <div><span>Latest data</span><strong>${escapeHtml(payload.summary.latest_data)}</strong></div>
          <div><span>Device type</span><strong>${escapeHtml(payload.station.device_label)}</strong></div>
          <div><span>Privacy</span><strong>${escapeHtml(payload.station.privacy)}</strong></div>
        </div>
        <div class="tab-row">${tabButtons}</div>
        ${tables}
        <footer class="modal-actions">
          <a class="primary-button" href="/station/${encodeURIComponent(payload.station.station_id)}">Open station</a>
          <button class="ghost-button" data-close-modal>Done</button>
        </footer>
      </article>
    `;
  }

  function wireMetadataTabs() {
    const dialog = document.getElementById('global-modal');
    dialog.querySelectorAll('[data-metadata-tab]').forEach((button) => {
      button.addEventListener('click', () => {
        const tab = button.getAttribute('data-metadata-tab');
        dialog.querySelectorAll('[data-metadata-tab]').forEach((item) => item.classList.toggle('is-active', item === button));
        dialog.querySelectorAll('[data-metadata-panel]').forEach((panel) => {
          panel.hidden = panel.getAttribute('data-metadata-panel') !== tab;
        });
      });
    });
  }

  async function showMetadata(stationId) {
    const cacheKey = String(stationId || '');
    const cached = metadataCache.get(cacheKey);
    if (cached) {
      openModal(buildMetadataModal(cached));
      wireMetadataTabs();
      return cached;
    }

    openModal(`
      <article class="modal-panel">
        <header class="modal-head">
          <div>
            <span class="eyebrow">Station metadata</span>
            <h2>Loading metadata</h2>
            <p>Fetching station descriptors and data coverage.</p>
          </div>
          <button class="ghost-button" data-close-modal>Close</button>
        </header>
        <section class="drawer-stack">
          <article class="drawer-card"><p>Loading station metadata...</p></article>
        </section>
      </article>
    `);
    try {
      const payload = await fetchJSON(`/api/stations/${encodeURIComponent(stationId)}/metadata`);
      metadataCache.set(cacheKey, payload);
      openModal(buildMetadataModal(payload));
      wireMetadataTabs();
      return payload;
    } catch (error) {
      openModal(`
        <article class="modal-panel">
          <header class="modal-head">
            <div>
              <span class="eyebrow">Station metadata</span>
              <h2>Metadata unavailable</h2>
              <p>${escapeHtml(error.message || 'The metadata request failed.')}</p>
            </div>
            <button class="ghost-button" data-close-modal>Close</button>
          </header>
        </article>
      `);
      throw error;
    }
  }

  return { fetchJSON, openModal, showMetadata, escapeHtml };
})();

window.App = App;
