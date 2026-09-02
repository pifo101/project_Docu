const databaseName = "adicla-sign-editor";
const storeName = "temporary-documents";
const documentKey = "current-pdf";
const pdfDocumentElement = document.querySelector("[data-pdf-document]");
const viewerState = document.querySelector("[data-viewer-state]");
const documentName = document.querySelector("[data-document-name]");
const documentStatus = document.querySelector("[data-document-status]");
const viewer = document.querySelector(".pdf-viewer");
const fieldTools = [...document.querySelectorAll("[data-field-type]")];
const continueButton = document.querySelector("[data-editor-continue]");
const editorFeedback = document.querySelector("[data-editor-feedback]");
const propertiesEmpty = document.querySelector("[data-properties-empty]");
const propertiesContent = document.querySelector("[data-properties-content]");
const propertyType = document.querySelector("[data-property-type]");
const propertyRequired = document.querySelector("[data-property-required]");
const textProperty = document.querySelector("[data-text-property]");
const propertyLabel = document.querySelector("[data-property-label]");
const propertyDelete = document.querySelector("[data-property-delete]");
const documentFields = [];
const FIELD_TYPES = {
    signature: {
        label: "Firma",
        description: "Campo de firma",
        width: 180,
        height: 58,
        minWidth: 120,
        minHeight: 44,
        icon: '<svg viewBox="0 0 24 24"><path d="M4 19c4-6 6-9 8-9 1 0 0 5 2 5 1 0 2-3 3-3s0 3 3 3M4 20h16"/></svg>',
    },
    name: {
        label: "Nombre",
        description: "Campo de nombre",
        width: 170,
        height: 48,
        minWidth: 110,
        minHeight: 38,
        icon: '<span class="document-field__icon-letter">Aa</span>',
    },
    date: {
        label: "Fecha",
        description: "Campo de fecha",
        width: 145,
        height: 48,
        minWidth: 100,
        minHeight: 38,
        icon: '<svg viewBox="0 0 24 24"><path d="M5 4h14v16H5zM8 2v4M16 2v4M5 9h14M9 13h2M13 13h2"/></svg>',
    },
    text: {
        label: "Texto",
        description: "Campo de texto",
        width: 180,
        height: 48,
        minWidth: 110,
        minHeight: 38,
        defaultLabel: "Texto",
        icon: '<span class="document-field__icon-letter">T</span>',
    },
};
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

