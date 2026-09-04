(() => {
    const selectionStorageKey = "adicla-sign-recipient-selection";
    const recipientStorageKey = "adicla-sign-recipient";
    const databaseName = "adicla-sign-editor";
    const storeName = "temporary-documents";
    const documentKey = "current-pdf";

    // Datos temporales centralizados para construir la UI mientras no existe una API de directorio.
    const MOCK_DIRECTORY = {
        people: [
            { id: "person-1", firstName: "Juan", lastName: "Martínez", email: "juan.martinez@adicla.org.gt", committeeId: "committee-demo-a", role: "Secretario" },
            { id: "person-2", firstName: "María", lastName: "López", email: "maria.lopez@adicla.org.gt", committeeId: "committee-demo-a", role: "Vocal" },
            { id: "person-3", firstName: "Sofía", lastName: "Herrera", email: "sofia.herrera@adicla.org.gt", committeeId: "committee-demo-a", role: "Tesorera" },
            { id: "person-4", firstName: "Carlos", lastName: "Pérez", email: "carlos.perez@adicla.org.gt", committeeId: "committee-demo-b", role: "Presidente" },
            { id: "person-5", firstName: "Ana", lastName: "Gómez", email: "ana.gomez@adicla.org.gt", committeeId: "committee-demo-b", role: "Vocal" },
            { id: "person-6", firstName: "Luis", lastName: "Ramírez", email: "luis.ramirez@adicla.org.gt", committeeId: "committee-demo-b", role: "Secretario" },
            { id: "person-7", firstName: "Elena", lastName: "Castillo", email: "elena.castillo@adicla.org.gt", committeeId: "committee-demo-c", role: "Presidenta" },
            { id: "person-8", firstName: "Diego", lastName: "Ortiz", email: "diego.ortiz@adicla.org.gt", committeeId: "committee-demo-c", role: "Vocal" },
            { id: "person-9", firstName: "Lucía", lastName: "Méndez", email: "lucia.mendez@adicla.org.gt", committeeId: "committee-demo-c", role: "Tesorera" },
        ],
        committees: [
            { id: "committee-demo-a", name: "Comité de demostración A", memberIds: ["person-1", "person-2", "person-3"] },
            { id: "committee-demo-b", name: "Comité de demostración B", memberIds: ["person-4", "person-5", "person-6"] },
            { id: "committee-demo-c", name: "Comité de demostración C", memberIds: ["person-7", "person-8", "person-9"] },
        ],
    };

    function readJsonStorage(key, fallback = null) {
        try {
            return JSON.parse(localStorage.getItem(key)) || fallback;
        } catch (error) {
            console.warn(`No se pudo leer el estado temporal ${key}.`, error);
            return fallback;
        }
    }

    function getRecipientPresentation() {
        return readJsonStorage(recipientStorageKey, {});
    }

    function readTemporaryDocument() {
        return new Promise((resolve) => {
            if (!window.indexedDB) return resolve(null);
            const request = indexedDB.open(databaseName, 1);
            request.addEventListener("upgradeneeded", () => {
                if (!request.result.objectStoreNames.contains(storeName)) request.result.createObjectStore(storeName);
            });
            request.addEventListener("error", () => resolve(null));
            request.addEventListener("success", () => {
                const database = request.result;
                const transaction = database.transaction(storeName, "readonly");
                const getRequest = transaction.objectStore(storeName).get(documentKey);
                getRequest.addEventListener("success", () => resolve(getRequest.result || null));
                getRequest.addEventListener("error", () => resolve(null));
                transaction.addEventListener("complete", () => database.close());
            });
        });
    }

    function createElement(tagName, className = "", text = "") {
        const element = document.createElement(tagName);
        if (className) element.className = className;
        if (text) element.textContent = text;
        return element;
    }

    function personName(person) {
        return `${person.firstName} ${person.lastName}`;
    }

    function personInitials(person) {
        return `${person.firstName[0]}${person.lastName[0]}`.toUpperCase();
    }

    function committeeForPerson(person) {
        return MOCK_DIRECTORY.committees.find((committee) => committee.id === person.committeeId);
    }

    function personById(personId) {
        return MOCK_DIRECTORY.people.find((person) => person.id === personId);
    }

    function normalizeSearch(value) {
        return value.trim().toLocaleLowerCase("es").normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    }

    function matchesSearch(person, query) {
        const searchable = normalizeSearch(`${person.firstName} ${person.lastName} ${person.email}`);
        return searchable.includes(normalizeSearch(query));
    }

    function pluralizeRecipients(count, unique = false) {
        if (count === 1) return unique ? "1 destinatario único" : "1 destinatario";
        return `${count} destinatarios${unique ? " únicos" : ""}`;
    }

    function initializeRecipientSelection(form) {
        const modeInputs = [...form.querySelectorAll("[data-recipient-mode]")];
        const modePanels = [...form.querySelectorAll("[data-mode-panel]")];
        const continueButton = form.querySelector("[type='submit']");
        const feedback = form.querySelector("[data-recipient-error]");
        const resultsStatus = form.querySelector("[data-recipient-results-status]");
        const countElement = document.querySelector("[data-recipient-count]");
        const summaryElement = document.querySelector("[data-recipient-summary]");
        const committeeSelect = form.querySelector("[data-committee-select]");
        const committeeFilter = form.querySelector("[data-committee-filter]");
        const storedState = readJsonStorage(selectionStorageKey, {});
        let state = {
            mode: ["single", "committee", "people"].includes(storedState.mode) ? storedState.mode : null,
            singlePersonId: storedState.mode === "single" ? storedState.people?.[0] || null : null,
            committeeId: storedState.mode === "committee" ? storedState.committee || null : null,
            additionalPeopleIds: storedState.mode === "committee" && Array.isArray(storedState.additional_people) ? [...new Set(storedState.additional_people)] : [],
            peopleIds: storedState.mode === "people" && Array.isArray(storedState.people) ? [...new Set(storedState.people)] : [],
        };

        const storedCommittee = MOCK_DIRECTORY.committees.find((committee) => committee.id === state.committeeId);
        state.singlePersonId = personById(state.singlePersonId)?.id || null;
        state.committeeId = storedCommittee?.id || null;
        state.peopleIds = state.peopleIds.filter(personById);
        state.additionalPeopleIds = state.additionalPeopleIds.filter((personId) => (
            personById(personId) && !storedCommittee?.memberIds.includes(personId)
        ));

        MOCK_DIRECTORY.committees.forEach((committee) => {
            committeeSelect.append(new Option(`${committee.name} (temporal)`, committee.id));
            committeeFilter.append(new Option(committee.name, committee.id));
        });

        function selectedIds() {
            if (state.mode === "single") return state.singlePersonId ? [state.singlePersonId] : [];
            if (state.mode === "people") return state.peopleIds.filter(personById);
            if (state.mode === "committee" && state.committeeId) {
                const committee = MOCK_DIRECTORY.committees.find((item) => item.id === state.committeeId);
                return [...new Set([...(committee?.memberIds || []), ...state.additionalPeopleIds])].filter(personById);
            }
            return [];
        }

        function hasSelection() {
            return selectedIds().length > 0;
        }

        function selectionContract() {
            if (state.mode === "single") return { mode: "single", people: state.singlePersonId ? [state.singlePersonId] : [] };
            if (state.mode === "committee") return { mode: "committee", committee: state.committeeId, additional_people: [...state.additionalPeopleIds] };
            if (state.mode === "people") return { mode: "people", people: [...state.peopleIds] };
            return { mode: null, people: [] };
        }

        function presentationData() {
            const people = selectedIds().map(personById).filter(Boolean);
            const committee = MOCK_DIRECTORY.committees.find((item) => item.id === state.committeeId);
            const singlePerson = state.mode === "single" ? people[0] : null;
            const modeLabels = {
                single: "Una persona",
                committee: committee?.name || "Comité completo",
                people: "Personas específicas",
            };

            return {
                mode: state.mode,
                name: singlePerson ? personName(singlePerson) : pluralizeRecipients(people.length, state.mode === "committee" && state.additionalPeopleIds.length > 0),
                email: singlePerson ? singlePerson.email : modeLabels[state.mode] || "Sin destinatarios",
                count: people.length,
                committeeName: committee?.name || null,
                committeeMemberCount: committee?.memberIds.length || 0,
                additionalCount: state.additionalPeopleIds.length,
                recipients: people.map((person) => ({
                    id: person.id,
                    name: personName(person),
                    email: person.email,
                    committee: committeeForPerson(person)?.name || "Sin comité",
                    role: person.role,
                })),
            };
        }

        function persistState() {
            if (!state.mode) {
                localStorage.removeItem(selectionStorageKey);
                localStorage.removeItem(recipientStorageKey);
                return;
            }
            localStorage.setItem(selectionStorageKey, JSON.stringify(selectionContract()));
            localStorage.setItem(recipientStorageKey, JSON.stringify(presentationData()));
        }

        function setFeedback(message = "") {
            feedback.textContent = message;
        }

        function buildPersonResult(person, context) {
            const article = createElement("article", "person-result");
            const avatar = createElement("span", "avatar", personInitials(person));
            avatar.setAttribute("aria-hidden", "true");
            const identity = createElement("div", "person-result__identity");
            const name = createElement("strong", "", personName(person));
            const email = createElement("span", "", person.email);
            const metadata = createElement("div", "person-result__meta");
            const committee = committeeForPerson(person);
            const button = createElement("button", "", context === "single" ? "Seleccionar" : "+ Agregar");
            const alreadySelected = context === "single"
                ? state.singlePersonId === person.id
                : context === "people"
                    ? state.peopleIds.includes(person.id)
                    : state.additionalPeopleIds.includes(person.id);

            metadata.append(
                createElement("span", "", `Comité: ${committee?.name || "Sin comité"}`),
                createElement("span", "", `Cargo: ${person.role}`),
            );
            identity.append(name, email, metadata);
            button.type = "button";
            button.dataset.personId = person.id;
            if (alreadySelected) {
                button.disabled = true;
                button.textContent = context === "single" ? "Seleccionada" : "Agregada";
            }
            button.addEventListener("click", () => addPerson(person.id, context));
            article.append(avatar, identity, button);
            return article;
        }

        function filteredPeople(context) {
            const search = form.querySelector(`[data-person-search='${context}']`);
            const committeeId = context === "people" ? committeeFilter.value : "";
            return MOCK_DIRECTORY.people.filter((person) => (
                matchesSearch(person, search.value)
                && (!committeeId || person.committeeId === committeeId)
            ));
        }

        function renderResults(context) {
            const results = form.querySelector(`[data-person-results='${context}']`);
            const people = filteredPeople(context);
            results.replaceChildren();
            if (!people.length) {
                results.append(createElement("p", "recipient-empty", "No se encontraron personas con esos datos."));
                return 0;
            }
            people.forEach((person) => results.append(buildPersonResult(person, context)));
            return people.length;
        }

        function buildSelectedPerson(person, context) {
            const article = createElement("article", context === "single" ? "selected-person-card" : "selected-person-row");
            const avatar = createElement("span", "avatar", personInitials(person));
            avatar.setAttribute("aria-hidden", "true");
            const identity = createElement("div");
            const committee = committeeForPerson(person);
            const removeButton = createElement("button", "recipient-remove", "Quitar");
            removeButton.type = "button";
            removeButton.setAttribute("aria-label", `Quitar a ${personName(person)}`);
            removeButton.addEventListener("click", () => removePerson(person.id, context));
            identity.append(
                createElement("strong", "", personName(person)),
                createElement("span", "", person.email),
                createElement("span", "", `${committee?.name || "Sin comité"} · ${person.role}`),
            );
            article.append(avatar, identity, removeButton);
            return article;
        }

        function renderSingleSelection() {
            const section = form.querySelector("[data-single-selection]");
            const container = form.querySelector("[data-selected-single]");
            const person = personById(state.singlePersonId);
            section.hidden = !person;
            container.replaceChildren();
            if (person) container.append(buildSelectedPerson(person, "single"));
        }

        function renderCommitteeSelection() {
            const section = form.querySelector("[data-committee-selection]");
            const additionalSection = form.querySelector("[data-additional-section]");
            const committee = MOCK_DIRECTORY.committees.find((item) => item.id === state.committeeId);
            committeeSelect.value = state.committeeId || "";
            section.hidden = !committee;
            additionalSection.hidden = !committee;
            if (!committee) return;

            form.querySelector("[data-committee-name]").textContent = committee.name;
            form.querySelector("[data-committee-size]").textContent = `${committee.memberIds.length} integrantes`;
            const memberList = form.querySelector("[data-committee-members]");
            memberList.replaceChildren();
            committee.memberIds.map(personById).filter(Boolean).forEach((person) => {
                memberList.append(createElement("li", "", `${personName(person)} · ${person.role}`));
            });

            const selectedSection = form.querySelector("[data-additional-selection]");
            const chips = form.querySelector("[data-selected-additional]");
            selectedSection.hidden = state.additionalPeopleIds.length === 0;
            chips.replaceChildren();
            state.additionalPeopleIds.map(personById).filter(Boolean).forEach((person) => {
                const chip = createElement("span", "recipient-chip");
                const label = createElement("span", "", `${personName(person)} · ${committeeForPerson(person)?.name || "Sin comité"}`);
                const removeButton = createElement("button", "", "×");
                removeButton.type = "button";
                removeButton.setAttribute("aria-label", `Quitar a ${personName(person)}`);
                removeButton.addEventListener("click", () => removePerson(person.id, "additional"));
                chip.append(label, removeButton);
                chips.append(chip);
            });
        }

        function renderPeopleSelection() {
            const section = form.querySelector("[data-people-selection]");
            const container = form.querySelector("[data-selected-people]");
            section.hidden = state.peopleIds.length === 0;
            container.replaceChildren();
            state.peopleIds.map(personById).filter(Boolean).forEach((person) => {
                container.append(buildSelectedPerson(person, "people"));
            });
        }

        function renderSummary() {
            const presentation = presentationData();
            countElement.textContent = pluralizeRecipients(
                presentation.count,
                state.mode === "committee" && presentation.additionalCount > 0,
            );
            summaryElement.replaceChildren();

            if (!state.mode) {
                summaryElement.append(createElement("p", "", "Selecciona un modo para comenzar."));
                return;
            }
            if (!presentation.count) {
                summaryElement.append(createElement("p", "", "Aún no has seleccionado destinatarios."));
                return;
            }

            if (state.mode === "single") {
                const person = presentation.recipients[0];
                const line = createElement("div", "recipient-summary__line");
                line.append(createElement("strong", "", person.name), createElement("span", "", person.email));
                summaryElement.append(line);
            }
            if (state.mode === "committee") {
                const committeeLine = createElement("div", "recipient-summary__line");
                committeeLine.append(
                    createElement("strong", "", presentation.committeeName),
                    createElement("span", "", `${presentation.committeeMemberCount} integrantes`),
                );
                summaryElement.append(committeeLine);
                if (presentation.additionalCount) {
                    const additionalLine = createElement("div", "recipient-summary__line");
                    additionalLine.append(
                        createElement("strong", "", "Personas adicionales"),
                        createElement("span", "", String(presentation.additionalCount)),
                    );
                    summaryElement.append(additionalLine);
                }
            }
            if (state.mode === "people") {
                summaryElement.append(createElement("strong", "", `${presentation.count} personas seleccionadas`));
                const list = createElement("ul", "recipient-summary__people");
                presentation.recipients.forEach((person) => list.append(createElement("li", "", person.name)));
                summaryElement.append(list);
            }
        }

        function render() {
            modeInputs.forEach((input) => { input.checked = input.value === state.mode; });
            modePanels.forEach((panel) => { panel.hidden = panel.dataset.modePanel !== state.mode; });
            if (state.mode === "single") {
                renderResults("single");
                renderSingleSelection();
            }
            if (state.mode === "committee") {
                renderCommitteeSelection();
                if (state.committeeId) renderResults("additional");
            }
            if (state.mode === "people") {
                renderResults("people");
                renderPeopleSelection();
            }
            renderSummary();
            continueButton.disabled = !hasSelection();
            persistState();
        }

        function addPerson(personId, context) {
            setFeedback();
            if (context === "single") {
                state.singlePersonId = personId;
            } else if (context === "people") {
                if (state.peopleIds.includes(personId)) {
                    setFeedback("Esta persona ya está seleccionada.");
                    return;
                }
                state.peopleIds.push(personId);
            } else {
                const committee = MOCK_DIRECTORY.committees.find((item) => item.id === state.committeeId);
                if (committee?.memberIds.includes(personId)) {
                    setFeedback("Esta persona ya está incluida en el comité seleccionado.");
                    return;
                }
                if (state.additionalPeopleIds.includes(personId)) {
                    setFeedback("Esta persona ya está seleccionada.");
                    return;
                }
                state.additionalPeopleIds.push(personId);
            }
            render();
            const focusTarget = context === "single"
                ? form.querySelector("[data-selected-single] .recipient-remove")
                : context === "people"
                    ? form.querySelector("[data-selected-people] .selected-person-row:last-child .recipient-remove")
                    : form.querySelector("[data-selected-additional] .recipient-chip:last-child button");
            focusTarget?.focus();
        }

        function removePerson(personId, context) {
            setFeedback();
            if (context === "single") state.singlePersonId = null;
            if (context === "people") state.peopleIds = state.peopleIds.filter((id) => id !== personId);
            if (context === "additional") state.additionalPeopleIds = state.additionalPeopleIds.filter((id) => id !== personId);
            render();
            form.querySelector(`[data-person-search='${context}']`)?.focus();
        }

        modeInputs.forEach((input) => {
            input.addEventListener("change", () => {
                if (!input.checked || input.value === state.mode) return;
                const lostSelection = hasSelection();
                state = {
                    mode: input.value,
                    singlePersonId: null,
                    committeeId: null,
                    additionalPeopleIds: [],
                    peopleIds: [],
                };
                form.querySelectorAll("[data-person-search]").forEach((search) => { search.value = ""; });
                committeeFilter.value = "";
                setFeedback(lostSelection ? "La selección anterior se limpió al cambiar de modo." : "");
                render();
            });
        });

        form.querySelectorAll("[data-person-search]").forEach((search) => {
            search.addEventListener("input", () => {
                const resultCount = renderResults(search.dataset.personSearch);
                setFeedback();
                resultsStatus.textContent = `${resultCount} ${resultCount === 1 ? "resultado" : "resultados"}.`;
            });
        });
        committeeFilter.addEventListener("change", () => renderResults("people"));
        committeeSelect.addEventListener("change", () => {
            state.committeeId = committeeSelect.value || null;
            state.additionalPeopleIds = [];
            setFeedback();
            render();
        });

        form.addEventListener("submit", (event) => {
            event.preventDefault();
            if (!hasSelection()) {
                setFeedback("Selecciona al menos un destinatario para continuar.");
                continueButton.disabled = true;
                return;
            }
            persistState();
            window.location.assign(continueButton.dataset.editorUrl);
        });

        readTemporaryDocument().then((documentData) => {
            const documentName = document.querySelector("[data-workflow-document-name]");
            if (documentName && documentData?.name) documentName.textContent = documentData.name;
        });

        render();
    }

    document.querySelectorAll("[data-mock-action]").forEach((button) => {
        button.addEventListener("click", () => {
            const feedback = document.querySelector("[data-workflow-feedback]") || document.querySelector("[data-recipient-error]");
            if (feedback) {
                feedback.textContent = button.dataset.mockAction;
                feedback.hidden = false;
            } else {
                button.setAttribute("aria-label", button.dataset.mockAction);
            }
        });
    });

    const recipientForm = document.querySelector("[data-recipient-form]");
    if (recipientForm) initializeRecipientSelection(recipientForm);

    const reviewForm = document.querySelector("[data-review-form]");
    if (reviewForm) {
        const storedRecipient = getRecipientPresentation();
        const fallbackName = "Destinatarios seleccionados";
        const fallbackDetail = "Información temporal no disponible";
        const sendButton = document.querySelector("[data-review-submit]");
        const recipientError = document.querySelector("[data-review-recipient-error]");
        const recipientList = document.querySelector("[data-review-recipient-list]");

        function updateReviewRecipient(recipient) {
            const hasLegacyRecipient = Boolean(recipient?.name && recipient?.email && recipient.count === undefined);
            const hasRecipients = Number(recipient?.count) > 0 || hasLegacyRecipient;
            document.querySelector("[data-review-recipient]").textContent = recipient?.name || fallbackName;
            document.querySelector("[data-review-email]").textContent = recipient?.email || fallbackDetail;
            document.querySelector("[data-success-recipient]").textContent = recipient?.name || fallbackName;
            document.querySelector("[data-success-email]").textContent = recipient?.email || fallbackDetail;
            sendButton.disabled = !hasRecipients;
            recipientError.hidden = hasRecipients;
            recipientList.replaceChildren();
            if (Array.isArray(recipient?.recipients)) {
                recipient.recipients.forEach((person) => {
                    recipientList.append(createElement("li", "", `${person.name} · ${person.committee}`));
                });
            }
        }

        updateReviewRecipient(storedRecipient);

        readTemporaryDocument().then((documentData) => {
            if (!documentData) return;
            if (documentData.recipient) updateReviewRecipient(documentData.recipient);
            document.querySelector("[data-review-document]").textContent = documentData.name || "Documento PDF";
            const fields = Array.isArray(documentData.fields) ? documentData.fields : [];
            const signatures = fields.filter((field) => field.type === "signature").length;
            document.querySelector("[data-review-fields]").textContent = String(fields.length);
            document.querySelector("[data-review-signature]").textContent = signatures ? "Sí" : "No";
            document.querySelector("[data-review-other]").textContent = String(Math.max(0, fields.length - signatures));
        });

        reviewForm.addEventListener("submit", (event) => {
            event.preventDefault();
            if (sendButton.disabled) return;
            if (!reviewForm.checkValidity()) return reviewForm.reportValidity();
            document.querySelector("[data-success-dialog]")?.showModal();
        });
    }
})();
