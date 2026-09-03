(() => {
    const documentCanvas = document.querySelector("[data-recipient-pdf]");
    const fields = Array.from(document.querySelectorAll("[data-completable]"));
    const progressCount = document.querySelector("[data-progress-count]");
    const progressBar = document.querySelector("[data-progress-bar]");
    const consentPanel = document.querySelector("[data-consent-panel]");
    const consentCheckbox = document.querySelector("[data-consent-checkbox]");
    const finalizeButton = document.querySelector("[data-finalize]");
    const signatureDialog = document.querySelector("[data-signature-dialog]");
    const signatureCanvas = document.querySelector("[data-signature-canvas]");
    const signatureError = document.querySelector("[data-signature-error]");
    let signatureContext = null;
    let drawing = false;
    let hasSignatureStroke = false;

    function drawMockDocument() {
        if (!documentCanvas) return;
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        documentCanvas.width = 720 * ratio;
        documentCanvas.height = 932 * ratio;
        const context = documentCanvas.getContext("2d");
        context.scale(ratio, ratio);
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, 720, 932);
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
    }

    function readTemporaryPdf() {
        return new Promise((resolve) => {
            if (!window.indexedDB) return resolve(null);
            const request = indexedDB.open("adicla-sign-editor", 1);
            request.addEventListener("upgradeneeded", () => {
                if (!request.result.objectStoreNames.contains("temporary-documents")) request.result.createObjectStore("temporary-documents");
            });
            request.addEventListener("error", () => resolve(null));
            request.addEventListener("success", () => {
                const database = request.result;
                const transaction = database.transaction("temporary-documents", "readonly");
                const getRequest = transaction.objectStore("temporary-documents").get("current-pdf");
                getRequest.addEventListener("success", () => resolve(getRequest.result?.file || null));
                getRequest.addEventListener("error", () => resolve(null));
                transaction.addEventListener("complete", () => database.close());
            });
        });
    }

    async function renderRecipientDocument() {
        if (!documentCanvas || !window.pdfjsLib) return drawMockDocument();
        try {
            const file = await readTemporaryPdf();
            if (!file) return drawMockDocument();
            window.pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
            const pdf = await window.pdfjsLib.getDocument(await file.arrayBuffer()).promise;
            const page = await pdf.getPage(1);
            const baseViewport = page.getViewport({ scale: 1 });
            const scale = 720 / baseViewport.width;
            const viewport = page.getViewport({ scale });
            const ratio = Math.min(window.devicePixelRatio || 1, 2);
            documentCanvas.width = viewport.width * ratio;
            documentCanvas.height = viewport.height * ratio;
            documentCanvas.parentElement.style.aspectRatio = `${viewport.width} / ${viewport.height}`;
            await page.render({ canvasContext: documentCanvas.getContext("2d"), viewport: page.getViewport({ scale: scale * ratio }) }).promise;
        } catch (error) {
            console.warn("No se pudo mostrar el PDF temporal; se utilizará la vista de demostración.", error);
            drawMockDocument();
        }
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
        if (completed === fields.length) consentPanel?.querySelector("input")?.focus({ preventScroll: true });
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

    fields.forEach((field) => {
        field.addEventListener("click", () => {
            if (field.dataset.completable === "signature") {
                signatureDialog?.showModal();
                window.requestAnimationFrame(configureSignatureCanvas);
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
        const signatureField = document.querySelector('[data-completable="signature"]');
        const image = document.createElement("img");
        image.src = signatureCanvas.toDataURL("image/png");
        image.alt = "Firma dibujada";
        signatureField.querySelector("[data-field-value], img")?.replaceWith(image);
        signatureField.classList.add("field-complete");
        signatureDialog.close();
        updateProgress();
    });

    consentCheckbox?.addEventListener("change", () => { finalizeButton.disabled = !consentCheckbox.checked; });
    finalizeButton?.addEventListener("click", () => {
        if (consentCheckbox.checked) window.location.assign(finalizeButton.dataset.finalizeUrl);
    });

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
            if (savedRecipient?.name) completedSigner.textContent = savedRecipient.name;
        } catch (error) {
            console.warn("No se pudo leer el firmante temporal.", error);
        }
    }

    renderRecipientDocument();
    updateProgress();
})();
