(function () {
    "use strict";

    var storageKey = "ludarium_lang";
    var translations = {
        "nav.dashboard": { en: "Dashboard", es: "Panel" },
        "nav.library": { en: "Library", es: "Biblioteca" },
        "nav.sessions": { en: "Sessions", es: "Sesiones" },
        "nav.stats": { en: "Stats", es: "Estadísticas" },
        "nav.activity": { en: "Activity", es: "Actividad" },
        "nav.index": { en: "Index", es: "Índice" },
        "nav.addGame": { en: "+ Game", es: "+ Juego" },
        "footer.copy": { en: "Ludarium", es: "Ludarium" },
        "dash.eyebrow": { en: "Your play history", es: "Tu historial de juego" },
        "dash.title": { en: "Dashboard", es: "Panel" },
        "dash.totalGames": { en: "Games", es: "Juegos" },
        "dash.playing": { en: "Playing", es: "Jugando" },
        "dash.completed": { en: "Completed", es: "Completados" },
        "dash.playTime": { en: "Play time", es: "Tiempo de juego" },
        "dash.backlog": { en: "Backlog", es: "Pendientes" },
        "dash.currentlyPlaying": { en: "Currently Playing", es: "Jugando ahora" },
        "dash.recentSessions": { en: "Recent Sessions", es: "Sesiones recientes" },
        "dash.recentlyAdded": { en: "Recently Added", es: "Añadidos recientemente" },
        "dash.noSessions": { en: "No play sessions yet. Log your first one from the Sessions tab.", es: "Aún no hay sesiones. Registra la primera desde Sesiones." },
        "dash.noGames": { en: "Your library is empty.", es: "Tu biblioteca está vacía." },
        "library.eyebrow": { en: "Your collection", es: "Tu colección" },
        "library.search": { en: "Search title, developer, publisher...", es: "Buscar título, desarrollador, editor..." },
        "library.allStatuses": { en: "All statuses", es: "Todos los estados" },
        "library.allPlatforms": { en: "All platforms", es: "Todas las plataformas" },
        "library.allGenres": { en: "All genres", es: "Todos los géneros" },
        "library.sortTitle": { en: "Title", es: "Título" },
        "library.sortAdded": { en: "Date added", es: "Fecha de añadido" },
        "library.sortRelease": { en: "Release year", es: "Año de lanzamiento" },
        "library.sortRating": { en: "Rating", es: "Valoración" },
        "library.sortStatus": { en: "Status", es: "Estado" },
        "library.emptyTitle": { en: "No games found", es: "No se encontraron juegos" },
        "library.emptyHint": { en: "Add a game or adjust your filters to start building your library.", es: "Añade un juego o ajusta los filtros para empezar." },
        "sessions.eyebrow": { en: "Time spent playing", es: "Tiempo jugando" },
        "sessions.logTitle": { en: "Log a play session", es: "Registrar sesión" },
        "sessions.rangeTitle": { en: "Add a date range", es: "Añadir un rango de fechas" },
        "sessions.rangeHint": { en: "Distribute total play time evenly across each day from the start date through the end date. The other session details apply to each day.", es: "Distribuye el tiempo total de juego por igual entre cada día desde la fecha inicial hasta la final. El resto de los datos de la sesión se aplica a cada día." },
        "sessions.rangeFrom": { en: "From", es: "Desde" },
        "sessions.rangeTo": { en: "To", es: "Hasta" },
        "sessions.rangeTotal": { en: "Total minutes", es: "Minutos totales" },
        "sessions.csvTitle": { en: "Import sessions from CSV", es: "Importar sesiones desde CSV" },
        "sessions.csvHint": { en: "Choose a CSV with date and time_played_minutes columns. Each row creates one session and uses the details selected above.", es: "Elige un CSV con columnas date y time_played_minutes. Cada fila crea una sesión y usa los datos seleccionados arriba." },
        "sessions.csvFile": { en: "CSV file", es: "Archivo CSV" },
        "sessions.allPlaythroughs": { en: "All playthroughs", es: "Todas las partidas" },
        "playthrough.eyebrow": { en: "Playthrough metadata", es: "Datos de la partida" },
        "playthrough.editTitle": { en: "Edit playthrough", es: "Editar partida" },
        "playthrough.title": { en: "Playthroughs", es: "Partidas" },
        "playthrough.countLabel": { en: "playthroughs", es: "partidas" },
        "playthrough.start": { en: "Start playthrough", es: "Iniciar partida" },
        "playthrough.name": { en: "Name", es: "Nombre" },
        "playthrough.namePlaceholder": { en: "Optional name, e.g. New Game+", es: "Nombre opcional, p. ej. Nueva partida+" },
        "playthrough.status": { en: "Status", es: "Estado" },
        "playthrough.completed": { en: "Completed", es: "Finalizada" },
        "playthrough.notes": { en: "Notes", es: "Notas" },
        "playthrough.numberLabel": { en: "Playthrough", es: "Partida" },
        "playthrough.defaultName": { en: "Playthrough", es: "Partida" },
        "playthrough.shortLabel": { en: "P", es: "P" },
        "playthrough.sessions": { en: "Sessions", es: "Sesiones" },
        "playthrough.playTime": { en: "Play time", es: "Tiempo de juego" },
        "playthrough.started": { en: "Started", es: "Inicio" },
        "playthrough.lastSession": { en: "Last session", es: "Última sesión" },
        "playthrough.viewSessions": { en: "View sessions", es: "Ver sesiones" },
        "playthrough.edit": { en: "Edit", es: "Editar" },
        "playthrough.sessionHistory": { en: "Play sessions", es: "Sesiones de juego" },
        "playthrough.openLog": { en: "Open log →", es: "Abrir registro →" },
        "playthrough.empty": { en: "No playthroughs yet. Start one when you begin a new run.", es: "Aún no hay partidas. Inicia una cuando comiences una nueva partida." },
        "playthrough.unassignedTitle": { en: "Unassigned sessions", es: "Sesiones sin asignar" },
        "playthrough.unassignedHint": { en: "These existing sessions are not assigned to a playthrough.", es: "Estas sesiones existentes no están asignadas a una partida." },
        "playthrough.assignTo": { en: "Assign them to", es: "Asignarlas a" },
        "playthrough.assign": { en: "Assign sessions", es: "Asignar sesiones" },
        "playthrough.fieldLabel": { en: "Playthrough", es: "Partida" },
        "playthrough.none": { en: "No playthrough", es: "Sin partida" },
        "playthrough.fieldHint": { en: "Use this to group sessions from the same run.", es: "Úsalo para agrupar las sesiones de una misma partida." },
        "playthrough.unassigned": { en: "Unassigned", es: "Sin asignar" },
        "common.viewAll": { en: "View all →", es: "Ver todo →" },
        "common.filter": { en: "Filter", es: "Filtrar" },
        "common.create": { en: "Create", es: "Crear" },
        "common.rename": { en: "Rename", es: "Renombrar" },
        "common.delete": { en: "Delete", es: "Eliminar" },
        "common.cancel": { en: "Cancel", es: "Cancelar" },
        "common.saveChanges": { en: "Save changes", es: "Guardar cambios" },
        "common.continue": { en: "Continue", es: "Continuar" },
        "common.backToLibrary": { en: "Back to library", es: "Volver a la biblioteca" },
        "library.manageTitle": { en: "Manage Libraries", es: "Gestionar bibliotecas" },
        "library.createNew": { en: "Create New Library", es: "Crear nueva biblioteca" },
        "library.existing": { en: "Existing Libraries", es: "Bibliotecas existentes" },
        "backup.title": { en: "Database Backup", es: "Copia de seguridad" },
        "backup.create": { en: "Create Backup Now", es: "Crear copia ahora" },
        "backup.shuttingDown": { en: "Backing up and closing...", es: "Guardando copia y cerrando..." },
        "users.subtitle": { en: "Your personal video game library", es: "Tu biblioteca personal de videojuegos" },
        "users.select": { en: "Select a user", es: "Selecciona un usuario" },
        "users.create": { en: "Create a new user", es: "Crear un usuario nuevo" },
        "users.name": { en: "Name", es: "Nombre" },
        "users.switch": { en: "Switch user", es: "Cambiar de usuario" }
    };

    function applyLanguage(language) {
        var selected = language === "es" ? "es" : "en";
        localStorage.setItem(storageKey, selected);
        document.querySelectorAll("[data-i18n]").forEach(function (element) {
            var value = translations[element.dataset.i18n];
            if (value) element.textContent = value[selected] || value.en;
        });
        document.querySelectorAll("[data-i18n-placeholder]").forEach(function (element) {
            var value = translations[element.dataset.i18nPlaceholder];
            if (value) element.placeholder = value[selected] || value.en;
        });
        document.querySelectorAll(".lang-btn").forEach(function (button) {
            button.classList.toggle("active", button.dataset.lang === selected);
        });
    }

    window.ludariumTranslate = function (key) {
        var language = localStorage.getItem(storageKey) || "en";
        return translations[key] ? (translations[key][language] || translations[key].en) : key;
    };

    document.addEventListener("DOMContentLoaded", function () {
        applyLanguage(localStorage.getItem(storageKey) || "en");
        document.querySelectorAll(".lang-btn").forEach(function (button) {
            button.addEventListener("click", function () { applyLanguage(button.dataset.lang); });
        });
    });
}());
