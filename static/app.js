(function () {
    "use strict";

    window.openModal = function (id) {
        var element = document.getElementById(id);
        if (element) element.classList.add("open");
    };

    window.closeModal = function (id) {
        var element = document.getElementById(id);
        if (element) element.classList.remove("open");
    };

    window.closeModalOnBackdrop = function (event, id) {
        if (event.target === event.currentTarget) closeModal(id);
    };

    window.toggleTheme = function () {
        var isDark = document.documentElement.getAttribute("data-theme") === "dark";
        var theme = isDark ? "light" : "dark";
        localStorage.setItem("ludarium_theme", theme);
        document.documentElement.setAttribute("data-theme", theme);
        updateThemeButton();
    };

    function updateThemeButton() {
        var button = document.getElementById("themeToggle");
        if (!button) return;
        var isDark = document.documentElement.getAttribute("data-theme") === "dark";
        button.textContent = isDark ? "☾" : "☀";
        button.setAttribute("aria-pressed", String(isDark));
    }

    window.ludariumMinimize = function () {
        if (window.ludarium && window.ludarium.minimize) window.ludarium.minimize();
    };

    window.ludariumToggleMaximize = function () {
        if (window.ludarium && window.ludarium.toggleMaximize) window.ludarium.toggleMaximize();
    };

    window.ludariumQuit = function () {
        var overlay = document.getElementById("shutdownOverlay");
        if (overlay) overlay.classList.add("open");
        fetch("/shutdown-backup", { method: "POST" })
            .then(function (response) {
                if (!response.ok) throw new Error("backup_failed");
                return response.json();
            })
            .then(function (payload) {
                if (!payload || !payload.ok) throw new Error("backup_failed");
                if (window.ludarium && window.ludarium.quit) window.ludarium.quit();
            })
            .catch(function () {
                if (overlay) overlay.classList.remove("open");
                window.alert("Backup failed. Ludarium will stay open so you can try again.");
            });
    };

    function setTodayDefaults() {
        var today = new Date().toISOString().slice(0, 10);
        document.querySelectorAll("[data-today]").forEach(function (input) {
            if (!input.value) input.value = today;
        });
    }

    function setupPlaythroughSelectors() {
        document.querySelectorAll("[data-playthrough-for]").forEach(function (select) {
            var gameSelect = document.getElementById(select.dataset.playthroughFor);
            if (!gameSelect) return;
            var updateOptions = function () {
                var gameId = gameSelect.value;
                var selectedVisible = false;
                select.querySelectorAll("option[data-game-id]").forEach(function (option) {
                    var visible = Boolean(gameId) && option.dataset.gameId === gameId;
                    option.hidden = !visible;
                    if (visible && option.value === select.value) selectedVisible = true;
                });
                if (!selectedVisible) select.value = "";
            };
            gameSelect.addEventListener("change", updateOptions);
            updateOptions();
        });
    }

    function setupSessionCsvInputs() {
        document.querySelectorAll("[data-session-form]").forEach(function (form) {
            var csvInput = form.querySelector("[data-session-csv]");
            var dateInput = form.querySelector("[data-session-date]");
            if (!csvInput || !dateInput) return;
            var updateRequiredFields = function () {
                var hasFile = csvInput.files && csvInput.files.length > 0;
                dateInput.required = !hasFile;
                form.querySelectorAll("[name^='range_']").forEach(function (input) {
                    input.disabled = Boolean(hasFile);
                });
            };
            csvInput.addEventListener("change", updateRequiredFields);
            updateRequiredFields();
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        updateThemeButton();
        setTodayDefaults();
        setupPlaythroughSelectors();
        setupSessionCsvInputs();
        document.querySelectorAll(".flash").forEach(function (element) {
            window.setTimeout(function () {
                element.classList.add("flash-fade");
            }, 5000);
        });
        if (window.ludarium && window.ludarium.getWindowState) {
            window.ludarium.getWindowState().then(updateWindowButton);
            window.ludarium.onWindowStateChanged(updateWindowButton);
        }
    });

    function updateWindowButton(state) {
        var button = document.getElementById("maximizeButton");
        if (!button) return;
        var maximized = typeof state === "object" ? state.isMaximized : state;
        button.textContent = maximized ? "❐" : "□";
        button.title = maximized ? "Restore" : "Maximize";
    }
}());
