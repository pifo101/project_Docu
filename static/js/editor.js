const databaseName = "adicla-sign-editor";
const storeName = "temporary-documents";
const documentKey = "current-pdf";
const pdfDocumentElement = document.querySelector("[data-pdf-document]");
const viewerState = document.querySelector("[data-viewer-state]");
const documentName = document.querySelector("[data-document-name]");
const documentStatus = document.querySelector("[data-document-status]");
const viewer = document.querySelector(".pdf-viewer");
let loadedPdf = null;
let pdfObjectUrl = null;
let renderVersion = 0;
let renderedWidth = 0;
let resizeTimer = null;

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
        fieldLayer.setAttribute("aria-hidden", "true");

        pageElement.append(canvas, fieldLayer);
        pdfDocumentElement.append(pageElement);

        await page.render({
            canvasContext: canvas.getContext("2d"),
            viewport: renderViewport,
        }).promise;
    }

    if (currentVersion !== renderVersion) return;
    viewerState.hidden = true;
    documentStatus.textContent = "Documento listo";
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
