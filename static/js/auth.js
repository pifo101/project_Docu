document.querySelectorAll(".password-toggle").forEach((button) => {
    button.addEventListener("click", () => {
        const input = button.parentElement.querySelector("input");
        const shouldShow = input.type === "password";

        input.type = shouldShow ? "text" : "password";
        button.setAttribute("aria-pressed", String(shouldShow));
        button.setAttribute("aria-label", shouldShow ? "Ocultar contraseña" : "Mostrar contraseña");
    });
});
