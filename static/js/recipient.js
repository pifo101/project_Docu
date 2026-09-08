(() => {
    const recipientViewer = document.querySelector("[data-recipient-viewer]");
    const recipientPages = document.querySelector("[data-recipient-pages]");
    const recipientPageStatus = document.querySelector("[data-recipient-page-status]");
    const fields = Array.from(document.querySelectorAll("[data-completable]"));
    const progressCount = document.querySelector("[data-progress-count]");
    const progressBar = document.querySelector("[data-progress-bar]");
    const consentPanel = document.querySelector("[data-consent-panel]");
    const consentCheckbox = document.querySelector("[data-consent-checkbox]");
    const finalizeButton = document.querySelector("[data-finalize]");
    const signatureDialog = document.querySelector("[data-signature-dialog]");
    const signatureCanvas = document.querySelector("[data-signature-canvas]");
    const signatureError = document.querySelector("[data-signature-error]");
    const signatureInput = document.querySelector("[data-signature-input]");
    const signatureMethod = document.querySelector("[data-signature-method]");
    const signatureTabs = Array.from(document.querySelectorAll("[data-signature-tab]"));
    const nextHelp = document.querySelector("[data-next-help]");
    let signatureContext = null;
    let drawing = false;
    let hasSignatureStroke = false;
    let recipientPdf = null;
    let recipientRenderVersion = 0;
    let recipientRenderedWidth = 0;
    let recipientResizeTimer = null;
    let assignedPageFocused = false;

    function readSignatureField() {
        const element = document.getElementById("recipient-signature-field");
        if (!element) return { page: 1, x: 0.5, y: 0.74, width: 0.38, height: 0.1 };
        try {
            return JSON.parse(element.textContent);
        } catch (error) {
            console.warn("No se pudo leer la ubicación de firma.", error);
            return null;
        }
    }

    const signatureFieldData = readSignatureField();

    function createRecipientPage(pageNumber, totalPages, width, height) {
        const pageElement = document.createElement("div");
        const canvas = document.createElement("canvas");
        const label = document.createElement("span");
        pageElement.className = "recipient-document-page";
        pageElement.dataset.page = String(pageNumber);
        pageElement.style.width = `${width}px`;
        pageElement.style.height = `${height}px`;
        canvas.className = "recipient-pdf-canvas";
        canvas.setAttribute("role", "img");
        canvas.setAttribute("aria-label", `Página ${pageNumber} de ${totalPages}`);
        label.className = "recipient-page-number";
        label.textContent = `Página ${pageNumber}`;
        pageElement.append(canvas, label);
        recipientPages.append(pageElement);
        return { pageElement, canvas };
    }

    function placeSignatureField() {
        const signatureField = fields.find((field) => field.dataset.completable === "signature");
        if (!signatureField || !signatureFieldData) return;
        const targetPage = recipientPages?.querySelector(`[data-page="${signatureFieldData.page}"]`);
        if (!targetPage) return;
        signatureField.style.left = `${signatureFieldData.x * 100}%`;
        signatureField.style.top = `${signatureFieldData.y * 100}%`;
        signatureField.style.width = `${signatureFieldData.width * 100}%`;
        signatureField.style.height = `${signatureFieldData.height * 100}%`;
        signatureField.style.right = "auto";
        signatureField.style.bottom = "auto";
        signatureField.hidden = false;
        targetPage.append(signatureField);
    }

    function focusAssignedPage() {
        if (assignedPageFocused || !signatureFieldData) return;
        const targetPage = recipientPages?.querySelector(`[data-page="${signatureFieldData.page}"]`);
        if (!targetPage) return;
        assignedPageFocused = true;
        targetPage.scrollIntoView({ block: "center" });
    }

    function drawMockDocument() {
        if (!recipientPages) return;
        recipientPages.replaceChildren();
        const availableWidth = Math.max(1, Math.min(720, recipientPages.clientWidth || 720));
        const pageHeight = availableWidth * (932 / 720);
        const { canvas } = createRecipientPage(1, 1, availableWidth, pageHeight);
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = availableWidth * ratio;
        canvas.height = pageHeight * ratio;
        const context = canvas.getContext("2d");
        context.scale(ratio, ratio);
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, availableWidth, pageHeight);
        const documentScale = availableWidth / 720;
        context.scale(documentScale, documentScale);
        context.fillStyle = "#101828";
        context.font = "700 22px Arial";
        context.fillText("CONTRATO DE SERVICIOS", 86, 100);
        context.fillStyle = "#667085";
        context.font = "12px Arial";
        context.fillText("Entre ADICLA y la persona firmante", 86, 128);
        context.fillStyle = "#d0d5dd";
        for (let line = 0; line < 16; line += 1) {
            const width = line % 4 === 3 ? 390 : 548;
            context.fillRect(86, 180 + line * 34, width, 3);
        }
        context.fillStyle = "#344054";
        context.font = "700 13px Arial";
        context.fillText("Aceptación y firma", 86, 710);
        context.strokeStyle = "#d0d5dd";
        context.strokeRect(72, 70, 576, 792);
        recipientPages.setAttribute("aria-busy", "false");
        placeSignatureField();
        focusAssignedPage();
    }

    async function renderRecipientDocument() {
        if (!recipientPages || !window.pdfjsLib) return drawMockDocument();
        try {
            const pdfUrl = recipientViewer?.dataset.pdfUrl;
            if (!pdfUrl) return drawMockDocument();
            window.pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
            if (!recipientPdf) recipientPdf = await window.pdfjsLib.getDocument(pdfUrl).promise;
            const currentVersion = ++recipientRenderVersion;
            const availableWidth = Math.max(1, Math.min(720, recipientPages.clientWidth || 720));
            const ratio = Math.min(window.devicePixelRatio || 1, 2);
            recipientRenderedWidth = availableWidth;
            recipientPages.replaceChildren();
            recipientPages.setAttribute("aria-busy", "true");

            for (let pageNumber = 1; pageNumber <= recipientPdf.numPages; pageNumber += 1) {
                const page = await recipientPdf.getPage(pageNumber);
                if (currentVersion !== recipientRenderVersion) return;
                const baseViewport = page.getViewport({ scale: 1 });
                const scale = availableWidth / baseViewport.width;
                const viewport = page.getViewport({ scale });
                const renderViewport = page.getViewport({ scale: scale * ratio });
                const { canvas } = createRecipientPage(
                    pageNumber,
                    recipientPdf.numPages,
                    viewport.width,
                    viewport.height,
                );
                canvas.width = Math.floor(renderViewport.width);
                canvas.height = Math.floor(renderViewport.height);
                await page.render({ canvasContext: canvas.getContext("2d"), viewport: renderViewport }).promise;
            }

            if (currentVersion !== recipientRenderVersion) return;
            recipientPages.setAttribute("aria-busy", "false");
            if (recipientPageStatus) recipientPageStatus.textContent = `${recipientPdf.numPages} páginas`;
            placeSignatureField();
            focusAssignedPage();
        } catch (error) {
            console.warn("No se pudo mostrar el PDF; se utilizará la vista de demostración.", error);
            drawMockDocument();
        }
    }

    function scheduleRecipientResize() {
        if (!recipientPdf || !recipientPages) return;
        window.clearTimeout(recipientResizeTimer);
        recipientResizeTimer = window.setTimeout(() => {
            const availableWidth = Math.max(1, Math.min(720, recipientPages.clientWidth || 720));
            if (Math.abs(availableWidth - recipientRenderedWidth) <= 8) return;
            renderRecipientDocument();
        }, 180);
    }

    function updateProgress() {
        const completed = fields.filter((field) => field.classList.contains("field-complete")).length;
        if (progressCount) progressCount.textContent = `${completed} de ${fields.length}`;
        if (progressBar) progressBar.style.width = `${fields.length ? (completed / fields.length) * 100 : 0}%`;
        fields.forEach((field) => {
            const guide = document.querySelector(`[data-guide-step="${field.dataset.completable}"]`);
            guide?.classList.toggle("field-complete", field.classList.contains("field-complete"));
        });
        if (consentPanel) consentPanel.hidden = completed !== fields.length;
        if (completed === fields.length) consentCheckbox?.focus({ preventScroll: true });
    }

    function completeSimpleField(field) {
        const type = field.dataset.completable;
        if (type === "name") field.querySelector("[data-field-value]").textContent = "José Ramírez";
        if (type === "date") field.querySelector("[data-field-value]").textContent = "3 sep 2026";
        field.classList.toggle("field-complete", type === "checkbox" ? !field.classList.contains("field-complete") : true);
        updateProgress();
    }

    function configureSignatureCanvas() {
        if (!signatureCanvas) return;
        const rect = signatureCanvas.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        signatureCanvas.width = Math.max(1, rect.width * ratio);
        signatureCanvas.height = Math.max(1, rect.height * ratio);
        signatureContext = signatureCanvas.getContext("2d");
        signatureContext.scale(ratio, ratio);
        signatureContext.lineWidth = 2.3;
        signatureContext.lineCap = "round";
        signatureContext.lineJoin = "round";
        signatureContext.strokeStyle = "#08246f";
        hasSignatureStroke = false;
    }

    function signaturePoint(event) {
        const rect = signatureCanvas.getBoundingClientRect();
        return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    }

    function selectSignatureMethod(method) {
        signatureTabs.forEach((tab) => {
            const selected = tab.dataset.signatureTab === method;
            tab.classList.toggle("signature-tab--active", selected);
            tab.setAttribute("aria-selected", String(selected));
        });
        document.querySelectorAll("[data-signature-panel]").forEach((panel) => {
            panel.hidden = panel.dataset.signaturePanel !== method;
        });
        if (signatureError) signatureError.textContent = "";
        if (method === "DIBUJADA") window.requestAnimationFrame(configureSignatureCanvas);
    }

    function applySignature(source, method, alt) {
        const signatureField = document.querySelector('[data-completable="signature"]');
        const image = document.createElement("img");
        image.src = source;
        image.alt = alt;
        if (signatureMethod) signatureMethod.value = method;
        if (signatureInput) signatureInput.value = method === "DIBUJADA" ? source : "";
        if (consentCheckbox) consentCheckbox.checked = false;
        if (finalizeButton) finalizeButton.disabled = true;
        if (nextHelp) nextHelp.textContent = method === "PERFIL" ? "Firma guardada seleccionada. Confirma tu aceptación." : "Firma dibujada preparada. Confirma tu aceptación.";
        signatureField.querySelector("[data-field-value], img")?.replaceWith(image);
        signatureField.classList.add("field-complete");
        signatureDialog.close();
        updateProgress();
    }

    signatureTabs.forEach((tab) => {
        tab.addEventListener("click", () => selectSignatureMethod(tab.dataset.signatureTab));
    });

    fields.forEach((field) => {
        field.addEventListener("click", () => {
            if (field.dataset.completable === "signature") {
                signatureDialog?.showModal();
                const selected = document.querySelector("[data-signature-tab].signature-tab--active");
                if (selected?.dataset.signatureTab === "DIBUJADA") window.requestAnimationFrame(configureSignatureCanvas);
                return;
            }
            completeSimpleField(field);
        });
    });

    document.querySelector("[data-next-field]")?.addEventListener("click", () => {
        const nextField = fields.find((field) => !field.classList.contains("field-complete"));
        if (nextField) {
            nextField.scrollIntoView({ behavior: "smooth", block: "center" });
            nextField.focus({ preventScroll: true });
        } else {
            consentPanel?.querySelector("input")?.focus();
        }
    });

    signatureCanvas?.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        if (!signatureContext) configureSignatureCanvas();
        drawing = true;
        signatureCanvas.setPointerCapture(event.pointerId);
        const point = signaturePoint(event);
        signatureContext.beginPath();
        signatureContext.moveTo(point.x, point.y);
    });
    signatureCanvas?.addEventListener("pointermove", (event) => {
        if (!drawing) return;
        event.preventDefault();
        const point = signaturePoint(event);
        signatureContext.lineTo(point.x, point.y);
        signatureContext.stroke();
        hasSignatureStroke = true;
    });
    const stopDrawing = () => { drawing = false; };
    signatureCanvas?.addEventListener("pointerup", stopDrawing);
    signatureCanvas?.addEventListener("pointercancel", stopDrawing);

    document.querySelector("[data-signature-clear]")?.addEventListener("click", configureSignatureCanvas);
    document.querySelectorAll("[data-signature-cancel]").forEach((button) => button.addEventListener("click", () => signatureDialog?.close()));
    document.querySelector("[data-signature-use]")?.addEventListener("click", () => {
        if (!hasSignatureStroke) {
            signatureError.textContent = "Dibuja tu firma antes de continuar.";
            return;
        }
        applySignature(signatureCanvas.toDataURL("image/png"), "DIBUJADA", "Firma dibujada");
    });
    document.querySelector("[data-saved-signature-use]")?.addEventListener("click", (event) => {
        applySignature(event.currentTarget.dataset.savedSignatureUrl, "PERFIL", "Firma guardada");
    });

    consentCheckbox?.addEventListener("change", () => { finalizeButton.disabled = !consentCheckbox.checked; });
    const rejectDialog = document.querySelector("[data-reject-dialog]");
    document.querySelectorAll("[data-reject-open]").forEach((button) => button.addEventListener("click", () => rejectDialog?.showModal()));
    document.querySelector("[data-reject-close]")?.addEventListener("click", () => rejectDialog?.close());
    document.querySelectorAll("[data-completed-action]").forEach((button) => {
        button.addEventListener("click", () => {
            const feedback = document.querySelector("[data-completed-feedback]");
            if (feedback) feedback.textContent = button.dataset.completedAction;
        });
    });

    const completedSigner = document.querySelector("[data-completed-signer]");
    if (completedSigner) {
        try {
            const savedRecipient = JSON.parse(localStorage.getItem("adicla-sign-recipient"));
            if (savedRecipient?.name && (!savedRecipient.mode || savedRecipient.mode === "single")) {
                completedSigner.textContent = savedRecipient.name;
            }
        } catch (error) {
            console.warn("No se pudo leer el firmante temporal.", error);
        }
    }

    renderRecipientDocument();
    window.addEventListener("resize", scheduleRecipientResize);
    updateProgress();
})();
