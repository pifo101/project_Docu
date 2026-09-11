const signatureFile = document.querySelector("[data-profile-signature-file]");
const signaturePreview = document.querySelector("[data-profile-signature-preview]");
const signatureFilename = document.querySelector("[data-profile-signature-filename]");

signatureFile?.addEventListener("change", () => {
    const file = signatureFile.files[0];
    if (!file) return;
    if (signatureFilename) signatureFilename.textContent = file.name;
    if (!file.type.match(/^image\/(png|jpeg)$/)) return;

    const image = document.createElement("img");
    image.alt = "Vista previa de la firma seleccionada";
    image.src = URL.createObjectURL(file);
    image.addEventListener("load", () => URL.revokeObjectURL(image.src), { once: true });
    signaturePreview?.querySelector("img, [data-profile-signature-empty]")?.replaceWith(image);
});
