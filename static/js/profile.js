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
