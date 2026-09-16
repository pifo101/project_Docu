(function () {
    "use strict";

    const form = document.querySelector("[data-real-recipient-form]");
    const directoryElement = document.getElementById("recipient-directory");
    if (!form || !directoryElement) return;

    const directory = JSON.parse(directoryElement.textContent);
    const modeInputs = [...form.querySelectorAll("[data-recipient-mode]")];
    const panels = [...form.querySelectorAll("[data-mode-panel]")];
    const values = form.querySelector("[data-recipient-values]");
    const submit = form.querySelector("[data-recipient-submit]");
    const feedback = form.querySelector("[data-recipient-error]");
    const resultStatus = form.querySelector("[data-recipient-results-status]");
    const count = document.querySelector("[data-recipient-count]");
    const summary = document.querySelector("[data-recipient-summary]");
    const committeeCount = count.textContent;
    const committeeSummary = [...summary.childNodes].map((node) => node.cloneNode(true));
    let selectedIds = [...values.selectedOptions].map((option) => Number(option.value));

    function mode() {
        return modeInputs.find((input) => input.checked)?.value || "committee";
    }

    function normalized(value) {
        return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    }

    function personById(id) {
        return directory.find((person) => person.id === id);
    }

    function initials(person) {
        return person.name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
    }

    function createElement(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;
        return element;
    }

    function selectedPeople() {
        return selectedIds.map(personById).filter(Boolean);
    }

    function syncValues() {
        const selected = new Set(selectedIds);
        [...values.options].forEach((option) => {
            option.selected = selected.has(Number(option.value));
        });
    }

    function addPerson(person) {
        if (mode() === "single") selectedIds = [person.id];
        else if (!selectedIds.includes(person.id)) selectedIds.push(person.id);
        feedback.textContent = "";
        render();
    }

    function removePerson(id) {
        selectedIds = selectedIds.filter((selectedId) => selectedId !== id);
        render();
    }

    function personCard(person, selected) {
        const card = createElement("article", selected ? "selected-person-row" : "person-result");
        const avatar = createElement("span", "avatar", initials(person));
        const identity = createElement("div", selected ? "" : "person-result__identity");
        const action = createElement("button", selected ? "recipient-remove" : "", selected ? "Quitar" : (mode() === "single" ? "Seleccionar" : "+ Agregar"));
        avatar.setAttribute("aria-hidden", "true");
        identity.append(createElement("strong", "", person.name), createElement("span", "", person.email));
        if (!selected) {
            const metadata = createElement("div", "person-result__meta");
            metadata.append(createElement("span", "", `Comité: ${person.committee}`), createElement("span", "", `Cargo: ${person.role}`));
            identity.append(metadata);
        } else {
            identity.append(createElement("span", "", `${person.committee} · ${person.role}`));
        }
        action.type = "button";
        action.addEventListener("click", () => selected ? removePerson(person.id) : addPerson(person));
        if (!selected && selectedIds.includes(person.id)) {
            action.disabled = true;
            action.textContent = mode() === "single" ? "Seleccionada" : "Agregada";
        }
        card.append(avatar, identity, action);
        return card;
    }

    function renderResults(currentMode) {
        const search = form.querySelector(`[data-person-search='${currentMode}']`);
        const results = form.querySelector(`[data-person-results='${currentMode}']`);
        if (!search || !results) return;
        const term = normalized(search.value.trim());
        const people = directory.filter((person) => normalized(`${person.name} ${person.email}`).includes(term));
        results.replaceChildren();
        if (!people.length) results.append(createElement("p", "recipient-empty", "No se encontraron personas con esos datos."));
        else people.forEach((person) => results.append(personCard(person, false)));
        resultStatus.textContent = `${people.length} resultado${people.length === 1 ? "" : "s"}.`;
    }

    function renderSelected(currentMode) {
        if (currentMode === "committee") return;
        const section = form.querySelector(`[data-selection='${currentMode}']`);
        const container = form.querySelector(`[data-selected-people='${currentMode}']`);
        const people = selectedPeople();
        section.hidden = people.length === 0;
        container.replaceChildren();
        people.forEach((person) => container.append(personCard(person, true)));
    }

    function renderSummary(currentMode) {
        summary.replaceChildren();
        if (currentMode === "committee") {
            count.textContent = committeeCount;
            summary.append(...committeeSummary.map((node) => node.cloneNode(true)));
            return;
        }
        const people = selectedPeople();
        count.textContent = `${people.length} destinatario${people.length === 1 ? "" : "s"}`;
        if (!people.length) {
            summary.append(createElement("p", "", "Aún no has seleccionado destinatarios."));
            return;
        }
        const list = createElement("ul", "recipient-summary__people");
        people.forEach((person) => list.append(createElement("li", "", person.name)));
        summary.append(list);
    }

    function render() {
        const currentMode = mode();
        if (currentMode === "single" && selectedIds.length > 1) selectedIds = selectedIds.slice(0, 1);
        panels.forEach((panel) => { panel.hidden = panel.dataset.modePanel !== currentMode; });
        syncValues();
        if (currentMode !== "committee") {
            renderResults(currentMode);
            renderSelected(currentMode);
        }
        renderSummary(currentMode);
        submit.disabled = currentMode === "committee" ? false : selectedIds.length === 0;
    }

    modeInputs.forEach((input) => input.addEventListener("change", () => {
        selectedIds = [];
        feedback.textContent = "";
        render();
    }));
    form.querySelectorAll("[data-person-search]").forEach((input) => input.addEventListener("input", render));
    form.addEventListener("submit", (event) => {
        if (mode() !== "committee" && selectedIds.length === 0) {
            event.preventDefault();
            feedback.textContent = mode() === "single" ? "Selecciona exactamente una persona válida." : "Selecciona al menos una persona válida.";
        }
    });
    render();
}());
