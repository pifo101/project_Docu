const databaseName = "adicla-sign-editor";
const storeName = "temporary-documents";
const documentKey = "current-pdf";
const pdfDocumentElement = document.querySelector("[data-pdf-document]");
const viewerState = document.querySelector("[data-viewer-state]");
const documentName = document.querySelector("[data-document-name]");
const documentStatus = document.querySelector("[data-document-status]");
const viewer = document.querySelector(".pdf-viewer");
const signatureTool = document.querySelector('[data-field-type="signature"]');
const continueButton = document.querySelector("[data-editor-continue]");
const documentFields = [];
const defaultFieldWidth = 180;
const defaultFieldHeight = 58;
const minimumFieldWidth = 120;
const minimumFieldHeight = 44;
let loadedPdf = null;
let pdfObjectUrl = null;
let renderVersion = 0;
let renderedWidth = 0;
let resizeTimer = null;
let selectedField = null;
let activeInteraction = null;
let autoScrollFrame = null;

function clamp(value, minimum, maximum) {
    return Math.min(Math.max(value, minimum), maximum);
}

function roundNormalized(value) {
    return Number(clamp(value, 0, 1).toFixed(6));
}

function createFieldId() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return `signature-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getNormalizedFieldData(fieldElement) {
    const layer = fieldElement.closest(".field-layer");
    const layerWidth = layer.clientWidth;
    const layerHeight = layer.clientHeight;
    const x = roundNormalized(parseFloat(fieldElement.style.left) / layerWidth);
    const y = roundNormalized(parseFloat(fieldElement.style.top) / layerHeight);
    const width = parseFloat(fieldElement.style.width) / layerWidth;
    const height = parseFloat(fieldElement.style.height) / layerHeight;

    return {
        id: fieldElement.dataset.id,
        type: fieldElement.dataset.type,
        page: Number(layer.dataset.page),
        x,
        y,
        width: roundNormalized(Math.min(width, 1 - x)),
        height: roundNormalized(Math.min(height, 1 - y)),
    };
}

function updateFieldState(fieldElement) {
    const normalizedField = getNormalizedFieldData(fieldElement);
    const fieldIndex = documentFields.findIndex((field) => field.id === normalizedField.id);

    if (fieldIndex >= 0) documentFields[fieldIndex] = normalizedField;
    return normalizedField;
}

function setFieldPixels(fieldElement, left, top, width, height) {
    fieldElement.style.left = `${left}px`;
    fieldElement.style.top = `${top}px`;
    fieldElement.style.width = `${width}px`;
    fieldElement.style.height = `${height}px`;
}

function setSelectedField(fieldElement) {
    selectedField?.classList.remove("document-field--selected");
    selectedField?.setAttribute("aria-selected", "false");
    selectedField = fieldElement;
    selectedField?.classList.add("document-field--selected");
    selectedField?.setAttribute("aria-selected", "true");
}

function removeField(fieldElement) {
    if (!fieldElement) return;

    if (activeInteraction?.fieldElement === fieldElement) cancelActiveInteraction();
    const fieldIndex = documentFields.findIndex((field) => field.id === fieldElement.dataset.id);
    if (fieldIndex >= 0) documentFields.splice(fieldIndex, 1);
    if (selectedField === fieldElement) selectedField = null;
    fieldElement.remove();
}

function signatureFieldMarkup() {
    return `
        <span class="document-field__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M4 19c4-6 6-9 8-9 1 0 0 5 2 5 1 0 2-3 3-3s0 3 3 3M4 20h16"/></svg>
        </span>
        <span class="document-field__label"><strong>Firma</strong><small>Campo de firma</small></span>
        <button class="document-field__delete" type="button" aria-label="Eliminar campo de firma">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M9 7V4h6v3M8 7l1 13h6l1-13M11 11v5M14 11v5"/></svg>
        </button>
        <button class="field-resize-handle" type="button" aria-label="Redimensionar campo de firma"></button>
    `;
}

function createFieldElement(fieldData, layer) {
    const fieldElement = document.createElement("div");
    const layerWidth = layer.clientWidth;
    const layerHeight = layer.clientHeight;

    fieldElement.className = "document-field signature-field";
    fieldElement.dataset.id = fieldData.id;
    fieldElement.dataset.type = fieldData.type;
    fieldElement.tabIndex = 0;
    fieldElement.setAttribute("role", "group");
    fieldElement.setAttribute("aria-label", `Firma en página ${fieldData.page}`);
    fieldElement.setAttribute("aria-selected", "false");
    fieldElement.innerHTML = signatureFieldMarkup();
    setFieldPixels(
        fieldElement,
        fieldData.x * layerWidth,
        fieldData.y * layerHeight,
        fieldData.width * layerWidth,
        fieldData.height * layerHeight,
    );
    fieldElement.addEventListener("pointerdown", startFieldInteraction);
    fieldElement.addEventListener("focus", () => setSelectedField(fieldElement));
    fieldElement.querySelector(".document-field__delete").addEventListener("click", () => removeField(fieldElement));
    return fieldElement;
}

function renderFieldsForLayer(layer) {
    const pageNumber = Number(layer.dataset.page);
    documentFields
        .filter((field) => field.page === pageNumber)
        .forEach((field) => layer.append(createFieldElement(field, layer)));
}

function createSignatureField(layer, clientX, clientY) {
    const layerRect = layer.getBoundingClientRect();
    const width = Math.min(defaultFieldWidth, layerRect.width);
    const height = Math.min(defaultFieldHeight, layerRect.height);
    const left = clamp(clientX - layerRect.left - width / 2, 0, layerRect.width - width);
    const top = clamp(clientY - layerRect.top - height / 2, 0, layerRect.height - height);
    const fieldData = {
        id: createFieldId(),
        type: "signature",
        page: Number(layer.dataset.page),
        x: 0,
        y: 0,
        width: 0,
        height: 0,
    };
    const fieldElement = createFieldElement(fieldData, layer);

    layer.append(fieldElement);
    setFieldPixels(fieldElement, left, top, width, height);
    documentFields.push(getNormalizedFieldData(fieldElement));
    setSelectedField(fieldElement);
    fieldElement.focus({ preventScroll: true });
}

function getFieldPixels(fieldElement) {
    return {
        left: parseFloat(fieldElement.style.left),
        top: parseFloat(fieldElement.style.top),
        width: parseFloat(fieldElement.style.width),
        height: parseFloat(fieldElement.style.height),
    };
}

function startFieldInteraction(event) {
    const fieldElement = event.currentTarget;
    if (activeInteraction || !event.isPrimary || event.button !== 0 || event.target.closest(".document-field__delete")) {
        return;
    }

    event.preventDefault();
    setSelectedField(fieldElement);
    fieldElement.focus({ preventScroll: true });
    fieldElement.setPointerCapture(event.pointerId);
    activeInteraction = {
        mode: event.target.closest(".field-resize-handle") ? "resize" : "move",
        pointerId: event.pointerId,
        fieldElement,
        layer: fieldElement.closest(".field-layer"),
        startX: event.clientX,
        startY: event.clientY,
        initial: getFieldPixels(fieldElement),
    };
    fieldElement.classList.add(activeInteraction.mode === "resize" ? "document-field--resizing" : "document-field--moving");
}

function createDragPreview() {
    const preview = document.createElement("div");
    preview.className = "field-drag-preview";
    preview.innerHTML = `
        <span class="field-drag-preview__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M4 19c4-6 6-9 8-9 1 0 0 5 2 5 1 0 2-3 3-3s0 3 3 3M4 20h16"/></svg>
        </span>
        <span class="field-drag-preview__label"><strong>Firma</strong><small>Suelta sobre una página</small></span>
    `;
    document.body.append(preview);
    return preview;
}

function findLayerAtPoint(clientX, clientY) {
    return document.elementFromPoint(clientX, clientY)?.closest(".field-layer") || null;
}

function startSignatureDrag(event) {
    if (activeInteraction || !event.isPrimary || event.button !== 0 || !loadedPdf || pdfDocumentElement.hidden) return;

    event.preventDefault();
    setSelectedField(null);
    signatureTool.setPointerCapture(event.pointerId);
    signatureTool.classList.add("field-tool--dragging");
    activeInteraction = {
        mode: "create",
        pointerId: event.pointerId,
        preview: createDragPreview(),
        targetLayer: null,
    };
    moveSignaturePreview(event);
}

function moveSignaturePreview(event) {
    const interaction = activeInteraction;
    interaction.preview.style.left = `${event.clientX}px`;
    interaction.preview.style.top = `${event.clientY}px`;
    interaction.clientX = event.clientX;
    interaction.clientY = event.clientY;
    updateDropTarget(interaction);
    if (!autoScrollFrame) autoScrollFrame = window.requestAnimationFrame(autoScrollDuringDrag);
}

function updateDropTarget(interaction) {
    interaction.targetLayer?.classList.remove("field-layer--drop-target");
    interaction.targetLayer = findLayerAtPoint(interaction.clientX, interaction.clientY);
    interaction.targetLayer?.classList.add("field-layer--drop-target");
    interaction.preview.classList.toggle("field-drag-preview--valid", Boolean(interaction.targetLayer));
}

function autoScrollDuringDrag() {
    autoScrollFrame = null;
    if (!activeInteraction || activeInteraction.mode !== "create") return;

    const interaction = activeInteraction;
    const viewerRect = viewer.getBoundingClientRect();
    const visibleTop = Math.max(0, viewerRect.top);
    const visibleBottom = Math.min(window.innerHeight, viewerRect.bottom);
    const edgeSize = 70;
    const isOverViewer = interaction.clientX >= viewerRect.left && interaction.clientX <= viewerRect.right;
    let scrollAmount = 0;

    if (isOverViewer && interaction.clientY >= visibleTop && interaction.clientY < visibleTop + edgeSize) {
        scrollAmount = -12 * (1 - (interaction.clientY - visibleTop) / edgeSize);
    } else if (
        isOverViewer
        && interaction.clientY <= visibleBottom
        && interaction.clientY > visibleBottom - edgeSize
    ) {
        scrollAmount = 12 * (1 - (visibleBottom - interaction.clientY) / edgeSize);
    }

    if (scrollAmount !== 0) {
        if (viewer.scrollHeight > viewer.clientHeight + 1) {
            viewer.scrollTop += scrollAmount;
        } else {
            window.scrollBy(0, scrollAmount);
        }
        updateDropTarget(interaction);
        autoScrollFrame = window.requestAnimationFrame(autoScrollDuringDrag);
    }
}

function stopAutoScroll() {
    if (autoScrollFrame) window.cancelAnimationFrame(autoScrollFrame);
    autoScrollFrame = null;
}

function movePlacedField(event) {
    const { fieldElement, layer, initial, startX, startY } = activeInteraction;
    const left = clamp(initial.left + event.clientX - startX, 0, layer.clientWidth - initial.width);
    const top = clamp(initial.top + event.clientY - startY, 0, layer.clientHeight - initial.height);

    setFieldPixels(fieldElement, left, top, initial.width, initial.height);
    updateFieldState(fieldElement);
}

function resizePlacedField(event) {
    const { fieldElement, layer, initial, startX, startY } = activeInteraction;
    const maximumWidth = layer.clientWidth - initial.left;
    const maximumHeight = layer.clientHeight - initial.top;
    const minimumWidth = Math.min(initial.width, minimumFieldWidth, maximumWidth);
    const minimumHeight = Math.min(initial.height, minimumFieldHeight, maximumHeight);
    const width = clamp(initial.width + event.clientX - startX, minimumWidth, maximumWidth);
    const height = clamp(initial.height + event.clientY - startY, minimumHeight, maximumHeight);

    setFieldPixels(fieldElement, initial.left, initial.top, width, height);
    updateFieldState(fieldElement);
}

function handlePointerMove(event) {
    if (!activeInteraction || event.pointerId !== activeInteraction.pointerId) return;
    event.preventDefault();

    if (activeInteraction.mode === "create") moveSignaturePreview(event);
    if (activeInteraction.mode === "move") movePlacedField(event);
    if (activeInteraction.mode === "resize") resizePlacedField(event);
}

function finishInteraction(event) {
    if (!activeInteraction || event.pointerId !== activeInteraction.pointerId) return;

    const interaction = activeInteraction;
    activeInteraction = null;
    stopAutoScroll();

    if (interaction.mode === "create") {
        interaction.targetLayer?.classList.remove("field-layer--drop-target");
        interaction.preview.remove();
        signatureTool.classList.remove("field-tool--dragging");
        const dropLayer = findLayerAtPoint(event.clientX, event.clientY);
        if (dropLayer && event.type === "pointerup") {
            createSignatureField(dropLayer, event.clientX, event.clientY);
        }
        return;
    }

    if (event.type === "pointercancel") {
        const { left, top, width, height } = interaction.initial;
        setFieldPixels(interaction.fieldElement, left, top, width, height);
    }
    interaction.fieldElement.classList.remove("document-field--moving", "document-field--resizing");
    updateFieldState(interaction.fieldElement);
}

function cancelActiveInteraction() {
    if (!activeInteraction) return;

    const interaction = activeInteraction;
    stopAutoScroll();
    activeInteraction.targetLayer?.classList.remove("field-layer--drop-target");
    activeInteraction.preview?.remove();
    activeInteraction.fieldElement?.classList.remove("document-field--moving", "document-field--resizing");
    if (interaction.fieldElement?.hasPointerCapture(interaction.pointerId)) {
        interaction.fieldElement.releasePointerCapture(interaction.pointerId);
    }
    if (interaction.mode === "create" && signatureTool?.hasPointerCapture(interaction.pointerId)) {
        signatureTool.releasePointerCapture(interaction.pointerId);
    }
    signatureTool?.classList.remove("field-tool--dragging");
    activeInteraction = null;
}

function showState(message, type = "loading") {
    viewerState.classList.toggle("viewer-state--error", type === "error");
    viewerState.classList.toggle("viewer-state--empty", type === "empty");
    viewerState.querySelector("strong").textContent = message;
    viewerState.hidden = false;
}

function takeTemporaryPdf() {
    return new Promise((resolve, reject) => {
        const openRequest = indexedDB.open(databaseName, 1);

        openRequest.addEventListener("upgradeneeded", () => {
            if (!openRequest.result.objectStoreNames.contains(storeName)) {
                openRequest.result.createObjectStore(storeName);
            }
        });
        openRequest.addEventListener("error", () => reject(openRequest.error));
        openRequest.addEventListener("success", () => {
            const database = openRequest.result;
            const transaction = database.transaction(storeName, "readwrite");
            const store = transaction.objectStore(storeName);
            const getRequest = store.get(documentKey);
            let storedDocument = null;

            getRequest.addEventListener("success", () => {
                storedDocument = getRequest.result;
                if (storedDocument) store.delete(documentKey);
            });
            transaction.addEventListener("complete", () => {
                database.close();
                resolve(storedDocument);
            });
            transaction.addEventListener("error", () => {
                database.close();
                reject(transaction.error);
            });
            transaction.addEventListener("abort", () => {
                database.close();
                reject(transaction.error);
            });
        });
    });
}

async function renderPages() {
    if (!loadedPdf) return;

    cancelActiveInteraction();
    setSelectedField(null);
    signatureTool.disabled = true;
    continueButton.disabled = true;
    const currentVersion = ++renderVersion;
    const availableWidth = Math.max(240, pdfDocumentElement.clientWidth);
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);

    renderedWidth = availableWidth;
    pdfDocumentElement.replaceChildren();

    for (let pageNumber = 1; pageNumber <= loadedPdf.numPages; pageNumber += 1) {
        const page = await loadedPdf.getPage(pageNumber);
        if (currentVersion !== renderVersion) return;

        const originalViewport = page.getViewport({ scale: 1 });
        const scale = Math.min(1.35, availableWidth / originalViewport.width);
        const viewport = page.getViewport({ scale });
        const renderViewport = page.getViewport({ scale: scale * pixelRatio });
        const pageElement = document.createElement("div");
        const canvas = document.createElement("canvas");
        const fieldLayer = document.createElement("div");

        pageElement.className = "pdf-page";
        pageElement.dataset.page = String(pageNumber);
        pageElement.style.width = `${viewport.width}px`;
        pageElement.style.height = `${viewport.height}px`;

        canvas.className = "pdf-canvas";
        canvas.width = Math.floor(renderViewport.width);
        canvas.height = Math.floor(renderViewport.height);
        canvas.setAttribute("role", "img");
        canvas.setAttribute("aria-label", `Página ${pageNumber} de ${loadedPdf.numPages}`);

        fieldLayer.className = "field-layer";
        fieldLayer.dataset.page = String(pageNumber);
        fieldLayer.setAttribute("aria-label", `Campos de la página ${pageNumber}`);

        pageElement.append(canvas, fieldLayer);
        pdfDocumentElement.append(pageElement);
        renderFieldsForLayer(fieldLayer);

        await page.render({
            canvasContext: canvas.getContext("2d"),
            viewport: renderViewport,
        }).promise;
    }

    if (currentVersion !== renderVersion) return;
    viewerState.hidden = true;
    documentStatus.textContent = "Documento listo";
    signatureTool.disabled = false;
    continueButton.disabled = false;
}

async function prepareEditor() {
    showState("Preparando documento...");

    try {
        const storedDocument = await takeTemporaryPdf();
        if (!storedDocument?.file) {
            documentStatus.textContent = "Sin documento";
            showState("No hay un documento seleccionado.", "empty");
            return;
        }

        documentName.textContent = storedDocument.name || storedDocument.file.name || "Documento PDF";
        pdfObjectUrl = URL.createObjectURL(storedDocument.file);
        window.pdfjsLib.GlobalWorkerOptions.workerSrc =
            "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
        loadedPdf = await window.pdfjsLib.getDocument(pdfObjectUrl).promise;
        pdfDocumentElement.hidden = false;
        await renderPages();
    } catch (error) {
        console.error("No se pudo cargar el documento PDF.", error);
        pdfDocumentElement.hidden = true;
        documentStatus.textContent = "Error al preparar";
        showState("No se pudo cargar el documento.", "error");
    }
}

function scheduleResize() {
    if (!loadedPdf || pdfDocumentElement.hidden) return;

    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
        if (Math.abs(pdfDocumentElement.clientWidth - renderedWidth) > 8) {
            showState("Preparando documento...");
            renderPages().catch((error) => {
                console.error("No se pudo ajustar el documento PDF.", error);
                showState("No se pudo cargar el documento.", "error");
            });
        }
    }, 180);
}

signatureTool?.addEventListener("pointerdown", startSignatureDrag);
document.addEventListener("pointermove", handlePointerMove);
document.addEventListener("pointerup", finishInteraction);
document.addEventListener("pointercancel", finishInteraction);
document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest(".document-field")) setSelectedField(null);
});
document.addEventListener("keydown", (event) => {
    const target = event.target;
    const isEditing = target instanceof HTMLElement
        && (target.matches("input, textarea, [contenteditable='true']") || target.isContentEditable);

    if (selectedField && !isEditing && (event.key === "Delete" || event.key === "Backspace")) {
        event.preventDefault();
        removeField(selectedField);
    }
});
continueButton?.addEventListener("click", () => {
    const normalizedFields = documentFields.map((field) => ({ ...field }));
    console.log("Campos normalizados:", normalizedFields);
    console.table(normalizedFields);
});

if (viewer && "ResizeObserver" in window) {
    const resizeObserver = new ResizeObserver(scheduleResize);
    resizeObserver.observe(viewer);
} else {
    window.addEventListener("resize", scheduleResize);
}

window.addEventListener("beforeunload", () => {
    if (pdfObjectUrl) URL.revokeObjectURL(pdfObjectUrl);
});

if (!window.indexedDB || !window.pdfjsLib) {
    documentStatus.textContent = "Error al preparar";
    showState("No se pudo cargar el documento.", "error");
} else {
    prepareEditor();
}
