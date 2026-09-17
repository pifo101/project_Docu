(() => {
    const searchInput = document.querySelector("[data-document-search]");
    document.addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
            event.preventDefault();
            searchInput?.focus();
        }
    });
})();
