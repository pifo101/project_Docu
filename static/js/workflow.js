(() => {
    const recipientStorageKey = "adicla-sign-recipient";
    const databaseName = "adicla-sign-editor";
    const storeName = "temporary-documents";
    const documentKey = "current-pdf";

    function getRecipient() {
        try {
            return JSON.parse(localStorage.getItem(recipientStorageKey)) || {};
        } catch (error) {
            console.warn("No se pudo leer el destinatario temporal.", error);
            return {};
        }
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
    if (recipientForm) {
        const nameInput = recipientForm.querySelector("[data-recipient-name]");
        const emailInput = recipientForm.querySelector("[data-recipient-email]");
        const errorMessage = recipientForm.querySelector("[data-recipient-error]");
        const savedRecipient = getRecipient();
        nameInput.value = savedRecipient.name || "";
        emailInput.value = savedRecipient.email || "";

        readTemporaryDocument().then((documentData) => {
            const documentName = document.querySelector("[data-workflow-document-name]");
            if (documentName && documentData?.name) documentName.textContent = documentData.name;
        });

        recipientForm.addEventListener("submit", (event) => {
            event.preventDefault();
            if (!recipientForm.checkValidity()) {
                errorMessage.textContent = "Completa el nombre y un correo electrónico válido.";
                recipientForm.reportValidity();
                return;
            }
            localStorage.setItem(recipientStorageKey, JSON.stringify({ name: nameInput.value.trim(), email: emailInput.value.trim(), action: "sign" }));
            window.location.assign(event.submitter.dataset.editorUrl);
        });
    }

    const reviewForm = document.querySelector("[data-review-form]");
    if (reviewForm) {
        const recipient = getRecipient();
        document.querySelector("[data-review-recipient]").textContent = recipient.name || "José Ramírez";
        document.querySelector("[data-review-email]").textContent = recipient.email || "jose.ramirez@empresa.com";
        document.querySelector("[data-success-recipient]").textContent = recipient.name || "José Ramírez";
        document.querySelector("[data-success-email]").textContent = recipient.email || "jose.ramirez@empresa.com";

        readTemporaryDocument().then((documentData) => {
            if (!documentData) return;
            document.querySelector("[data-review-document]").textContent = documentData.name || "Documento PDF";
            const fields = Array.isArray(documentData.fields) ? documentData.fields : [];
            const signatures = fields.filter((field) => field.type === "signature").length;
            document.querySelector("[data-review-fields]").textContent = String(fields.length);
            document.querySelector("[data-review-signature]").textContent = signatures ? "Sí" : "No";
            document.querySelector("[data-review-other]").textContent = String(Math.max(0, fields.length - signatures));
        });

        reviewForm.addEventListener("submit", (event) => {
            event.preventDefault();
            if (!reviewForm.checkValidity()) return reviewForm.reportValidity();
            document.querySelector("[data-success-dialog]")?.showModal();
        });
    }
})();
