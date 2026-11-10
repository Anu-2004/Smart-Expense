function togglePassword(inputId, iconId) {

    const input = document.getElementById(inputId);
    const icon = document.getElementById(iconId);

    if (!input || !icon) {
        return;
    }

    if (input.type === "password") {

        input.type = "text";

        icon.classList.remove("fa-eye");
        icon.classList.add("fa-eye-slash");

    } else {

        input.type = "password";

        icon.classList.remove("fa-eye-slash");
        icon.classList.add("fa-eye");

    }
}


function addItem() {

    const container =
        document.getElementById("itemsContainer");

    if (!container) {
        return;
    }

    const row = document.createElement("div");

    row.className = "row item-row mb-3";

    row.innerHTML = `
        <div class="col-md-6">
            <input type="text"
                   name="item_name[]"
                   class="form-control"
                   placeholder="Item name"
                   required>
        </div>

        <div class="col-md-4">
            <input type="number"
                   name="amount[]"
                   class="form-control"
                   placeholder="Amount ₹"
                   min="0.01"
                   step="0.01"
                   required>
        </div>

        <div class="col-md-2">
            <button type="button"
                    class="btn btn-outline-danger w-100"
                    onclick="removeItem(this)">
                ×
            </button>
        </div>
    `;

    container.appendChild(row);
}


function removeItem(button) {

    const row = button.closest(".item-row");

    if (!row) {
        return;
    }

    const container =
        document.getElementById("itemsContainer");

    if (container &&
        container.querySelectorAll(".item-row").length > 1) {

        row.remove();

    }
}


function toggleSidebar() {

    const sidebar =
        document.querySelector(".sidebar");

    if (sidebar) {
        sidebar.classList.toggle("show");
    }
}
