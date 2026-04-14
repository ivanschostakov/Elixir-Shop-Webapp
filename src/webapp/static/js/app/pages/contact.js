import { showLoader, hideLoader } from "../ui/loader.js";
import { state } from "../state.js";
import {
    isTelegramApp,
    showMainButton,
    showBackButton,
    hideMainButton,
} from "../ui/telegram.js";
import {
    cartPageEl,
    checkoutPageEl,
    contactPageEl,
    detailEl,
    headerTitle,
    listEl,
    navBottomEl,
    orderDetailEl,
    ordersPageEl,
    paymentPageEl,
    processPaymentEl,
    profilePageEl,
    searchBtnEl,
    toolbarEl,
} from "./constants.js";
import { apiGet } from "../../services/api.js";
import { navigateTo } from "../router.js";

const form = document.getElementById("contact-form");

export async function renderContactPage() {
    if (!checkoutPageEl || !contactPageEl || !form) return;

    if (!isTelegramApp()) {
        console.warn("[contact] Not in Telegram WebApp.");
        return;
    }

    cartPageEl.style.display = "none";
    detailEl.style.display = "none";
    listEl.style.display = "none";
    toolbarEl.style.display = "none";
    checkoutPageEl.style.display = "none";
    contactPageEl.style.display = "none";
    paymentPageEl && (paymentPageEl.style.display = "none");
    processPaymentEl.style.display = "none";
    profilePageEl.style.display = "none";
    ordersPageEl.style.display = "none";
    orderDetailEl.style.display = "none";

    headerTitle.textContent = "Оформление заказа";
    searchBtnEl.style.display = "none";

    navBottomEl.style.display = "none";

    contactPageEl.style.display = "block";

    form.addEventListener("submit", (e) => e.preventDefault());
    form.addEventListener("keydown", (e) => {
        if (e.key === "Enter") e.preventDefault();
    });

    const tg = state.telegram;
    const user_id = tg?.initDataUnsafe?.user?.id ?? null;

    const nameInput = form.querySelector('[name="name"]');
    const surnameInput = form.querySelector('[name="surname"]');
    const emailInput = form.querySelector('[name="email"]');
    const phoneInput = form.querySelector('[name="phone"]');
    const commentaryInput = form.querySelector("#payment-commentary-input");

    function ensureErrorEl(input) {
        if (!input) return null;
        if (input._errorEl) return input._errorEl;

        const err = document.createElement("div");
        err.className = "field-error";
        input.insertAdjacentElement("afterend", err);
        input._errorEl = err;
        return err;
    }

    const nameErrorEl = ensureErrorEl(nameInput);
    const surnameErrorEl = ensureErrorEl(surnameInput);
    const emailErrorEl = ensureErrorEl(emailInput);
    const phoneErrorEl = ensureErrorEl(phoneInput);

    function clearError(input, errEl) {
        if (!input || !errEl) return;
        input.classList.remove("input-error");
        errEl.textContent = "";
    }

    function setError(input, errEl, message) {
        if (!input || !errEl) return;
        input.classList.add("input-error");
        errEl.textContent = message;
    }

    function hasCompleteProfile(u) {
        return Boolean(u?.name && u?.surname && u?.email && u?.phone);
    }

    function prefillFormFromUser(u) {
        const map = {name: "name", surname: "surname", email: "email", phone: "phone"};
        Object.entries(map).forEach(([k, inputName]) => {
            const el = form.querySelector(`[name="${inputName}"]`);
            if (el && u?.[k]) el.value = u[k];
        });
    }

    async function fetchUserModel(uid) {
        if (!uid) return null;
        try {
            showLoader();
            const url = `/users?column_name=tg_id&value=${encodeURIComponent(String(uid))}`;
            const res = await apiGet(url);
            return res;
        } catch {
            return null;
        } finally {
            hideLoader();
        }
    }

    function saveContactInfo(contact_info) {
        sessionStorage.setItem("contact_info", JSON.stringify(contact_info));
        if (user_id) sessionStorage.setItem("tg_user_id", String(user_id));
    }

    async function handleSubmit() {
        if (!validateForm()) return;

        const formData = Object.fromEntries(new FormData(form).entries());
        saveContactInfo({
            name: formData.name,
            surname: formData.surname,
            email: formData.email,
            phone: formData.phone,
        });
        if (commentaryInput) {
            sessionStorage.setItem("payment_commentary", commentaryInput.value);
        }
        navigateTo("/payment");
    }

    hideMainButton();
    showBackButton();

    function validateEmail(v) {
        if (!v) return false;
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim());
    }

    function validatePhone(v) {
        if (!v) return false;
        const digits = v.replace(/[^\d+]/g, "");
        return digits.length >= 7;
    }

    function validateForm() {
        let isValid = true;

        if (!nameInput?.value.trim()) {
            setError(nameInput, nameErrorEl, "Введите имя");
            isValid = false;
        } else {
            clearError(nameInput, nameErrorEl);
        }

        if (!surnameInput?.value.trim()) {
            setError(surnameInput, surnameErrorEl, "Введите фамилию");
            isValid = false;
        } else {
            clearError(surnameInput, surnameErrorEl);
        }

        const emailVal = emailInput?.value.trim() ?? "";
        if (!emailVal) {
            setError(emailInput, emailErrorEl, "Введите email");
            isValid = false;
        } else if (!validateEmail(emailVal)) {
            setError(emailInput, emailErrorEl, "Некорректный email");
            isValid = false;
        } else {
            clearError(emailInput, emailErrorEl);
        }

        const phoneVal = phoneInput?.value.trim() ?? "";
        if (!phoneVal) {
            setError(phoneInput, phoneErrorEl, "Введите телефон");
            isValid = false;
        } else if (!validatePhone(phoneVal)) {
            setError(phoneInput, phoneErrorEl, "Некорректный номер телефона");
            isValid = false;
        } else {
            clearError(phoneInput, phoneErrorEl);
        }

        if (isValid) {
            showMainButton("Продолжить", () => {
                handleSubmit();
            });
        } else {
            hideMainButton();
        }

        return isValid;
    }

    if (!form._contactValidationBound) {
        form._contactValidationBound = true;

        [nameInput, surnameInput, emailInput, phoneInput].forEach((input) => {
            input &&
            input.addEventListener("input", () => {
                validateForm();
            });
        });

        if (commentaryInput) {
            commentaryInput.addEventListener("input", () => {
                sessionStorage.setItem("payment_commentary", commentaryInput.value);
            });
        }
    }

    const savedComment = sessionStorage.getItem("payment_commentary");
    if (savedComment && commentaryInput) {
        commentaryInput.value = savedComment;
    }
    const savedContact = JSON.parse(sessionStorage.getItem("contact_info") || "null");

    let userModel = null;
    if (user_id) {
        userModel = await fetchUserModel(user_id);
    }

    if (savedContact && hasCompleteProfile(savedContact)) {
        prefillFormFromUser(savedContact);
        validateForm();
    } else if (userModel && hasCompleteProfile(userModel)) {
        const contact_info = {
            name: userModel.name,
            surname: userModel.surname,
            email: userModel.email,
            phone: userModel.phone,
        };

        saveContactInfo(contact_info);
        prefillFormFromUser(userModel);
        validateForm();
    } else {
        if (userModel) {
            prefillFormFromUser(userModel);
        }
        validateForm();
    }
}
