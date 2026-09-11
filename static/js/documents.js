(() => {
    const searchInput = document.querySelector("[data-document-search]");
    const filters = Array.from(document.querySelectorAll("[data-filter]"));
    const documents = Array.from(document.querySelectorAll("[data-document]"));
    const documentList = document.querySelector("[data-document-list]");
    const count = document.querySelector("[data-document-count]");
    const emptyState = document.querySelector("[data-empty-state]");
    const emptyTitle = emptyState?.querySelector("[data-empty-title]");
    const emptyCopy = emptyState?.querySelector("[data-empty-copy]");
    let activeFilter = "all";

    const normalize = (value) => value
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .trim();

    function updateDocuments() {
        const query = normalize(searchInput?.value || "");
        let visibleCount = 0;

        documents.forEach((documentRow) => {
            const matchesFilter = activeFilter === "all" || documentRow.dataset.status === activeFilter;
            const matchesSearch = normalize(documentRow.dataset.search).includes(query);
            const isVisible = matchesFilter && matchesSearch;
            documentRow.hidden = !isVisible;
            if (isVisible) visibleCount += 1;
        });

        if (count) count.textContent = `${visibleCount} ${visibleCount === 1 ? "documento" : "documentos"}`;
        if (documentList) documentList.hidden = visibleCount === 0;
        if (emptyState) emptyState.hidden = visibleCount !== 0;

        if (visibleCount === 0 && emptyTitle && emptyCopy) {
            emptyTitle.textContent = query ? "No encontramos resultados" : "No hay documentos aquí";
            emptyCopy.textContent = query
                ? `No hay documentos que coincidan con “${searchInput.value.trim()}”. Prueba con otro término.`
                : "Cuando tengas documentos en este estado, aparecerán en esta sección.";
        }

    }

    filters.forEach((filter) => {
        filter.addEventListener("click", () => {
            activeFilter = filter.dataset.filter;
            filters.forEach((item) => {
                const isActive = item === filter;
                item.classList.toggle("document-filter--active", isActive);
                item.setAttribute("aria-pressed", String(isActive));
            });
            updateDocuments();
        });

        filter.addEventListener("keydown", (event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            const direction = event.key === "ArrowRight" ? 1 : -1;
            const nextIndex = (filters.indexOf(filter) + direction + filters.length) % filters.length;
            filters[nextIndex].focus();
            filters[nextIndex].click();
        });
    });

    searchInput?.addEventListener("input", updateDocuments);

    document.addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
            event.preventDefault();
            searchInput?.focus();
        }
    });

})();