function createFieldId(type) {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return `${type}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getNormalizedFieldData(fieldElement) {
    const layer = fieldElement.closest(".field-layer");
    const layerWidth = layer.clientWidth;
    const layerHeight = layer.clientHeight;
    const x = roundNormalized(parseFloat(fieldElement.style.left) / layerWidth);
    const y = roundNormalized(parseFloat(fieldElement.style.top) / layerHeight);
    const width = parseFloat(fieldElement.style.width) / layerWidth;
    const height = parseFloat(fieldElement.style.height) / layerHeight;
    const existingField = documentFields.find((field) => field.id === fieldElement.dataset.id);
    const normalizedField = {
        id: fieldElement.dataset.id,
        type: fieldElement.dataset.type,
        page: Number(layer.dataset.page),
        x,
        y,
        width: roundNormalized(Math.min(width, 1 - x)),
        height: roundNormalized(Math.min(height, 1 - y)),
        required: existingField?.required ?? fieldElement.dataset.required !== "false",
    };

    if (normalizedField.type === "text") {
        normalizedField.label = existingField?.label ?? fieldElement.dataset.label ?? FIELD_TYPES.text.defaultLabel;
    }
    return normalizedField;
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

function normalizeTextLabel(fieldElement) {
    if (!fieldElement || fieldElement.dataset.type !== "text") return;

    const fieldData = documentFields.find((field) => field.id === fieldElement.dataset.id);
    if (!fieldData) return;

    fieldData.label = fieldData.label.trim() || FIELD_TYPES.text.defaultLabel;
    updateFieldPresentation(fieldElement, fieldData);
    if (selectedField === fieldElement) propertyLabel.value = fieldData.label;
}

function setSelectedField(fieldElement) {
    if (selectedField !== fieldElement) normalizeTextLabel(selectedField);
    selectedField?.classList.remove("document-field--selected");
    selectedField?.setAttribute("aria-selected", "false");
    selectedField = fieldElement;
    selectedField?.classList.add("document-field--selected");
    selectedField?.setAttribute("aria-selected", "true");
    updatePropertiesPanel();
}

function removeField(fieldElement) {
    if (!fieldElement) return;

    if (activeInteraction?.fieldElement === fieldElement) cancelActiveInteraction();
    const fieldIndex = documentFields.findIndex((field) => field.id === fieldElement.dataset.id);
    if (fieldIndex >= 0) documentFields.splice(fieldIndex, 1);
    if (selectedField === fieldElement) setSelectedField(null);
    fieldElement.remove();
}

function fieldMarkup(fieldData) {
    const config = FIELD_TYPES[fieldData.type];
    return `
        <span class="document-field__icon" aria-hidden="true">${config.icon}</span>
        <span class="document-field__label"><strong></strong><small></small></span>
        <button class="document-field__delete" type="button" aria-label="Eliminar campo ${config.label}">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M9 7V4h6v3M8 7l1 13h6l1-13M11 11v5M14 11v5"/></svg>
        </button>
        <button class="field-resize-handle" type="button" aria-label="Redimensionar campo ${config.label}"></button>
    `;
}

function updateFieldPresentation(fieldElement, fieldData) {
    const config = FIELD_TYPES[fieldData.type];
    const visibleLabel = fieldData.type === "text" ? fieldData.label || config.defaultLabel : config.label;

    fieldElement.dataset.required = String(fieldData.required);
    if (fieldData.type === "text") fieldElement.dataset.label = fieldData.label;
    fieldElement.querySelector(".document-field__label strong").textContent = visibleLabel;
    fieldElement.querySelector(".document-field__label small").textContent =
        `${config.description} · ${fieldData.required ? "Obligatorio" : "Opcional"}`;
    fieldElement.setAttribute("aria-label", `${visibleLabel} en página ${fieldData.page}`);
}

function createFieldElement(fieldData, layer) {
    const fieldElement = document.createElement("div");
    const layerWidth = layer.clientWidth;
    const layerHeight = layer.clientHeight;

    fieldElement.className = `document-field document-field--${fieldData.type}`;
    fieldElement.dataset.id = fieldData.id;
    fieldElement.dataset.type = fieldData.type;
    fieldElement.tabIndex = 0;
    fieldElement.setAttribute("role", "group");
    fieldElement.setAttribute("aria-selected", "false");
    fieldElement.innerHTML = fieldMarkup(fieldData);
    updateFieldPresentation(fieldElement, fieldData);
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

function createDocumentField(type, layer, clientX, clientY) {
    const config = FIELD_TYPES[type];
    const layerRect = layer.getBoundingClientRect();
    const width = Math.min(config.width, layerRect.width);
    const height = Math.min(config.height, layerRect.height);
    const left = clamp(clientX - layerRect.left - width / 2, 0, layerRect.width - width);
    const top = clamp(clientY - layerRect.top - height / 2, 0, layerRect.height - height);
    const fieldData = {
        id: createFieldId(type),
        type,
        page: Number(layer.dataset.page),
        x: 0,
        y: 0,
        width: 0,
        height: 0,
        required: true,
    };
    if (type === "text") fieldData.label = config.defaultLabel;
    const fieldElement = createFieldElement(fieldData, layer);

    layer.append(fieldElement);
    setFieldPixels(fieldElement, left, top, width, height);
    documentFields.push(getNormalizedFieldData(fieldElement));
    setSelectedField(fieldElement);
    fieldElement.focus({ preventScroll: true });
    hideEditorFeedback();
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

function createDragPreview(type) {
    const config = FIELD_TYPES[type];
    const preview = document.createElement("div");
    preview.className = `field-drag-preview field-drag-preview--${type}`;
    preview.style.width = `${config.width}px`;
    preview.style.height = `${config.height}px`;
    preview.innerHTML = `
        <span class="field-drag-preview__icon" aria-hidden="true">${config.icon}</span>
        <span class="field-drag-preview__label"><strong></strong><small>Suelta sobre una página</small></span>
    `;
    preview.querySelector("strong").textContent = config.label;
    document.body.append(preview);
    return preview;
}

function findLayerAtPoint(clientX, clientY) {
    return document.elementFromPoint(clientX, clientY)?.closest(".field-layer") || null;
}

function startToolDrag(event) {
    if (activeInteraction || !event.isPrimary || event.button !== 0 || !loadedPdf || pdfDocumentElement.hidden) return;

    const sourceTool = event.currentTarget;
    const type = sourceTool.dataset.fieldType;
    if (!FIELD_TYPES[type]) return;

    event.preventDefault();
    setSelectedField(null);
    sourceTool.setPointerCapture(event.pointerId);
    sourceTool.classList.add("field-tool--dragging");
    activeInteraction = {
        mode: "create",
        type,
        pointerId: event.pointerId,
        sourceTool,
        preview: createDragPreview(type),
        targetLayer: null,
    };
    moveFieldPreview(event);
}

function moveFieldPreview(event) {
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
    const config = FIELD_TYPES[fieldElement.dataset.type];
    const maximumWidth = layer.clientWidth - initial.left;
    const maximumHeight = layer.clientHeight - initial.top;
    const minimumWidth = Math.min(initial.width, config.minWidth, maximumWidth);
    const minimumHeight = Math.min(initial.height, config.minHeight, maximumHeight);
    const width = clamp(initial.width + event.clientX - startX, minimumWidth, maximumWidth);
    const height = clamp(initial.height + event.clientY - startY, minimumHeight, maximumHeight);

    setFieldPixels(fieldElement, initial.left, initial.top, width, height);
    updateFieldState(fieldElement);
}

function handlePointerMove(event) {
    if (!activeInteraction || event.pointerId !== activeInteraction.pointerId) return;
    event.preventDefault();

    if (activeInteraction.mode === "create") moveFieldPreview(event);
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
        interaction.sourceTool.classList.remove("field-tool--dragging");
        const dropLayer = findLayerAtPoint(event.clientX, event.clientY);
        if (dropLayer && event.type === "pointerup") {
            createDocumentField(interaction.type, dropLayer, event.clientX, event.clientY);
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
    if (interaction.mode === "create" && interaction.sourceTool.hasPointerCapture(interaction.pointerId)) {
        interaction.sourceTool.releasePointerCapture(interaction.pointerId);
    }
    interaction.sourceTool?.classList.remove("field-tool--dragging");
    activeInteraction = null;
}

function updatePropertiesPanel() {
    const fieldData = selectedField
        ? documentFields.find((field) => field.id === selectedField.dataset.id)
        : null;

    propertiesEmpty.hidden = Boolean(fieldData);
    propertiesContent.hidden = !fieldData;
    if (!fieldData) return;

    propertyType.textContent = FIELD_TYPES[fieldData.type].label;
    propertyRequired.checked = fieldData.required;
    textProperty.hidden = fieldData.type !== "text";
    propertyLabel.value = fieldData.type === "text" ? fieldData.label : "";
}

function updateSelectedProperty(property, value) {
    if (!selectedField) return;

    const fieldData = documentFields.find((field) => field.id === selectedField.dataset.id);
    if (!fieldData) return;

    fieldData[property] = value;
    updateFieldPresentation(selectedField, fieldData);
}

function showEditorFeedback(message) {
    editorFeedback.textContent = message;
    editorFeedback.hidden = false;
}

function hideEditorFeedback() {
    editorFeedback.hidden = true;
    editorFeedback.textContent = "";
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
    fieldTools.forEach((tool) => { tool.disabled = true; });
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
    fieldTools.forEach((tool) => { tool.disabled = false; });
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

fieldTools.forEach((tool) => tool.addEventListener("pointerdown", startToolDrag));
document.addEventListener("pointermove", handlePointerMove);
document.addEventListener("pointerup", finishInteraction);
document.addEventListener("pointercancel", finishInteraction);
document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest(".document-field, .field-properties")) setSelectedField(null);
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
propertyRequired?.addEventListener("change", () => {
    updateSelectedProperty("required", propertyRequired.checked);
});
propertyLabel?.addEventListener("input", () => {
    updateSelectedProperty("label", propertyLabel.value.slice(0, 60));
});
propertyLabel?.addEventListener("blur", () => {
    normalizeTextLabel(selectedField);
});
propertyDelete?.addEventListener("click", () => removeField(selectedField));
continueButton?.addEventListener("click", () => {
    if (documentFields.length === 0) {
        showEditorFeedback("Agrega al menos un campo al documento para continuar.");
        return;
    }

    hideEditorFeedback();
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
