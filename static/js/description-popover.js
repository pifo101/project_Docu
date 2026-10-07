(() => {
    let trigger = null;
    let panel = null;
    let pinned = false;
    let closeTimer;
    let restoringFocus = false;

    function position() {
        if (!panel || !trigger) return;
        const viewport = window.visualViewport;
        const leftEdge = (viewport?.offsetLeft || 0) + 12;
        const topEdge = (viewport?.offsetTop || 0) + 12;
        const width = (viewport?.width || window.innerWidth) - 24;
        const height = (viewport?.height || window.innerHeight) - 24;
        panel.style.maxWidth = `${Math.max(0, width)}px`;
        panel.style.maxHeight = `${Math.max(0, height)}px`;
        const anchor = trigger.getBoundingClientRect();
        const rect = panel.getBoundingClientRect();
        const below = anchor.bottom + 8;
        const top = below + rect.height <= topEdge + height ? below : anchor.top - rect.height - 8;
        panel.style.left = `${Math.max(leftEdge, Math.min(anchor.left, leftEdge + width - rect.width))}px`;
        panel.style.top = `${Math.max(topEdge, Math.min(top, topEdge + height - rect.height))}px`;
    }

    function close(returnFocus = false) {
        window.clearTimeout(closeTimer);
        if (!trigger) return;
        const previous = trigger;
        previous.setAttribute("aria-expanded", "false");
        previous.removeAttribute("aria-controls");
        panel?.remove();
        panel = null;
        trigger = null;
        pinned = false;
        if (returnFocus) {
            restoringFocus = true;
            previous.focus({ preventScroll: true });
            restoringFocus = false;
        }
    }

    function scheduleClose() {
        window.clearTimeout(closeTimer);
        closeTimer = window.setTimeout(() => {
            if (!panel || pinned || panel.matches(":hover") || trigger.matches(":hover")) return;
            if (panel.contains(document.activeElement) || document.activeElement === trigger) return;
            close();
        }, 250);
    }

    function open(button) {
        window.clearTimeout(closeTimer);
        if (trigger === button || restoringFocus) return;
        close();
        trigger = button;
        // Clone Django-rendered markup, never interpret description text as HTML in JS.
        panel = button.parentElement.querySelector("template").content.firstElementChild.cloneNode(true);
        panel.id = "document-description-popover";
        document.body.append(panel);
        button.setAttribute("aria-controls", panel.id);
        button.setAttribute("aria-expanded", "true");
        panel.addEventListener("pointerenter", () => window.clearTimeout(closeTimer));
        panel.addEventListener("pointerleave", scheduleClose);
        panel.addEventListener("focusout", () => {
            window.setTimeout(() => {
                if (panel && !panel.contains(document.activeElement) && document.activeElement !== trigger) close();
            }, 0);
        });
        panel.querySelector("[data-description-close]").addEventListener("click", () => close(true));
        panel.addEventListener("keydown", (event) => {
            if (event.key !== "Tab") return;
            const first = panel.querySelector("button");
            const last = panel.querySelector("[tabindex='0']");
            if (event.shiftKey && (event.target === panel || event.target === first)) {
                event.preventDefault();
                close(true);
            } else if (!event.shiftKey && event.target === last) {
                // Restore the original tab order rather than jumping to the end of body.
                close(true);
            }
        });
        position();
    }

    document.querySelectorAll("[data-description-trigger]").forEach((button) => {
        button.hidden = false;
        button.addEventListener("pointerenter", (event) => {
            if (event.pointerType === "mouse") open(button);
        });
        button.addEventListener("pointerleave", scheduleClose);
        button.addEventListener("focus", () => open(button));
        button.addEventListener("blur", () => {
            window.setTimeout(() => {
                if (trigger === button && !panel?.contains(document.activeElement)) {
                    pinned = false;
                    scheduleClose();
                }
            }, 0);
        });
        button.addEventListener("click", () => {
            if (trigger === button && pinned) close(true);
            else {
                open(button);
                pinned = true;
            }
        });
        button.addEventListener("keydown", (event) => {
            if (event.key === "Tab" && !event.shiftKey && trigger === button) {
                event.preventDefault();
                panel.focus();
            }
        });
    });

    document.addEventListener("pointerdown", (event) => {
        if (panel && !panel.contains(event.target) && !trigger.contains(event.target)) {
            close(panel.contains(document.activeElement));
        }
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && panel) {
            event.preventDefault();
            close(panel.contains(document.activeElement) || document.activeElement === trigger);
        }
    });
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    window.visualViewport?.addEventListener("resize", position);
    window.visualViewport?.addEventListener("scroll", position);
})();
