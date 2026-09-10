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
    const nextFieldButton = document.querySelector("[data-next-field]");
    const readonly = recipientViewer?.dataset.readonly === "true";
    const protectedViewer = recipientViewer?.dataset.protected === "true";
    let signatureContext = null;
    let drawing = false;
    let hasSignatureStroke = false;
    let recipientPdf = null;
    let recipientRenderVersion = 0;
    let recipientRenderedWidth = 0;
    let recipientResizeTimer = null;
    let assignedPageFocused = false;

    function readSignatureFields() {
        const element = document.getElementById("recipient-signature-fields");
        if (!element) return [{ page: 1, x: 0.5, y: 0.74, width: 0.38, height: 0.1 }];
        try {
            const parsed = JSON.parse(element.textContent);
            return Array.isArray(parsed) ? parsed : [];
        } catch (error) {
            console.warn("No se pudieron leer las ubicaciones de firma.", error);
            return [];
        }
    }

    const signatureFieldsData = readSignatureFields();

    function createRecipientPage(pageNumber, totalPages, width, height) {
        const pageElement = document.createElement("div");
        const canvas = document.createElement("canvas");
        const label = document.createElement("span");
        pageElement.className = "recipient-document-page";
        pageElement.dataset.page = String(pageNumber);
        pageElement.style.width = `${width}px`;
        pageElement.style.height = `${height}px`;
        canvas.className = "recipient-pdf-canvas";
        canvas.draggable = false;
        canvas.setAttribute("role", "img");
        canvas.setAttribute("aria-label", `Página ${pageNumber} de ${totalPages}`);
        label.className = "recipient-page-number";
        label.textContent = `Página ${pageNumber}`;
        pageElement.append(canvas, label);
        recipientPages.append(pageElement);
        return { pageElement, canvas };
    }

    function placeSignatureFields() {
        fields.filter((field) => field.dataset.completable === "signature").forEach((field, index) => {
            const fieldData = signatureFieldsData[index];
            if (!fieldData) return;
            const targetPage = recipientPages?.querySelector(`[data-page="${fieldData.page}"]`);
            if (!targetPage) return;
            field.style.left = `${fieldData.x * 100}%`;
            field.style.top = `${fieldData.y * 100}%`;
            field.style.width = `${fieldData.width * 100}%`;
            field.style.height = `${fieldData.height * 100}%`;
            field.style.right = "auto";
            field.style.bottom = "auto";
            field.hidden = false;
            targetPage.append(field);
        });
    }

    function focusAssignedPage() {
        const firstField = signatureFieldsData[0];
        if (assignedPageFocused || !firstField) return;
        const targetPage = recipientPages?.querySelector(`[data-page="${firstField.page}"]`);
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
        placeSignatureFields();
        focusAssignedPage();
        if (nextFieldButton && !readonly) nextFieldButton.disabled = false;
        if (nextHelp) nextHelp.textContent = "Dibuja tu firma para continuar.";
    }

    function showDocumentError() {
        if (!recipientPages) return;
        const message = document.createElement("div");
        message.className = "recipient-document-error";
        message.setAttribute("role", "alert");
        message.innerHTML = "<strong>No se pudo mostrar el PDF.</strong><span>Recarga la página antes de firmar. No se utilizará contenido de demostración para un documento real.</span>";
        recipientPages.replaceChildren(message);
        recipientPages.setAttribute("aria-busy", "false");
        if (recipientPageStatus) recipientPageStatus.textContent = "PDF no disponible";
        if (nextHelp) nextHelp.textContent = "La firma está bloqueada hasta que el PDF pueda mostrarse.";
        if (nextFieldButton) nextFieldButton.disabled = true;
        fields.forEach((field) => { field.hidden = true; });
        if (consentPanel) consentPanel.hidden = true;
    }

    async function renderRecipientDocument() {
        if (!recipientPages) return;
        const demo = recipientViewer?.dataset.demo === "true";
        if (!window.pdfjsLib) return demo ? drawMockDocument() : showDocumentError();
        try {
            const pdfUrl = recipientViewer?.dataset.pdfUrl;
            if (!pdfUrl) return demo ? drawMockDocument() : showDocumentError();
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
            placeSignatureFields();
            focusAssignedPage();
            if (nextFieldButton && !readonly) nextFieldButton.disabled = false;
            if (nextHelp && !readonly) nextHelp.textContent = "Elige una firma guardada o dibuja una nueva.";
        } catch (error) {
            console.warn("No se pudo mostrar el PDF.", error);
            if (demo) drawMockDocument();
            else showDocumentError();
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
        if (type === "name") field.querySelector("[data-field-value]").textContent = "Nombre de demostración";
        if (type === "date") field.querySelector("[data-field-value]").textContent = "Fecha de demostración";
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
        if (signatureMethod) signatureMethod.value = method;
        if (signatureInput) signatureInput.value = method === "DIBUJADA" ? source : "";
        if (consentCheckbox) consentCheckbox.checked = false;
        if (finalizeButton) finalizeButton.disabled = true;
        if (nextHelp) nextHelp.textContent = method === "PERFIL" ? "Firma guardada seleccionada. Confirma tu aceptación." : "Firma dibujada preparada. Confirma tu aceptación.";
        fields.filter((field) => field.dataset.completable === "signature").forEach((field) => {
            const image = document.createElement("img");
            image.src = source;
            image.alt = alt;
            field.querySelector("[data-field-value], img")?.replaceWith(image);
            field.classList.add("field-complete");
        });
        signatureDialog.close();
        updateProgress();
    }

    signatureTabs.forEach((tab) => {
        tab.addEventListener("click", () => selectSignatureMethod(tab.dataset.signatureTab));
    });

    fields.forEach((field) => {
        field.addEventListener("click", () => {
            if (readonly) return;
            if (field.dataset.completable === "signature") {
                signatureDialog?.showModal();
                const selected = document.querySelector("[data-signature-tab].signature-tab--active");
                if (selected?.dataset.signatureTab === "DIBUJADA") window.requestAnimationFrame(configureSignatureCanvas);
                return;
            }
            completeSimpleField(field);
        });
    });

    nextFieldButton?.addEventListener("click", () => {
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

    if (protectedViewer) {
        recipientViewer.addEventListener("contextmenu", (event) => event.preventDefault());
        recipientViewer.addEventListener("copy", (event) => event.preventDefault());
        recipientViewer.addEventListener("dragstart", (event) => event.preventDefault());
        recipientViewer.addEventListener("pointerdown", (event) => {
            if (event.target.closest(".recipient-document-page, .recipient-pdf-canvas")) {
                recipientViewer.focus({ preventScroll: true });
            }
        });
        document.addEventListener("keydown", (event) => {
            const shortcut = (event.ctrlKey || event.metaKey) && ["s", "p"].includes(
                event.key.toLowerCase(),
            );
            if (shortcut) event.preventDefault();
        });
    }

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
