const profileForm = document.querySelector("#profile-form");
const profileFields = document.querySelector("#personal-fields");
const editButton = document.querySelector(".edit-profile-button");
const cancelButton = document.querySelector(".cancel-profile-button");
const formActions = document.querySelector(".profile-form__actions");
const saveMessage = document.querySelector(".save-message");

function setEditing(editing) {
    profileFields.disabled = !editing;
    formActions.hidden = !editing;
    editButton.hidden = editing;
    editButton.setAttribute("aria-expanded", String(editing));
    saveMessage.hidden = true;

    if (editing) {
        profileFields.querySelector("input")?.focus();
    }
}

editButton?.addEventListener("click", () => setEditing(true));
cancelButton?.addEventListener("click", () => {
    profileForm.reset();
    setEditing(false);
});

profileForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    setEditing(false);
    saveMessage.hidden = false;
});

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
