(() => {
  const page = document.querySelector('[data-guide-page]');
  if (!page) return;

  function parseJson(id, fallback = []) {
    const node = document.getElementById(id);
    if (!node) return fallback;
    try {
      return JSON.parse(node.textContent || '[]');
    } catch (error) {
      console.error(error);
      return fallback;
    }
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function renderFamilies() {
    const metadata = parseJson('guide-metadata-data');
    const root = document.getElementById('instrument-families');
    if (!root) return;
    root.innerHTML = metadata.map((group) => `
      <article class="guide-family-card">
        <span>${escapeHtml(group.label)}</span>
        <strong>${escapeHtml(String((group.items || []).length))}</strong>
        <p>${escapeHtml((group.items || []).slice(0, 3).map((item) => item.full_descriptor).join(', ') || 'Metadata definitions')}</p>
      </article>
    `).join('');
  }

  function initGlossaryFilters() {
    const glossary = parseJson('guide-glossary-data');
    const filterRoot = document.getElementById('guide-category-filters');
    const search = document.getElementById('guide-search');
    const cards = Array.from(document.querySelectorAll('[data-guide-term]'));
    if (!filterRoot || !search || !cards.length) return;
    const categories = ['All', ...Array.from(new Set(glossary.map((item) => item.category).filter(Boolean)))];
    let active = 'All';

    function renderButtons() {
      filterRoot.innerHTML = categories.map((category) => `
        <button type="button" class="${category === active ? 'is-active' : ''}" data-category="${escapeHtml(category)}">${escapeHtml(category)}</button>
      `).join('');
    }

    function applyFilters() {
      const query = search.value.trim().toLowerCase();
      let visible = 0;
      cards.forEach((card) => {
        const categoryMatch = active === 'All' || card.dataset.category === active.toLowerCase();
        const textMatch = !query || card.textContent.toLowerCase().includes(query);
        const show = categoryMatch && textMatch;
        card.hidden = !show;
        if (show) visible += 1;
      });
      page.dataset.visibleTerms = String(visible);
    }

    filterRoot.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-category]');
      if (!button) return;
      active = button.dataset.category || 'All';
      renderButtons();
      applyFilters();
    });
    search.addEventListener('input', applyFilters);
    renderButtons();
    applyFilters();
  }

  renderFamilies();
  initGlossaryFilters();
})();
