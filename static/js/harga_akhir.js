var price = document.getElementById("id_price");
var discount = document.getElementById("id_discount");
var hasil = document.getElementById("final-price");

function hitung() {
    var akhir = (price.value || 0) * (100 - (discount.value || 0)) / 100;
    hasil.value = "Rp. " + Math.round(akhir).toLocaleString("id-ID");
}

price.addEventListener("input", hitung);
discount.addEventListener("input", hitung);
hitung();