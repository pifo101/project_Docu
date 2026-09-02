const menuButton = document.querySelector(".menu-toggle");
const sidebar = document.querySelector(".sidebar");
const backdrop = document.querySelector(".sidebar-backdrop");

function setMenu(open) {
    sidebar.classList.toggle("sidebar--open", open);
    backdrop.classList.toggle("sidebar-backdrop--visible", open);
    menuButton.setAttribute("aria-expanded", String(open));
    menuButton.setAttribute("aria-label", open ? "Cerrar navegación" : "Abrir navegación");
}

menuButton?.addEventListener("click", () => {
    setMenu(!sidebar.classList.contains("sidebar--open"));
});

backdrop?.addEventListener("click", () => setMenu(false));

sidebar?.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => setMenu(false));
});

const uploadDialog = document.querySelector(".upload-dialog");
const uploadForm = document.querySelector(".upload-form");
const uploadInput = document.querySelector(".upload-input");
const dropZone = document.querySelector(".drop-zone");
const uploadError = document.querySelector(".upload-error");
const selectedFile = document.querySelector(".selected-file");
const selectedName = selectedFile?.querySelector("strong");
const selectedMeta = selectedFile?.querySelector("small");
const removeFileButton = document.querySelector(".selected-file__remove");
const continueButton = document.querySelector(".upload-continue");
const maxFileSize = 20 * 1024 * 1024;
const editorDatabaseName = "adicla-sign-editor";
const editorStoreName = "temporary-documents";
const editorDocumentKey = "current-pdf";
let dragDepth = 0;
let currentPdf = null;

function resetUpload() {
    uploadForm?.reset();
    dragDepth = 0;
    currentPdf = null;
    dropZone?.classList.remove("drop-zone--active", "drop-zone--error");
    uploadInput?.removeAttribute("aria-invalid");
    if (uploadError) uploadError.textContent = "";
    if (selectedFile) selectedFile.hidden = true;
    if (continueButton) {
        continueButton.disabled = true;
        continueButton.textContent = "Continuar";
    }
}

function showUploadError(message) {
    resetUpload();
    dropZone?.classList.add("drop-zone--error");
    uploadInput?.setAttribute("aria-invalid", "true");
    if (uploadError) uploadError.textContent = message;
}

function formatFileSize(bytes) {
    return bytes >= 1024 * 1024
        ? `${(bytes / (1024 * 1024)).toFixed(1)} MB`
        : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function selectPdf(file) {
    if (!file) return;

    const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    if (!isPdf) {
        showUploadError("El archivo no es válido. Selecciona un documento en formato PDF.");
        return;
    }

    if (file.size > maxFileSize) {
        showUploadError("El PDF supera el límite de 20 MB. Selecciona un archivo más pequeño.");
        return;
    }

    dropZone?.classList.remove("drop-zone--error");
    if (uploadError) uploadError.textContent = "";
    if (selectedName) selectedName.textContent = file.name;
    if (selectedMeta) selectedMeta.textContent = `${formatFileSize(file.size)} · PDF`;
    if (selectedFile) selectedFile.hidden = false;
    if (continueButton) continueButton.disabled = false;
    currentPdf = file;
}

function storePdfForEditor(file) {
    return new Promise((resolve, reject) => {
        const openRequest = indexedDB.open(editorDatabaseName, 1);

        openRequest.addEventListener("upgradeneeded", () => {
            if (!openRequest.result.objectStoreNames.contains(editorStoreName)) {
                openRequest.result.createObjectStore(editorStoreName);
            }
        });
        openRequest.addEventListener("error", () => reject(openRequest.error));
        openRequest.addEventListener("success", () => {
            const database = openRequest.result;
            const transaction = database.transaction(editorStoreName, "readwrite");
            const store = transaction.objectStore(editorStoreName);

            store.put({ file, name: file.name }, editorDocumentKey);
            transaction.addEventListener("complete", () => {
                database.close();
                resolve();
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

document.querySelector("[data-upload-open]")?.addEventListener("click", () => {
    resetUpload();
    uploadDialog?.showModal();
});

document.querySelectorAll("[data-upload-close]").forEach((button) => {
    button.addEventListener("click", () => uploadDialog?.close());
});

uploadDialog?.addEventListener("click", (event) => {
    if (event.target === uploadDialog) uploadDialog.close();
});

uploadDialog?.addEventListener("close", resetUpload);

uploadInput?.addEventListener("change", () => selectPdf(uploadInput.files[0]));

dropZone?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        uploadInput?.click();
    }
});

dropZone?.addEventListener("dragenter", (event) => {
    event.preventDefault();
    dragDepth += 1;
    dropZone.classList.add("drop-zone--active");
});

dropZone?.addEventListener("dragover", (event) => event.preventDefault());

dropZone?.addEventListener("dragleave", (event) => {
    event.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) {
        dropZone.classList.remove("drop-zone--active");
    }
});

dropZone?.addEventListener("drop", (event) => {
    event.preventDefault();
    dragDepth = 0;
    dropZone.classList.remove("drop-zone--active");
    if (event.dataTransfer.files.length > 1) {
        showUploadError("Carga un solo documento PDF a la vez.");
        return;
    }
    selectPdf(event.dataTransfer.files[0]);
});

removeFileButton?.addEventListener("click", () => {
    resetUpload();
    uploadInput?.focus();
});

continueButton?.addEventListener("click", async () => {
    if (!currentPdf) return;

    continueButton.disabled = true;
    continueButton.textContent = "Preparando...";

    try {
        await storePdfForEditor(currentPdf);
        uploadDialog?.close();
        window.location.assign(continueButton.dataset.editorUrl);
    } catch (error) {
        console.error("No se pudo preparar el PDF para el editor.", error);
        if (uploadError) {
            uploadError.textContent = "No se pudo abrir el editor. Intenta seleccionar el PDF nuevamente.";
        }
        continueButton.disabled = false;
        continueButton.textContent = "Continuar";
    }
});

window.addEventListener("pageshow", (event) => {
    if (event.persisted) resetUpload();
});
