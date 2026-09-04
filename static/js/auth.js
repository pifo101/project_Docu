document.querySelectorAll(".password-toggle").forEach((button) => {
    button.addEventListener("click", () => {
        const input = button.parentElement.querySelector("input");
        const shouldShow = input.type === "password";

        input.type = shouldShow ? "text" : "password";
        button.setAttribute("aria-pressed", String(shouldShow));
        button.setAttribute("aria-label", shouldShow ? "Ocultar contraseña" : "Mostrar contraseña");
    });
});

const institutionalEmailPattern = /^[^\s@]+@adicla\.org\.gt$/i;

const validators = {
    login: {
        email: (input) => input.value.trim()
            ? institutionalEmailPattern.test(input.value.trim())
                ? ""
                : "Utiliza un correo institucional @adicla.org.gt."
            : "Ingresa tu correo institucional.",
        password: (input) => input.value ? "" : "Ingresa tu contraseña.",
    },
    register: {
        first_name: (input) => input.value.trim() ? "" : "Ingresa tus nombres.",
        last_name: (input) => input.value.trim() ? "" : "Ingresa tus apellidos.",
        email: (input) => input.value.trim()
            ? institutionalEmailPattern.test(input.value.trim())
                ? ""
                : "Utiliza un correo institucional @adicla.org.gt."
            : "Ingresa tu correo institucional.",
        comite: (input) => input.value ? "" : "Selecciona un comité.",
        cargo: (input) => input.value ? "" : "Selecciona un cargo.",
        password: (input) => input.value.length >= 8
            ? ""
            : "La contraseña debe tener al menos 8 caracteres.",
        password_confirm: (input, form) => {
            if (!input.value) {
                return "Confirma tu contraseña.";
            }

            return input.value === form.elements.password.value
                ? ""
                : "Las contraseñas no coinciden.";
        },
    },
};

const setFieldState = (input, message) => {
    const field = input.closest(".field");
    const error = field.querySelector(".field__error");

    field.classList.toggle("is-invalid", Boolean(message));
    field.classList.toggle("is-valid", !message && Boolean(input.value));
    input.setAttribute("aria-invalid", String(Boolean(message)));
    error.textContent = message;
};

document.querySelectorAll("[data-auth-form]").forEach((form) => {
    const formValidators = validators[form.dataset.authForm];
    const fields = Array.from(form.elements).filter((input) => formValidators[input.name]);

    const validateField = (input) => {
        const message = formValidators[input.name](input, form);
        setFieldState(input, message);
        return !message;
    };

    fields.forEach((input) => {
        const eventName = input.tagName === "SELECT" ? "change" : "input";
        input.addEventListener(eventName, () => {
            validateField(input);

            if (input.name === "password" && form.elements.password_confirm?.value) {
                validateField(form.elements.password_confirm);
            }
        });
        input.addEventListener("blur", () => validateField(input));
    });

    form.addEventListener("submit", (event) => {
        const validationResults = fields.map((input) => ({
            input,
            isValid: validateField(input),
        }));
        const firstInvalidField = validationResults.find((result) => !result.isValid)?.input;

        if (firstInvalidField) {
            event.preventDefault();
            firstInvalidField.focus();
        }
    });
});
