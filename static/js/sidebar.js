document.addEventListener('DOMContentLoaded', () => {
    var layout = document.querySelector('.layout');
    var hamburger = document.querySelector('.menu');
    var popups = document.querySelectorAll('.sidebar-popup');   

    if (hamburger && layout) {                                  
        hamburger.style.cursor = 'pointer';
        hamburger.addEventListener('click', function () {
            layout.classList.toggle('sidebar-closed');
            hamburger.classList.toggle('is-open', !layout.classList.contains('sidebar-closed'));
        });
    }

    document.querySelectorAll('.sidebar-gear').forEach(function (gear) {
        gear.addEventListener('click', function (e) {
            e.stopPropagation();
            var popup = gear.nextElementSibling;
            popup.hidden = !popup.hidden;
        });
    });

    document.addEventListener('click', function () {
        popups.forEach(function (popup) {
            popup.hidden = true;
        });
    });
});