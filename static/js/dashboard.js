document.addEventListener('DOMContentLoaded', () => {
    var layout = document.querySelector('.dash-layout');
    var hamburger = document.querySelector('.menu');
    var popups = document.querySelectorAll('.dash-user-menu');

    hamburger.style.cursor = 'pointer';
    hamburger.addEventListener('click', function () {
        layout.classList.toggle('sidebar-closed');
    });


    document.querySelectorAll('.dash-gear').forEach(function (gear) {
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